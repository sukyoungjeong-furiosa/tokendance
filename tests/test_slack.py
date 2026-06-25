import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import slack as SL

HUMAN = "U_HUMAN"


class FilterNewTest(unittest.TestCase):
    def _msgs(self):
        return [
            {"ts": "100.0", "user": HUMAN, "text": "old"},
            {"ts": "200.0", "user": HUMAN, "text": "new1"},
            {"ts": "210.0", "user": "U_BOT", "text": "bot echo"},      # 봇 → 제외
            {"ts": "220.0", "user": HUMAN, "subtype": "channel_join"},  # 시스템 → 제외
            {"ts": "230.0", "user": HUMAN, "text": "new2"},
        ]

    def test_only_newer_human_messages_sorted(self):
        out = SL.filter_new(self._msgs(), "150.0", HUMAN)
        self.assertEqual([t for _, t in out], ["new1", "new2"])

    def test_no_cursor_takes_all_human(self):
        out = SL.filter_new(self._msgs(), "", HUMAN)
        self.assertEqual([t for _, t in out], ["old", "new1", "new2"])

    def test_cursor_is_exclusive(self):
        out = SL.filter_new(self._msgs(), "230.0", HUMAN)
        self.assertEqual(out, [])

    def test_ordering_oldest_first(self):
        msgs = [{"ts": "300.0", "user": HUMAN, "text": "b"},
                {"ts": "250.0", "user": HUMAN, "text": "a"}]
        self.assertEqual([t for _, t in SL.filter_new(msgs, "0", HUMAN)], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
