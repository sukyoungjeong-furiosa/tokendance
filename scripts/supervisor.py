#!/usr/bin/env python3
"""상주 루프: 짧은 주기로 워커 헬스/즉사를 감시하고, 30분마다 headless 마스터를 1회 기동."""
import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import status as S
import tasks as TK

INTERVAL = 1800          # 30분 — 마스터 기동 주기
MONITOR_INTERVAL = 60    # 60초 — 헬스/즉사 감시 주기(마스터보다 훨씬 자주)
STALE_SECONDS = 1200     # 20분 — heartbeat 이보다 오래되면 죽은 워커로 간주(느린 주 판정)

# ── 즉사(fast-crash) 감지 파라미터 ──
GRACE_SECONDS = 180      # launch 후 이 시간 안에는 즉사로 판정하지 않는다(갓 띄운 워커 오판 방지)
PROGRESS_EPSILON = 30    # heartbeat 가 launch 보다 이 이상 신선하면 "한 번이라도 체크포인트함"으로 본다
MAX_ATTEMPTS = 3         # 즉사 자동 재시도 상한(리뷰 반려 재시도와 attempts 필드 공유)

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


def _log(msg):
    # tick 로그(start.sh 가 state/supervisor.log 로 리다이렉트). 판정/재시도 관측 가능성(criteria #4).
    print(f"[supervisor] {msg}", file=sys.stderr, flush=True)


def health_check(root, now=None, stale_seconds=STALE_SECONDS):
    """running 인데 heartbeat 가 없거나 stale 한 워커를 needs_human 으로 전환.

    생사 판정을 pid 가 아니라 heartbeat 신선도로 하는 이유: setsid 후 claude 가
    재fork/재부모화하여 launch 시점의 pid 가 실제 워커 pid 와 불일치(Task 1 스파이크).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    dead = []
    for d in TK.list_tasks(root, state="running"):
        hb = d.get("heartbeat")
        stale = (hb is None) or ((now - _parse_iso(hb)).total_seconds() > stale_seconds)
        if stale:
            S.update(root, d["id"], {"state": "needs_human"})
            dead.append(d["id"])
    return dead


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


def _relaunch_worker(root, task_id):
    """launch-worker.sh 로 워커를 in-place 재기동. 성공하면 True."""
    script = os.path.join(root, "scripts", "launch-worker.sh")
    try:
        r = subprocess.run(["bash", script, task_id], cwd=root,
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


def monitor(root):
    """짧은 주기로 도는 경량 감시: 즉사 빠른 감지/재시도 + heartbeat staleness 판정.

    즉사 처리(handle_fast_crashes)를 먼저 한다 → transient 크래시는 staleness 로 needs_human 되기
    전에 자동 재시도되어야 하므로(특히 supervisor 가 한동안 멈췄다 재기동된 경우).
    """
    handle_fast_crashes(root)
    health_check(root)


def run_master(root, claude_bin):
    master_md = os.path.join(root, "prompts", "master.md")
    prompt = (f"너는 tokendance 마스터다. {root}/CLAUDE.md 와 {master_md} 를 읽고 "
              f"정확히 한 번의 관리 사이클을 수행한 뒤 종료하라.")
    with open(master_md) as f:
        sysprompt = f.read()
    env = {**os.environ, "IS_SANDBOX": "1"}  # root 에서 자율 권한 허용에 필수
    return subprocess.run(
        [claude_bin, "-p", prompt,
         "--append-system-prompt", sysprompt,
         "--dangerously-skip-permissions"],
        cwd=root, env=env)


def tick(root, claude_bin):
    monitor(root)
    run_master(root, claude_bin)


def _default_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=INTERVAL,
                    help="마스터 기동 주기(초)")
    ap.add_argument("--monitor-interval", type=int, default=MONITOR_INTERVAL,
                    help="헬스/즉사 감시 주기(초)")
    args = ap.parse_args(argv)
    root = _default_root()
    claude_bin = os.environ["TOKENDANCE_CLAUDE"]
    if args.once:
        tick(root, claude_bin)
        return
    # monitor 는 monitor_interval 마다, run_master 는 interval 마다. 첫 사이클은 즉시 마스터 기동.
    next_master = 0.0
    while True:
        try:
            monitor(root)
        except Exception as e:  # 루프는 절대 죽지 않는다
            print(f"[supervisor] monitor error: {e}", file=sys.stderr, flush=True)
        if time.monotonic() >= next_master:
            try:
                run_master(root, claude_bin)
            except Exception as e:
                print(f"[supervisor] master error: {e}", file=sys.stderr, flush=True)
            next_master = time.monotonic() + args.interval
        time.sleep(args.monitor_interval)


if __name__ == "__main__":
    main()
