#!/usr/bin/env bash
# keepalive 래퍼: supervisor.py 가 죽으면 자동 재기동(자기 회복). systemd 없이 동작.
#
#   supervise.sh
#
# 동작:
#   - state/supervisor.lock 에 flock(비차단) → 중복 supervisor 방지(이미 실행 중이면 즉시 종료).
#   - supervisor.py 를 foreground 자식으로 실행하고 죽으면 재기동.
#   - 빠른 크래시(가동 < FAST_CRASH_SECONDS)면 백오프를 2배로(상한 MAX_BACKOFF) → 무한 재기동 루프 방지.
#     오래 가동 후 죽으면 백오프 리셋.
#   - SIGTERM/SIGINT(=stop.sh) 수신 시 자식을 종료하고 재기동하지 않고 깔끔히 빠진다(crash 와 구분).
#   - 재기동 이벤트는 state/supervisor.respawn.log 로 타임스탬프와 함께 남긴다(관측).
#
# 주: 이 래퍼는 사소한 bash 루프라 크래시 표면이 거의 없다. supervisor.py(파이썬)가 자기 회복 대상.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${TOKENDANCE_CLAUDE:?TOKENDANCE_CLAUDE 미설정}"

mkdir -p "$ROOT/state"
LOG="$ROOT/state/supervisor.log"
RESPAWN_LOG="$ROOT/state/supervisor.respawn.log"
LOCK="$ROOT/state/supervisor.lock"

# ── 중복 방지: flock 비차단. 이미 누가 잡고 있으면 즉시 종료(이중 supervisor 금지). ──
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[supervise] 이미 실행 중(lock 점유) — 종료" >&2
  exit 0
fi

# config.local.md 의 POLL_INTERVAL → supervisor 주기 인자.
INTERVAL_ARG=()
if [ -f "$ROOT/config.local.md" ]; then
  VAL="$(grep -oE '^POLL_INTERVAL=[0-9]+' "$ROOT/config.local.md" | head -1 | cut -d= -f2)"
  [ -n "$VAL" ] && INTERVAL_ARG=(--interval "$VAL")
fi

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
note() { echo "$(ts) $*" >> "$RESPAWN_LOG"; }

# 감시 대상 명령. 기본은 supervisor.py. 테스트는 TOKENDANCE_SUPERVISOR_CMD 로 대체(seam).
if [ -n "${TOKENDANCE_SUPERVISOR_CMD:-}" ]; then
  SUP_CMD=(bash -c "$TOKENDANCE_SUPERVISOR_CMD")
else
  SUP_CMD=(python3 "$ROOT/scripts/supervisor.py" "${INTERVAL_ARG[@]}")
fi

STOP=0
CHILD=""
on_term() {
  STOP=1
  [ -n "$CHILD" ] && kill -TERM "$CHILD" 2>/dev/null || true
}
trap on_term TERM INT

MIN_BACKOFF=2
MAX_BACKOFF=60
FAST_CRASH_SECONDS=30   # 가동이 이보다 짧으면 "빠른 크래시" → 백오프 증가
backoff=$MIN_BACKOFF

note "supervise 시작 wrapper_pid=$$"
while [ "$STOP" -eq 0 ]; do
  start_ts=$SECONDS
  "${SUP_CMD[@]}" >>"$LOG" 2>&1 &
  CHILD=$!
  wait "$CHILD"
  rc=$?
  CHILD=""
  [ "$STOP" -eq 1 ] && break
  ran=$(( SECONDS - start_ts ))
  if [ "$ran" -lt "$FAST_CRASH_SECONDS" ]; then
    note "supervisor 종료(rc=$rc, ${ran}s — 빠른 크래시) → ${backoff}s 후 재기동"
    sleep "$backoff"
    backoff=$(( backoff * 2 )); [ "$backoff" -gt "$MAX_BACKOFF" ] && backoff=$MAX_BACKOFF
  else
    note "supervisor 종료(rc=$rc, ${ran}s 가동) → 재기동(백오프 리셋)"
    backoff=$MIN_BACKOFF
    sleep "$MIN_BACKOFF"
  fi
done
note "supervise 종료(stop 요청)"
