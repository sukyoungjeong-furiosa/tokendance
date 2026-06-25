#!/usr/bin/env bash
# 멀티레포 워커 e2e 스모크: 타겟이 tokendance 가 아닌 더미 git 레포에 대해
#   tasks.py new --repo <dummy> → prepare-worktree.sh <id> → cwd=worktree 에서
#   절대경로로 checkpoint.py / finish.py 호출 시 tokendance state 가 갱신되는 흐름을 검증한다.
#
# 핵심 회귀 방어: 워커 cwd 는 타겟 레포 worktree 라 거기엔 scripts/·state/ 가 없다.
#   - 상대경로 `python3 scripts/checkpoint.py` 는 깨져야 하고(존재 증명),
#   - 절대경로 `python3 $TOKENDANCE_ROOT/scripts/checkpoint.py` 는 동작해야 한다.
# 실제 tokendance state 오염을 막으려 격리된 FAKE tokendance ROOT(mktemp)에 scripts 를 복사해 돌린다.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
fail() { echo "FAIL: $*"; exit 1; }

ID="2099-01-01-smoke"

# ── (1) 격리된 fake tokendance ROOT (scripts 전체 복사) ──
FAKE="$WORK/tokendance"
mkdir -p "$FAKE/scripts" "$FAKE/prompts"
cp "$ROOT"/scripts/*.py "$ROOT"/scripts/*.sh "$FAKE/scripts/"

# ── (2) 더미 **비-tokendance** 타겟 레포 ──
REPO="$WORK/dummy-repo"
mkdir -p "$REPO/src"
git -C "$REPO" init -q
git -C "$REPO" config user.email t@t.test
git -C "$REPO" config user.name tester
echo 'print("hi")' > "$REPO/src/app.py"
git -C "$REPO" add -A
git -C "$REPO" commit -qm init
# 이 레포엔 tokendance 의 scripts/state 가 없음을 확인(전제).
test ! -e "$REPO/scripts" || fail "더미 레포에 scripts/ 가 있으면 테스트 전제 깨짐"

# ── (3) tasks.py new --repo <dummy> ──
python3 "$FAKE/scripts/tasks.py" --root "$FAKE" new "$ID" --title "스모크" --repo "$REPO" >/dev/null
RB="$(python3 "$FAKE/scripts/status.py" --root "$FAKE" get "$ID" --field repo)"
test "$RB" = "$REPO" || fail "status.repo 미저장: $RB"

# ── (4) prepare-worktree.sh <id> → worktree·브랜치 생성 ──
WT="$(bash "$FAKE/scripts/prepare-worktree.sh" "$ID" 2>"$WORK/pw.err")" \
  || { cat "$WORK/pw.err"; fail "prepare-worktree 실패"; }
test -d "$WT" || fail "worktree 디렉토리 없음: $WT"
test "$WT" = "$FAKE/state/worktrees/$ID" || fail "worktree 위치 예상과 다름: $WT"
BR="$(git -C "$WT" rev-parse --abbrev-ref HEAD)"
test "$BR" = "tokendance/$ID" || fail "브랜치 불일치: $BR"
# worktree 는 더미 레포의 작업트리(=npu-tools 같은 임의 레포 모사). tokendance scripts 없음.
test -f "$WT/src/app.py" || fail "worktree 에 타겟 레포 파일 없음"
test ! -e "$WT/scripts" || fail "worktree 에 tokendance scripts/ 가 있으면 안 됨(비-tokendance 레포)"

# ── (5) 상대경로는 깨진다는 것 증명(cwd=worktree) ──
if ( cd "$WT" && python3 scripts/checkpoint.py "$ID" ) 2>/dev/null; then
  fail "상대경로 checkpoint 가 worktree 에서 성공하면 안 됨(버그 재현 실패)"
fi

# ── (6) 절대경로 checkpoint: heartbeat 갱신 + steer 읽기 (cwd=worktree, TOKENDANCE_ROOT env) ──
printf 'STEER-XYZ 새 지시\n' > "$FAKE/state/tasks/$ID/steer.md"
OUT="$( cd "$WT" && export TOKENDANCE_ROOT="$FAKE" && python3 "$TOKENDANCE_ROOT/scripts/checkpoint.py" "$ID" )" \
  || fail "절대경로 checkpoint 실패"
echo "$OUT" | grep -q "STEER-XYZ" || fail "checkpoint 가 steer 신규분을 못 읽음: [$OUT]"
HB="$(python3 "$FAKE/scripts/status.py" --root "$FAKE" get "$ID" --field heartbeat)"
test -n "$HB" -a "$HB" != "None" || fail "heartbeat 미갱신: $HB"
# cursor 가 전진해 재호출 시 같은 steer 가 안 나오는지(중복 방지)
OUT2="$( cd "$WT" && export TOKENDANCE_ROOT="$FAKE" && python3 "$TOKENDANCE_ROOT/scripts/checkpoint.py" "$ID" )"
echo "$OUT2" | grep -q "STEER-XYZ" && fail "cursor 미전진(steer 중복 출력)"

# ── (7) 절대경로 finish --review → 상태 전이 (cwd=worktree) ──
( cd "$WT" && export TOKENDANCE_ROOT="$FAKE" && python3 "$TOKENDANCE_ROOT/scripts/finish.py" "$ID" --review ) \
  || fail "절대경로 finish 실패"
ST="$(python3 "$FAKE/scripts/status.py" --root "$FAKE" get "$ID" --field state)"
test "$ST" = "review" || fail "finish 후 상태가 review 아님: $ST"

# ── (8) 회수: 더미 레포에서 worktree/브랜치 제거 (git -C <repo>) ──
git -C "$REPO" worktree remove --force "$WT"
git -C "$REPO" worktree prune
git -C "$REPO" branch -D "tokendance/$ID"
test ! -d "$WT" || fail "회수 후 worktree 가 남아있음"

echo "PASS"
