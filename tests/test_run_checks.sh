#!/usr/bin/env bash
# run-checks.sh 단위 테스트: pass / fail / skip / 오버라이드 / 자동탐지 / worktree 격리 분기.
set -uo pipefail
ROOT_REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fail() { echo "FAIL: $*"; exit 1; }

# ── fake tokendance ROOT (필요한 스크립트만 복사) ──
FROOT="$WORK/root"
mkdir -p "$FROOT/scripts"
cp "$ROOT_REAL/scripts/status.py" "$FROOT/scripts/"
cp "$ROOT_REAL/scripts/run-checks.sh" "$FROOT/scripts/"
cp "$ROOT_REAL/scripts/checks_report.py" "$FROOT/scripts/"

# 헬퍼: git 레포 하나 만들기
mkrepo() {  # $1 = path
  local r="$1"
  mkdir -p "$r"
  git -C "$r" init -q
  git -C "$r" config user.email t@t.test
  git -C "$r" config user.name tester
  echo x > "$r/README.md"; git -C "$r" add -A; git -C "$r" commit -qm init
}

# 헬퍼: checks.json 필드 읽기
jget() {  # $1 = task-id, $2 = field
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],""))' \
    "$FROOT/state/tasks/$1/checks.json" "$2"
}

run() { bash "$FROOT/scripts/run-checks.sh" "$1" --root "$FROOT"; }

# ── (a) PASS: 매니페스트의 명령이 모두 성공 ──
R="$WORK/repo_pass"; mkrepo "$R"
printf 'true\ntrue\n' > "$R/.tokendance-checks"
python3 "$FROOT/scripts/status.py" --root "$FROOT" init pass1 --repo "$R" >/dev/null
out="$(run pass1)"; rc=$?
test "$rc" -eq 0 || fail "(a) pass 인데 exit=$rc"
test "$(jget pass1 status)" = "passed" || fail "(a) status != passed: $(jget pass1 status)"
test "$(jget pass1 source)" = "manifest" || fail "(a) source != manifest: $(jget pass1 source)"
test "$(jget pass1 total)" = "2" || fail "(a) total != 2"
test -f "$FROOT/state/tasks/pass1/checks.md" || fail "(a) checks.md 없음"
test -f "$FROOT/state/tasks/pass1/checks.log" || fail "(a) checks.log 없음"
echo "$out" | grep -q "PASSED" || fail "(a) stdout 에 PASSED 없음"

# ── (b) FAIL: 한 명령이라도 비0 이면 fail (exit 1) ──
R="$WORK/repo_fail"; mkrepo "$R"
printf 'true\nfalse\n' > "$R/.tokendance-checks"
python3 "$FROOT/scripts/status.py" --root "$FROOT" init fail1 --repo "$R" >/dev/null
run fail1 >/dev/null; rc=$?
test "$rc" -eq 1 || fail "(b) fail 인데 exit=$rc"
test "$(jget fail1 status)" = "failed" || fail "(b) status != failed"
test "$(jget fail1 failed)" = "1" || fail "(b) failed count != 1"

# ── (c) SKIP: 명령 소스가 전혀 없으면 skip (exit 2) ──
R="$WORK/repo_skip"; mkrepo "$R"   # 매니페스트/탐지 대상 파일 없음
python3 "$FROOT/scripts/status.py" --root "$FROOT" init skip1 --repo "$R" >/dev/null
run skip1 >/dev/null; rc=$?
test "$rc" -eq 2 || fail "(c) skip 인데 exit=$rc"
test "$(jget skip1 status)" = "skipped" || fail "(c) status != skipped"
test "$(jget skip1 source)" = "none" || fail "(c) source != none"

# ── (d) OVERRIDE: check.cmd 가 매니페스트보다 우선 ──
R="$WORK/repo_ovr"; mkrepo "$R"
printf 'false\n' > "$R/.tokendance-checks"      # 매니페스트는 실패 명령
python3 "$FROOT/scripts/status.py" --root "$FROOT" init ovr1 --repo "$R" >/dev/null
printf 'true\n' > "$FROOT/state/tasks/ovr1/check.cmd"   # 오버라이드는 성공 명령
run ovr1 >/dev/null; rc=$?
test "$rc" -eq 0 || fail "(d) override 인데 exit=$rc (매니페스트가 이김?)"
test "$(jget ovr1 source)" = "override" || fail "(d) source != override"

# ── (e) AUTODETECT: tests/test_*.py → unittest discover ──
R="$WORK/repo_auto"; mkdir -p "$R/tests"; mkrepo "$R"
cat > "$R/tests/test_ok.py" <<'EOF'
import unittest
class T(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(True)
EOF
python3 "$FROOT/scripts/status.py" --root "$FROOT" init auto1 --repo "$R" >/dev/null
run auto1 >/dev/null; rc=$?
test "$rc" -eq 0 || fail "(e) autodetect 인데 exit=$rc"
test "$(jget auto1 source)" = "autodetect:unittest" || fail "(e) source != autodetect:unittest: $(jget auto1 source)"

# ── (f) WORKTREE 격리: worktree.path 가 있으면 그 안에서 실행, 매니페스트도 worktree 것을 사용 ──
R="$WORK/repo_wt"; mkrepo "$R"
printf 'false\n' > "$R/.tokendance-checks"      # repo(메인) 매니페스트는 실패 명령
WT="$WORK/wt_wt"
git -C "$R" worktree add -q -b tokendance/wt1 "$WT" >/dev/null 2>&1
printf 'true\n' > "$WT/.tokendance-checks"      # worktree 매니페스트는 성공 명령
python3 "$FROOT/scripts/status.py" --root "$FROOT" init wt1 --repo "$R" >/dev/null
echo "$WT" > "$FROOT/state/tasks/wt1/worktree.path"
run wt1 >/dev/null; rc=$?
test "$rc" -eq 0 || fail "(f) worktree 안 매니페스트(성공) 무시됨, exit=$rc"
test "$(jget wt1 cwd)" = "$WT" || fail "(f) cwd != worktree: $(jget wt1 cwd)"

echo "PASS"
