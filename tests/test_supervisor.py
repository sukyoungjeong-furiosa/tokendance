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


def _dead(pid):
    return False


def _alive(pid):
    return True


class DetectFastCrashTest(unittest.TestCase):
    """detect_fast_crash: launch 직후 즉사한 워커를 staleness 보다 빨리 식별."""

    def setUp(self):
        self.now = datetime.now(timezone.utc)

    def _task(self, launched_delta=None, hb_delta=None, pid=4242, attempts=0):
        # launched_delta/hb_delta: now 기준 과거 초(양수=과거). None 이면 필드 없음.
        d = {"id": "t1", "state": "running", "worker_pid": pid, "attempts": attempts}
        if launched_delta is not None:
            d["launched_at"] = _iso(self.now - timedelta(seconds=launched_delta))
        if hb_delta is not None:
            d["heartbeat"] = _iso(self.now - timedelta(seconds=hb_delta))
        return d

    def test_within_grace_not_flagged_even_if_pid_dead(self):
        # 갓 띄운 워커(grace 안)는 pid 가 죽은 것처럼 보여도 즉사로 오판하지 않는다.
        d = self._task(launched_delta=30, hb_delta=30)  # 30s 전 launch, grace(180) 안
        self.assertIsNone(SV.detect_fast_crash(d, self.now, pid_alive=_dead))

    def test_past_grace_not_progressed_pid_dead_flagged(self):
        # grace 지났고, launch 이후 체크포인트 없음(heartbeat==launch), pid 죽음 → 즉사.
        d = self._task(launched_delta=300, hb_delta=300)
        self.assertEqual(SV.detect_fast_crash(d, self.now, pid_alive=_dead), "pid_dead")

    def test_past_grace_no_heartbeat_pid_dead_flagged(self):
        # heartbeat 가 한 번도 없음 + pid 죽음 → 즉사.
        d = self._task(launched_delta=300, hb_delta=None)
        self.assertEqual(SV.detect_fast_crash(d, self.now, pid_alive=_dead), "pid_dead")

    def test_transient_log_signature_flagged_even_if_pid_alive(self):
        # pid 가 살아 보여도(드리프트) 로그 끝에 transient 시그니처 + 미진행 → 즉사.
        d = self._task(launched_delta=300, hb_delta=300)
        log = "...\nAPI Error: 529 overloaded_error\n"
        self.assertEqual(
            SV.detect_fast_crash(d, self.now, pid_alive=_alive, log_text=log),
            "transient_log")

    def test_progressed_worker_not_flagged(self):
        # launch 이후 체크포인트가 진행됨(heartbeat 가 launch 보다 훨씬 신선) → 즉사 아님(staleness 가 담당).
        d = self._task(launched_delta=600, hb_delta=60)  # launch 600s 전, 마지막 hb 60s 전
        self.assertIsNone(SV.detect_fast_crash(d, self.now, pid_alive=_dead))

    def test_legacy_no_launched_at_skipped(self):
        # launched_at 없는 레거시 태스크는 빠른 감지에서 제외(기존 staleness 에 위임, 오탐 방지).
        d = self._task(launched_delta=None, hb_delta=300)
        self.assertIsNone(SV.detect_fast_crash(d, self.now, pid_alive=_dead))

    def test_slow_but_alive_not_flagged(self):
        # grace 지났고 미진행이라도 pid 살아있고 transient 시그니처 없으면 죽이지 않는다(보수적).
        d = self._task(launched_delta=300, hb_delta=300)
        self.assertIsNone(SV.detect_fast_crash(d, self.now, pid_alive=_alive, log_text="working..."))

    def test_no_pid_no_signature_not_flagged(self):
        # pid 정보 없음 + transient 시그니처 없음 → 사망 증거 부족 → 죽이지 않는다.
        d = self._task(launched_delta=300, hb_delta=300, pid=None)
        self.assertIsNone(SV.detect_fast_crash(d, self.now, pid_alive=_dead))


class RelaunchArgvTest(unittest.TestCase):
    """재투입은 항상 --resume(컨텍스트 보존). 세션 없으면 launch-worker 가 fresh 폴백."""

    def test_relaunch_argv_passes_resume(self):
        argv = SV._relaunch_argv("/some/root", "t1")
        self.assertEqual(argv[0], "bash")
        self.assertTrue(argv[1].endswith("launch-worker.sh"))
        self.assertEqual(argv[2], "t1")
        self.assertIn("--resume", argv[3:])


