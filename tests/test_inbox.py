import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import inbox as IB


class InboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_then_list_then_read(self):
        name = IB.add(self.root, "로그인 버그 고쳐줘", slug="login")
        self.assertIn(name, IB.list_pending(self.root))
        self.assertEqual(IB.read_pending(self.root, name), "로그인 버그 고쳐줘")

    def test_mark_processed_moves_file(self):
        name = IB.add(self.root, "x", slug="x")
        IB.mark_processed(self.root, name)
        self.assertNotIn(name, IB.list_pending(self.root))
        moved = os.path.join(self.root, "state", "inbox", "processed", name)
        self.assertTrue(os.path.exists(moved))


if __name__ == "__main__":
    unittest.main()
