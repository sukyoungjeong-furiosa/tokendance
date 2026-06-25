#!/usr/bin/env python3
"""워커 종료 상태 전이 표준화.

  python3 scripts/finish.py <task-id> --review                 # 결과물 리뷰 대기
  python3 scripts/finish.py <task-id> --needs-human            # 사람 판단 대기(reason 선택)
  python3 scripts/finish.py <task-id> --blocked  --reason "…"  # 기술적 막힘
  python3 scripts/finish.py <task-id> --failed   --reason "…"  # 회복 불가 실패(reason 필수)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import status as S


def finish(root, task_id, state, reason=None):
    if state not in ("review", "needs_human", "blocked", "failed"):
        raise ValueError(f"finish state must be review|needs_human|blocked|failed, got {state}")
    if state == "failed" and not reason:
        raise ValueError("--failed requires --reason")
    changes = {"state": state}
    if reason:
        changes["failure_reason"] = reason
    return S.update(root, task_id, changes)


def _default_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("task_id")
    ap.add_argument("--root", default=_default_root())
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--review", action="store_const", dest="state", const="review")
    g.add_argument("--needs-human", action="store_const", dest="state", const="needs_human")
    g.add_argument("--blocked", action="store_const", dest="state", const="blocked")
    g.add_argument("--failed", action="store_const", dest="state", const="failed")
    ap.add_argument("--reason")
    args = ap.parse_args(argv)
    finish(args.root, args.task_id, args.state, args.reason)


if __name__ == "__main__":
    main()
