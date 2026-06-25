import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import checkpoint as CP
import tasks as TK
import status as S


class CheckpointTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        TK.create_task(self.root, "t1")

    def tearDown(self):
        self.tmp.cleanup()

    def _td(self):
        return os.path.join(self.root, "state", "tasks", "t1")

    def _append_steer(self, text):
        with open(os.path.join(self._td(), "steer.md"), "a") as f:
            f.write(text)

    def test_first_read_returns_all_then_empty(self):
        self._append_steer("## 2026 (master)\n방향 바꿔\n")
        out1 = CP.read_new_steer(self.root, "t1")
        self.assertIn("방향 바꿔", out1)
        out2 = CP.read_new_steer(self.root, "t1")   # 이미 소비 → 없음
        self.assertEqual(out2, "")

    def test_only_new_appended_returned(self):
        self._append_steer("first\n")
        CP.read_new_steer(self.root, "t1")
        self._append_steer("second\n")
        out = CP.read_new_steer(self.root, "t1")
        self.assertEqual(out.strip(), "second")

    def test_checkpoint_updates_heartbeat(self):
        before = S.read(self.root, "t1")
        CP.checkpoint(self.root, "t1")
        after = S.read(self.root, "t1")
        self.assertIsNotNone(after["heartbeat"])
        self.assertEqual(after["version"], before["version"] + 1)

    def test_no_steer_file_is_empty(self):
        os.remove(os.path.join(self._td(), "steer.md"))
        self.assertEqual(CP.read_new_steer(self.root, "t1"), "")


if __name__ == "__main__":
    unittest.main()
