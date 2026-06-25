#!/usr/bin/env bash
# launch-worker.sh 의 --resume / 세션 캡처 / 멱등 가드 검증.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# fake claude: 받은 args 를 로그로 남기고 잠깐 살아있다 종료(워커 모사).
FAKE="$WORK/fake-claude"
cat > "$FAKE" <<'EOF'
#!/usr/bin/env bash
echo "fake worker args: $*"
echo "cwd=$(pwd)"
sleep 2
EOF
chmod +x "$FAKE"

# 타겟 git 레포 (worktree 격리 대상)
REPO="$WORK/repo"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" config user.email t@t.test
git -C "$REPO" config user.name tester
echo hi > "$REPO/README.md"; git -C "$REPO" add -A; git -C "$REPO" commit -qm init

# fake tokendance root
mkdir -p "$WORK/scripts" "$WORK/prompts"
cp "$ROOT/scripts/status.py" "$WORK/scripts/"
cp "$ROOT/scripts/prepare-worktree.sh" "$WORK/scripts/"
cp "$ROOT/scripts/launch-worker.sh" "$WORK/scripts/"
cp "$ROOT/scripts/prompt.py" "$WORK/scripts/"
echo "worker prompt" > "$WORK/prompts/worker.md"

# 세션파일을 들여다보는 디렉토리를 격리(실제 ~/.claude 오염 방지).
export CLAUDE_CONFIG_DIR="$WORK/claude"
mkdir -p "$CLAUDE_CONFIG_DIR/projects/somewt"

run_launch() {  # run_launch <task-id> [--resume]  → stdout+stderr 캡처를 OUT 에
  OUT="$(TOKENDANCE_CLAUDE="$FAKE" bash "$WORK/scripts/launch-worker.sh" "$@" 2>&1)"
}
field() { python3 "$WORK/scripts/status.py" --root "$WORK" get "$1" --field "$2"; }
logof() { cat "$WORK/state/workers/$1.log"; }
fail() { echo "FAIL: $1"; echo "--- OUT ---"; echo "${OUT:-}"; exit 1; }

# ── 1) fresh 기동: 세션 id 를 민팅해 기록하고 --session-id 로 claude 기동 (완료기준 #1) ──
python3 "$WORK/scripts/status.py" --root "$WORK" init t1 --title T --repo "$REPO" >/dev/null
run_launch t1
sleep 1
SID1="$(field t1 worker_session_id)"
[ -n "$SID1" ] && [ "$SID1" != "None" ] || fail "fresh: 세션 id 미기록 ($SID1)"
echo "$SID1" | grep -Eq '^[0-9a-f-]{36}$' || fail "fresh: 세션 id 가 UUID 아님 ($SID1)"
grep -q -- "--session-id $SID1" "$WORK/state/workers/t1.log" || fail "fresh: claude 가 --session-id 로 안 받음 ($(logof t1))"

# ── 2) resume(유효 세션): 기록된 sid 의 세션파일이 있으면 --resume 으로 이어감, sid 불변 (완료기준 #2) ──
python3 "$WORK/scripts/status.py" --root "$WORK" init t2 --title T --repo "$REPO" >/dev/null
SIDV="11111111-2222-3333-4444-555555555555"
python3 "$WORK/scripts/status.py" --root "$WORK" set t2 --session "$SIDV" >/dev/null
touch "$CLAUDE_CONFIG_DIR/projects/somewt/$SIDV.jsonl"
run_launch t2 --resume
sleep 1
grep -q -- "--resume $SIDV" "$WORK/state/workers/t2.log" || fail "resume: --resume 로 안 받음 ($(logof t2))"
test "$(field t2 worker_session_id)" = "$SIDV" || fail "resume: sid 가 바뀜"

# ── 3) resume(만료=세션파일 없음): 깨끗이 fresh 폴백 + 명확 로그 (완료기준 #2) ──
python3 "$WORK/scripts/status.py" --root "$WORK" init t3 --title T --repo "$REPO" >/dev/null
SIDX="99999999-8888-7777-6666-555555555555"
python3 "$WORK/scripts/status.py" --root "$WORK" set t3 --session "$SIDX" >/dev/null
# 세션파일 일부러 안 만듦 → 만료로 간주
run_launch t3 --resume
sleep 1
NEW3="$(field t3 worker_session_id)"
[ "$NEW3" != "$SIDX" ] || fail "expired: fresh 폴백 안 함(sid 그대로)"
echo "$NEW3" | grep -Eq '^[0-9a-f-]{36}$' || fail "expired: 새 sid 가 UUID 아님 ($NEW3)"
grep -q -- "--session-id $NEW3" "$WORK/state/workers/t3.log" || fail "expired: --session-id 로 fresh 기동 안 함"
echo "$OUT" | grep -qi "fallback\|폴백\|fresh" || fail "expired: 폴백 로그 없음"

# ── 4) resume(세션 미기록): --resume 줘도 fresh 폴백 (완료기준 #2) ──
python3 "$WORK/scripts/status.py" --root "$WORK" init t4 --title T --repo "$REPO" >/dev/null
run_launch t4 --resume
sleep 1
SID4="$(field t4 worker_session_id)"
[ -n "$SID4" ] && [ "$SID4" != "None" ] || fail "no-session resume: 세션 미민팅"
grep -q -- "--session-id $SID4" "$WORK/state/workers/t4.log" || fail "no-session resume: fresh 기동 안 함"

# ── 5) 멱등 가드: 기록된 워커 pid 가 살아있으면 재기동 skip (완료기준 #4) ──
python3 "$WORK/scripts/status.py" --root "$WORK" init t5 --title T --repo "$REPO" >/dev/null
sleep 60 &
LIVE=$!
python3 "$WORK/scripts/status.py" --root "$WORK" set t5 --state running --pid "$LIVE" --session "alive-sid" >/dev/null
run_launch t5 --resume
echo "$OUT" | grep -qi "alive\|살아\|skip\|건너" || fail "guard: skip 로그 없음 ($OUT)"
test "$(field t5 worker_session_id)" = "alive-sid" || fail "guard: 세션이 덮어써짐(재기동됨)"
test ! -f "$WORK/state/workers/t5.log" || fail "guard: 새 워커가 떠버림(t5.log 생성)"
kill "$LIVE" 2>/dev/null || true

echo "PASS"
