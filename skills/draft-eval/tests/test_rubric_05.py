"""Rubric 0.5: the confirmed lesson groups as anchors, deck-level rulings in the arc pass, the
sources field, and the keep list in the review brief. No network."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import arc  # noqa: E402
import brief  # noqa: E402
import extract  # noqa: E402
import packet  # noqa: E402
import validate  # noqa: E402
from test_brief import run_dir  # noqa: E402

RUBRIC = json.loads((HERE / "rubric.json").read_text())
CRIT = {c["id"]: c for c in RUBRIC["criteria"]}
ARC = {c["id"]: c for c in RUBRIC["arc"]["criteria"]}
RULINGS = [
    {"criterion": "taxonomy_ids", "excerpt": "Two frameworks share one look.", "score": 3, "reason": "One look each.",
     "unit": "deck"},
    {"criterion": "one_model", "excerpt": "Two slides model one idea.", "score": 3, "reason": "Merge them.",
     "unit": "s4"},
    {"criterion": "flow", "excerpt": "Unit-level flow.", "score": 4, "reason": "A unit ruling.", "unit": "s7"},
    {"criterion": "clear", "excerpt": "A step name.", "score": 3, "reason": "One guess.", "unit": "s2"},
]


class Rubric05Test(unittest.TestCase):
    def test_version_and_changelog(self):
        self.assertIn(RUBRIC["rubric_version"], ("0.5", "0.6"))  # 0.6 keeps these anchors
        self.assertEqual(RUBRIC["phase"], "experimental")
        self.assertIn("eight lesson groups", {c["version"]: c["note"] for c in RUBRIC["changelog"]}["0.5"])

    def test_cold_reader_lets_slides_build_on_earlier_slides(self):
        q = CRIT["clear"]["question"]
        self.assertIn("introduces on an earlier slide", q)
        self.assertIn("context clues", q)
        self.assertIn("only beside the speaker", q)

    def test_hedges_are_filler_and_provenance_goes_in_the_sources_field(self):
        self.assertIn("did not test this", CRIT["economy"]["question"])
        self.assertIn("sources field", CRIT["economy"]["question"])
        self.assertIn("sources field", CRIT["honest_numbers"]["anchors"]["5"])
        self.assertIn("say aloud", CRIT["notes_actionable"]["question"])

    def test_visual_draws_the_shape_true_and_recognisable(self):
        v = CRIT["visual"]
        self.assertIn("shape the idea already has", v["question"])
        for phrase in ("contour lines that cross", "pipette", "the story does not need"):
            self.assertIn(phrase, v["anchors"]["3"])
        self.assertIn("fewest encodings", v["anchors"]["5"])

    def test_one_distinct_look_per_framework_and_curiosity_in_variety(self):
        t = ARC["taxonomy_ids"]
        self.assertIn("one distinct look", t["question"])
        self.assertIn("share a look", t["anchors"]["3"])
        self.assertIn("curiosity", ARC["variety"]["question"])

    def test_lessons_list_carries_eight_groups(self):
        g = RUBRIC["lessons"]["groups"][:8]  # 0.6 appends motion
        self.assertEqual([x["id"] for x in g], ["words", "economy", "shape", "encodings", "frameworks", "devices",
                                                "regressions", "evals"])
        self.assertTrue(all(x["checks"] for x in g))

    def test_deck_level_rulings_reach_the_arc_pass_and_unit_rulings_do_not(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            rl = t / "rulings.jsonl"
            rl.write_text("\n".join(json.dumps(r) for r in RULINGS) + "\n")
            picked = arc.load_arc_examples(rl, RUBRIC)
            self.assertEqual([e["criterion"] for e in picked], ["taxonomy_ids", "one_model"])
            (t / "contact.png").write_bytes(b"png")
            (t / "shots.json").write_text(json.dumps({"contact": "contact.png", "shots": []}))
            doc = {"kind": "deck", "units": [{"id": "a", "role": "title", "text": "Hi"}]}
            b = arc.build(doc, t / "out", t / "shots.json", examples=rl)
            prompt = Path(b["prompt"]).read_text()
            self.assertIn("## Calibration examples", prompt)
            self.assertIn("Two frameworks share one look.", prompt)
            self.assertNotIn("Unit-level flow.", prompt)
            self.assertEqual((b["examples"], len(b["examples_sha256"])), (2, 64))
            plain = Path(arc.build(doc, t / "out2", t / "shots.json")["prompt"]).read_text()
            self.assertNotIn("Calibration examples", plain)
            self.assertNotIn("{{", plain)
            # packet.py keeps the unit rulings and skips the arc-only ones
            self.assertEqual({e["criterion"] for e in packet.load_examples(rl, RUBRIC)}, {"flow", "clear"})

    def test_sources_field_is_extracted_packed_and_quotable(self):
        html = ('<html><body><deck-stage><section data-slide-id="s1">Most readers missed it</section>'
                '</deck-stage><script type="application/json" id="speaker-notes">[{"index":1,"note":"Ask."}]'
                '</script><script type="application/json" id="slide-sources">'
                '[{"index":1,"sources":"Dratsch 2023, 27 readers; the study did not test the advice."}]'
                '</script></body></html>')
        u = extract.extract_deck(html)["units"][0]
        self.assertIn("did not test", u["sources"])
        self.assertNotIn("did not test", u["notes"])
        self.assertEqual(validate.quote_sources('It says "27 readers".', u), ["unit"])
        with tempfile.TemporaryDirectory() as t:
            packet.build({"kind": "article", "units": [dict(u, role="content")]}, t)
            self.assertTrue(list(Path(t).rglob("sources.txt")))

    def test_brief_reports_the_keep_list_against_the_rewrites(self):
        with tempfile.TemporaryDirectory() as t:
            run = run_dir(Path(t) / "eval-runs" / "r")
            (run / "rounds" / "r1" / "rewrites.json").write_text(json.dumps({"rewrites": [
                {"unit": "a", "why": "w"}, {"unit": "b", "why": "w", "keep": "the funnel stays, relabelled"}]}))
            (Path(t) / "keep.json").write_text(json.dumps({"keep": [
                {"unit": "a", "element": "the sticky notes"}, {"unit": "b", "element": "the funnel"},
                {"unit": "c", "element": "the map"}]}))
            text = brief.fill(run)
            self.assertIn("rewritten with no keep note: check by eye", text)
            self.assertIn("rewritten: the funnel stays, relabelled", text)
            self.assertIn("| c | the map | untouched |", text)
        with tempfile.TemporaryDirectory() as t:
            self.assertIn("no keep.json yet", brief.fill(run_dir(Path(t) / "eval-runs" / "r")))


if __name__ == "__main__":
    unittest.main()
