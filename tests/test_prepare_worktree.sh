#!/usr/bin/env bash
# prepare-worktree.sh 단위 테스트: (a) 격리 트리 생성 (b) artifact 링크 (c) 멱등 재실행 (d) 커스텀 manifest.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fail() { echo "FAIL: $*"; exit 1; }

# ── 타겟 레포 준비 (커밋 1개 + 공유 artifact 디렉토리) ──
REPO="$WORK/repo"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" config user.email t@t.test
git -C "$REPO" config user.name tester
echo hello > "$REPO/README.md"
git -C "$REPO" add -A
git -C "$REPO" commit -qm init
# 공유/무거운 디렉토리 (gitignore 대상이라고 가정 — 링크 대상)
mkdir -p "$REPO/node_modules/pkg" "$REPO/target"
echo dep > "$REPO/node_modules/pkg/index.js"
echo build > "$REPO/target/out.bin"

# ── fake tokendance ROOT ──
mkdir -p "$WORK/scripts"
cp "$ROOT/scripts/status.py" "$WORK/scripts/"
cp "$ROOT/scripts/prepare-worktree.sh" "$WORK/scripts/"
python3 "$WORK/scripts/status.py" --root "$WORK" init t1 --title T --repo "$REPO" >/dev/null

# ── (a) 첫 실행: 격리 트리 생성, stdout = worktree 경로 ──
WT="$(bash "$WORK/scripts/prepare-worktree.sh" t1 2>"$WORK/err1.log")" \
  || { cat "$WORK/err1.log"; fail "prepare-worktree exited nonzero"; }
test -n "$WT" || fail "worktree 경로가 stdout 으로 안 나옴"
test -d "$WT" || fail "worktree 디렉토리 없음: $WT"

# git worktree 이며 브랜치가 tokendance/t1 인지
git -C "$WT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "worktree 가 git 작업트리가 아님"
BR="$(git -C "$WT" rev-parse --abbrev-ref HEAD)"
test "$BR" = "tokendance/t1" || fail "브랜치 불일치: $BR"
# 메인 레포에 worktree 가 등록됐는지
git -C "$REPO" worktree list | grep -q "$WT" || fail "worktree 가 레포에 등록 안 됨"
# 워커 소스가 격리됐는지: worktree 의 작업트리는 메인과 다른 경로
test "$(git -C "$WT" rev-parse --show-toplevel)" != "$REPO" || fail "worktree 가 격리 안 됨"

# ── (b) artifact 링크 (symlink, 원본으로 resolve) ──
test -L "$WT/node_modules" || fail "node_modules 가 symlink 아님"
test -L "$WT/target" || fail "target 이 symlink 아님"
test "$(readlink -f "$WT/node_modules")" = "$(readlink -f "$REPO/node_modules")" \
  || fail "node_modules 링크가 원본을 안 가리킴"
test -f "$WT/node_modules/pkg/index.js" || fail "링크 통해 dep 파일 접근 불가"

# ── status.json 의 branch 가 갱신됐는지 ──
SB="$(python3 "$WORK/scripts/status.py" --root "$WORK" get t1 --field branch)"
test "$SB" = "tokendance/t1" || fail "status.branch 미갱신: $SB"

# ── (c) 멱등 재실행: 같은 경로, 충돌 없이 성공 ──
WT2="$(bash "$WORK/scripts/prepare-worktree.sh" t1 2>"$WORK/err2.log")" \
  || { cat "$WORK/err2.log"; fail "멱등 재실행 실패"; }
test "$WT2" = "$WT" || fail "재실행 경로 불일치: $WT2 != $WT"
test "$(git -C "$WT2" rev-parse --abbrev-ref HEAD)" = "tokendance/t1" || fail "재실행 후 브랜치 깨짐"
test -L "$WT2/node_modules" || fail "재실행 후 링크 깨짐"
# worktree 가 중복 등록되지 않았는지 (정확히 1개)
CNT="$(git -C "$REPO" worktree list | grep -c "$WT")"
test "$CNT" = "1" || fail "worktree 중복 등록: $CNT"

# ── (d) 커스텀 manifest: 명시된 항목만 링크 ──
REPO2="$WORK/repo2"
mkdir -p "$REPO2"
git -C "$REPO2" init -q
git -C "$REPO2" config user.email t@t.test
git -C "$REPO2" config user.name tester
echo x > "$REPO2/f"; git -C "$REPO2" add -A; git -C "$REPO2" commit -qm init
mkdir -p "$REPO2/.venv" "$REPO2/node_modules"
printf '.venv\n# 주석\n\n' > "$REPO2/.tokendance-worktree.manifest"
python3 "$WORK/scripts/status.py" --root "$WORK" init t2 --repo "$REPO2" >/dev/null
WT3="$(bash "$WORK/scripts/prepare-worktree.sh" t2 2>"$WORK/err3.log")" \
  || { cat "$WORK/err3.log"; fail "manifest 케이스 실패"; }
test -L "$WT3/.venv" || fail "manifest 항목 .venv 링크 안 됨"
test ! -e "$WT3/node_modules" || fail "manifest 에 없는 node_modules 가 링크됨"

echo "PASS"
