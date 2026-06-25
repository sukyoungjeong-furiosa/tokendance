import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import cycle as CY
import tasks as TK
import status as S
import inbox as IB


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.launched = []

    def tearDown(self):
        self.tmp.cleanup()

    def _launcher(self, root, tid):
        self.launched.append(tid)
        S.update(root, tid, {"state": "running"})   # 디스패치 효과 모사
        return True

    def test_respects_max_workers(self):
        for t in ("a", "b", "c"):
            TK.create_task(self.root, t)  # 3 queued
        CY.dispatch_queued(self.root, self._launcher, max_workers=2)
        self.assertEqual(len(self.launched), 2)

    def test_counts_existing_running(self):
        TK.create_task(self.root, "a")
        S.update(self.root, "a", {"state": "running"})   # 이미 1 running
        TK.create_task(self.root, "b")                   # 1 queued
        CY.dispatch_queued(self.root, self._launcher, max_workers=2)
        self.assertEqual(self.launched, ["b"])           # 슬롯 1개만 남음

    def test_no_free_slots(self):
        TK.create_task(self.root, "a")
        S.update(self.root, "a", {"state": "running"})
        TK.create_task(self.root, "b")
        CY.dispatch_queued(self.root, self._launcher, max_workers=1)
        self.assertEqual(self.launched, [])


class LaunchArgvTest(unittest.TestCase):
    """재투입 정합(#3): 디스패치는 항상 --resume 으로 기동(세션 없으면 launch-worker 가 fresh 폴백)."""

    def test_launch_argv_passes_resume(self):
        argv = CY._launch_argv("/some/root", "t1")
        self.assertEqual(argv[0], "bash")
        self.assertTrue(argv[1].endswith("launch-worker.sh"))
        self.assertEqual(argv[2], "t1")
        self.assertIn("--resume", argv[3:])


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_groups_states_and_inbox(self):
        TK.create_task(self.root, "r")
        S.update(self.root, "r", {"state": "review"})
        TK.create_task(self.root, "h")
        S.update(self.root, "h", {"state": "needs_human"})
        IB.add(self.root, "새 일감 줘", slug="x")
        plan = CY.build_plan(self.root)
        self.assertEqual(plan["review"], ["r"])
        self.assertEqual(plan["needs_human"], ["h"])
        self.assertEqual(len(plan["inbox_pending"]), 1)
        self.assertIn("새 일감", plan["inbox_pending"][0]["text"])
        self.assertEqual(plan["counts"].get("review"), 1)


if __name__ == "__main__":
    unittest.main()
