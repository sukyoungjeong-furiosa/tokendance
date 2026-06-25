#!/usr/bin/env bash
# review 단계 자동 검증: 타겟 레포의 테스트 스위트를 워커 worktree 안에서 실행한다.
#
#   run-checks.sh <task-id> [--root <tokendance-root>]
#
# 동작:
#   - status.json 의 repo(타겟 레포)와 worktree.path 를 해석한다.
#     테스트는 워커 worktree(있고 유효하면) 안에서 실행해 소스 격리를 보장한다(worktree-isolation).
#     worktree 가 없으면 repo 디렉토리로 fallback(테스트는 read-only 가정).
#   - 검증 명령 해석 우선순위(먼저 매칭되는 소스 하나만 사용):
#       1) state/tasks/<id>/check.cmd     (태스크 오버라이드; 줄당 한 명령, #주석/빈줄 무시)
#       2) <cwd>/.tokendance-checks       (레포 매니페스트; 줄당 한 명령, #주석/빈줄 무시)
#       3) 자동탐지 (cargo / go / npm / python / make)
#       4) 없으면 skip
#   - 각 명령을 cwd(worktree/repo) 에서 순차 실행, 결합 출력을 checks.log 로 캡처.
#     모두 exit 0 → pass. 하나라도 비0 → fail. 명령당 타임아웃 CHECK_TIMEOUT(기본 1800초).
#   - 결과 기록(마스터/자동화가 참조):
#       state/tasks/<id>/checks.json  기계용(status/commands/log_tail/...)
#       state/tasks/<id>/checks.md    사람용 요약
#       state/tasks/<id>/checks.log   전체 결합 출력
#     review.md 는 마스터 소유라 건드리지 않는다.
#   - stdout: 한 줄 요약. exit code: 0=pass, 1=fail, 2=skip, 3=오류(repo/worktree 해석 실패).
#
# 안전: 테스트 명령만 실행한다. git push / main 변경은 하지 않으며 cwd 는 격리 worktree 다.
set -uo pipefail

TASK_ID=""
ROOT_OVERRIDE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT_OVERRIDE="$2"; shift 2 ;;
    --root=*) ROOT_OVERRIDE="${1#*=}"; shift ;;
    -*) echo "[run-checks] unknown flag: $1" >&2; exit 3 ;;
    *) if [ -z "$TASK_ID" ]; then TASK_ID="$1"; else echo "[run-checks] extra arg: $1" >&2; exit 3; fi; shift ;;
  esac
done
[ -n "$TASK_ID" ] || { echo "[run-checks] usage: run-checks.sh <task-id> [--root <root>]" >&2; exit 3; }

if [ -n "$ROOT_OVERRIDE" ]; then
  ROOT="$(cd "$ROOT_OVERRIDE" && pwd)"
else
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
TASK_DIR="$ROOT/state/tasks/$TASK_ID"
[ -d "$TASK_DIR" ] || { echo "[run-checks] no such task dir: $TASK_DIR" >&2; exit 3; }

CHECK_TIMEOUT="${CHECK_TIMEOUT:-1800}"

log() { echo "[run-checks] $*" >&2; }

# ── repo / cwd 해석 ──
REPO="$(python3 "$ROOT/scripts/status.py" --root "$ROOT" get "$TASK_ID" --field repo 2>/dev/null || true)"
if [ -z "$REPO" ] || [ "$REPO" = "None" ]; then
  log "task $TASK_ID 에 repo 가 비어 있음 — 검증 불가"
  exit 3
fi

CWD=""
WT_PATH_FILE="$TASK_DIR/worktree.path"
if [ -f "$WT_PATH_FILE" ]; then
  WT="$(cat "$WT_PATH_FILE")"
  if [ -n "$WT" ] && [ -d "$WT" ] && git -C "$WT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    CWD="$WT"
    log "worktree 안에서 실행: $CWD"
  fi
fi
if [ -z "$CWD" ]; then
  if [ -d "$REPO" ]; then
    CWD="$(cd "$REPO" && pwd)"
    log "worktree 없음 — repo 디렉토리로 fallback: $CWD"
  else
    log "repo 디렉토리 없음: $REPO"
    exit 3
  fi
fi

# ── 검증 명령 해석 ──
COMMANDS=()
SOURCE="none"

read_cmd_file() {  # $1 = path → COMMANDS 채움
  local f="$1" line
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    # 앞뒤 공백 trim
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [ -n "$line" ] && COMMANDS+=("$line")
  done < "$f"
}

