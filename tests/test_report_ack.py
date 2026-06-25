import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import report as RP
import tasks as TK
import status as S
import inbox as IB


class AckTextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_inbox_and_named_states_caps(self):
        IB.add(self.root, "로그인 고쳐줘", slug="slack")
        IB.add(self.root, "리포트 양식 바꿔", slug="slack")
        TK.create_task(self.root, "t-run", title="결제 리팩터")
        S.update(self.root, "t-run", {"state": "running"})
        TK.create_task(self.root, "t-hum", title="DB 마이그 결정 필요")
        S.update(self.root, "t-hum", {"state": "needs_human"})
        for i in range(4):  # done 4개 → 숫자만
            TK.create_task(self.root, f"d{i}")
            S.update(self.root, f"d{i}", {"state": "done"})

        txt = RP.ack_text(self.root)
        self.assertIn("받았어요", txt)
        self.assertIn("미처리 2건", txt)            # inbox 2건
        self.assertIn("로그인 고쳐줘", txt)          # echo
        self.assertIn("결제 리팩터", txt)            # running 이름
        self.assertIn("DB 마이그", txt)              # needs_human 이름
        self.assertIn("✅4", txt)                    # done 은 숫자만

    def test_cap_plus_more(self):
        for i in range(5):  # running 5개 → 3개 이름 + "+2"
            TK.create_task(self.root, f"r{i}", title=f"작업{i}")
            S.update(self.root, f"r{i}", {"state": "running"})
        txt = RP.ack_text(self.root, max_each=3)
        self.assertIn("진행 5", txt)
        self.assertIn("+2", txt)

    def test_empty_is_just_header_and_tail(self):
        txt = RP.ack_text(self.root)
        self.assertIn("받았어요", txt)
        self.assertIn("✅0", txt)


if __name__ == "__main__":
    unittest.main()
