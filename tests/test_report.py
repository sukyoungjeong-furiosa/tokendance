import os, sys, tempfile, unittest
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import report as R
import tasks as TK
import status as S


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_kst_is_utc_plus_9(self):
        # 2026-06-24 15:00 UTC → 2026-06-25 00:00 KST
        s = R._kst(datetime(2026, 6, 24, 15, 0, tzinfo=timezone.utc))
        self.assertEqual(s, "2026-06-25 00:00 KST")

    def test_counts_and_sections(self):
        TK.create_task(self.root, "a")
        S.update(self.root, "a", {"state": "running"})
        TK.create_task(self.root, "b")
        S.update(self.root, "b", {"state": "needs_human"})
        TK.create_task(self.root, "c")
        S.update(self.root, "c", {"state": "failed", "failure_reason": "boom"})
        text = R.build_report(self.root, now=datetime(2026, 6, 24, 0, 0, tzinfo=timezone.utc))
        self.assertIn("🤖 tokendance", text)
        self.assertIn("🟢1", text)        # running count
        self.assertIn("판단 필요", text)   # needs_human section present
        self.assertIn("a", text)
        self.assertIn("boom", text)        # failure_reason surfaced

    def test_empty_state_has_header_only(self):
        text = R.build_report(self.root, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertIn("🤖 tokendance", text)
        self.assertIn("🟢0", text)


if __name__ == "__main__":
    unittest.main()
