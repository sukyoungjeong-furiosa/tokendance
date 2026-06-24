#!/usr/bin/env python3
"""status.json 의 유일한 변경 통로. flock 직렬화 + atomic rename + version 관리."""
import argparse
import fcntl
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

STATES = {"queued", "running", "needs_human", "blocked", "review", "done", "failed"}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _task_dir(root, task_id):
    return os.path.join(root, "state", "tasks", task_id)


def _status_path(root, task_id):
    return os.path.join(_task_dir(root, task_id), "status.json")


def _lock_path(root, task_id):
    return os.path.join(_task_dir(root, task_id), "status.json.lock")


class _Lock:
    def __init__(self, path):
        self.path = path
        self.fd = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fd = open(self.path, "w")
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        except BaseException:
            self.fd.close()
            raise
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        self.fd.close()


def _atomic_write(path, data):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".status.", suffix=".tmp")
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


def read(root, task_id):
    with open(_status_path(root, task_id)) as f:
        return json.load(f)


def init(root, task_id, title="", repo=""):
    with _Lock(_lock_path(root, task_id)):
        sp = _status_path(root, task_id)
        if os.path.exists(sp):
            raise ValueError(f"task already exists: {task_id}")
        data = {
            "id": task_id, "title": title, "repo": repo,
            "state": "queued", "version": 1,
            "worker_pid": None, "worker_session_id": None, "branch": None,
            "heartbeat": None, "created": _now(), "updated": _now(),
            "attempts": 0, "failure_reason": None,
        }
        _atomic_write(sp, data)
        return data


def update(root, task_id, changes, expected_version=None, increment_attempts=False):
    with _Lock(_lock_path(root, task_id)):
        sp = _status_path(root, task_id)
        if not os.path.exists(sp):
            raise ValueError(f"no such task: {task_id}")
        with open(sp) as f:
            data = json.load(f)
        if expected_version is not None and data.get("version") != expected_version:
            raise ValueError(
                f"version mismatch: expected {expected_version}, got {data.get('version')}")
        data.update(changes)
        if increment_attempts:
            data["attempts"] = data.get("attempts", 0) + 1
        if "state" in data and data["state"] not in STATES:
            raise ValueError(f"invalid state: {data['state']}")
        if data.get("state") == "failed" and not data.get("failure_reason"):
            raise ValueError("state=failed requires failure_reason")
        data["version"] = data.get("version", 0) + 1
        data["updated"] = _now()
        _atomic_write(sp, data)
        return data


def heartbeat(root, task_id):
    return update(root, task_id, {"heartbeat": _now()})


def _default_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser(description="status.json 변경 통로")
    ap.add_argument("--root", default=_default_root())
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("task_id")
    p.add_argument("--title", default="")
    p.add_argument("--repo", default="")

    p = sub.add_parser("set")
    p.add_argument("task_id")
    p.add_argument("--state")
    p.add_argument("--pid", type=int)
    p.add_argument("--session")
    p.add_argument("--branch")
    p.add_argument("--failure-reason")
    p.add_argument("--bump-attempts", action="store_true")
    p.add_argument("--expected-version", type=int)

    p = sub.add_parser("get")
    p.add_argument("task_id")
    p.add_argument("--field")

    p = sub.add_parser("heartbeat")
    p.add_argument("task_id")

    args = ap.parse_args(argv)

    if args.cmd == "init":
        print(json.dumps(init(args.root, args.task_id, args.title, args.repo)))
    elif args.cmd == "set":
        changes = {}
        if args.state is not None:
            changes["state"] = args.state
        if args.pid is not None:
            changes["worker_pid"] = args.pid
        if args.session is not None:
            changes["worker_session_id"] = args.session
        if args.branch is not None:
            changes["branch"] = args.branch
        if args.failure_reason is not None:
            changes["failure_reason"] = args.failure_reason
        print(json.dumps(update(args.root, args.task_id, changes,
                                expected_version=args.expected_version,
                                increment_attempts=args.bump_attempts)))
    elif args.cmd == "get":
        d = read(args.root, args.task_id)
        print(d[args.field] if args.field else json.dumps(d, ensure_ascii=False))
    elif args.cmd == "heartbeat":
        print(json.dumps(heartbeat(args.root, args.task_id)))


if __name__ == "__main__":
    main()
