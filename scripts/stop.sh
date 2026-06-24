#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDFILE="$ROOT/state/supervisor.pid"
[ -f "$PIDFILE" ] || { echo "실행 중 아님"; exit 0; }
kill "$(cat "$PIDFILE")" 2>/dev/null || true
rm -f "$PIDFILE"
echo "supervisor 정지"
