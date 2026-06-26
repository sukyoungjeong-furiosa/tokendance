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

    def test_update_nonexistent_does_not_resurrect_dir(self):
        # 이미 archive 된(=없는) task 를 update/set/heartbeat 해도 유령 디렉토리를 만들지 않는다.
        with self.assertRaises(ValueError):
            S.update(self.root, "ghost", {"state": "done"})
        self.assertFalse(os.path.exists(os.path.join(self.root, "state", "tasks", "ghost")))
        with self.assertRaises(ValueError):
            S.heartbeat(self.root, "ghost")
        self.assertFalse(os.path.exists(os.path.join(self.root, "state", "tasks", "ghost")))

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
        self.assertIsInstance(after["updated"], str)
        self.assertTrue(len(after["updated"]) > 0)

    def test_bump_attempts_increments(self):
        S.init(self.root, "t1")
        S.update(self.root, "t1", {}, increment_attempts=True)
        self.assertEqual(S.read(self.root, "t1")["attempts"], 1)
        S.update(self.root, "t1", {}, increment_attempts=True)
        self.assertEqual(S.read(self.root, "t1")["attempts"], 2)

    def test_init_has_launched_at_none(self):
        # launched_at: 디스패치 시각(즉사 감지 grace window 기준점). 초기엔 None.
        S.init(self.root, "t1")
        self.assertIn("launched_at", S.read(self.root, "t1"))
        self.assertIsNone(S.read(self.root, "t1")["launched_at"])

    def test_cli_set_launched_now_stamps_timestamp(self):
        S.init(self.root, "t1")
        S.main(["--root", self.root, "set", "t1", "--state", "running", "--launched-now"])
        d = S.read(self.root, "t1")
        self.assertEqual(d["state"], "running")
        self.assertIsInstance(d["launched_at"], str)
        self.assertTrue(d["launched_at"].endswith("Z"))


if __name__ == "__main__":
    unittest.main()
