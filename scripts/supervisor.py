#!/usr/bin/env python3
"""상주 루프: 짧은 주기로 워커 헬스/즉사를 감시하고, 30분마다 headless 마스터를 1회 기동."""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import status as S
import tasks as TK
import prompt as PROMPT
import slack as SL

INTERVAL = 1800          # 30분 — 마스터 기동 base 주기(일이 있을 때)
MAX_INTERVAL = 21600     # 6시간 — idle 백오프 상한(마스터 주기)
BACKOFF_FACTOR = 2       # idle 마스터 틱이 연속될 때 다음 주기를 늘리는 배수
MONITOR_INTERVAL = 60    # 60초 — 헬스/즉사 감시 주기(마스터보다 훨씬 자주)
STALE_SECONDS = 1200     # 20분 — heartbeat 이보다 오래되면 죽은 워커로 간주(느린 주 판정)

# ── 즉사(fast-crash) 감지 파라미터 ──
GRACE_SECONDS = 180      # launch 후 이 시간 안에는 즉사로 판정하지 않는다(갓 띄운 워커 오판 방지)
PROGRESS_EPSILON = 30    # heartbeat 가 launch 보다 이 이상 신선하면 "한 번이라도 체크포인트함"으로 본다
MAX_ATTEMPTS = 3         # 즉사 자동 재시도 상한(리뷰 반려 재시도와 attempts 필드 공유)

# 마스터가 이번 틱에 실제로 행동할 수 있는 일감 상태(idle 백오프 판정용).
# needs_human/blocked 는 사람/외부 대기라 마스터 주기를 짧게 유지할 이유가 아니다 → idle 로 본다.
ACTIVE_STATES = ("queued", "running", "review")

# 워커 로그 끝에서 찾는 transient 오류 시그니처(대소문자 무시). claude 가 내부 재시도에 성공하면
# 워커가 진행(progressed)하므로 그 경우는 아래 detect_fast_crash 의 progressed 게이트에서 걸러진다.
TRANSIENT_RE = re.compile(
    r"(overloaded|rate.?limit|too many requests|temporarily unavailable|"
    r"service unavailable|bad gateway|connection reset|connection refused|"
    r"network error|timed?.?out|econnreset|etimedout|"
    r"\b(429|502|503|529)\b)",   # 흔한 평문 숫자(500 등)는 오탐 줄이려 제외, API 특이코드만
    re.IGNORECASE)


def _parse_iso(s):
    # "2026-06-24T10:05:00Z" → aware datetime
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(msg):
    # 사람용 텍스트 로그(start.sh 가 state/supervisor.log 로 리다이렉트). master stdout 과 섞인다.
    # 기계 판독용 구조화 관측은 _ticks_path/_metrics_path(별도 파일)를 쓴다(criteria #3,#4).
    print(f"[supervisor] {msg}", file=sys.stderr, flush=True)


def _ticks_path(root):
    # tick 당 JSON 1줄(append-only). 구조화 관측 — 타임스탬프/검사 워커 수/상태 전이.
    return os.path.join(root, "state", "supervisor.ticks.jsonl")


def _metrics_path(root):
    # 매 tick 덮어쓰는 bounded 요약 스냅샷(마스터/사람 조회 경로).
    return os.path.join(root, "state", "supervisor.metrics.json")


