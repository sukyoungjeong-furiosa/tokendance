# tokendance 마스터 에이전트 하네스 MVP 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 상시 호스트 위에서 30분마다 깨어나, 격리된 워커 프로세스에 코딩 일감을 시키고, 결과물을 직접 리뷰하며, 진행/판단 필요 지점을 보고하고 사람 피드백을 워커에 주입하는 자율 매니저 에이전트의 MVP를 구축한다.

**Architecture:** `nohup` supervisor 루프(상주)가 30분마다 헬스체크 후 headless `claude` 마스터를 1회 기동한다. 마스터는 inbox 큐를 처리하고, status.json 상태머신을 스캔하며, `launch-worker.sh`로 워커를 detached OS 프로세스로 띄우고(기다리지 않음), 완료물을 리뷰하고, 리포트를 쓴다. 모든 소통은 tokendance 레포 안 파일을 통한다. status.json은 `status.py`(flock+atomic)로만 변경한다.

**Tech Stack:** Python 3.10 **표준 라이브러리만**(`unittest`, `fcntl`, `json`, `os`, `subprocess`, `argparse`, `tempfile`, `shutil`, `datetime`), Bash, 네이티브 `claude` 바이너리. 외부 패키지/pip/jq/node 불사용.

## Global Constraints

- **Python 3.10 표준 라이브러리만.** pip 패키지 금지(pip 자체가 없음). 테스트는 `python3 -m unittest`.
- **`jq` 금지.** 모든 JSON 입출력은 Python(`status.py`)이 담당.
- **status.json 변경은 `scripts/status.py` 경유만.** 직접 편집·다른 도구 금지. (flock 직렬화 + atomic rename + version+1)
- **워커 프로세스 기동은 `scripts/launch-worker.sh` 경유만.** 마스터가 자유 shell로 `setsid`/`kill` 금지.
- **상태 7개:** `queued | running | needs_human | blocked | review | done | failed`. `failed`는 `failure_reason` 필수.
- **파일 단일 소유자:** progress/log/steer.cursor=워커, review/reports=마스터, steer.md=append-only, status.json=status.py 경유.
- **claude 바이너리 경로는 환경변수 `TOKENDANCE_CLAUDE`로 주입.** 하드코딩 금지(버전 디렉토리가 바뀜).
- **모든 claude 기동은 `IS_SANDBOX=1` + `--dangerously-skip-permissions`.** root 실행이라 IS_SANDBOX 없이는 거부됨(Task 1 스파이크 확인).
- **워커 생사 판정은 heartbeat 신선도로 한다 (pid 생존 아님).** setsid 후 claude가 재fork/재부모화해 `$!`가 실제 pid와 불일치(스파이크 확인). staleness 임계 = 1200초(20분). worker_pid 는 디버깅용 best-effort 저장.
- **타겟 레포 변경은 브랜치/PR로만.** main 직접 push 금지.
- **자주 커밋.** 각 태스크 끝에 커밋.
- 레포 루트의 모든 함수는 `root` 인자를 받아 테스트 가능해야 한다(CLI는 `dirname(dirname(__file__))`로 기본값 계산).

---

## File Structure

```
tokendance/
  CLAUDE.md                 # 마스터/워커 공유 운영 규칙 (Task 9)
  prompts/master.md         # 마스터 시스템 프롬프트 (Task 8)
  prompts/worker.md         # 워커 시스템 프롬프트 (Task 9)
  scripts/status.py         # status.json 유일 변경 통로 (Task 2)
  scripts/tasks.py          # task 디렉토리 스캐폴딩/조회/카운트 (Task 3)
  scripts/inbox.py          # inbox pending/processed 큐 (Task 4)
  scripts/prepare-worktree.sh   # worktree 셋업 MVP stub (Task 5)
  scripts/launch-worker.sh  # worktree + setsid claude 워커 기동 (Task 6)
  scripts/supervisor.py     # 헬스체크 + 마스터 기동 + 루프 (Task 7)
  scripts/start.sh, stop.sh # supervisor 기동/정지 (Task 7)
  library/index.md          # 지식 라이브러리 뼈대 (Task 10)
  tests/test_status.py, test_tasks.py, test_inbox.py, test_supervisor.py
  state/                    # 런타임 생성 (gitignore 일부)
```

---

## Task 1: 기반 검증 스파이크 (headless + detached + MCP)

이 스파이크가 실패하면 아키텍처 전제가 무너지므로 **반드시 먼저** 한다. 코드가 아니라 사실 확인이며, 산출물은 문서화된 결론이다.

**Files:**
- Create: `docs/superpowers/spikes/2026-06-24-foundation-findings.md`

- [ ] **Step 1: claude 바이너리 경로 고정**

```bash
ls -dt /root/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude | head -1
# 출력 경로를 export 해서 이후 모두 사용
export TOKENDANCE_CLAUDE="$(ls -dt /root/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude | head -1)"
echo "$TOKENDANCE_CLAUDE"
```
Expected: 실제 파일 경로 1개 출력.

- [ ] **Step 2: headless 자율 실행 스모크**

```bash
cd /tmp && rm -rf td-spike && mkdir td-spike && cd td-spike
"$TOKENDANCE_CLAUDE" -p "Create a file named hello.txt containing exactly the word: hi. Then stop." --dangerously-skip-permissions
cat hello.txt
```
Expected: `hi` 출력. (실패 시: 인증/권한 문제 — findings에 기록하고 사람 에스컬레이션.)

- [ ] **Step 3: detached 생존 확인**

