"""Rubric 0.6: motion that carries meaning, the visual and motion journey, and the ?motion gate.
No network."""
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
import validate  # noqa: E402

RUBRIC = json.loads((HERE / "rubric.json").read_text())
CRIT = {c["id"]: c for c in RUBRIC["criteria"]}
ARC = {c["id"]: c for c in RUBRIC["arc"]["criteria"]}
DECK = ('<html><body><deck-stage>'
        '<section data-slide-id="s1" data-role="content" data-motion="the numbers shake in proportion to their rate, '
        'then go still">Error rates</section>'
        '<section data-slide-id="s2" data-role="content" data-motion="none">A plain rule</section>'
        '<section data-slide-id="s3" data-role="content">No intent declared</section>'
        '</deck-stage></body></html>')
PASSING = """09 settles 7.0s  [09 Hallucination scatter]
05 settles 1.5s  1 ambient  [05 Drift]
01 still  [01 PROBLEM slide label]

all presented slides settle by 7s"""
FAILING = """03 LATE settles 8.0s  [03 Slow reveal]
31 settles 0.6s  LOOP x1 (mark data-ambient if it is background)  [31 Spinner]
05 settles 1.5s  1 ambient  [05 Drift]

2 PROBLEM(S)"""


class Rubric06Test(unittest.TestCase):
    def test_version_and_changelog(self):
        self.assertEqual(RUBRIC["rubric_version"], "0.6")
        self.assertEqual(RUBRIC["phase"], "experimental")
        note = {c["version"]: c["note"] for c in RUBRIC["changelog"]}["0.6"]
        self.assertIn("not comparable", note)
        new = [note, CRIT["motion"], ARC["visual_journey"], RUBRIC["lessons"]["groups"][-1]]
        self.assertNotIn("\u2014", json.dumps(new, ensure_ascii=False))

    def test_motion_criterion_judges_declared_motion_on_decks(self):
        m = CRIT["motion"]
        self.assertEqual((m["name"], m["kind"], m["applies_to"]), ("Motion carries meaning", "judged", ["deck"]))
        for phrase in ("act out", "settle by 7s", "subtle and meaningful", "static screenshot", "motion.txt"):
            self.assertIn(phrase, m["question"])
        self.assertIn("decorative", m["anchors"]["1"])
        self.assertIn("Generic entrance motion", m["anchors"]["3"])
        self.assertIn("still slide whose idea plainly moves", m["anchors"]["3"])
        for phrase in ("shake in proportion", "stamped", "next slide's headword", "settles"):
            self.assertIn(phrase, m["anchors"]["5"])
        self.assertEqual(m["na_allowed"], {"roles": ["evidence"], "conditions": ["motion_none"]})
        self.assertNotIn("motion", {c["id"] for c in RUBRIC["criteria"] if "article" in c["applies_to"]})

    def test_visual_journey_is_an_arc_criterion_in_the_bar(self):
        v = ARC["visual_journey"]
        self.assertEqual(v["name"], "Visual and motion journey")
        for phrase in ("nine presented slides in ten", "no two neighbours alike", "callbacks", "immersive"):
            self.assertIn(phrase, v["question"])
        self.assertEqual(sorted(v["anchors"]), ["1", "3", "5"])
        self.assertIn("visual_journey", RUBRIC["bars"]["arc_criteria"])
        self.assertEqual(RUBRIC["lessons"]["groups"][-1]["id"], "motion")

    def test_schemas_and_prompts_name_the_new_ids(self):
        schema = json.loads((HERE / "schema.json").read_text())
        scores = schema["properties"]["records"]["items"]["properties"]["scores"]
        self.assertEqual(set(scores["required"]), {c["id"] for c in RUBRIC["criteria"]})
        arc_schema = json.loads((HERE / "arc-schema.json").read_text())
        self.assertEqual(set(arc_schema["properties"]["scores"]["required"]), set(ARC))
        self.assertIn("`motion`", (HERE / "grader-prompt.md").read_text())
        self.assertIn('"visual_journey": {"score"', (HERE / "arc-prompt.md").read_text())

    def test_motion_verdict_passes_on_the_summary_line(self):
        # a slide label containing PROBLEM must not fail a clean report
        self.assertEqual(check.motion_verdict(PASSING), {"pass": True, "problems": []})

    def test_motion_verdict_fails_late_and_loop(self):
        v = check.motion_verdict(FAILING)
        self.assertFalse(v["pass"])
        self.assertEqual(len(v["problems"]), 2)
        self.assertTrue(v["problems"][0].startswith("03 LATE"))
        self.assertIn("LOOP x1", v["problems"][1])
        self.assertFalse(check.motion_verdict("")["pass"])

    def test_missing_motion_report_skips_the_gate(self):
        old = check.dump_dom
        check.dump_dom = lambda index, query: "<html><body><deck-stage></deck-stage></body></html>"
        try:
            g = check.motion("index.html")
        finally:
            check.dump_dom = old
        self.assertTrue(g["pass"])
        self.assertEqual(g["skipped"], "deck-tools.js predates ?motion")

    def test_extract_carries_data_motion_and_packet_and_arc_show_it(self):
        u = extract.extract_deck(DECK)["units"]
        self.assertEqual([x["motion"] for x in u],
                         ["the numbers shake in proportion to their rate, then go still", "none", ""])
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            shots = {"contact": "contact.png", "shots": [{"id": x["id"], "file": "s.png"} for x in u]}
            (t / "s.png").write_bytes(b"png")
            (t / "contact.png").write_bytes(b"png")
            (t / "shots.json").write_text(json.dumps(shots))
            doc = {"kind": "deck", "units": u}
            packet.build(doc, t / "p", t / "shots.json")
            self.assertEqual(sorted(p.parent.name for p in (t / "p").rglob("motion.txt")), ["01-s1", "02-s2"])
            b = arc.build(doc, t / "out", t / "shots.json")
            self.assertIn("Motion (declared):", (Path(b["dir"]) / "units.md").read_text())
            self.assertIn("### `motion`: Motion carries meaning", packet.render_criteria(RUBRIC, "deck"))

    def test_motion_none_allows_na_and_never_forces_it(self):
        u = extract.extract_deck(DECK)["units"]
        m = CRIT["motion"]
        self.assertFalse(validate.na_allowed(m, u[0], False, False, RUBRIC))
        self.assertTrue(validate.na_allowed(m, u[1], False, False, RUBRIC))
        self.assertIsNone(validate.na_forced(m, u[1], False))
        self.assertTrue(validate.na_allowed(m, dict(u[2], role="evidence"), False, False, RUBRIC))
        self.assertEqual(validate.quote_sources('It says "shake in proportion".', u[0]), ["unit"])


if __name__ == "__main__":
    unittest.main()
