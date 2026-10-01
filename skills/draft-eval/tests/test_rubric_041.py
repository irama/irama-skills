"""Rubric 0.4.1: loaded wording needs an unclear object, the deck's terms list, the two new arc
criteria, findings against recommendations. No network."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import arc  # noqa: E402
import check  # noqa: E402
import extract  # noqa: E402
import packet  # noqa: E402

RUBRIC = json.loads((HERE / "rubric.json").read_text())
DECK = """<html><body><deck-stage>
<section data-slide-id="title">Opening</section>
<section data-slide-id="terms" data-role="terms" data-hidden><dl>
<dt>the loop</dt><dd>The cycle of acting, checking and correcting.</dd>
<dt>D1</dt><dd>Deployment one, machine learning.</dd>
<dt>orphan</dt><dd>A term no slide introduces.</dd></dl></section>
<section data-slide-id="early">Who holds the loop?</section>
<section data-slide-id="intro" data-introduces="the loop, D1">A thermostat is a loop</section>
<section data-slide-id="later">D1 keeps the loop</section>
</deck-stage>
<script type="application/json" id="speaker-notes">["n1","","n3","n4","n5"]</script></body></html>"""


class Rubric041Test(unittest.TestCase):
    def setUp(self):
        self.doc = extract.extract_deck(DECK)

    def test_version_and_changelog(self):
        self.assertIn(RUBRIC["rubric_version"], ("0.4.1", "0.4.2", "0.5"))  # 0.4.2 and 0.5 keep these rulings
        self.assertIn("fair-or-harsh", {c["version"]: c["note"] for c in RUBRIC["changelog"]}["0.4.1"])

    def test_extract_reads_terms_and_hides_the_terms_slide(self):
        t = {x["term"]: x for x in self.doc["terms"]}
        self.assertEqual(list(t), ["the loop", "D1", "orphan"])
        self.assertEqual(t["the loop"]["definition"], "The cycle of acting, checking and correcting.")
        self.assertEqual((t["the loop"]["introduced_by"], t["the loop"]["introduced_at"]), ("intro", 4))
        self.assertEqual(t["D1"]["introduced_by"], "intro")
        self.assertIsNone(t["orphan"]["introduced_at"])
        terms_unit = next(u for u in self.doc["units"] if u["id"] == "terms")
        self.assertTrue(terms_unit["hidden"])
        self.assertEqual(self.doc["units"][2]["notes"], "n3")  # notes stay aligned past the hidden slide

    def test_packet_passes_terms_and_skips_the_terms_slide(self):
        with tempfile.TemporaryDirectory() as t:
            shots = Path(t) / "shots.json"
            (Path(t) / "x.png").write_bytes(b"png")
            shots.write_text(json.dumps({"shots": [{"id": u["id"], "file": "x.png"} for u in self.doc["units"]]}))
            b = packet.build(self.doc, Path(t) / "out", shots, rubric=RUBRIC)[0]
            self.assertNotIn("terms", b["units"])
            prompt = Path(b["prompt"]).read_text()
            self.assertIn('"term": "the loop"', prompt)
            self.assertIn('"introduced_at": 4', prompt)
            self.assertIn('"ordinal": 3', prompt)
        self.assertIn("defines no terms", packet.render_prompt(RUBRIC, "deck", []))

    def test_check_warns_on_a_term_used_before_it_is_introduced(self):
        units = [u for u in self.doc["units"] if not u["hidden"]]
        warn = {w["term"]: w for w in check.terms_before_intro(units, self.doc["terms"])}
        self.assertEqual(warn["the loop"]["used_before"], ["early"])
        self.assertEqual(warn["orphan"]["used_before"], [])
        self.assertNotIn("D1", warn)

    def test_arc_carries_the_two_new_criteria_and_the_terms(self):
        ids = [c["id"] for c in RUBRIC["arc"]["criteria"]]
        for c in ("terms_introduced", "taxonomy_ids"):
            self.assertIn(c, ids)
            self.assertIn(c, RUBRIC["bars"]["arc_criteria"])
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "contact.png").write_bytes(b"png")
            shots = Path(t) / "shots.json"
            shots.write_text(json.dumps({"contact": "contact.png", "shots": []}))
            out = arc.build(self.doc, t, shots, rubric=RUBRIC)
            terms = (Path(out["dir"]) / "terms.md").read_text()
            self.assertIn('"the loop"', terms)
            self.assertIn("introduced on slide 3", terms)  # slide numbers skip the hidden terms slide
            self.assertIn("terms_introduced", Path(out["prompt"]).read_text())

    def test_anchors_carry_the_rulings(self):
        c = {x["id"]: x for x in RUBRIC["criteria"]}
        self.assertIn("only when its object is not clear", c["clear"]["anchors"]["3"])
        self.assertIn("introduces on an earlier slide", c["clear"]["question"])  # 0.5 widens the terms-slide rule
        self.assertIn("findings and recommendations", c["visual"]["anchors"]["3"])
        self.assertIn("look visibly different", c["visual"]["anchors"]["5"])

    def test_bars_claude_sets_it_codex_audits(self):
        b = RUBRIC["bars"]
        self.assertNotIn("both_graders_required", b)
        self.assertEqual((b["bar_grader"], b["audit_grader"]), ("claude", "codex"))
        self.assertIn("--graders both", b["split_regrade"])


if __name__ == "__main__":
    unittest.main()
