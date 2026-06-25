import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import prompt as P


class PromptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "prompts"))

    def tearDown(self):
        self.tmp.cleanup()

    def _w(self, rel, body):
        p = os.path.join(self.root, "prompts", rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(body)

    def test_single_file(self):
        self._w("worker.md", "single worker prompt\n")
        self.assertEqual(P.build(self.root, "worker"), "single worker prompt\n")

    def test_dir_concatenated_in_filename_order(self):
        self._w("master/02-tools.md", "TOOLS")
        self._w("master/01-persona.md", "PERSONA")
        self._w("master/03-rules.md", "RULES")
        out = P.build(self.root, "master")
        self.assertEqual(out.index("PERSONA") < out.index("TOOLS") < out.index("RULES"), True)

    def test_dir_wins_over_file(self):
        self._w("master.md", "OLD SINGLE")
        self._w("master/01.md", "NEW PARTS")
        self.assertIn("NEW PARTS", P.build(self.root, "master"))
        self.assertNotIn("OLD SINGLE", P.build(self.root, "master"))


if __name__ == "__main__":
    unittest.main()
