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
