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
                                           "one_model", "visual_journey")},
        "moments": {c: {"pass": True, "reason": 'Slide 2 says "x".'}
                    for c in ("star_moment", "peak_and_end", "five_moves", "people_and_stories",
                              "wrong_and_credible", "quoted_close", "light_moment", "notes_briefing",
                              "pain_before_solution", "four_acts")}}


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

    def test_validate_refuses_a_run_started_under_another_rubric_version(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "rubric.json").write_text(json.dumps({"rubric_version": "0.1"}))
            (t / "rounds" / "r1").mkdir(parents=True)
            raw = t / "r.json"
            raw.write_text(json.dumps(GOOD))
            out = t / "rounds" / "r1" / "arc.json"
            self.assertEqual(arc.main(["validate", str(raw), "--grader", "claude", "--round", "1", "-o", str(out)]), 1)
            self.assertFalse(out.exists())

    def test_hidden_backstage_slide_without_hidden_src_is_still_backstage(self):
        import extract
        units = extract.extract_deck('<deck-stage><section data-slide-id="open">Open</section>'
                                     '<section data-slide-id="plan" data-hidden data-role="backstage-plan">move tags</section>'
                                     '</deck-stage>')
        plan = next(u for u in units["units"] if u["id"] == "plan")
        self.assertTrue(plan["hidden"])
        self.assertTrue(arc.is_backstage(plan))

    def test_backstage_slides_reach_units_md_and_other_hidden_slides_do_not(self):
        import extract
        html = ("<deck-stage>"
                '<section data-slide-id="open" data-role="title">Open</section>'
                '<section data-slide-id="plan" data-role="backstage-plan" data-hidden data-hidden-src>'
                "Act 1 0:00 to 5:00, slide 1 confirm their suspicions</section>"
                '<section data-slide-id="spare" data-hidden-src>spare slide</section>'
                '<section data-slide-id="body">Body</section></deck-stage>')
        units = extract.extract_deck(html)
        self.assertTrue(next(u for u in units["units"] if u["id"] == "plan")["hidden"])
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "contact.png").write_bytes(b"png")
            (t / "shots.json").write_text(json.dumps({"contact": "contact.png", "shots": []}))
            md = (Path(arc.build(units, t / "out", t / "shots.json")["dir"]) / "units.md").read_text()
        head = md.index("# Backstage, not presented")
        self.assertIn("confirm their suspicions", md[head:])
        self.assertIn("## Backstage 1", md[head:])
        self.assertNotIn("spare slide", md)
        self.assertIn("## Slide 2", md[:head])  # presented slides keep their numbers
        self.assertNotIn("## Slide 3", md)


if __name__ == "__main__":
    unittest.main()
