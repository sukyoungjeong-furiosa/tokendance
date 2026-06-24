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
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug)[:40]
    name = f"{ts}-{safe}.md"
    with open(os.path.join(_sub(root, "pending"), name), "w") as f:
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