def _atomic_write_json(path, data):
    """status.py 와 동일한 tmp+fsync+rename 패턴. status.json 은 아니므로 직접 써도 규칙 위배 아님."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".sv.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def health_check(root, now=None, stale_seconds=STALE_SECONDS, max_attempts=MAX_ATTEMPTS,
                 pid_alive=None, relaunch=None, log=_log):
    """running 인데 heartbeat 가 없거나 stale 한 워커를 처리.

    stale 워커가 직전 세션을 갖고 있고(worker_session_id) pid 가 죽었고 재시도 한도가
    남았으면 `--resume` 으로 in-place 재투입한다(컨텍스트 보존, running 유지). 그렇지 않으면
    — 살아있는 hung(중복 위험) / 세션 없음(이어받을 것 없음) / 한도 초과 — needs_human 으로 에스컬레이션.

    생사 판정을 pid 가 아니라 heartbeat 신선도로 하는 이유: setsid 후 claude 가
    재fork/재부모화하여 launch 시점의 pid 가 실제 워커 pid 와 불일치(Task 1 스파이크).
    pid 는 "안전하게 재투입해도 되는가(=죽었는가)"의 보조 신호로만 쓴다.

    반환값: needs_human 으로 전환된 task id 목록(재투입된 것은 제외).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if relaunch is None:
        relaunch = _relaunch_worker
    if pid_alive is None:
        pid_alive = _pid_alive
    dead = []
    for d in TK.list_tasks(root, state="running"):
        hb = d.get("heartbeat")
        stale = (hb is None) or ((now - _parse_iso(hb)).total_seconds() > stale_seconds)
        if not stale:
            continue
        tid = d["id"]
        session = d.get("worker_session_id")
        attempts = d.get("attempts", 0)
        if session and not pid_alive(d.get("worker_pid")) and attempts < max_attempts:
            S.update(root, tid, {}, increment_attempts=True)   # attempts++ (상태 running 유지)
            ok = relaunch(root, tid)
            log(f"stale {tid}: heartbeat 정지 + pid 죽음 → --resume 재투입 "
                f"(attempt {attempts + 1}/{max_attempts}) relaunch={'ok' if ok else 'FAIL'}")
            continue
        reason = ("재투입 한도 초과" if (session and attempts >= max_attempts)
                  else "재개할 세션 없음" if not session
                  else "워커 살아있음(hung) — 중복 방지")
        S.update(root, tid, {
            "state": "needs_human",
            "failure_reason": f"heartbeat 정지(stale); {reason}",
        })
        log(f"stale {tid}: heartbeat 정지 → needs_human ({reason})")
        dead.append(tid)
    return dead


