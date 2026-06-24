#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# fake claude: cwd 를 기록하고 잠깐 살아있다 종료
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

# fake root 구조
mkdir -p "$WORK/scripts" "$WORK/prompts"
cp "$ROOT/scripts/status.py" "$WORK/scripts/"
cp "$ROOT/scripts/prepare-worktree.sh" "$WORK/scripts/"
cp "$ROOT/scripts/launch-worker.sh" "$WORK/scripts/"
echo "worker prompt" > "$WORK/prompts/worker.md"
python3 "$WORK/scripts/status.py" --root "$WORK" init t1 --title T --repo "$REPO"

TOKENDANCE_CLAUDE="$FAKE" bash "$WORK/scripts/launch-worker.sh" t1
sleep 1
STATE="$(python3 "$WORK/scripts/status.py" --root "$WORK" get t1 --field state)"
PID="$(python3 "$WORK/scripts/status.py" --root "$WORK" get t1 --field worker_pid)"
test "$STATE" = "running" || { echo "FAIL: state=$STATE"; exit 1; }
# 주의: fake-claude 는 재fork 를 안 하므로 $! == 실제 pid 라 이 검사가 유효하다.
# 실제 claude 바이너리는 재fork/재부모화하여 pid 가 드리프트하므로(스파이크 확인),
# 운영 생사 판정은 pid 가 아니라 heartbeat staleness(supervisor.health_check)로 한다.
test -n "$PID" && kill -0 "$PID" 2>/dev/null || { echo "FAIL: worker pid not alive ($PID)"; exit 1; }
test -f "$WORK/state/workers/t1.log" || { echo "FAIL: no worker log"; exit 1; }
# 워커가 격리된 worktree 를 cwd 로 기동됐는지
WT="$WORK/state/worktrees/t1"
test -d "$WT" || { echo "FAIL: worktree 미생성"; exit 1; }
grep -q "cwd=$WT" "$WORK/state/workers/t1.log" || {
  echo "FAIL: 워커 cwd 가 worktree 아님"; cat "$WORK/state/workers/t1.log"; exit 1; }
echo "PASS"
