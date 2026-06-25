#!/usr/bin/env bash
# launch-worker.sh 가 타겟 레포의 .tokendance-worktree.env 를 worktree 생성 후 source 해
# 워커 프로세스 환경에 주입하는지 검증한다($WORKTREE 확장 포함). 파일 없는 레포는 무영향.
# (npu-tools 가 이 메커니즘으로 LIBTORCH 를 자동 주입 → 워커가 수동 export 없이 libtorch 사용.)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
fail() { echo "FAIL: $*"; exit 1; }

# fake claude: 주입돼야 할 env 를 로그로 남기고 잠깐 살아있다 종료
FAKE="$WORK/fake-claude"
cat > "$FAKE" <<'EOF'
#!/usr/bin/env bash
echo "LIBTORCH=${LIBTORCH:-<unset>}"
echo "WORKER_FLAG=${WORKER_FLAG:-<unset>}"
sleep 2
EOF
chmod +x "$FAKE"

# fake root 구조
mkdir -p "$WORK/scripts" "$WORK/prompts"
for f in status.py prepare-worktree.sh launch-worker.sh prompt.py; do cp "$ROOT/scripts/$f" "$WORK/scripts/"; done
echo "worker prompt" > "$WORK/prompts/worker.md"

# ── (1) env 파일이 있는 레포: LIBTORCH 가 $WORKTREE 로 확장돼 주입됨 ──
REPO="$WORK/repo"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" config user.email t@t.test
git -C "$REPO" config user.name tester
echo hi > "$REPO/README.md"
git -C "$REPO" add -A; git -C "$REPO" commit -qm init
# 레포가 제공하는 worker 환경 — launch-worker 가 메인 체크아웃($REPO)에서 source. $WORKTREE 참조 가능.
# 미추적 드롭(커밋 안 함)으로도 동작해야 한다(호스트 운영 설정 모델).
cat > "$REPO/.tokendance-worktree.env" <<'EOF'
LIBTORCH="$WORKTREE/artifacts/furiosa-libtorch/current"
WORKER_FLAG=on
EOF
python3 "$WORK/scripts/status.py" --root "$WORK" init t1 --title T --repo "$REPO" >/dev/null

TOKENDANCE_CLAUDE="$FAKE" bash "$WORK/scripts/launch-worker.sh" t1 >/dev/null
sleep 1
WT="$WORK/state/worktrees/t1"
LOG="$WORK/state/workers/t1.log"
test -d "$WT" || fail "worktree 미생성"
grep -q "LIBTORCH=$WT/artifacts/furiosa-libtorch/current" "$LOG" \
  || { echo "--- log ---"; cat "$LOG"; fail "LIBTORCH 가 \$WORKTREE 로 확장 주입 안 됨"; }
grep -q "WORKER_FLAG=on" "$LOG" || { cat "$LOG"; fail "WORKER_FLAG 미주입"; }

# ── (2) env 파일이 없는 레포: 아무 것도 주입되지 않음(무영향) ──
REPO2="$WORK/repo2"
mkdir -p "$REPO2"
git -C "$REPO2" init -q
git -C "$REPO2" config user.email t@t.test
git -C "$REPO2" config user.name tester
echo x > "$REPO2/f"; git -C "$REPO2" add -A; git -C "$REPO2" commit -qm init
python3 "$WORK/scripts/status.py" --root "$WORK" init t2 --title T --repo "$REPO2" >/dev/null
TOKENDANCE_CLAUDE="$FAKE" bash "$WORK/scripts/launch-worker.sh" t2 >/dev/null
sleep 1
LOG2="$WORK/state/workers/t2.log"
grep -q "LIBTORCH=<unset>" "$LOG2" || { cat "$LOG2"; fail "env 파일 없는데 LIBTORCH 가 주입됨(무영향 위반)"; }

echo "PASS"
