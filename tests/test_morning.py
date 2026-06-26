import os, sys, unittest, tempfile
from types import SimpleNamespace
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import morning as M

UTC = timezone.utc


def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


# ── should_run 게이트 (KST 시각 + 하루 1회; librarian 과 달리 idle 불요) ────────
class ShouldRunTest(unittest.TestCase):
    def test_runs_at_target_hour_not_run_today(self):
        # 2026-06-25 22:00Z = 2026-06-26 07:00 KST → target_hour=7, 오늘 미실행 → 실행.
        now = _utc(2026, 6, 25, 22)
        self.assertEqual(M.kst_hour(now), 7)
        self.assertTrue(M.should_run(now, last_run_date="", target_hour=7))

    def test_wrong_hour_blocks(self):
        now = _utc(2026, 6, 25, 21)   # 06:00 KST
        self.assertFalse(M.should_run(now, last_run_date="", target_hour=7))

    def test_already_ran_today_blocks(self):
        now = _utc(2026, 6, 25, 22)   # KST 2026-06-26
        self.assertFalse(M.should_run(now, last_run_date="2026-06-26", target_hour=7))

    def test_ran_yesterday_allows(self):
        now = _utc(2026, 6, 25, 22)   # KST 2026-06-26
        self.assertTrue(M.should_run(now, last_run_date="2026-06-25", target_hour=7))

    def test_idle_irrelevant(self):
        # 다이제스트는 진행중 작업을 보고하므로 idle 여부와 무관(시그니처에 idle 인자 없음).
        now = _utc(2026, 6, 25, 22)
        self.assertTrue(M.should_run(now, last_run_date="", target_hour=7))


class LastRunStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_absent_is_empty(self):
        self.assertEqual(M.read_last_run(self.root), "")

    def test_mark_and_read_roundtrip(self):
        M.mark_run(self.root, _utc(2026, 6, 25, 22))   # KST 2026-06-26
        self.assertEqual(M.read_last_run(self.root), "2026-06-26")


# ── GC 결정 가드 (순수) ──────────────────────────────────────────────────────
def _task(tid, state="done", repo="/repo", branch="tokendance/x"):
    return {"id": tid, "state": state, "repo": repo, "branch": branch}


PRESERVED = {"worktree_exists": True, "branch_exists": True, "branch_preserved": True}


class GcDecisionTest(unittest.TestCase):
    def test_done_preserved_removes_worktree_and_branch(self):
        # 결과 보존(머지/푸시) → worktree + branch 둘 다 제거.
        d = M.gc_decision(_task("t1"), PRESERVED)
        self.assertEqual(d["action"], "remove")
        self.assertTrue(d["remove_worktree"])
        self.assertTrue(d["remove_branch"])

    def test_done_not_preserved_removes_worktree_keeps_branch(self):
        # 미보존이지만 로컬 branch 존재(=백업) → worktree 회수하되 branch 는 보존.
        facts = {**PRESERVED, "branch_preserved": False}
        d = M.gc_decision(_task("t1"), facts)
        self.assertEqual(d["action"], "remove")
        self.assertTrue(d["remove_worktree"])
        self.assertFalse(d["remove_branch"])

    def test_worktree_gone_branch_kept_not_preserved_is_idempotent_skip(self):
        # worktree 이미 회수됨 + branch 는 백업으로 남김 + 미보존 → 할 일 없음(멱등 skip).
        facts = {"worktree_exists": False, "branch_exists": True, "branch_preserved": False}
        d = M.gc_decision(_task("t1"), facts)
        self.assertEqual(d["action"], "skip")

    def test_no_backup_anywhere_is_candidate(self):
        # worktree 존재하나 branch 없음 + 미보존 → 어디에도 백업 없음(이상 케이스) → candidate.
        facts = {"worktree_exists": True, "branch_exists": False, "branch_preserved": False}
        d = M.gc_decision(_task("t1"), facts)
        self.assertEqual(d["action"], "candidate")

    def test_nonterminal_states_protected(self):
        for st in ("running", "needs_human", "review", "queued", "blocked"):
            d = M.gc_decision(_task("t1", state=st), PRESERVED)
            self.assertEqual(d["action"], "skip", st)

    def test_failed_not_eligible(self):
        # failed 는 제거 대상도 보호 명시 대상도 아님 → 보수적으로 skip(보호).
        d = M.gc_decision(_task("t1", state="failed"), PRESERVED)
        self.assertEqual(d["action"], "skip")

    def test_protected_worktree_name_never_removed(self):
        # npu-pr-18434: 사용자 소유. 설사 done + 보존이어도 절대 건드리지 않는다.
        d = M.gc_decision(_task("npu-pr-18434"), PRESERVED)
        self.assertEqual(d["action"], "skip")
        self.assertIn("npu-pr-18434", d["reason"])

    def test_current_worker_self_protected(self):
        d = M.gc_decision(_task("t1"), PRESERVED, current_task_id="t1")
        self.assertEqual(d["action"], "skip")

    def test_idempotent_nothing_exists(self):
        facts = {"worktree_exists": False, "branch_exists": False, "branch_preserved": True}
        d = M.gc_decision(_task("t1"), facts)
        self.assertEqual(d["action"], "skip")

    def test_worktree_gone_branch_remains_preserved_removes(self):
        # worktree 없음 + branch 보존됨 → branch-only 정리(remove). worktree 단계는 멱등 생략.
        facts = {"worktree_exists": False, "branch_exists": True, "branch_preserved": True}
        d = M.gc_decision(_task("t1"), facts)
        self.assertEqual(d["action"], "remove")
        self.assertTrue(d["remove_branch"])