OVERRIDE="$TASK_DIR/check.cmd"
MANIFEST="$CWD/.tokendance-checks"
if [ -f "$OVERRIDE" ]; then
  read_cmd_file "$OVERRIDE"
  [ ${#COMMANDS[@]} -gt 0 ] && SOURCE="override"
fi
if [ "$SOURCE" = "none" ] && [ -f "$MANIFEST" ]; then
  read_cmd_file "$MANIFEST"
  [ ${#COMMANDS[@]} -gt 0 ] && SOURCE="manifest"
fi
if [ "$SOURCE" = "none" ]; then
  # ── 자동탐지 (첫 매칭 하나) ──
  if [ -f "$CWD/Cargo.toml" ]; then
    COMMANDS=("cargo test"); SOURCE="autodetect:cargo"
  elif [ -f "$CWD/go.mod" ]; then
    COMMANDS=("go test ./..."); SOURCE="autodetect:go"
  elif [ -f "$CWD/package.json" ] && python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if (d.get("scripts") or {}).get("test") else 1)' "$CWD/package.json" 2>/dev/null; then
    COMMANDS=("npm test"); SOURCE="autodetect:npm"
  elif [ -f "$CWD/pyproject.toml" ] || [ -f "$CWD/setup.py" ] || [ -f "$CWD/setup.cfg" ]; then
    if command -v pytest >/dev/null 2>&1; then
      COMMANDS=("pytest"); SOURCE="autodetect:pytest"
    else
      COMMANDS=("python3 -m unittest discover"); SOURCE="autodetect:unittest"
    fi
  elif [ -d "$CWD/tests" ] && ls "$CWD"/tests/test_*.py >/dev/null 2>&1; then
    COMMANDS=("python3 -m unittest discover -s tests -p 'test_*.py'"); SOURCE="autodetect:unittest"
  elif [ -f "$CWD/Makefile" ] && grep -qE '^test:' "$CWD/Makefile"; then
    COMMANDS=("make test"); SOURCE="autodetect:make"
  fi
fi

CHECKS_JSON="$TASK_DIR/checks.json"
CHECKS_MD="$TASK_DIR/checks.md"
CHECKS_LOG="$TASK_DIR/checks.log"
RESULTS="$(mktemp)"
trap 'rm -f "$RESULTS"' EXIT

emit() {  # $1=status  (RESULTS 파일과 변수 사용). 산출물 기록 실패는 치명적(마스터가 checks.json 의존).
  if ! python3 "$ROOT/scripts/checks_report.py" \
      --task-id "$TASK_ID" --status "$1" --source "$SOURCE" --cwd "$CWD" \
      --results "$RESULTS" --log "$CHECKS_LOG" \
      --out-json "$CHECKS_JSON" --out-md "$CHECKS_MD"; then
    log "checks_report.py 실패 — checks.json/checks.md 기록 불가"
    echo "run-checks: ERROR ($TASK_ID) — 결과 기록 실패"
    exit 3
  fi
}

# ── skip ──
if [ "$SOURCE" = "none" ] || [ ${#COMMANDS[@]} -eq 0 ]; then
  : > "$CHECKS_LOG"
  echo "검증 명령을 찾지 못함(오버라이드/매니페스트/자동탐지 모두 미매칭)." >> "$CHECKS_LOG"
  emit "skipped"
  echo "run-checks: SKIPPED ($TASK_ID) — 검증 명령 없음"
  exit 2
fi

# ── 실행 ──
log "소스=$SOURCE, ${#COMMANDS[@]}개 명령, cwd=$CWD, timeout=${CHECK_TIMEOUT}s"
: > "$CHECKS_LOG"
overall=0
TIMEOUT_BIN=""
command -v timeout >/dev/null 2>&1 && TIMEOUT_BIN="timeout"
for cmd in "${COMMANDS[@]}"; do
  {
    echo "===================================================================="
    echo "\$ $cmd"
    echo "--------------------------------------------------------------------"
  } >> "$CHECKS_LOG"
  start="$SECONDS"
  if [ -n "$TIMEOUT_BIN" ]; then
    ( cd "$CWD" && $TIMEOUT_BIN "$CHECK_TIMEOUT" bash -c "$cmd" ) >> "$CHECKS_LOG" 2>&1
  else
    ( cd "$CWD" && bash -c "$cmd" ) >> "$CHECKS_LOG" 2>&1
  fi
  rc=$?
  dur=$(( SECONDS - start ))
  printf '%s\t%s\t%s\n' "$rc" "$dur" "$cmd" >> "$RESULTS"
  {
    echo "--------------------------------------------------------------------"
    echo "[exit $rc, ${dur}s]"
    echo
  } >> "$CHECKS_LOG"
  if [ "$rc" -ne 0 ]; then overall=1; fi
done

if [ "$overall" -eq 0 ]; then
  emit "passed"
  echo "run-checks: PASSED ($TASK_ID) — ${#COMMANDS[@]}/${#COMMANDS[@]} 명령 통과"
  exit 0
else
  emit "failed"
  echo "run-checks: FAILED ($TASK_ID) — 일부 명령 실패 (자세한 건 checks.md/checks.log)"
  exit 1
fi
