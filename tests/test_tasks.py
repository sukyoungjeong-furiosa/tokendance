import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import tasks as TK
import status as S


class TasksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_scaffolds_files(self):
        td = TK.create_task(self.root, "t1", title="제목", repo="r")
        for name in ("status.json", "task.md", "progress.md",
                     "steer.md", "steer.cursor", "log.md", "review.md"):
            self.assertTrue(os.path.exists(os.path.join(td, name)), name)
        with open(os.path.join(td, "steer.cursor")) as f:
            self.assertEqual(f.read().strip(), "0")

    def test_list_filters_by_state(self):
        TK.create_task(self.root, "t1")
        TK.create_task(self.root, "t2")
        S.update(self.root, "t2", {"state": "running", "worker_pid": 1})
        running = TK.list_tasks(self.root, state="running")
        self.assertEqual([d["id"] for d in running], ["t2"])
        self.assertEqual(len(TK.list_tasks(self.root)), 2)

    def test_count_running(self):
        TK.create_task(self.root, "t1")
        TK.create_task(self.root, "t2")
        S.update(self.root, "t1", {"state": "running", "worker_pid": 1})
        self.assertEqual(TK.count_running(self.root), 1)


if __name__ == "__main__":
    unittest.main()