# ── branch_preserved (injectable runner) ─────────────────────────────────────
def _ns(rc=0, out=""):
    return SimpleNamespace(returncode=rc, stdout=out, stderr="")


class BranchPreservedTest(unittest.TestCase):
    def _runner(self, *, present, merged_into=None, remote=False):
        present_names = set(present)

        def run(cmd):
            if "--verify" in cmd:
                ref = cmd[-1].split("refs/heads/", 1)[-1]   # 슬래시 포함 브랜치명 보존
                return _ns(0 if ref in present_names else 1)
            if "merge-base" in cmd:
                br, base = cmd[-2], cmd[-1]
                return _ns(0 if merged_into == (br, base) else 1)
            if "-r" in cmd and "--contains" in cmd:
                return _ns(0, "  origin/tokendance/x\n" if remote else "")
            return _ns(0)
        return run

    def test_absent_branch_is_preserved(self):
        r = self._runner(present=("master",))   # 대상 브랜치 없음
        self.assertTrue(M.branch_preserved("/repo", "tokendance/x", runner=r))

    def test_merged_into_master_is_preserved(self):
        r = self._runner(present=("tokendance/x", "master"),
                         merged_into=("tokendance/x", "master"))
        self.assertTrue(M.branch_preserved("/repo", "tokendance/x", runner=r))

    def test_pushed_to_remote_is_preserved(self):
        r = self._runner(present=("tokendance/x", "master"), remote=True)
        self.assertTrue(M.branch_preserved("/repo", "tokendance/x", runner=r))

    def test_neither_merged_nor_pushed_not_preserved(self):
        r = self._runner(present=("tokendance/x", "master"))
        self.assertFalse(M.branch_preserved("/repo", "tokendance/x", runner=r))


