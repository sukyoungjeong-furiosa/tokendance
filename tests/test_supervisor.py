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


class NextIntervalTest(unittest.TestCase):
    def test_idle_backoff_increases_geometrically(self):
        # idle 틱이 연속되면 base → base*f → base*f^2 ... 로 늘어난다.
        i = SV.next_interval(1800, idle=True, base=1800, max_interval=21600, factor=2)
        self.assertEqual(i, 3600)
        i = SV.next_interval(i, idle=True, base=1800, max_interval=21600, factor=2)
        self.assertEqual(i, 7200)
        i = SV.next_interval(i, idle=True, base=1800, max_interval=21600, factor=2)
        self.assertEqual(i, 14400)

    def test_work_resets_to_base(self):
        # 일이 생기면(idle=False) 직전 간격과 무관하게 base 로 즉시 복귀.
        self.assertEqual(
            SV.next_interval(14400, idle=False, base=1800, max_interval=21600, factor=2),
            1800)

    def test_clamps_at_max(self):
        # base*f 가 max 를 넘으면 max 로 클램프.
        self.assertEqual(
            SV.next_interval(14400, idle=True, base=1800, max_interval=21600, factor=2),
            21600)  # 14400*2=28800 → 21600

    def test_stays_at_max_when_already_clamped(self):
        self.assertEqual(
            SV.next_interval(21600, idle=True, base=1800, max_interval=21600, factor=2),
            21600)

    def test_defaults_use_module_constants(self):
        # 기본 인자(base/max/factor)는 모듈 상수를 쓴다.
        self.assertEqual(SV.next_interval(SV.INTERVAL, idle=True),
                         min(SV.INTERVAL * SV.BACKOFF_FACTOR, SV.MAX_INTERVAL))
        self.assertEqual(SV.next_interval(SV.MAX_INTERVAL, idle=False), SV.INTERVAL)


class HasActiveWorkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_tasks_is_idle(self):
        self.assertFalse(SV.has_active_work(self.root))

    def test_queued_is_active(self):
        TK.create_task(self.root, "t1")  # 기본 queued
        self.assertTrue(SV.has_active_work(self.root))

    def test_running_is_active(self):
        TK.create_task(self.root, "t1")
        S.update(self.root, "t1", {"state": "running"})
        self.assertTrue(SV.has_active_work(self.root))

    def test_review_is_active(self):
        TK.create_task(self.root, "t1")
        S.update(self.root, "t1", {"state": "review"})
        self.assertTrue(SV.has_active_work(self.root))

    def test_only_needs_human_or_blocked_is_idle(self):
        # 사람/외부 대기 상태뿐이면 폴링을 늦춰도 되므로 idle.
        TK.create_task(self.root, "t1")
        S.update(self.root, "t1", {"state": "needs_human"})
        TK.create_task(self.root, "t2")
        S.update(self.root, "t2", {"state": "blocked"})
        TK.create_task(self.root, "t3")
        S.update(self.root, "t3", {"state": "done"})
        self.assertFalse(SV.has_active_work(self.root))


if __name__ == "__main__":
    unittest.main()
