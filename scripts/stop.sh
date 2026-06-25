#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDFILE="$ROOT/state/supervisor.pid"
[ -f "$PIDFILE" ] || { echo "실행 중 아님"; exit 0; }
PID="$(cat "$PIDFILE")"
# 래퍼는 setsid 로 자기 프로세스그룹 리더(pgid==pid)다. 그룹째 SIGTERM →
# 래퍼가 trap 으로 supervisor.py 자식까지 종료하고 재기동하지 않고 빠진다(clean stop).
if ! kill -- -"$PID" 2>/dev/null; then
  kill "$PID" 2>/dev/null || true   # 그룹 kill 실패 시 단일 pid fallback
fi
rm -f "$PIDFILE"
echo "supervisor 정지"
