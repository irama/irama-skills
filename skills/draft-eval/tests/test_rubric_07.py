"""Rubric 0.7: the deck-level moments group, graded pass or fail in the arc pass and held in the bar.
No network."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import arc  # noqa: E402
import brief  # noqa: E402
import score_round as sr  # noqa: E402

RUBRIC = json.loads((HERE / "rubric.json").read_text())
M = RUBRIC["moments"]
IDS = ["star_moment", "peak_and_end", "five_moves", "people_and_stories", "wrong_and_credible",
       "light_moment", "stage_directions"]
CRITS = [c["id"] for c in RUBRIC["criteria"]]
UNITS = {"kind": "deck", "units": [{"id": u} for u in "abc"]}
SCORES = {c: {"score": 5, "reason": 'Slide 2 says "x".'} for c in RUBRIC["bars"]["arc_criteria"]}


def moments(passed):
    return {c: {"pass": passed, "reason": 'Slide 2 says "x".'} for c in IDS}


def bar(arc_by_grader):
    recs = [{"unit": u, "scores": {c: {"score": 5} for c in CRITS}} for u in "abc"]
    return sr.score(UNITS, {"claude": recs}, mechanical={"pass": True}, arc=arc_by_grader,
                    rubric=RUBRIC)["bar"]


class Rubric07Test(unittest.TestCase):
    def test_version_and_changelog(self):
        self.assertEqual(RUBRIC["rubric_version"], "0.7")
        self.assertEqual(M["phase"], "experimental")
        note = {c["version"]: c["note"] for c in RUBRIC["changelog"]}["0.7"]
        self.assertIn("not comparable", note)
        self.assertNotIn("—", json.dumps([note, M], ensure_ascii=False))
        self.assertIn("0.7", (HERE / "rubric-history.md").read_text())

    def test_seven_checks_each_with_pass_and_fail(self):
        self.assertEqual([c["id"] for c in M["checks"]], IDS)
        for c in M["checks"]:
            self.assertTrue(c["name"] and c["pass"] and c["fail"], c["id"])
        text = {c["id"]: c["pass"] for c in M["checks"]}
        self.assertIn("Something They'll Always Remember", text["star_moment"])
        self.assertIn("echoes the first", text["peak_and_end"])
        self.assertIn("comes before the first promise", text["five_moves"])
        self.assertIn("physical scale", text["people_and_stories"])
        self.assertIn("first three minutes", text["wrong_and_credible"])
        for tag in ("[MOVE:", "[STORY]", "[ASK]", "[PAUSE]"):
            self.assertIn(tag, text["stage_directions"])

    def test_the_five_moves_and_no_ethics_guard(self):
        self.assertEqual([m["name"] for m in M["moves"]],
                         ["encourage their dreams", "justify their failures", "allay their fears",
                          "confirm their suspicions", "always on your side"])
        blob = json.dumps(M).lower()
        for gone in ("throw rocks", "enemies", "ethic"):
            self.assertNotIn(gone, blob)

    def test_schema_requires_every_check_as_a_boolean(self):
        good = {"model": "m", "scores": SCORES, "moments": moments(True)}
        self.assertEqual(arc.check(json.dumps(good))[1], [])
        for broken in ({k: v for k, v in good.items() if k != "moments"},
                       dict(good, moments={k: v for k, v in moments(True).items() if k != "light_moment"}),
                       dict(good, moments=dict(moments(True), light_moment={"pass": "yes", "reason": "r"}))):
            self.assertTrue(arc.check(json.dumps(broken))[1])

    def test_prompt_renders_the_group(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "contact.png").write_bytes(b"png")
            shots = Path(t) / "shots.json"
            shots.write_text(json.dumps({"contact": "contact.png", "shots": []}))
            prompt = Path(arc.build(UNITS, t, shots, rubric=RUBRIC)["prompt"]).read_text()
        self.assertNotIn("{{", prompt)
        self.assertIn("all argument and no moments fails this group", prompt)
        self.assertIn("- always on your side:", prompt)
        for c in M["checks"]:
            self.assertIn(f"### `{c['id']}`", prompt)
            self.assertIn(f'"{c["id"]}": {{"pass"', prompt)

    def test_validate_keeps_moments_in_arc_json(self):
        with tempfile.TemporaryDirectory() as t:
            raw, out = Path(t) / "r.json", Path(t) / "arc.json"
            raw.write_text(json.dumps({"model": "m", "scores": SCORES, "moments": moments(True)}))
            self.assertEqual(arc.main(["validate", str(raw), "--grader", "claude", "--round", "1", "-o", str(out)]), 0)
            self.assertEqual(json.loads(out.read_text())["graders"]["claude"]["moments"], moments(True))

    def test_a_dry_deck_fails_the_bar(self):
        # every unit and arc score at 5, but no moments: argument alone cannot finish
        self.assertTrue(bar({"claude": {"scores": SCORES, "moments": moments(True)}})["met"])
        dry = bar({"claude": {"scores": SCORES, "moments": moments(False)}})
        self.assertFalse(dry["met"])
        self.assertEqual(dry["arc_failing"], [f"claude:moments.{c}" for c in IDS])
        one = dict(moments(True), light_moment={"pass": False, "reason": "r"})
        self.assertEqual(bar({"claude": {"scores": SCORES, "moments": one}})["arc_failing"],
                         ["claude:moments.light_moment"])
        # an arc record from before 0.7 has no moments block and does not meet a 0.7 bar
        self.assertEqual(bar({"claude": {"scores": SCORES}})["arc_failing"], ["claude:moments.moments"])

    def test_brief_shows_a_moments_row(self):
        sc = {"bar": {"mechanical_pass": True}, "per_grader": {}, "units": {}, "units_total": 0,
              "self_preference": {"compared_with": "baseline", "excess_vs_baseline": None}}
        rows = brief.gate_rows(sc, {"claude": {"scores": SCORES, "moments": moments(False)}}, None)
        row = [r for r in rows if r[0] == "Moments, claude"][0]
        self.assertEqual(row[3], "failed")
        self.assertIn("light_moment", row[2])


if __name__ == "__main__":
    unittest.main()