```bash
cd /tmp/td-spike
setsid "$TOKENDANCE_CLAUDE" -p "Sleep is not available; instead create a file slow.txt with the word done after writing the word start to slow.txt first." --dangerously-skip-permissions > worker.log 2>&1 < /dev/null &
WPID=$!; disown || true
echo "worker pid=$WPID"; ps -o pid=,stat= -p "$WPID" || echo "not running"
# 부모 쉘과 독립적으로 동작하는지(프로세스 그룹 분리) 확인
ps -o pid=,pgid=,ppid= -p "$WPID"
```
Expected: 워커 PID가 살아있고 자체 프로세스 그룹(pgid==pid)을 가짐 → 부모 종료와 무관히 생존 가능.

- [ ] **Step 4: Slack MCP의 headless 가용성 확인**

```bash
cd /tmp/td-spike
"$TOKENDANCE_CLAUDE" -p "List the MCP tools available to you. If any Slack tool exists, print its exact name. If none, print: NO_SLACK_MCP." --dangerously-skip-permissions 2>&1 | tail -20
```
Expected: Slack 툴 이름이 보이면 → 마스터 프롬프트에서 직접 사용 가능(Task 11 경로 A). `NO_SLACK_MCP`이면 → Task 11은 봇 토큰 폴백 또는 dogfood 연기.

- [ ] **Step 5: findings 문서화 + 커밋**

`docs/superpowers/spikes/2026-06-24-foundation-findings.md`에 각 스텝의 실제 결과(성공/실패, Slack 가용 여부, 고정한 claude 경로)를 적는다. 환경변수 영구화를 위해 같은 export 라인을 문서에 박는다.

```bash
git add docs/superpowers/spikes/2026-06-24-foundation-findings.md
git commit -m "spike: validate headless claude, detached survival, slack mcp availability"
```

**결정 게이트:** Step 2·3 실패 시 여기서 멈추고 사람과 재설계. 통과 시 Task 2로.

---

## Task 2: status.py — status.json 상태머신 (유일 변경 통로)

**Files:**
- Create: `scripts/status.py`
- Test: `tests/test_status.py`

**Interfaces:**
- Produces:
  - `init(root, task_id, title="", repo="") -> dict` — task 디렉토리 생성 + status.json(version=1, state="queued", attempts=0)
  - `read(root, task_id) -> dict`
  - `update(root, task_id, changes: dict, expected_version=None) -> dict` — flock 직렬화 + atomic write, version+1, updated 갱신, 상태/failure_reason 검증
  - `heartbeat(root, task_id) -> dict`
  - 모듈 상수 `STATES: set[str]`
  - CLI: `status.py init|set|get|heartbeat <task-id> [...]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_status.py`:
```python
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import status as S


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_creates_version_1_queued(self):
        S.init(self.root, "t1", title="T", repo="r")
        d = S.read(self.root, "t1")
        self.assertEqual(d["version"], 1)
        self.assertEqual(d["state"], "queued")
        self.assertEqual(d["attempts"], 0)
        self.assertIsNone(d["failure_reason"])

    def test_init_twice_rejected(self):
        S.init(self.root, "t1")
        with self.assertRaises(ValueError):
            S.init(self.root, "t1")

    def test_set_bumps_version(self):
        S.init(self.root, "t1")
        S.update(self.root, "t1", {"state": "running", "worker_pid": 42})
        d = S.read(self.root, "t1")
        self.assertEqual(d["state"], "running")
        self.assertEqual(d["worker_pid"], 42)
        self.assertEqual(d["version"], 2)

    def test_invalid_state_rejected(self):
        S.init(self.root, "t1")
        with self.assertRaises(ValueError):
            S.update(self.root, "t1", {"state": "bogus"})

    def test_failed_requires_reason(self):
        S.init(self.root, "t1")
        with self.assertRaises(ValueError):
            S.update(self.root, "t1", {"state": "failed"})
        S.update(self.root, "t1", {"state": "failed", "failure_reason": "boom"})
        self.assertEqual(S.read(self.root, "t1")["state"], "failed")

    def test_version_mismatch_rejected(self):
        S.init(self.root, "t1")
        with self.assertRaises(ValueError):
            S.update(self.root, "t1", {"state": "running"}, expected_version=999)

    def test_heartbeat_updates_only_heartbeat(self):
        S.init(self.root, "t1")
        before = S.read(self.root, "t1")
        S.heartbeat(self.root, "t1")
        after = S.read(self.root, "t1")
        self.assertEqual(after["version"], before["version"] + 1)
        self.assertIsNotNone(after["heartbeat"])
        self.assertEqual(after["state"], before["state"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /root/src/tokendance && python3 -m unittest discover -s tests -p 'test_status.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'status'`.

- [ ] **Step 3: status.py 구현**