# ── execute_gc (injectable runner, 멱등, 경로 가드, 순서) ─────────────────────
class ExecuteGcTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def _runner(self, branch_present=True):
        def run(cmd):
            self.calls.append(cmd)
            if "--verify" in cmd:
                return _ns(0 if branch_present else 1)
            return _ns(0)
        return run

    def _wt(self, tid):
        p = os.path.join(self.root, "state", "worktrees", tid)
        os.makedirs(p)
        return p

    def test_skip_action_does_nothing(self):
        self._wt("t1")
        steps = M.execute_gc(self.root, _task("t1"), {"action": "skip", "reason": "x"},
                             runner=self._runner())
        self.assertEqual(steps, [])
        self.assertEqual(self.calls, [])

    def test_remove_issues_worktree_then_branch_in_order(self):
        self._wt("t1")
        steps = M.execute_gc(self.root, _task("t1", branch="tokendance/x"),
                             {"action": "remove", "reason": "ok"}, runner=self._runner())
        joined = [" ".join(c) for c in self.calls]
        # worktree remove → prune → branch -D 순서.
        self.assertTrue(any("worktree remove --force" in j for j in joined))
        self.assertTrue(any("worktree prune" in j for j in joined))
        i_remove = next(i for i, j in enumerate(joined) if "worktree remove" in j)
        i_branch = next(i for i, j in enumerate(joined) if "branch -D" in j)
        self.assertLess(i_remove, i_branch)
        self.assertEqual(len(steps), 2)

    def test_remove_worktree_only_keeps_branch(self):
        # remove_branch=False → worktree 만 제거하고 branch -D 는 호출하지 않는다(백업 보존).
        self._wt("t1")
        steps = M.execute_gc(self.root, _task("t1", branch="tokendance/x"),
                             {"action": "remove", "remove_worktree": True,
                              "remove_branch": False, "reason": "worktree 회수(branch 보존)"},
                             runner=self._runner())
        joined = [" ".join(c) for c in self.calls]
        self.assertTrue(any("worktree remove" in j for j in joined))
        self.assertFalse(any("branch -D" in j for j in joined))
        self.assertEqual(len(steps), 1)

    def test_idempotent_no_worktree_dir_only_branch(self):
        # worktree 디렉토리 없음 → worktree 명령 생략, 브랜치만 삭제.
        steps = M.execute_gc(self.root, _task("t1", branch="tokendance/x"),
                             {"action": "remove", "reason": "ok"}, runner=self._runner())
        joined = [" ".join(c) for c in self.calls]
        self.assertFalse(any("worktree remove" in j for j in joined))
        self.assertTrue(any("branch -D" in j for j in joined))

    def test_idempotent_branch_absent(self):
        self._wt("t1")
        steps = M.execute_gc(self.root, _task("t1", branch="tokendance/x"),
                             {"action": "remove", "reason": "ok"},
                             runner=self._runner(branch_present=False))
        joined = [" ".join(c) for c in self.calls]
        self.assertFalse(any("branch -D" in j for j in joined))

    def test_path_guard_refuses_outside_worktrees(self):
        # worktree_path 가 state/worktrees/<id> 가 아니면(이론상) 절대 조작 안 함.
        # id 에 경로탈출 시도 → 실제 경로가 기대 경로와 달라 무시.
        steps = M.execute_gc(self.root, _task("../../evil", branch="b"),
                             {"action": "remove", "reason": "ok"}, runner=self._runner())
        self.assertEqual(steps, [])


# ── run_gc end-to-end (temp root + fake runner) ──────────────────────────────
class RunGcTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def _runner(self):
        def run(cmd):
            self.calls.append(cmd)
            if "--verify" in cmd:        # 모든 브랜치 존재
                return _ns(0)
            if "merge-base" in cmd:      # 모두 머지됨 → 보존
                return _ns(0)
            return _ns(0)
        return run

    def test_active_and_protected_skipped_without_git(self):
        tasks = [
            _task("running-one", state="running"),
            _task("npu-pr-18434", state="done"),
        ]
        res = M.run_gc(self.root, tasks, runner=self._runner())
        actions = {r["task"]: r["action"] for r in res}
        self.assertEqual(actions["running-one"], "skip")
        self.assertEqual(actions["npu-pr-18434"], "skip")
        # cheap-guard 로 걸러지므로 git 호출 0.
        self.assertEqual(self.calls, [])

    def test_done_preserved_removed(self):
        os.makedirs(os.path.join(self.root, "state", "worktrees", "done-one"))
        res = M.run_gc(self.root, [_task("done-one")], runner=self._runner())
        self.assertEqual(res[0]["action"], "remove")
        joined = [" ".join(c) for c in self.calls]
        self.assertTrue(any("worktree remove" in j for j in joined))

    def test_dry_run_decides_but_does_not_mutate(self):
        wt = os.path.join(self.root, "state", "worktrees", "done-one")
        os.makedirs(wt)
        res = M.run_gc(self.root, [_task("done-one")], runner=self._runner(), dry_run=True)
        self.assertEqual(res[0]["action"], "remove")
        joined = [" ".join(c) for c in self.calls]
        # mutating 명령(worktree remove / branch -D)은 호출되지 않는다.
        self.assertFalse(any("worktree remove" in j for j in joined))
        self.assertFalse(any("branch -D" in j for j in joined))
        # 디렉토리도 그대로.
        self.assertTrue(os.path.isdir(wt))
        self.assertTrue(any("dry-run" in s for s in res[0]["steps"]))


