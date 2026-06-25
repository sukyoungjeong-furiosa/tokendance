#!/usr/bin/env bash
# supervise.sh(keepalive 래퍼) 통합 테스트:
#   1) 감시 대상(supervisor) 강제 종료 → 자동 재기동(자기 회복).
#   2) clean stop(SIGTERM) → 재기동하지 않고 종료.
#   3) flock → 중복 supervisor 방지.
# 실제 supervisor.py/claude 를 띄우지 않도록 TOKENDANCE_SUPERVISOR_CMD seam 으로 가짜 자식을 쓴다.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"

PIDS=()   # 정리 대상 래퍼 pid 들
cleanup() {
  for p in "${PIDS[@]:-}"; do
    kill "$p" 2>/dev/null || true
  done
  # 잔여 가짜 자식(sleep) 정리
  if [ -f "$WORK/child.pids" ]; then
    while read -r cp; do kill -9 "$cp" 2>/dev/null || true; done < "$WORK/child.pids"
  fi
  # 래퍼들이 완전히 종료한 뒤 삭제(rm 도중 백그라운드 쓰기로 인한 stderr 노이즈 방지)
  for p in "${PIDS[@]:-}"; do
    for _ in $(seq 1 25); do kill -0 "$p" 2>/dev/null || break; sleep 0.2; done
  done
  rm -rf "$WORK"
}
trap cleanup EXIT

mkdir -p "$WORK/scripts" "$WORK/state"
cp "$ROOT/scripts/supervise.sh" "$WORK/scripts/"

# 가짜 감시 대상: 자기 pid 를 기록하고 오래 잠든다. 재기동마다 새 줄이 추가된다.
FAKE_CMD="echo \$\$ >> '$WORK/child.pids'; exec sleep 300"

export TOKENDANCE_CLAUDE=/bin/true       # 래퍼의 필수 env 가드 충족(가짜라 실제 미사용)
export TOKENDANCE_SUPERVISOR_CMD="$FAKE_CMD"

fail() { echo "FAIL: $*"; exit 1; }

# FILE 에 줄 수가 N 이상이 될 때까지 최대 TIMEOUT(0.2s 단위) 대기.
wait_for_lines() {  # $1=file $2=n $3=tries
  local f="$1" n="$2" tries="$3" i=0
  while [ "$i" -lt "$tries" ]; do
    [ -f "$f" ] && [ "$(wc -l < "$f")" -ge "$n" ] && return 0
    sleep 0.2; i=$((i+1))
  done
  return 1
}

# ── 테스트 1: 강제 종료 후 자동 재기동 ──
bash "$WORK/scripts/supervise.sh" 2>>"$WORK/wrapper.err" &
W1=$!; PIDS+=("$W1")
wait_for_lines "$WORK/child.pids" 1 50 || fail "가짜 자식이 기동되지 않음"
PID1="$(sed -n 1p "$WORK/child.pids")"
kill -9 "$PID1" 2>/dev/null || fail "자식 강제 종료 실패 (pid=$PID1)"
wait_for_lines "$WORK/child.pids" 2 50 || fail "자식 크래시 후 재기동되지 않음(자기 회복 실패)"
PID2="$(sed -n 2p "$WORK/child.pids")"
[ "$PID2" != "$PID1" ] || fail "재기동된 자식 pid 가 동일($PID1) — 재기동 아님"
[ -s "$WORK/state/supervisor.respawn.log" ] || fail "respawn.log 가 비어 있음(관측 누락)"
grep -q "재기동" "$WORK/state/supervisor.respawn.log" || fail "respawn.log 에 재기동 이벤트 없음"
echo "  [1] 강제 종료 후 자동 재기동 OK (pid $PID1 → $PID2)"

# 정리: 래퍼1 깔끔히 정지(테스트2의 lock 충돌 방지)
kill -TERM "$W1" 2>/dev/null || true
# 래퍼1 과 자식이 완전히 사라질 때까지 대기(lock 해제 보장)
for _ in $(seq 1 50); do kill -0 "$W1" 2>/dev/null || break; sleep 0.2; done
kill -0 "$W1" 2>/dev/null && fail "래퍼1 이 SIGTERM 후에도 살아있음(clean stop 실패)"

# ── 테스트 2: clean stop 후 재기동 안 함 ──
: > "$WORK/child.pids"
bash "$WORK/scripts/supervise.sh" 2>>"$WORK/wrapper.err" &
W2=$!; PIDS+=("$W2")
wait_for_lines "$WORK/child.pids" 1 50 || fail "테스트2: 자식 기동 안 됨"
CHILD2="$(sed -n 1p "$WORK/child.pids")"
kill -TERM "$W2" 2>/dev/null || fail "래퍼2 SIGTERM 실패"
for _ in $(seq 1 50); do kill -0 "$W2" 2>/dev/null || break; sleep 0.2; done
kill -0 "$W2" 2>/dev/null && fail "래퍼2 가 stop 후에도 살아있음"
kill -0 "$CHILD2" 2>/dev/null && fail "stop 후 자식이 살아있음(자식 종료 안 됨)"
sleep 1   # 재기동이 일어난다면 이 사이에 새 줄이 생길 것
[ "$(wc -l < "$WORK/child.pids")" -eq 1 ] || fail "clean stop 후 재기동됨(줄 수=$(wc -l < "$WORK/child.pids"))"
echo "  [2] clean stop 후 재기동 안 함 OK"

# ── 테스트 3: flock 중복 방지 ──
: > "$WORK/child.pids"
bash "$WORK/scripts/supervise.sh" 2>>"$WORK/wrapper.err" &
W3=$!; PIDS+=("$W3")
wait_for_lines "$WORK/child.pids" 1 50 || fail "테스트3: 첫 래퍼 자식 기동 안 됨"
OUT="$(bash "$WORK/scripts/supervise.sh" 2>&1)"; RC=$?
[ "$RC" -eq 0 ] || fail "중복 래퍼 종료코드 비0 ($RC)"
echo "$OUT" | grep -q "이미 실행 중" || fail "중복 래퍼가 lock 메시지 없이 진행함: $OUT"
sleep 0.5
[ "$(wc -l < "$WORK/child.pids")" -eq 1 ] || fail "중복 래퍼가 두 번째 자식을 띄움(중복 supervisor)"
echo "  [3] flock 중복 방지 OK"

echo "PASS"
