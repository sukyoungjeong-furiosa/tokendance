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

    def test_burst_adds_no_collision(self):
        # 같은 순간(같은 초)에 여러 메시지를 넣어도 전부 보존돼야 한다(유실/덮어쓰기 금지).
        names = [IB.add(self.root, f"msg{i}", slug="slack") for i in range(5)]
        self.assertEqual(len(set(names)), 5)                  # 파일명 전부 distinct
        self.assertEqual(len(IB.list_pending(self.root)), 5)  # 5개 모두 디스크에
        texts = {IB.read_pending(self.root, n) for n in names}
        self.assertEqual(texts, {f"msg{i}" for i in range(5)})

    def test_mark_processed_moves_file(self):
        name = IB.add(self.root, "x", slug="x")
        IB.mark_processed(self.root, name)
        self.assertNotIn(name, IB.list_pending(self.root))
        moved = os.path.join(self.root, "state", "inbox", "processed", name)
        self.assertTrue(os.path.exists(moved))


if __name__ == "__main__":
    unittest.main()
