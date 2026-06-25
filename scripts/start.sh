#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${TOKENDANCE_CLAUDE:?TOKENDANCE_CLAUDE 미설정}"
PIDFILE="$ROOT/state/supervisor.pid"
mkdir -p "$ROOT/state"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "이미 실행 중: $(cat "$PIDFILE")"; exit 0
fi
# config.local.md 의 POLL_INTERVAL(초)이 있으면 supervisor 주기로 전달(없으면 기본 1800).
INTERVAL_ARG=""
if [ -f "$ROOT/config.local.md" ]; then
  VAL="$(grep -oE '^POLL_INTERVAL=[0-9]+' "$ROOT/config.local.md" | head -1 | cut -d= -f2)"
  [ -n "$VAL" ] && INTERVAL_ARG="--interval $VAL"
fi
nohup python3 "$ROOT/scripts/supervisor.py" $INTERVAL_ARG >"$ROOT/state/supervisor.log" 2>&1 < /dev/null &
echo $! > "$PIDFILE"
echo "supervisor 시작: $(cat "$PIDFILE")"
