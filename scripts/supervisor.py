#!/usr/bin/env python3
"""상주 루프: 30분마다 헬스체크 후 headless 마스터 1회 기동."""
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import status as S
import tasks as TK

INTERVAL = 1800         # 30분 (base 틱 주기 — 일이 있을 때 깨어나는 간격)
MAX_INTERVAL = 21600    # 6시간 — idle 백오프 상한
BACKOFF_FACTOR = 2      # idle 틱이 연속될 때 다음 sleep 을 늘리는 배수
STALE_SECONDS = 1200    # 20분 — heartbeat 이보다 오래되면 죽은 워커로 간주

# 마스터가 이번 틱에 실제로 행동할 수 있는 일감 상태.
# needs_human/blocked 는 사람/외부 대기라 폴링 주기를 짧게 유지할 이유가 아니다 → idle 로 본다.
ACTIVE_STATES = ("queued", "running", "review")


def _parse_iso(s):
    # "2026-06-24T10:05:00Z" → aware datetime
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


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
    health_check(root)
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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=INTERVAL,
                    help="base 틱 주기(초). 일이 있을 때 깨어나는 간격이자 백오프 리셋 값.")
    ap.add_argument("--max-interval", type=int, default=MAX_INTERVAL,
                    help="idle 백오프 sleep 상한(초).")
    ap.add_argument("--backoff-factor", type=float, default=BACKOFF_FACTOR,
                    help="idle 틱이 연속될 때 다음 sleep 을 늘리는 배수.")
    args = ap.parse_args(argv)
    root = _default_root()
    claude_bin = os.environ["TOKENDANCE_CLAUDE"]
    if args.once:
        tick(root, claude_bin)
        return
    interval = args.interval
    while True:
        # idle 판정은 tick 직전에: 이번 사이클에 마스터가 처리할 일이 있었나.
        idle = not has_active_work(root)
        try:
            tick(root, claude_bin)
        except Exception as e:  # 루프는 절대 죽지 않는다
            print(f"[supervisor] tick error: {e}", file=sys.stderr)
        interval = next_interval(interval, idle, base=args.interval,
                                 max_interval=args.max_interval,
                                 factor=args.backoff_factor)
        time.sleep(interval)


if __name__ == "__main__":
    main()
