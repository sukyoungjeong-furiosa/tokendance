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
#
#    실제 워커 pid 캡처: setsid 가 새 세션을 위해 fork 하므로 $!(=setsid)는 실제 워커 pid 와 어긋난다
#    (스파이크). 그래서 내부 bash 가 exec 직전 자기 pid($$)를 pidfile 에 기록하고, exec 로 claude 가
#    같은 pid 를 물려받게 한다 → status 의 worker_pid 가 진짜 워커 pid 가 되어 즉사 감지의 보조
#    신호(supervisor.detect_fast_crash)로 신뢰성 있게 쓰인다. (PROMPT/sysprompt 는 위치인자로 넘겨
#    재평가/쿼팅 문제를 피한다.)
PROMPT="너는 tokendance 워커다. task id=${TASK_ID}. ${ROOT}/prompts/worker.md 를 읽고 그대로 따르라. 일감 명세: ${TASK_DIR}/task.md"
SYSPROMPT="$(cat "$ROOT/prompts/worker.md")"
PIDFILE="$ROOT/state/workers/$TASK_ID.pid"
rm -f "$PIDFILE"   # 이전 (재)기동의 잔여 pidfile 제거
cd "$WORKTREE"
setsid bash -c '
  echo $$ > "$1"
  exec env IS_SANDBOX=1 "$2" -p "$3" \
    --append-system-prompt "$4" \
    --dangerously-skip-permissions
' _ "$PIDFILE" "$TOKENDANCE_CLAUDE" "$PROMPT" "$SYSPROMPT" \
  >>"$LOG" 2>&1 < /dev/null &
WRAPPER_PID=$!
disown 2>/dev/null || true

# pidfile 이 써질 때까지 잠깐 대기(없으면 wrapper pid 로 fallback — 드리프트하지만 best-effort).
PID=""
for _ in $(seq 1 20); do
  if [ -s "$PIDFILE" ]; then PID="$(cat "$PIDFILE")"; break; fi
  sleep 0.1
done
[ -n "$PID" ] || PID="$WRAPPER_PID"

# 3) 상태를 running 으로 기록(+launched_at: 즉사 grace window 기준점) + 즉시 heartbeat
#    (갓 띄운 워커가 stale 로 오판되지 않게).
python3 "$ROOT/scripts/status.py" set "$TASK_ID" --state running --pid "$PID" --launched-now
python3 "$ROOT/scripts/status.py" heartbeat "$TASK_ID"
echo "$PID"
