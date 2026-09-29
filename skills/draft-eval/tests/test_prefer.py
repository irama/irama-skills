import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import prefer  # noqa: E402


def key(n):
    return {"key_id": "k", "pairs": {f"p{i:02d}": {"unit": f"u{i}", "after": "left"} for i in range(1, n + 1)}}


def answers(choices):
    return {"key_id": "k", "answers": {f"p{i:02d}": c for i, c in enumerate(choices, 1)}}


class PreferTest(unittest.TestCase):
    def test_seventy_percent_rule_counts_only_sided_pairs(self):
        # 7 after, 3 before, 2 no difference: 7 of 10 sided is exactly 70%, a pass at the threshold
        r = prefer.score(answers(["left"] * 7 + ["right"] * 3 + ["none"] * 2), key(12))
        self.assertEqual((r["after"], r["before"], r["none"], r["sided"]), (7, 3, 2, 10))
        self.assertTrue(r["pass"])
        self.assertTrue(r["at_threshold"])
        r = prefer.score(answers(["left"] * 6 + ["right"] * 4), key(10))
        self.assertFalse(r["pass"])
        self.assertIn("calibration", r["verdict"])

    def test_wrong_page_is_refused(self):
        with self.assertRaises(SystemExit):
            prefer.score({"key_id": "other", "answers": {}}, key(1))

    def test_page_hides_the_key(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            for side, byte in (("before", b"\x01"), ("after", b"\x02")):
                (t / side).mkdir()
                (t / side / "01-a.png").write_bytes(byte)
                (t / side / "02-b.png").write_bytes(byte)
                (t / side / "shots.json").write_text(json.dumps({"shots": [
                    {"id": "a", "file": "01-a.png"}, {"id": "b", "file": "02-b.png"}]}))
            page = prefer.build(t / "before/shots.json", t / "after/shots.json", ["a", "b"], t / "out", seed=1)
            html = page.read_text()
            k = json.loads((t / "out/prefer-key.json").read_text())
            self.assertEqual(sorted(v["unit"] for v in k["pairs"].values()), ["a", "b"])
            self.assertNotIn('"after"', html)
            self.assertNotIn('"unit"', html)
            self.assertIn(k["key_id"], html)


if __name__ == "__main__":
    unittest.main()
