import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import finish as F
import tasks as TK
import status as S


class FinishTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        TK.create_task(self.root, "t1")

    def tearDown(self):
        self.tmp.cleanup()

    def test_review(self):
        F.finish(self.root, "t1", "review")
        self.assertEqual(S.read(self.root, "t1")["state"], "review")

    def test_blocked_with_reason(self):
        F.finish(self.root, "t1", "blocked", "build broken")
        d = S.read(self.root, "t1")
        self.assertEqual(d["state"], "blocked")
        self.assertEqual(d["failure_reason"], "build broken")

    def test_failed_requires_reason(self):
        with self.assertRaises(ValueError):
            F.finish(self.root, "t1", "failed")
        F.finish(self.root, "t1", "failed", "irrecoverable")
        self.assertEqual(S.read(self.root, "t1")["state"], "failed")

    def test_needs_human(self):
        F.finish(self.root, "t1", "needs_human")
        self.assertEqual(S.read(self.root, "t1")["state"], "needs_human")

    def test_invalid_state_rejected(self):
        with self.assertRaises(ValueError):
            F.finish(self.root, "t1", "done")


if __name__ == "__main__":
    unittest.main()