class HealthCheckResumeTest(unittest.TestCase):
    """stale running 워커: 세션 있고 pid 죽음 & attempts<MAX → bounded --resume 재투입,
    아니면(살아있는 hung / 세션 없음 / 한도 초과) needs_human."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.now = datetime.now(timezone.utc)
        self.stale = _iso(self.now - timedelta(seconds=3000))

    def tearDown(self):
        self.tmp.cleanup()

    def _stale(self, tid, session="sid-1", pid=4242, attempts=0):
        TK.create_task(self.root, tid)
        S.update(self.root, tid, {"state": "running", "heartbeat": self.stale,
                                  "worker_session_id": session, "worker_pid": pid,
                                  "attempts": attempts})

    def test_stale_with_session_pid_dead_resumes(self):
        self._stale("t1", session="sid-1", attempts=0)
        relaunched = []
        dead = SV.health_check(self.root, now=self.now, pid_alive=_dead,
                               relaunch=lambda root, tid: relaunched.append(tid) or True,
                               log=lambda m: None)
        self.assertEqual(relaunched, ["t1"])
        self.assertEqual(dead, [])                       # needs_human 아님
        d = S.read(self.root, "t1")
        self.assertEqual(d["state"], "running")          # in-place 재투입
        self.assertEqual(d["attempts"], 1)               # bounded 카운트

    def test_stale_with_session_pid_alive_escalates(self):
        # 살아있는데 heartbeat 만 멈춘 hung 워커 → 중복 위험 → needs_human(재투입 X).
        self._stale("t1", session="sid-1")
        relaunched = []
        dead = SV.health_check(self.root, now=self.now, pid_alive=_alive,
                               relaunch=lambda root, tid: relaunched.append(tid) or True,
                               log=lambda m: None)
        self.assertEqual(relaunched, [])
        self.assertEqual(dead, ["t1"])
        self.assertEqual(S.read(self.root, "t1")["state"], "needs_human")

    def test_stale_without_session_escalates(self):
        # 세션 id 없음(실제로 돈 적 없거나 캡처 실패) → 이어받을 게 없음 → 기존대로 needs_human.
        self._stale("t1", session=None)
        relaunched = []
        dead = SV.health_check(self.root, now=self.now, pid_alive=_dead,
                               relaunch=lambda root, tid: relaunched.append(tid) or True,
                               log=lambda m: None)
        self.assertEqual(relaunched, [])
        self.assertEqual(dead, ["t1"])
        self.assertEqual(S.read(self.root, "t1")["state"], "needs_human")

    def test_stale_attempts_exhausted_escalates(self):
        self._stale("t1", session="sid-1", attempts=3)
        relaunched = []
        dead = SV.health_check(self.root, now=self.now, max_attempts=3, pid_alive=_dead,
                               relaunch=lambda root, tid: relaunched.append(tid) or True,
                               log=lambda m: None)
        self.assertEqual(relaunched, [])
        self.assertEqual(dead, ["t1"])
        self.assertEqual(S.read(self.root, "t1")["state"], "needs_human")


class HandleFastCrashesTest(unittest.TestCase):
    """handle_fast_crashes: 감지된 즉사에 bounded 재시도/에스컬레이션 적용."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def _running(self, tid, launched_delta, hb_delta, pid=4242, attempts=0):
        TK.create_task(self.root, tid)
        changes = {"state": "running", "worker_pid": pid, "attempts": attempts,
                   "launched_at": _iso(self.now - timedelta(seconds=launched_delta))}
        if hb_delta is not None:
            changes["heartbeat"] = _iso(self.now - timedelta(seconds=hb_delta))
        S.update(self.root, tid, changes)

    def test_retry_within_limit_relaunches_and_bumps_attempts(self):
        self._running("t1", launched_delta=300, hb_delta=300, attempts=0)
        relaunched = []
        logs = []
        acted = SV.handle_fast_crashes(
            self.root, now=self.now, pid_alive=_dead,
            relaunch=lambda root, tid: relaunched.append(tid) or True,
            log=logs.append)
        self.assertEqual(acted, [("t1", "retry")])
        self.assertEqual(relaunched, ["t1"])
        d = S.read(self.root, "t1")
        self.assertEqual(d["attempts"], 1)
        self.assertEqual(d["state"], "running")  # in-place 재기동 → 마스터 중복 디스패치 방지
        self.assertTrue(any("t1" in m for m in logs))  # 결정이 tick 로그로 관측 가능

    def test_retry_limit_exceeded_escalates_to_needs_human(self):
        self._running("t1", launched_delta=300, hb_delta=300, attempts=3)
        relaunched = []
        logs = []
        acted = SV.handle_fast_crashes(
            self.root, now=self.now, max_attempts=3, pid_alive=_dead,
            relaunch=lambda root, tid: relaunched.append(tid) or True,
            log=logs.append)
        self.assertEqual(acted, [("t1", "needs_human")])
        self.assertEqual(relaunched, [])  # 더는 재기동 안 함
        d = S.read(self.root, "t1")
        self.assertEqual(d["state"], "needs_human")
        self.assertTrue(d["failure_reason"])  # 사유 가시화

    def test_healthy_worker_untouched(self):
        self._running("t1", launched_delta=600, hb_delta=30, attempts=0)  # 진행 중
        acted = SV.handle_fast_crashes(
            self.root, now=self.now, pid_alive=_dead,
            relaunch=lambda root, tid: True, log=lambda m: None)
        self.assertEqual(acted, [])
        self.assertEqual(S.read(self.root, "t1")["state"], "running")

    def test_transient_log_tail_read_from_disk(self):
        # 로그 시그니처 경로가 실제 워커 로그 파일에서 동작하는지(통합).
        self._running("t1", launched_delta=300, hb_delta=300, pid=4242)
        wdir = os.path.join(self.root, "state", "workers")
        os.makedirs(wdir, exist_ok=True)
        with open(os.path.join(wdir, "t1.log"), "w") as f:
            f.write("starting...\nError: Overloaded (429), retrying\n")
        acted = SV.handle_fast_crashes(
            self.root, now=self.now, pid_alive=_alive,  # pid 살아있어도 로그로 감지
            relaunch=lambda root, tid: True, log=lambda m: None)
        self.assertEqual(acted, [("t1", "retry")])


if __name__ == "__main__":
    unittest.main()
