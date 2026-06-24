#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${TOKENDANCE_CLAUDE:?TOKENDANCE_CLAUDE 미설정}"
PIDFILE="$ROOT/state/supervisor.pid"
mkdir -p "$ROOT/state"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "이미 실행 중: $(cat "$PIDFILE")"; exit 0
fi
nohup python3 "$ROOT/scripts/supervisor.py" >"$ROOT/state/supervisor.log" 2>&1 < /dev/null &
echo $! > "$PIDFILE"
echo "supervisor 시작: $(cat "$PIDFILE")"