`scripts/status.py`:
```python
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
        fcntl.flock(self.fd, fcntl.LOCK_EX)
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


def update(root, task_id, changes, expected_version=None):
    with _Lock(_lock_path(root, task_id)):
        sp = _status_path(root, task_id)
        if not os.path.exists(sp):
            raise ValueError(f"no such task: {task_id}")
        with open(sp) as f:
            data = json.load(f)
        if expected_version is not None and data.get("version") != expected_version:
            raise ValueError(
                f"version mismatch: expected {expected_version}, got {data.get('version')}")
        if "state" in changes and changes["state"] not in STATES:
            raise ValueError(f"invalid state: {changes['state']}")
        merged = {**data, **changes}
        if merged.get("state") == "failed" and not merged.get("failure_reason"):
            raise ValueError("state=failed requires failure_reason")
        data.update(changes)
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
        if args.bump_attempts:
            cur = read(args.root, args.task_id)
            changes["attempts"] = cur.get("attempts", 0) + 1
        print(json.dumps(update(args.root, args.task_id, changes,
                                expected_version=args.expected_version)))
    elif args.cmd == "get":
        d = read(args.root, args.task_id)
        print(d[args.field] if args.field else json.dumps(d, ensure_ascii=False))
    elif args.cmd == "heartbeat":
        print(json.dumps(heartbeat(args.root, args.task_id)))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /root/src/tokendance && python3 -m unittest discover -s tests -p 'test_status.py' -v`
Expected: PASS — 7 tests OK.

- [ ] **Step 5: CLI 스모크**

Run:
```bash
cd /root/src/tokendance
python3 scripts/status.py init smoke1 --title "스모크" --repo demo
python3 scripts/status.py set smoke1 --state running --pid 123
python3 scripts/status.py get smoke1 --field state
python3 scripts/status.py heartbeat smoke1
rm -rf state/tasks/smoke1
```
Expected: `running` 출력, JSON에 version 증가.

- [ ] **Step 6: 커밋**

```bash
git add scripts/status.py tests/test_status.py
git commit -m "feat: status.py — atomic flock-guarded status.json state machine"
```

---

## Task 3: tasks.py — task 스캐폴딩/조회/카운트

**Files:**
- Create: `scripts/tasks.py`
- Test: `tests/test_tasks.py`

**Interfaces:**
- Consumes: `status` 모듈(`init`, `read`)
- Produces:
  - `create_task(root, task_id, title="", repo="") -> str` (task 디렉토리 경로). status.json + task.md/progress.md/steer.md/steer.cursor/log.md/review.md 스캐폴딩.
  - `list_tasks(root, state=None) -> list[dict]`
  - `count_running(root) -> int`
  - CLI: `tasks.py new|list|count-running`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_tasks.py`:
```python
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import tasks as TK
import status as S


class TasksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_scaffolds_files(self):
        td = TK.create_task(self.root, "t1", title="제목", repo="r")
        for name in ("status.json", "task.md", "progress.md",
                     "steer.md", "steer.cursor", "log.md", "review.md"):
            self.assertTrue(os.path.exists(os.path.join(td, name)), name)
        with open(os.path.join(td, "steer.cursor")) as f:
            self.assertEqual(f.read().strip(), "0")

    def test_list_filters_by_state(self):
        TK.create_task(self.root, "t1")
        TK.create_task(self.root, "t2")
        S.update(self.root, "t2", {"state": "running", "worker_pid": 1})
        running = TK.list_tasks(self.root, state="running")
        self.assertEqual([d["id"] for d in running], ["t2"])
        self.assertEqual(len(TK.list_tasks(self.root)), 2)

    def test_count_running(self):
        TK.create_task(self.root, "t1")
        TK.create_task(self.root, "t2")
        S.update(self.root, "t1", {"state": "running", "worker_pid": 1})
        self.assertEqual(TK.count_running(self.root), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /root/src/tokendance && python3 -m unittest discover -s tests -p 'test_tasks.py' -v`
Expected: FAIL — `No module named 'tasks'`.

- [ ] **Step 3: tasks.py 구현**

`scripts/tasks.py`:
```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /root/src/tokendance && python3 -m unittest discover -s tests -p 'test_tasks.py' -v`
Expected: PASS — 3 tests OK.

- [ ] **Step 5: 커밋**

```bash
git add scripts/tasks.py tests/test_tasks.py
git commit -m "feat: tasks.py — task scaffolding, listing, running-count"
```

---

## Task 4: inbox.py — pending/processed 큐

**Files:**
- Create: `scripts/inbox.py`
- Test: `tests/test_inbox.py`

**Interfaces:**
- Produces:
  - `add(root, text, slug="item") -> str` (생성된 파일명). `state/inbox/pending/<ts>-<slug>.md` 작성.
  - `list_pending(root) -> list[str]`
  - `read_pending(root, name) -> str`
  - `mark_processed(root, name) -> str` (이동 후 경로). pending → processed 이동.
  - CLI: `inbox.py add|list`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_inbox.py`:
```python
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import inbox as IB


class InboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_then_list_then_read(self):
        name = IB.add(self.root, "로그인 버그 고쳐줘", slug="login")
        self.assertIn(name, IB.list_pending(self.root))
        self.assertEqual(IB.read_pending(self.root, name), "로그인 버그 고쳐줘")

    def test_mark_processed_moves_file(self):
        name = IB.add(self.root, "x", slug="x")
        IB.mark_processed(self.root, name)
        self.assertNotIn(name, IB.list_pending(self.root))
        moved = os.path.join(self.root, "state", "inbox", "processed", name)
        self.assertTrue(os.path.exists(moved))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /root/src/tokendance && python3 -m unittest discover -s tests -p 'test_inbox.py' -v`
Expected: FAIL — `No module named 'inbox'`.

- [ ] **Step 3: inbox.py 구현**

`scripts/inbox.py`:
```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /root/src/tokendance && python3 -m unittest discover -s tests -p 'test_inbox.py' -v`
Expected: PASS — 2 tests OK.

- [ ] **Step 5: 커밋**

```bash
git add scripts/inbox.py tests/test_inbox.py
git commit -m "feat: inbox.py — pending/processed file queue"
```

---

## Task 5: prepare-worktree.sh — MVP stub

실제 공통 artifact 셋업은 dogfood 백로그(항목 1). MVP는 동작하는 no-op stub.

**Files:**
- Create: `scripts/prepare-worktree.sh`

- [ ] **Step 1: stub 작성**

`scripts/prepare-worktree.sh`:
```bash
#!/usr/bin/env bash
# MVP stub. 실제 worktree + 공통 artifact 셋업은 dogfood 백로그 항목 1에서 구현.
# 인자: $1 = task-id
set -euo pipefail
TASK_ID="${1:?task-id required}"
echo "[prepare-worktree] stub for task ${TASK_ID} (no-op; dogfood backlog #1에서 구현 예정)"
exit 0
```

- [ ] **Step 2: 실행 권한 + 스모크**

Run:
```bash
cd /root/src/tokendance && chmod +x scripts/prepare-worktree.sh
scripts/prepare-worktree.sh demo-task; echo "exit=$?"
```
Expected: stub 메시지 출력, `exit=0`.

- [ ] **Step 3: 커밋**

```bash
git add scripts/prepare-worktree.sh
git commit -m "feat: prepare-worktree.sh MVP stub (real setup deferred to dogfood)"
```

---

## Task 6: launch-worker.sh — detached 워커 기동

**Files:**
- Create: `scripts/launch-worker.sh`
- Test: `tests/test_launch_worker.sh` (bash 기반, fake claude 사용)

**Interfaces:**
- Consumes: `prepare-worktree.sh`, `status.py`, `prompts/worker.md`, 환경변수 `TOKENDANCE_CLAUDE`
- Produces: 워커를 detached로 띄우고 status를 `running`+pid로 설정. stdout에 PID 출력.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_launch_worker.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# fake claude: 잠깐 살아있다 종료
FAKE="$WORK/fake-claude"
cat > "$FAKE" <<'EOF'
#!/usr/bin/env bash
echo "fake worker args: $*"
sleep 2
EOF
chmod +x "$FAKE"

# fake root 구조
mkdir -p "$WORK/scripts" "$WORK/prompts"
cp "$ROOT/scripts/status.py" "$WORK/scripts/"
cp "$ROOT/scripts/prepare-worktree.sh" "$WORK/scripts/"
cp "$ROOT/scripts/launch-worker.sh" "$WORK/scripts/"
echo "worker prompt" > "$WORK/prompts/worker.md"
python3 "$WORK/scripts/status.py" --root "$WORK" init t1 --title T

TOKENDANCE_CLAUDE="$FAKE" bash "$WORK/scripts/launch-worker.sh" t1
sleep 1
STATE="$(python3 "$WORK/scripts/status.py" --root "$WORK" get t1 --field state)"
PID="$(python3 "$WORK/scripts/status.py" --root "$WORK" get t1 --field worker_pid)"
test "$STATE" = "running" || { echo "FAIL: state=$STATE"; exit 1; }
test -n "$PID" && kill -0 "$PID" 2>/dev/null || { echo "FAIL: worker pid not alive ($PID)"; exit 1; }
test -f "$WORK/state/workers/t1.log" || { echo "FAIL: no worker log"; exit 1; }
echo "PASS"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /root/src/tokendance && chmod +x tests/test_launch_worker.sh && bash tests/test_launch_worker.sh`
Expected: FAIL — `launch-worker.sh` 없음.

- [ ] **Step 3: launch-worker.sh 구현**

`scripts/launch-worker.sh`:
```bash
#!/usr/bin/env bash
# 워커를 detached OS 프로세스로 기동. 마스터의 유일한 워커 기동 통로.
# 인자: $1 = task-id
set -euo pipefail
TASK_ID="${1:?task-id required}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${TOKENDANCE_CLAUDE:?TOKENDANCE_CLAUDE (claude 바이너리 경로) 미설정}"

TASK_DIR="$ROOT/state/tasks/$TASK_ID"
LOG="$ROOT/state/workers/$TASK_ID.log"
mkdir -p "$ROOT/state/workers"

# 1) worktree 셋업 (실패하면 blocked 처리)
if ! "$ROOT/scripts/prepare-worktree.sh" "$TASK_ID" >>"$LOG" 2>&1; then
  python3 "$ROOT/scripts/status.py" set "$TASK_ID" --state blocked
  echo "[launch-worker] prepare-worktree failed for $TASK_ID" >&2
  exit 1
fi

# 2) 워커 기동 (detached: setsid + IS_SANDBOX=1 + stdin 차단 + disown)
#    IS_SANDBOX=1 은 root에서 --dangerously-skip-permissions 를 허용하기 위해 필수(스파이크 확인).
PROMPT="너는 tokendance 워커다. task id=${TASK_ID}. ${ROOT}/prompts/worker.md 를 읽고 그대로 따르라. 일감 명세: ${TASK_DIR}/task.md"
setsid env IS_SANDBOX=1 "$TOKENDANCE_CLAUDE" -p "$PROMPT" \
  --append-system-prompt "$(cat "$ROOT/prompts/worker.md")" \
  --dangerously-skip-permissions \
  >>"$LOG" 2>&1 < /dev/null &
PID=$!
disown 2>/dev/null || true

# 3) 상태를 running 으로 기록 + 즉시 heartbeat (갓 띄운 워커가 stale 로 오판되지 않게).
#    PID 는 best-effort(디버깅용) — 생사 판정은 supervisor 가 heartbeat 로 함.
python3 "$ROOT/scripts/status.py" set "$TASK_ID" --state running --pid "$PID"
python3 "$ROOT/scripts/status.py" heartbeat "$TASK_ID"
echo "$PID"
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /root/src/tokendance && chmod +x scripts/launch-worker.sh && bash tests/test_launch_worker.sh`
Expected: `PASS`.

- [ ] **Step 5: 커밋**

```bash
git add scripts/launch-worker.sh tests/test_launch_worker.sh
git commit -m "feat: launch-worker.sh — detached worker process launch"
```

---

## Task 7: supervisor.py + start/stop — 상주 루프 + 헬스체크

**Files:**
- Create: `scripts/supervisor.py`, `scripts/start.sh`, `scripts/stop.sh`
- Test: `tests/test_supervisor.py`

**Interfaces:**
- Consumes: `status`, `tasks` 모듈, 환경변수 `TOKENDANCE_CLAUDE`
- Produces:
  - `STALE_SECONDS = 1200` (모듈 상수)
  - `health_check(root, now=None, stale_seconds=STALE_SECONDS) -> list[str]` — running인데 heartbeat가 없거나 stale_seconds 초과로 오래된 task를 `needs_human`으로 전환, 그 id 목록 반환. `now`는 테스트 주입용(`datetime`).
  - `run_master(root, claude_bin) -> subprocess.CompletedProcess` — `IS_SANDBOX=1` 환경으로 마스터 기동
  - `tick(root, claude_bin)` — health_check 후 run_master
  - CLI: `supervisor.py [--once] [--interval N]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_supervisor.py`:
```python
import os, sys, tempfile, unittest
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import supervisor as SV
import tasks as TK
import status as S


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class SupervisorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_health_check_marks_stale_worker(self):
        TK.create_task(self.root, "t1")
        old = datetime.now(timezone.utc) - timedelta(seconds=3000)
        S.update(self.root, "t1", {"state": "running", "heartbeat": _iso(old)})
        dead = SV.health_check(self.root)
        self.assertEqual(dead, ["t1"])
        self.assertEqual(S.read(self.root, "t1")["state"], "needs_human")

    def test_health_check_leaves_fresh_worker(self):
        TK.create_task(self.root, "t1")
        fresh = datetime.now(timezone.utc)
        S.update(self.root, "t1", {"state": "running", "heartbeat": _iso(fresh)})
        self.assertEqual(SV.health_check(self.root), [])
        self.assertEqual(S.read(self.root, "t1")["state"], "running")

    def test_health_check_marks_running_without_heartbeat(self):
        TK.create_task(self.root, "t1")
        S.update(self.root, "t1", {"state": "running"})  # heartbeat 없음 = 이상
        dead = SV.health_check(self.root)
        self.assertEqual(dead, ["t1"])
        self.assertEqual(S.read(self.root, "t1")["state"], "needs_human")

    def test_health_check_ignores_non_running(self):
        TK.create_task(self.root, "t1")  # queued, heartbeat 없음
        self.assertEqual(SV.health_check(self.root), [])
        self.assertEqual(S.read(self.root, "t1")["state"], "queued")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /root/src/tokendance && python3 -m unittest discover -s tests -p 'test_supervisor.py' -v`
Expected: FAIL — `No module named 'supervisor'`.

- [ ] **Step 3: supervisor.py 구현**

`scripts/supervisor.py`:
```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /root/src/tokendance && python3 -m unittest discover -s tests -p 'test_supervisor.py' -v`
Expected: PASS — 3 tests OK.

- [ ] **Step 5: start.sh / stop.sh 작성**

`scripts/start.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${TOKENDANCE_CLAUDE:?TOKENDANCE_CLAUDE 미설정}"
PIDFILE="$ROOT/state/supervisor.pid"
mkdir -p "$ROOT/state"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "이미 실행 중: $(cat "$PIDFILE")"; exit 0
fi
nohup python3 "$ROOT/scripts/supervisor.py" >"$ROOT/state/supervisor.log" 2>&1 < /dev/null &
echo $! > "$PIDFILE"
echo "supervisor 시작: $(cat "$PIDFILE")"
```

`scripts/stop.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDFILE="$ROOT/state/supervisor.pid"
[ -f "$PIDFILE" ] || { echo "실행 중 아님"; exit 0; }
kill "$(cat "$PIDFILE")" 2>/dev/null || true
rm -f "$PIDFILE"
echo "supervisor 정지"
```

- [ ] **Step 6: start/stop 스모크 (fake claude, 짧은 interval로 1회 tick 후 sleep)**

Run:
```bash
cd /root/src/tokendance && chmod +x scripts/start.sh scripts/stop.sh
FAKE=$(mktemp); printf '#!/usr/bin/env bash\nexit 0\n' > "$FAKE"; chmod +x "$FAKE"
TOKENDANCE_CLAUDE="$FAKE" scripts/start.sh
sleep 1; kill -0 "$(cat state/supervisor.pid)" && echo "alive"
scripts/stop.sh
rm -f "$FAKE"
```
Expected: `supervisor 시작`, `alive`, `supervisor 정지`.

- [ ] **Step 7: 커밋**

```bash
git add scripts/supervisor.py scripts/start.sh scripts/stop.sh tests/test_supervisor.py
git commit -m "feat: supervisor loop, health-check, start/stop scripts"
```

---

## Task 8: prompts/master.md — 마스터 운영 절차

**Files:**
- Create: `prompts/master.md`

마스터의 행동 표면은 좁다: 판단만 하고 부수효과는 `status.py`/`launch-worker.sh`로만. 아래 내용 그대로 작성한다.

- [ ] **Step 1: prompts/master.md 작성**

`prompts/master.md`:
```markdown
# tokendance 마스터

너는 tokendance 시스템의 매니저/테크리더다. 한 번의 관리 사이클을 수행하고 종료한다.
워커가 끝나길 기다리지 않는다. 모든 소통은 파일을 통한다. 컨텍스트를 워커와 공유하지 않는다.

## 절대 규칙
- status.json 은 `python3 scripts/status.py ...` 로만 변경한다. 직접 편집·jq 금지.
- 워커 기동은 `bash scripts/launch-worker.sh <task-id>` 로만 한다. 직접 setsid/kill/claude 실행 금지.
- 동시 running 워커는 4개를 넘기지 않는다 (`python3 scripts/tasks.py count-running`).
- steer.md 는 append 만 한다. 덮어쓰지 않는다.
- 타겟 레포에 main 직접 push 금지. 브랜치/PR만.

## 사이클 절차 (순서대로)
1. **inbox 처리.** `python3 scripts/inbox.py list` 의 각 pending 파일을 읽어:
   - 새 일감이면 `python3 scripts/tasks.py new <task-id> --title "..." --repo "..."` 로 생성하고 task.md 에 명세/완료기준을 적는다.
   - 기존 일감 피드백이면 해당 `state/tasks/<id>/steer.md` 에 timestamped 블록으로 append 한다.
   - 처리 후 그 파일을 `state/inbox/processed/` 로 이동한다(`mv`).
2. **상태 스캔.** `python3 scripts/tasks.py list` 의 각 일감을 상태별로 처리:
   - `running` & heartbeat 신선 & pid 생존 → 냅둔다. progress.md 를 읽어 엉뚱하면 steer.md 에 교정 블록 append.
   - `running` 인데 pid 죽음/heartbeat 멈춤 → log/progress 보고 `--resume`로 재투입하거나 needs_human 으로 올린다.
   - `review` → **직접 리뷰**(아래).
   - `needs_human`/`blocked` → 리포트에 올린다(아래).
   - `queued` & running<4 → `bash scripts/launch-worker.sh <id>` 로 디스패치.
3. **리뷰 (state=review).** task.md 완료 기준 대비 워커 결과물(브랜치/diff/산출물)을 검수하고 `review.md` 에 평을 쓴다.
   - 합격 → `status.py set <id> --state done`. 필요 시 PR 생성.
   - 반려 → `steer.md` 에 교정 블록 append + `status.py set <id> --state queued --bump-attempts`.
4. **지식 수확.** 워커가 log.md 에 남긴 노하우/레포 사실 중 재사용 가치가 있는 것을 `library/` 에 반영하고 `library/index.md` 에 링크를 추가한다.
5. **리포트.** `state/reports/<오늘날짜>.md` 에 append (없으면 생성):
   - 🟢 순항(running): 일감 + progress.md 한 줄 요약
   - 🟡 판단 필요(needs_human): "X 애매 → 일단 Y, 맞나요?" — 사람 답을 유도
   - 🔴 막힘(blocked): 기술적 이유 + 마스터 제안
   - ✅ 완료(done): 결과물 + 한 줄 평
   - ⚫ 실패(failed): failure_reason
6. (Slack 연동이 켜져 있으면) 리포트 요약을 지정 채널에 푸시한다.

## task-id 규칙
`YYYY-MM-DD-<짧은-슬러그>` (예: `2026-06-24-fix-login`).
```

- [ ] **Step 2: 커밋**

```bash
git add prompts/master.md
git commit -m "feat: master.md operating procedure"
```

---

## Task 9: prompts/worker.md + CLAUDE.md — 워커 절차 + 공유 규칙

**Files:**
- Create: `prompts/worker.md`, `CLAUDE.md`

- [ ] **Step 1: prompts/worker.md 작성**

`prompts/worker.md`:
```markdown
# tokendance 워커

너는 격리된 코딩 일꾼이다. 너의 task id 는 프롬프트에 주어진다. ROOT=tokendance 레포 루트.
마스터와 컨텍스트를 공유하지 않는다. 모든 소통은 파일을 통한다.

## 시작
1. `state/tasks/<task-id>/task.md` 를 읽어 일감과 완료 기준을 파악한다.
2. `library/index.md` 를 보고 **필요한 항목만** 골라 읽는다(전부 읽지 말 것).
3. 대상 레포에서 작업한다. 변경은 항상 브랜치에서. main 직접 push 금지.

## 체크포인트 프로토콜 (각 의미 있는 단계 경계마다 반드시)
1. `state/tasks/<task-id>/progress.md` 를 덮어써 현재 상태를 적는다:
   현재 단계 / 지금 하는 일 / 부딪힌 애매함 / 일단 한 가정 / 자체 점검("이 방향 맞나").
2. `state/tasks/<task-id>/steer.md` 에서 `steer.cursor`(바이트 offset) 이후의 새 지시만 읽어 반영하고,
   반영 사실을 `log.md` 에 append 한 뒤 `steer.cursor` 를 파일 끝 offset 으로 갱신한다.
3. `python3 scripts/status.py heartbeat <task-id>` 로 heartbeat 갱신.
   **heartbeat 가 20분 이상 멈추면 supervisor 가 너를 죽은 것으로 보고 needs_human 으로 돌린다.**
   따라서 긴 작업(빌드/테스트 등) 전후로 자주(최소 10분 간격) heartbeat 를 찍어라.
4. 사람 판단이 꼭 필요하면 progress.md 에 질문을 명확히 적고
   `python3 scripts/status.py set <task-id> --state needs_human` 후 멈춘다.

## 종료
- 성공 → 결과물(브랜치명/diff/산출물 경로)을 progress.md 에 명시하고
  `python3 scripts/status.py set <task-id> --state review`.
- 기술적 막힘 → `python3 scripts/status.py set <task-id> --state blocked` + 이유를 progress.md 에.
- 회복 불가 실패 → `python3 scripts/status.py set <task-id> --state failed --failure-reason "..."`.

## 지식 수확
작업 중 알게 된 재사용 가능한 노하우/레포 사실을 log.md 에 "## 지식:" 블록으로 남긴다.
마스터가 이를 library 로 승격한다.
```

- [ ] **Step 2: CLAUDE.md 작성**

`CLAUDE.md`:
```markdown
# tokendance

상시 호스트 위에서 코딩 일감을 자율 관리하는 마스터 에이전트 하네스.
설계: docs/superpowers/specs/2026-06-24-tokendance-master-agent-design.md

## 불변 규칙 (마스터·워커 공통)
- status.json 변경은 `scripts/status.py` 로만.
- 워커 기동은 `scripts/launch-worker.sh` 로만.
- 상태: queued | running | needs_human | blocked | review | done | failed. failed 는 failure_reason 필수.
- 파일 소유: progress/log/steer.cursor=워커, review/reports=마스터, steer.md=append-only, status.json=status.py.
- 타겟 레포 변경은 브랜치/PR만. main 직접 push 금지.
- 모든 자동화 도구는 Python 표준 라이브러리만 사용(외부 패키지/jq 금지).

## 환경
- claude 바이너리: 환경변수 `TOKENDANCE_CLAUDE`.
- supervisor 기동/정지: `scripts/start.sh` / `scripts/stop.sh`.
```

- [ ] **Step 3: 커밋**

```bash
git add prompts/worker.md CLAUDE.md
git commit -m "feat: worker.md checkpoint protocol + CLAUDE.md shared rules"
```

---

## Task 10: 엔드투엔드 통합 스모크 + 라이브러리 뼈대

실제 `claude` 바이너리로 한 사이클이 도는지 확인한다(토큰 소비). 사소한 일감 하나로 dispatch→worker→review→done 를 본다.

**Files:**
- Create: `library/index.md`, `.gitignore`

- [ ] **Step 1: library 뼈대 + .gitignore**

`library/index.md`:
```markdown
# tokendance 지식 라이브러리 — 목차

필요할 때 필요한 항목만 펼쳐 본다. (점진 탐색)

## playbooks/   재사용 노하우
## repos/       레포별 지식 베이스

(아직 비어 있음. 워커가 수확하고 마스터가 승격한다.)
```

`.gitignore`:
```
state/workers/
state/supervisor.log
state/supervisor.pid
state/**/status.json.lock
```
(주의: `state/tasks/`·`state/inbox/`·`state/reports/`는 추적한다 — git이 진실원.)

- [ ] **Step 2: 환경변수 + 테스트용 타겟 레포 준비**

Run:
```bash
cd /root/src/tokendance
export TOKENDANCE_CLAUDE="$(ls -dt /root/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude | head -1)"
# 사소한 일감을 inbox 에 투입
python3 scripts/inbox.py add "scratch 레포에 GREETING.md 파일을 만들고 'hello from tokendance' 한 줄을 적어라. task-id: 2026-06-24-greeting" --slug greeting
python3 scripts/inbox.py list
```
Expected: pending 에 파일 1개.

- [ ] **Step 3: 마스터 1회 실행 (inbox→task→dispatch)**

Run: `cd /root/src/tokendance && python3 scripts/supervisor.py --once`
그 후:
```bash
python3 scripts/tasks.py list
cat state/tasks/2026-06-24-greeting/status.json 2>/dev/null || echo "task 미생성"
```
Expected: task 가 생성되고 상태가 `running`(또는 빠르면 `review`). pending 은 processed 로 이동.

- [ ] **Step 4: 워커 진행 관찰 (peek)**

Run:
```bash
cd /root/src/tokendance
cat state/tasks/2026-06-24-greeting/progress.md
tail -20 state/workers/2026-06-24-greeting.log
```
Expected: progress.md 에 진행 서술. 워커가 살아있거나 완료.

- [ ] **Step 5: 두 번째 사이클로 리뷰→done 확인**

워커가 `review` 로 바뀐 뒤:
```bash
cd /root/src/tokendance && python3 scripts/supervisor.py --once
python3 scripts/status.py get 2026-06-24-greeting --field state
cat state/tasks/2026-06-24-greeting/review.md
cat state/reports/2026-06-24.md
```
Expected: 상태 `done`, review.md 에 평, 리포트에 ✅ 항목.

- [ ] **Step 6: 커밋 (런타임 산출물 제외, 코드/뼈대만)**

```bash
cd /root/src/tokendance
git add library/index.md .gitignore
git add state/tasks state/inbox state/reports 2>/dev/null || true
git commit -m "feat: library skeleton, gitignore; e2e smoke verified"
```

**검증 게이트:** Step 5가 `done` 에 도달하지 못하면 멈추고 워커 로그/progress 로 원인 파악(systematic-debugging).

---

## Task 11: Slack 연동 (경로 A — MCP, 스파이크에서 확정)

Task 1 스파이크에서 headless 실행에 `mcp__claude_ai_Slack__*` 툴이 노출됨을 확인했으므로 경로 A로 간다.

**Files:**
- Modify: `prompts/master.md`, `CLAUDE.md`

- [ ] **Step 1: 채널 ID 확보**

사람에게 대상 Slack 채널명/ID를 받는다(미확보 시 이 태스크를 보류하고 사람 확인). `CLAUDE.md` 에 `SLACK_CHANNEL=<id 또는 #이름>` 한 줄로 기록.

- [ ] **Step 2: master.md 에 Slack 단계 구체화**

`prompts/master.md` 의 사이클 절차 1(inbox 처리)과 6(리포트)에 추가:
- 사이클 시작 시: `mcp__claude_ai_Slack__slack_read_channel` 로 `SLACK_CHANNEL` 의 새 메시지를 읽어, 마지막 처리 시각(`state/slack.cursor` 파일에 저장) 이후 메시지를 각각 `python3 scripts/inbox.py add "<메시지>" --slug slack` 로 떨군다. 처리 후 `state/slack.cursor` 를 최신 메시지 ts 로 갱신.
- 사이클 끝에: `mcp__claude_ai_Slack__slack_send_message` 로 리포트 요약(🟢🟡🔴✅⚫ 카운트 + 🟡/🔴 상세)을 `SLACK_CHANNEL` 에 푸시.

```bash
git add prompts/master.md CLAUDE.md
git commit -m "feat(slack): master pulls inbox from / pushes reports to Slack via MCP"
```

- [ ] **Step 3: Slack 왕복 스모크**

지정 채널에 "테스트 일감 추가" 한 줄 → `python3 scripts/supervisor.py --once` → inbox(또는 task)에 반영됐는지 + 리포트 요약이 채널에 푸시됐는지 확인.

---

## Task 12: dogfood 백로그 시드 + README

핵심 시스템이 검증됐으면, 나머지 디테일을 tokendance 자신의 첫 일감으로 inbox 에 넣는다.

**Files:**
- Create: `README.md`

- [ ] **Step 1: README 작성**

`README.md` 에: 무엇인지, 아키텍처 한 단락, `start.sh`/`stop.sh` 사용법, 일감 투입법(`inbox.py add`), 상태 보는 법, 설계/플랜 문서 링크.

- [ ] **Step 2: dogfood 백로그를 inbox 에 시드**

Run:
```bash
cd /root/src/tokendance
python3 scripts/inbox.py add "prepare-worktree.sh 를 실제 구현하라. 타겟 레포의 공통 artifact 의존성을 worktree 에 심볼릭링크/복사로 셋업. 현재는 no-op stub." --slug dogfood-worktree
python3 scripts/inbox.py add "지식 라이브러리 자동화: 워커 log.md 의 '## 지식:' 블록을 library/playbooks 또는 repos/<repo>.md 로 승격하고 index.md 링크를 갱신하는 흐름을 만들라." --slug dogfood-library
python3 scripts/inbox.py add "워커 반려 재투입을 --resume 세션 기반으로 신뢰성 있게 만들라(worker_session_id 활용)." --slug dogfood-resume
python3 scripts/inbox.py add "리뷰 루프에 자동 테스트 실행/검증을 결합하라." --slug dogfood-review-tests
python3 scripts/inbox.py add "supervisor 자기 회복(크래시 후 재기동)과 관측성(틱 로그/메트릭)을 추가하라." --slug dogfood-resilience
python3 scripts/inbox.py add "remote-control 에이전트 입력 경로를 정식화하라." --slug dogfood-remote
python3 scripts/inbox.py add "멀티 레포 핸들링을 추상화하라." --slug dogfood-multirepo
python3 scripts/inbox.py list
```
Expected: pending 에 7개.

- [ ] **Step 3: 커밋**

```bash
git add README.md state/inbox 2>/dev/null
git commit -m "docs: README; seed dogfood backlog into inbox"
```

- [ ] **Step 4: supervisor 상시 기동 (사람 확인 후)**

```bash
cd /root/src/tokendance
export TOKENDANCE_CLAUDE="$(ls -dt /root/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude | head -1)"
scripts/start.sh
```
이후 tokendance 가 자신의 dogfood 백로그를 스스로 처리하기 시작한다.

---

## Self-Review (작성자 점검 결과)

**Spec coverage:** §4 아키텍처→Task 6/7, §5 레이아웃→전 태스크, §6.1 스키마+상태→Task 2, §6.2 분기→Task 8, §6.3 동시성→Task 2(status.py), §7 리뷰루프→Task 8, §8 peek/steer→Task 9(worker.md), §9 inbox→Task 4, §10 리포트→Task 8, §11 Slack→Task 11, §12 안전→Global Constraints+Task 6/8, §13 MVP/dogfood→Task 12, §14 검증→Task 1 스파이크. 누락 없음.

**Placeholder scan:** Task 11 경로 B 코드는 스파이크 결과·토큰 가용성에 의존하므로 의도적으로 조건부(분기 게이트 명시). 그 외 모든 코드 스텝은 완전한 실제 코드.

**Type consistency:** `status.py`의 `init/read/update/heartbeat/STATES` 시그니처가 tasks.py·supervisor.py·테스트에서 일관되게 사용됨. `tasks.create_task/list_tasks/count_running`, `inbox.add/list_pending/read_pending/mark_processed`, `supervisor.is_alive/health_check/run_master/tick` 명칭 전 구간 일치 확인.
