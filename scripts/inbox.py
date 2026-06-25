#!/usr/bin/env python3
"""inbox 큐: pending/<ts>-<slug>.md 추가, processed/ 로 이동."""
import argparse
import os
import shutil
import sys
from datetime import datetime, timezone


def _sub(root, name):
    p = os.path.join(root, "state", "inbox", name)
    os.makedirs(p, exist_ok=True)
    return p


def add(root, text, slug="item"):
    # 마이크로초까지 포함해 한 poll 에서 연달아 들어온 메시지도 파일명이 안 겹치게 하고,
    # 그래도 겹치면(동일 마이크로초) 카운터를 붙여 절대 덮어쓰지 않는다(메시지 유실 방지).
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond:06d}Z"
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug)[:40]
    pending = _sub(root, "pending")
    name = f"{ts}-{safe}.md"
    n = 1
    while os.path.exists(os.path.join(pending, name)):
        name = f"{ts}-{safe}-{n}.md"
        n += 1
    with open(os.path.join(pending, name), "w") as f:
        f.write(text)
    return name


def list_pending(root):
    return sorted(os.listdir(_sub(root, "pending")))


def read_pending(root, name):
    with open(os.path.join(_sub(root, "pending"), name)) as f:
        return f.read()


def mark_processed(root, name):
    src = os.path.join(_sub(root, "pending"), name)
    dst = os.path.join(_sub(root, "processed"), name)
    shutil.move(src, dst)
    return dst


def _default_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=_default_root())
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("text")
    p.add_argument("--slug", default="item")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    if args.cmd == "add":
        print(add(args.root, args.text, args.slug))
    elif args.cmd == "list":
        for n in list_pending(args.root):
            print(n)


if __name__ == "__main__":
    main()
