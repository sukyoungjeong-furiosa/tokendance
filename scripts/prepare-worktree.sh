#!/usr/bin/env bash
# 워커 격리용 git worktree 셋업.
#
#   prepare-worktree.sh <task-id>
#
# 동작:
#   1. status.json 의 repo(타겟 레포)에 대해 `git worktree add` 로 격리 작업트리를 만든다.
#      위치: <tokendance ROOT>/state/worktrees/<task-id>, 브랜치: tokendance/<task-id>.
#      (state/ 는 gitignore 라 도그푸딩(타겟==tokendance) 시에도 메인 트리를 오염시키지 않는다.)
#   2. 공유/무거운 디렉토리(node_modules, target, .venv 등)를 worktree 에 symlink 해 풀 빌드를 피한다.
#      대상은 타겟 레포의 `.tokendance-worktree.manifest`(한 줄당 경로, # 주석/빈 줄 무시)로 지정,
#      없으면 기본값(아래 DEFAULT_ARTIFACTS) 사용. 원본이 없는 항목은 건너뛴다.
#   3. 멱등: 이미 올바른 worktree 가 있으면 재사용, 아니면 깨끗이 제거 후 재생성. 항상 `worktree prune` 안전.
#
# 출력: 마지막 줄(stdout)에 worktree 절대경로만 인쇄. 진단 메시지는 모두 stderr 로.
#       launch-worker.sh 가 이 경로를 받아 워커의 cwd 로 삼는다.
#
# ── worktree 회수(reclaim) ──
#   책임자: 마스터. task 가 종료 상태(done/failed)가 된 뒤 회수한다.
#     git -C <repo> worktree remove --force <tokendance ROOT>/state/worktrees/<task-id>
#     git -C <repo> worktree prune          # 잔여 등록 정리(항상 안전)
#   브랜치(tokendance/<task-id>)는 PR 머지/검토 후 삭제: git -C <repo> branch -D tokendance/<task-id>
set -euo pipefail

TASK_ID="${1:?task-id required}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# manifest 미지정 시 링크할 기본 디렉토리 (무겁거나 공유되는 빌드 의존성).
DEFAULT_ARTIFACTS=(node_modules target .venv venv vendor .gradle)

log() { echo "[prepare-worktree] $*" >&2; }

REPO="$(python3 "$ROOT/scripts/status.py" --root "$ROOT" get "$TASK_ID" --field repo)"
if [ -z "$REPO" ] || [ "$REPO" = "None" ]; then
  log "task $TASK_ID 에 repo 가 비어 있음 — worktree 격리 불가"
  exit 1
fi
if [ ! -d "$REPO/.git" ] && ! git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
  log "repo 가 git 레포가 아님: $REPO"
  exit 1
fi
REPO="$(cd "$REPO" && pwd)"

BRANCH="tokendance/$TASK_ID"
WT_BASE="$ROOT/state/worktrees"
WT="$WT_BASE/$TASK_ID"

# 잔여 등록(이전 실행에서 디렉토리만 지워진 경우 등) 정리.
git -C "$REPO" worktree prune

# ── 멱등: 기존 worktree 가 올바른 브랜치면 재사용, 아니면 재생성 ──
reuse=false
if [ -d "$WT" ] && git -C "$WT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  cur="$(git -C "$WT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
  if [ "$cur" = "$BRANCH" ]; then
    reuse=true
    log "기존 worktree 재사용: $WT ($BRANCH)"
  fi
fi

if [ "$reuse" = false ]; then
  log "worktree 생성: $WT ($BRANCH)"
  git -C "$REPO" worktree remove --force "$WT" 2>/dev/null || true
  rm -rf "$WT"
  git -C "$REPO" worktree prune
  mkdir -p "$WT_BASE"
  if git -C "$REPO" show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git -C "$REPO" worktree add --force "$WT" "$BRANCH" >&2
  else
    git -C "$REPO" worktree add --force -b "$BRANCH" "$WT" >&2
  fi
fi

# ── artifact 링크 ──
artifacts=()
MANIFEST="$REPO/.tokendance-worktree.manifest"
if [ -f "$MANIFEST" ]; then
  while IFS= read -r line; do
    line="${line%%#*}"                       # 주석 제거
    line="$(echo "$line" | xargs 2>/dev/null || true)"  # 공백 trim
    [ -n "$line" ] && artifacts+=("$line")
  done < "$MANIFEST"
  log "manifest 사용: ${artifacts[*]:-(없음)}"
else
  artifacts=("${DEFAULT_ARTIFACTS[@]}")
fi

# src(메인레포) → dst(worktree) 단일 symlink. 멱등(낡은 링크 교체, 추적 실체는 보존).
link_one() {
  local src="$1" dst="$2" label="$3"
  if [ -L "$dst" ]; then rm -f "$dst"; fi     # 낡은/잘못된 링크 교체
  [ -e "$dst" ] && return 0                    # 추적되는 실제 콘텐츠는 보존
  mkdir -p "$(dirname "$dst")"
  ln -s "$src" "$dst"
  log "링크: $label -> $src"
}

for entry in "${artifacts[@]}"; do
  src="$REPO/$entry"
  dst="$WT/$entry"
  [ -e "$src" ] || continue                    # 원본 없으면 건너뜀
  if [ -L "$dst" ]; then rm -f "$dst"; fi       # 낡은/잘못된 링크 교체
  if [ -e "$dst" ]; then
    # dst 가 worktree 의 실제(추적) 콘텐츠. src·dst 둘 다 진짜 디렉토리면,
    # 통째 보존-skip 대신 자식 1단계 병합 — dst 에 이미 있는 자식(추적 포인터: dvc 등)은
    # 보존하고, worktree 에 없는 자식(gitignore 추출본: libtorch jammy/current 등)만 링크한다.
    # (예: npu-tools artifacts/furiosa-libtorch — dvc 포인터는 추적, 추출본은 gitignore.)
    # 1단계만 병합한다: 자식이 다시 부분추적이면 그 자식을 manifest 에 따로 명시하라.
    if [ -d "$dst" ] && [ ! -L "$dst" ] && [ -d "$src" ] && [ ! -L "$src" ]; then
      shopt -s nullglob dotglob
      for child in "$src"/*; do
        link_one "$child" "$dst/$(basename "$child")" "$entry/$(basename "$child")"
      done
      shopt -u nullglob dotglob
    fi
    continue                                    # 그 외(파일 충돌 등)는 보존
  fi
  mkdir -p "$(dirname "$dst")"
  ln -s "$src" "$dst"
  log "링크: $entry -> $src"
done

# branch 를 status.json 에 기록(가시성).
python3 "$ROOT/scripts/status.py" --root "$ROOT" set "$TASK_ID" --branch "$BRANCH" >/dev/null
# 회수/디버깅용으로 경로도 남긴다.
echo "$WT" > "$ROOT/state/tasks/$TASK_ID/worktree.path"

echo "$WT"
