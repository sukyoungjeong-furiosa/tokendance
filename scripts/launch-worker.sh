#!/usr/bin/env bash
# 워커를 detached OS 프로세스로 기동. 마스터의 유일한 워커 기동 통로.
# 인자: $1 = task-id
set -euo pipefail
TASK_ID="${1:?task-id required}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${TOKENDANCE_CLAUDE:?TOKENDANCE_CLAUDE (claude 바이너리 경로) 미설정}"

TASK_DIR="$ROOT/state/tasks/$TASK_ID"
LOG="$ROOT/state/workers/$TASK_ID.log"
mkdir -p "$ROOT/state/workers"

# 1) worktree 셋업 (실패하면 blocked 처리).
#    prepare-worktree 는 stdout 마지막 줄에 worktree 경로만 인쇄하고 진단은 stderr 로 보낸다.
#    stdout 을 캡처하고 stderr 만 LOG 로 흘린다.
if ! WORKTREE="$("$ROOT/scripts/prepare-worktree.sh" "$TASK_ID" 2>>"$LOG")"; then
  python3 "$ROOT/scripts/status.py" set "$TASK_ID" --state blocked
  echo "[launch-worker] prepare-worktree failed for $TASK_ID" >&2
  exit 1
fi

# 2) 워커 기동 — 격리된 worktree 를 cwd 로 (detached: setsid + IS_SANDBOX=1 + stdin 차단 + disown).
#    IS_SANDBOX=1 은 root에서 --dangerously-skip-permissions 를 허용하기 위해 필수(스파이크 확인).
#    ROOT/LOG/worker.md 경로는 모두 절대경로라 cd 후에도 안전하다.
PROMPT="너는 tokendance 워커다. task id=${TASK_ID}. ${ROOT}/prompts/worker.md 를 읽고 그대로 따르라. 일감 명세: ${TASK_DIR}/task.md"
cd "$WORKTREE"
setsid env IS_SANDBOX=1 "$TOKENDANCE_CLAUDE" -p "$PROMPT" \
  --append-system-prompt "$(cat "$ROOT/prompts/worker.md")" \
  --dangerously-skip-permissions \
  >>"$LOG" 2>&1 < /dev/null &
PID=$!
disown 2>/dev/null || true

# 3) 상태를 running 으로 기록 + 즉시 heartbeat (갓 띄운 워커가 stale 로 오판되지 않게).
#    PID 는 best-effort(디버깅용) — 생사 판정은 supervisor 가 heartbeat 로 함.
python3 "$ROOT/scripts/status.py" set "$TASK_ID" --state running --pid "$PID"
python3 "$ROOT/scripts/status.py" heartbeat "$TASK_ID"
echo "$PID"
