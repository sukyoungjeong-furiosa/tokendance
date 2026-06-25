import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import config as C


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, body):
        with open(os.path.join(self.root, "config.local.md"), "w") as f:
            f.write(body)

    def test_defaults_when_missing(self):
        self.assertEqual(C.get("SLACK_CHANNEL", r=self.root), "")
        self.assertEqual(C.get_int("MAX_WORKERS", r=self.root), 1)
        self.assertEqual(C.get_int("POLL_INTERVAL", r=self.root), 1800)

    def test_reads_values_ignoring_fence_and_comments(self):
        self._write("# header\n```\nSLACK_CHANNEL=U999  # inline comment\nMAX_WORKERS=4\n```\n")
        self.assertEqual(C.get("SLACK_CHANNEL", r=self.root), "U999")
        self.assertEqual(C.get_int("MAX_WORKERS", r=self.root), 4)

    def test_bad_int_falls_back_to_default(self):
        self._write("```\nMAX_WORKERS=oops\n```\n")
        self.assertEqual(C.get_int("MAX_WORKERS", r=self.root), 1)

    def test_paths_have_expected_keys(self):
        p = C.paths(self.root)
        for k in ("tasks", "inbox_pending", "reports", "worktrees", "slack_cursor", "master_notes"):
            self.assertIn(k, p)
            self.assertTrue(p[k].startswith(self.root))


if __name__ == "__main__":
    unittest.main()
