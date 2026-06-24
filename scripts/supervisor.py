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

INTERVAL = 1800       # 30분 (틱 주기)
STALE_SECONDS = 1200  # 20분 — heartbeat 이보다 오래되면 죽은 워커로 간주


def _parse_iso(s):
    # "2026-06-24T10:05:00Z" → aware datetime
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def health_check(root, now=None, stale_seconds=STALE_SECONDS):
    """running 인데 heartbeat 가 없거나 stale 한 워커를 needs_human 으로 전환.

    생사 판정을 pid 가 아니라 heartbeat 신선도로 하는 이유: setsid 후 claude 가
    재fork/재부모화하여 launch 시점의 pid 가 실제 워커 pid 와 불일치(Task 1 스파이크).
    """
    now = now or datetime.now(timezone.utc)
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


def _default_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=INTERVAL)
    args = ap.parse_args(argv)
    root = _default_root()
    claude_bin = os.environ["TOKENDANCE_CLAUDE"]
    if args.once:
        tick(root, claude_bin)
        return
    while True:
        try:
            tick(root, claude_bin)
        except Exception as e:  # 루프는 절대 죽지 않는다
            print(f"[supervisor] tick error: {e}", file=sys.stderr)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
