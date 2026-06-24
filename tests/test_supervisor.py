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

    def test_health_check_respects_injected_now(self):
        # now 주입 seam 검증: heartbeat 가 신선해도 주입된 now 가 충분히 미래면 stale.
        TK.create_task(self.root, "t1")
        hb = datetime.now(timezone.utc)
        S.update(self.root, "t1", {"state": "running", "heartbeat": _iso(hb)})
        future = hb + timedelta(seconds=2000)
        self.assertEqual(SV.health_check(self.root, now=future), ["t1"])
        self.assertEqual(S.read(self.root, "t1")["state"], "needs_human")


if __name__ == "__main__":
    unittest.main()