# ── 다이제스트 포맷 (순수) ───────────────────────────────────────────────────
class DigestTest(unittest.TestCase):
    def _tasks(self):
        return [
            {"id": "r1", "state": "running", "title": "진행중 작업"},
            {"id": "q1", "state": "queued", "title": "대기 작업"},
            {"id": "v1", "state": "review", "title": "리뷰 작업"},
            {"id": "h1", "state": "needs_human", "title": "확인필요",
             "failure_reason": "API 키 필요"},
            {"id": "d1", "state": "done", "title": "끝난거"},
        ]

    def test_digest_has_all_sections(self):
        gc = [
            {"task": "d1", "state": "done", "action": "remove",
             "reason": "ok", "steps": ["worktree removed: ...", "branch deleted: ..."]},
            {"task": "d2", "state": "done", "action": "candidate",
             "reason": "결과 미보존(머지/푸시 안 됨) — 수동 확인", "steps": []},
        ]
        text = M.build_digest(self._tasks(), gc, now_str="2026-06-26 07:00 KST")
        self.assertIn("2026-06-26 07:00 KST", text)
        # 3 분류 헤딩(steer 2026-06-26).
        self.assertIn("🟢 진행중", text)
        self.assertIn("🟡 사람 확인 필요", text)
        self.assertIn("✅ 완료 · 사용자 미확인", text)
        # 🟢 진행중: running/queued/review 모두.
        self.assertIn("r1", text)
        self.assertIn("q1", text)
        self.assertIn("v1", text)
        # 사람 확인 필요 + 대기사유.
        self.assertIn("h1", text)
        self.assertIn("API 키 필요", text)
        # 완료-미확인(done) + GC 정리/후보.
        self.assertIn("d1", text)
        self.assertIn("정리 후보", text)
        self.assertIn("d2", text)

    def test_digest_distinguishes_branch_preserved_vs_deleted(self):
        # worktree 회수(branch 보존) 와 worktree+branch 회수(보존됨)를 다르게 표기한다.
        gc = [
            {"task": "d1", "state": "done", "action": "remove", "remove_branch": True,
             "reason": "ok", "steps": ["worktree 제거: ...", "브랜치 삭제: ..."]},
            {"task": "d2", "state": "done", "action": "remove", "remove_branch": False,
             "reason": "worktree 회수(branch 보존)", "steps": ["worktree 제거: ..."]},
        ]
        text = M.build_digest([], gc, now_str="X")
        self.assertIn("branch 보존", text)
        # d2 줄은 branch 보존을 표기, d1 줄은 branch 까지 회수.
        d2_line = next(l for l in text.splitlines() if "d2" in l)
        self.assertIn("보존", d2_line)
        d1_line = next(l for l in text.splitlines() if "d1" in l)
        self.assertNotIn("보존", d1_line)

    def test_done_appears_under_unconfirmed_not_blocking(self):
        # done 은 needs_human 과 별개 분류(✅ 완료·사용자 미확인)에 들어간다.
        tasks = [{"id": "d1", "state": "done", "title": "끝난거"}]
        text = M.build_digest(tasks, [], now_str="X")
        unconfirmed = text.split("✅ 완료 · 사용자 미확인")[1]
        self.assertIn("d1", unconfirmed)

    def test_empty_sections_render_none(self):
        text = M.build_digest([], [], now_str="2026-06-26 07:00 KST")
        self.assertIn("없음", text)

    def test_note_fn_used_for_needs_human(self):
        tasks = [{"id": "h1", "state": "needs_human", "title": "T"}]
        text = M.build_digest(tasks, [], now_str="X",
                              note_fn=lambda d: "사용자 결정 대기")
        self.assertIn("사용자 결정 대기", text)


if __name__ == "__main__":
    unittest.main()
