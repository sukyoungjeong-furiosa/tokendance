#!/usr/bin/env python3
"""task 디렉토리 스캐폴딩/조회/카운트/아카이브."""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import status as S

TERMINAL_STATES = ("done", "failed")

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


def archive(root, task_id):
    """종료(done/failed) task 를 state/tasks-archive/ 로 이동. 활성 task 는 거부.

    worktree 가 남아있으면 morning 의 안전 결정으로 'remove' 가능할 때만 회수하고,
    회수 불가(결과 미보존/조사 중 등)면 archive 를 거부한다 — 고아 worktree 방지(수동 확인 유도).
    반환: 이동된 아카이브 경로.
    """
    d = S.read(root, task_id)              # 없으면 여기서 에러
    state = d.get("state")
    if state not in TERMINAL_STATES:
        raise ValueError(f"종료 상태(done/failed)만 archive 가능 — 현재 '{state}'. 활성 task 는 보호됨.")

    wt = os.path.join(root, "state", "worktrees", task_id)
    if os.path.isdir(wt):
        import morning as M                # 지연 import (순환 방지)
        facts = M.gather_facts(root, d)
        dec = M.gc_decision(d, facts)
        if dec.get("action") == "remove":
            M.execute_gc(root, d, dec)
        else:
            raise ValueError(
                f"worktree 가 남아있고 자동 회수 대상이 아님({dec.get('reason')}). "
                f"수동으로 worktree 를 정리한 뒤 다시 archive 하세요. (archive 중단)")

    src = os.path.join(root, "state", "tasks", task_id)
    dst_base = os.path.join(root, "state", "tasks-archive")
    os.makedirs(dst_base, exist_ok=True)
    dst = os.path.join(dst_base, task_id)
    if os.path.exists(dst):
        raise ValueError(f"이미 아카이브에 존재: {dst}")
    shutil.move(src, dst)
    return dst


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
    p = sub.add_parser("archive")
    p.add_argument("task_id")
    args = ap.parse_args(argv)
    if args.cmd == "new":
        print(create_task(args.root, args.task_id, args.title, args.repo))
    elif args.cmd == "list":
        for d in list_tasks(args.root, args.state):
            print(f"{d['id']}\t{d['state']}\t{d.get('title','')}")
    elif args.cmd == "count-running":
        print(count_running(args.root))
    elif args.cmd == "archive":
        print("archived →", archive(args.root, args.task_id))


if __name__ == "__main__":
    main()
