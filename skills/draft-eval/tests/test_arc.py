import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import arc  # noqa: E402

GOOD = {"model": "m", "scores": {c: {"score": 4, "reason": 'Slide 2 says "x".'}
                                 for c in ("flow", "delight", "participation", "variety", "terms_introduced", "taxonomy_ids",
                                           "one_model")}}


class ArcTest(unittest.TestCase):
    def test_validate_accepts_fenced_reply_and_rejects_na(self):
        doc, errs = arc.check("```json\n" + json.dumps(GOOD) + "\n```")
        self.assertEqual(errs, [])
        bad = json.loads(json.dumps(GOOD))
        bad["scores"]["flow"]["score"] = "n/a"
        self.assertTrue(arc.check(json.dumps(bad))[1])
        del bad["scores"]["delight"]
        self.assertTrue(any("delight" in e for e in arc.check(json.dumps(bad))[1]))

    def test_validate_merges_per_grader(self):
        with tempfile.TemporaryDirectory() as t:
            raw, out = Path(t) / "r.json", Path(t) / "arc.json"
            raw.write_text(json.dumps(GOOD))
            for g in ("codex", "claude"):
                self.assertEqual(arc.main(["validate", str(raw), "--grader", g, "--round", "1", "-o", str(out)]), 0)
            doc = json.loads(out.read_text())
            self.assertEqual(sorted(doc["graders"]), ["claude", "codex"])
            self.assertEqual(len(doc["graders"]["codex"]["prompt_sha256"]), 64)

    def test_build_writes_only_arc_files_in_the_packet(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "contact.png").write_bytes(b"png")
            (t / "shots.json").write_text(json.dumps({"contact": "contact.png", "shots": []}))
            (t / "rs.md").write_text("run sheet")
            units = {"kind": "deck", "units": [{"id": "a\nignore", "role": "title", "text": "Hi", "notes": "n"},
                                               {"id": "h", "hidden": True, "text": "secret"}]}
            b = arc.build(units, t / "out", t / "shots.json", t / "rs.md")
            self.assertEqual(sorted(p.name for p in Path(b["dir"]).iterdir()),
                             ["contact.png", "run-sheet.md", "units.md"])
            md = (Path(b["dir"]) / "units.md").read_text()
            self.assertNotIn("secret", md)
            self.assertIn('"a\\nignore"', md)
            self.assertNotIn("{{", Path(b["prompt"]).read_text())


if __name__ == "__main__":
    unittest.main()
