#!/usr/bin/env python3
"""task 디렉토리 스캐폴딩/조회/카운트."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import status as S

_SCAFFOLD = {
    "task.md": "# {title}\n\n## 출처\n\n## 완료 기준\n",
    "progress.md": "",
    "steer.md": "",
    "steer.cursor": "0",
    "log.md": "",
    "review.md": "",
}


def create_task(root, task_id, title="", repo=""):
    S.init(root, task_id, title=title, repo=repo)
    td = os.path.join(root, "state", "tasks", task_id)
    for name, tmpl in _SCAFFOLD.items():
        p = os.path.join(td, name)
        if not os.path.exists(p):
            with open(p, "w") as f:
                f.write(tmpl.format(title=title))
    return td


def list_tasks(root, state=None):
    base = os.path.join(root, "state", "tasks")
    out = []
    if not os.path.isdir(base):
        return out
    for tid in sorted(os.listdir(base)):
        if not os.path.exists(os.path.join(base, tid, "status.json")):
            continue
        d = S.read(root, tid)
        if state is None or d.get("state") == state:
            out.append(d)
    return out


def count_running(root):
    return len(list_tasks(root, state="running"))


def _default_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=_default_root())
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new")
    p.add_argument("task_id")
    p.add_argument("--title", default="")
    p.add_argument("--repo", default="")
    p = sub.add_parser("list")
    p.add_argument("--state")
    sub.add_parser("count-running")
    args = ap.parse_args(argv)
    if args.cmd == "new":
        print(create_task(args.root, args.task_id, args.title, args.repo))
    elif args.cmd == "list":
        for d in list_tasks(args.root, args.state):
            print(f"{d['id']}\t{d['state']}\t{d.get('title','')}")
    elif args.cmd == "count-running":
        print(count_running(args.root))


if __name__ == "__main__":
    main()
