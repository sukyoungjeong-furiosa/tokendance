#!/usr/bin/env python3
"""워커 체크포인트 한 명령: heartbeat 갱신 + steer 신규분 읽기 + cursor 전진.

  python3 scripts/checkpoint.py <task-id>

stdout: steer.md 에서 지난 cursor 이후 새로 추가된 지시(없으면 빈 출력).
워커는 각 작업 경계마다 이걸 호출하고, 출력이 있으면 그 지시를 반영한다.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import status as S


def read_new_steer(root, task_id):
    """steer.md 에서 steer.cursor(바이트 offset) 이후의 새 텍스트를 반환하고 cursor 를 EOF 로 전진."""
    td = S.task_dir(root, task_id)       # active/done 양쪽 해석
    steer = os.path.join(td, "steer.md")
    cursor = os.path.join(td, "steer.cursor")
    try:
        with open(steer, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        return ""
    try:
        with open(cursor) as f:
            off = int((f.read() or "0").strip() or "0")
    except (FileNotFoundError, ValueError):
        off = 0
    if off > len(data):           # steer.md 가 줄어든 비정상 상황 → 처음부터
        off = 0
    new = data[off:].decode("utf-8", "replace")
    with open(cursor, "w") as f:
        f.write(str(len(data)))
    return new


def checkpoint(root, task_id):
    S.heartbeat(root, task_id)
    return read_new_steer(root, task_id)


def _default_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("task_id")
    ap.add_argument("--root", default=_default_root())
    args = ap.parse_args(argv)
    out = checkpoint(args.root, args.task_id)
    if out.strip():
        sys.stdout.write(out if out.endswith("\n") else out + "\n")


if __name__ == "__main__":
    main()