def alive_workers(root, now=None, stale_seconds=STALE_SECONDS):
    """running 이면서 heartbeat 가 신선한 워커 수(관측 메트릭 criteria #4).

    health_check 의 역(stale 가 아닌 running). 갓 재기동된 워커는 launch-worker.sh 가
    즉시 heartbeat 를 찍으므로 신선으로 잡힌다.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    n = 0
    for d in TK.list_tasks(root, state="running"):
        hb = d.get("heartbeat")
        if hb is not None and (now - _parse_iso(hb)).total_seconds() <= stale_seconds:
            n += 1
    return n


def _pid_alive(pid):
    """pid 가 살아있으면 True. 신뢰 보조 신호로만 사용(주 판정은 heartbeat/progress)."""
    if pid is None:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True   # 존재하지만 소유자 아님 → 살아있음
    except (OSError, ValueError):
        return False


def _read_log_tail(root, task_id, max_bytes=4096):
    """워커 로그 끝부분을 읽어 반환(없으면 "")."""
    p = os.path.join(root, "state", "workers", f"{task_id}.log")
    try:
        with open(p, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", "replace")
    except FileNotFoundError:
        return ""
    except OSError:
        return ""


def detect_fast_crash(d, now, grace=GRACE_SECONDS, pid_alive=_pid_alive, log_text=""):
    """running 워커가 "기동했으나 곧바로 죽은(즉사)" 상태면 사유 문자열, 아니면 None.

    규칙: launched_at 존재 AND grace 경과 AND launch 이후 미진행(체크포인트 없음)
          AND (pid 죽음 OR 로그 끝 transient 시그니처).
    - heartbeat/progress 가 주 판정(즉사 = 미진행). pid 는 보조 사망 증거로만 사용(criteria #3).
    - launched_at 없는 레거시 태스크는 빠른 감지 대상에서 제외 → 기존 staleness 에 위임(오탐 방지).
    """
    launched = d.get("launched_at")
    if not launched:
        return None
    age = (now - _parse_iso(launched)).total_seconds()
    if age < grace:           # grace window: 너무 어려서 판정 보류
        return None
    hb = d.get("heartbeat")
    progressed = bool(hb) and (_parse_iso(hb) - _parse_iso(launched)).total_seconds() > PROGRESS_EPSILON
    if progressed:            # 한 번이라도 체크포인트함 → 즉사 아님(staleness 가 담당)
        return None
    transient = bool(TRANSIENT_RE.search(log_text)) if log_text else False
    if transient:
        return "transient_log"
    pid = d.get("worker_pid")
    if pid is not None and not pid_alive(pid):   # pid 가 있을 때만 사망 증거로 사용
        return "pid_dead"
    return None               # 미진행이지만 살아있거나 pid 불명 + 시그니처 없음 → 보수적으로 둔다


def _relaunch_argv(root, task_id):
    """재투입은 항상 --resume: 직전 세션 컨텍스트를 이어받는다(없으면 launch-worker 가 fresh 폴백).
    fast-crash·stale 재시도 공통 진입점."""
    script = os.path.join(root, "scripts", "launch-worker.sh")
    return ["bash", script, task_id, "--resume"]


def _relaunch_worker(root, task_id):
    """launch-worker.sh --resume 로 워커를 in-place 재기동. 성공하면 True."""
    try:
        r = subprocess.run(_relaunch_argv(root, task_id), cwd=root,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode == 0
    except Exception:
        return False


def handle_fast_crashes(root, now=None, grace=GRACE_SECONDS, max_attempts=MAX_ATTEMPTS,
                        pid_alive=_pid_alive, relaunch=None, log=_log):
    """즉사한 워커를 빠르게 감지해 bounded 재시도 또는 needs_human 에스컬레이션.

    재시도는 launch-worker.sh in-place 재기동(상태 running 유지)으로 한다 → 마스터가 같은
    일감을 동시에 중복 디스패치하지 않는다(마스터는 queued 만 디스패치). 모든 결정은 tick 로그로.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if relaunch is None:
        relaunch = _relaunch_worker
    acted = []
    for d in TK.list_tasks(root, state="running"):
        tid = d["id"]
        reason = detect_fast_crash(d, now, grace, pid_alive, _read_log_tail(root, tid))
        if not reason:
            continue
        attempts = d.get("attempts", 0)
        if attempts < max_attempts:
            S.update(root, tid, {}, increment_attempts=True)   # attempts++ (상태는 running 유지)
            ok = relaunch(root, tid)
            log(f"fast-crash {tid}: {reason} → 재시도 (attempt {attempts + 1}/{max_attempts}) "
                f"relaunch={'ok' if ok else 'FAIL'}")
            acted.append((tid, "retry"))
        else:
            S.update(root, tid, {
                "state": "needs_human",
                "failure_reason": (f"fast-crash 재시도 한도 초과 ({attempts}/{max_attempts}); "
                                   f"마지막 신호={reason}"),
            })
            log(f"fast-crash {tid}: {reason} → 재시도 한도 초과 ({attempts}/{max_attempts}) → needs_human")
            acted.append((tid, "needs_human"))
    return acted


def _build_transitions(dead, acted):
    """health_check(dead) + handle_fast_crashes(acted) 결과를 구조화 transition 리스트로."""
    out = []
    for tid, action in acted:
        out.append({"task": tid, "action": action, "by": "fast_crash"})
    for tid in dead:
        out.append({"task": tid, "action": "needs_human", "by": "health_check",
                    "reason": "stale_heartbeat"})
    return out


def monitor(root, now=None):
    """짧은 주기로 도는 경량 감시: 즉사 빠른 감지/재시도 + heartbeat staleness 판정.

    즉사 처리(handle_fast_crashes)를 먼저 한다 → transient 크래시는 staleness 로 needs_human 되기
    전에 자동 재시도되어야 하므로(특히 supervisor 가 한동안 멈췄다 재기동된 경우).

    반환: 이 tick 의 구조화 레코드(관측성 criteria #3). 호출측이 record_tick 으로 영속화.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    running_checked = len(TK.list_tasks(root, state="running"))   # 이번 틱에 검사한 워커 수
    acted = handle_fast_crashes(root, now=now)
    dead = health_check(root, now=now)
    try:
        new_msgs = SL.poll_new(root)   # 봇 토큰으로 새 DM 을 inbox 로(LLM 없이). 새 메시지 수.
    except Exception as e:
        print(f"[supervisor] slack poll error: {e}", file=sys.stderr, flush=True)
        new_msgs = 0
    return {
        "ts": _iso(now),
        "running_checked": running_checked,
        "alive_workers": alive_workers(root, now=now),   # transition 적용 후 신선 running 수
        "transitions": _build_transitions(dead, acted),
        "new_slack_msgs": new_msgs,
    }


def record_tick(root, tick, run_state):
    """tick 레코드를 ticks.jsonl 에 append + metrics.json 스냅샷 덮어쓰기(criteria #3,#4).

    run_state: {"pid", "started_at", "ticks_total"} — 호출측이 보유하는 supervisor 가동 상태.
    ticks_total 을 증가시키는 쪽이라 호출측 dict 를 in-place 갱신한다.
    """
    run_state["ticks_total"] = run_state.get("ticks_total", 0) + 1
    p = _ticks_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(tick, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    _atomic_write_json(_metrics_path(root), {
        "last_tick_at": tick["ts"],
        "alive_workers": tick["alive_workers"],
        "running_workers": tick["running_checked"],
        "supervisor_pid": run_state.get("pid"),
        "started_at": run_state.get("started_at"),
        "ticks_total": run_state["ticks_total"],
        "last_transitions": tick["transitions"],
        "new_slack_msgs": tick["new_slack_msgs"],
    })


def read_metrics(root):
    """metrics.json 을 읽어 dict 반환(없으면 None). 마스터/사람 조회 경로."""
    try:
        with open(_metrics_path(root)) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def startup_reabsorb(root, now=None, log=_log):
    """(재)기동 시 상태 재흡수 관측(criteria #2).

    실제 재흡수는 monitor 가 매 tick status.json 을 디스크에서 새로 읽어 무상태로 처리하므로
    별도 동기화가 필요 없다. 여기서는 재기동을 가시화하기 위해 진행 중 워커 수와 직전 tick 시각을
    로깅하고 running 목록을 돌려준다(중복 감시/오판 없음을 검증 가능하게).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    running = TK.list_tasks(root, state="running")
    prev = read_metrics(root)
    last_tick = prev.get("last_tick_at") if prev else None
    log(f"startup: 상태 재흡수 running={len(running)} prev_tick={last_tick or 'none'}")
    return running


def run_master(root, claude_bin):
    user_prompt = ("너는 tokendance 마스터다. 시스템 프롬프트의 지침대로 "
                   "정확히 한 번의 관리 사이클을 수행한 뒤 종료하라.")
    sysprompt = PROMPT.build(root, "master")   # prompts/master/*.md 조립
    env = {**os.environ, "IS_SANDBOX": "1"}  # root 에서 자율 권한 허용에 필수
    return subprocess.run(
        [claude_bin, "-p", user_prompt,
         "--append-system-prompt", sysprompt,
         "--dangerously-skip-permissions"],
        cwd=root, env=env)


def tick(root, claude_bin, run_state=None):
    if run_state is None:
        run_state = {"pid": os.getpid(), "started_at": _iso(datetime.now(timezone.utc)),
                     "ticks_total": 0}
    rec = monitor(root)
    record_tick(root, rec, run_state)
    run_master(root, claude_bin)


def has_active_work(root):
    """이번 틱에 마스터가 처리할 일감이 있는가(= idle 이 아닌가)."""
    return any(TK.list_tasks(root, state=s) for s in ACTIVE_STATES)


def next_interval(prev_interval, idle, base=INTERVAL,
                  max_interval=MAX_INTERVAL, factor=BACKOFF_FACTOR):
    """다음 sleep 간격(초)을 계산하는 순수 함수(부작용 없음).

    - idle=False(이번 틱에 처리할 일이 있었음): base 로 즉시 복귀(백오프 리셋).
    - idle=True: 직전 간격을 factor 배로 늘리되 max_interval 로 클램프.
    """
    if not idle:
        return base
    return min(prev_interval * factor, max_interval)


def _default_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def print_metrics(root):
    """metrics.json 요약을 사람이 읽기 좋게 출력(조회 경로 criteria #4)."""
    m = read_metrics(root)
    if not m:
        print("supervisor metrics: 아직 없음(supervisor 가 한 번도 tick 하지 않음)")
        return
    print(f"supervisor metrics ({_metrics_path(root)}):")
    print(f"  last_tick_at   : {m.get('last_tick_at')}")
    print(f"  alive_workers  : {m.get('alive_workers')}")
    print(f"  running_workers: {m.get('running_workers')}")
    print(f"  supervisor_pid : {m.get('supervisor_pid')}")
    print(f"  started_at     : {m.get('started_at')}")
    print(f"  ticks_total    : {m.get('ticks_total')}")
    tr = m.get("last_transitions") or []
    print(f"  last_transitions: {len(tr)}")
    for t in tr:
        print(f"    - {t.get('task')} → {t.get('action')} (by {t.get('by')})")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", choices=["run", "metrics"], default="run",
                    help="run(기본, 상주 루프) | metrics(현재 메트릭 요약 출력 후 종료)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=INTERVAL,
                    help="마스터 기동 base 주기(초). 일이 있을 때 간격이자 idle 백오프 리셋 값.")
    ap.add_argument("--max-interval", type=int, default=MAX_INTERVAL,
                    help="idle 백오프 마스터 주기 상한(초).")
    ap.add_argument("--backoff-factor", type=float, default=BACKOFF_FACTOR,
                    help="idle 마스터 틱이 연속될 때 다음 주기를 늘리는 배수.")
    ap.add_argument("--monitor-interval", type=int, default=MONITOR_INTERVAL,
                    help="헬스/즉사 감시 주기(초). 마스터보다 훨씬 자주.")
    args = ap.parse_args(argv)
    root = _default_root()
    if args.mode == "metrics":       # 조회 전용: claude_bin 없이도 동작
        print_metrics(root)
        return
    claude_bin = os.environ["TOKENDANCE_CLAUDE"]
    run_state = {"pid": os.getpid(), "started_at": _iso(datetime.now(timezone.utc)),
                 "ticks_total": 0}
    if args.once:
        tick(root, claude_bin, run_state)
        return
    startup_reabsorb(root)           # 재기동 가시화(criteria #2): 진행 중 워커/직전 tick 로깅.
    # monitor 는 monitor_interval(60초)마다 — 즉사 빠른 감지/재시도.
    # run_master 는 idle 백오프 주기마다(일 있으면 base, idle 면 점점 늘려 max). 첫 사이클 즉시 기동.
    next_master = 0.0
    master_interval = args.interval
    while True:
        try:
            rec = monitor(root)
            record_tick(root, rec, run_state)   # 구조화 tick 영속화(관측성)
            new_msgs = rec["new_slack_msgs"]
        except Exception as e:  # 루프는 절대 죽지 않는다
            print(f"[supervisor] monitor error: {e}", file=sys.stderr, flush=True)
            new_msgs = 0
        if new_msgs:                 # 새 Slack 메시지 → 마스터를 즉시 깨운다(백오프 무시)
            next_master = 0.0
        if time.monotonic() >= next_master:
            idle = not has_active_work(root)   # 마스터 기동 직전 판정
            try:
                run_master(root, claude_bin)
            except Exception as e:
                print(f"[supervisor] master error: {e}", file=sys.stderr, flush=True)
            master_interval = next_interval(master_interval, idle, base=args.interval,
                                            max_interval=args.max_interval,
                                            factor=args.backoff_factor)
            next_master = time.monotonic() + master_interval
        time.sleep(args.monitor_interval)


if __name__ == "__main__":
    main()
