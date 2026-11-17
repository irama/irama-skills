"""Rubric 0.11: the moments group reads the backstage layer, and must-pass follows the tier. No network."""
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
SCHEMA = json.loads((HERE / "arc-schema.json").read_text())
CHECKS = {c["id"]: c for c in RUBRIC["moments"]["checks"]}
CRITS = [c["id"] for c in RUBRIC["criteria"]]
SCORES = {c: {"score": 5, "reason": 'Slide 2 says "x".'} for c in RUBRIC["bars"]["arc_criteria"]}
UNITS = {"kind": "deck", "units": [{"id": u} for u in "abc"]}


def moments(**fails):
    return {c: {"pass": c not in fails, "reason": 'Slide 2 says "x".'} for c in CHECKS}


def bar(m):
    recs = [{"unit": u, "scores": {c: {"score": 5} for c in CRITS}} for u in "abc"]
    return sr.score(UNITS, {"claude": recs}, mechanical={"pass": True},
                    arc={"claude": {"scores": SCORES, "moments": m}}, rubric=RUBRIC)["bar"]


class TestRubric011(unittest.TestCase):
    def test_version_ids_and_tiers(self):
        self.assertIn(RUBRIC["rubric_version"], ("0.11", "0.12"))  # 0.12 keeps these checks
        self.assertNotIn("stage_directions", CHECKS)
        self.assertIn("notes_briefing", CHECKS)
        self.assertIn("four_acts", CHECKS)
        self.assertEqual({c for c, v in CHECKS.items() if v["tier"] == "recommended"}, {"star_moment", "quoted_close", "light_moment"})
        self.assertTrue(all(v["tier"] in ("required", "recommended") for v in CHECKS.values()))
        self.assertEqual(SCHEMA["properties"]["moments"]["required"], list(CHECKS))
        prompt = (HERE / "arc-prompt.md").read_text()
        for c in CHECKS:
            self.assertIn(f'"{c}": {{"pass"', prompt)
        self.assertNotIn("stage_directions", prompt)
        self.assertIn("Backstage, not presented", prompt)

    def test_checks_read_the_planning_slide(self):
        for c in ("star_moment", "peak_and_end", "five_moves", "notes_briefing", "four_acts"):
            self.assertIn("planning slide", CHECKS[c]["pass"], c)
        self.assertIn("end of act 3", CHECKS["peak_and_end"]["pass"])
        self.assertNotIn("in quotes", CHECKS["peak_and_end"]["pass"])
        self.assertIn("in quotes", CHECKS["quoted_close"]["pass"])
        self.assertIn("mission", CHECKS["wrong_and_credible"]["pass"])
        self.assertIn("optional", CHECKS["wrong_and_credible"]["pass"])
        for line in ("in quotes", "story cue", "one number", "the bridge", "likely question"):
            self.assertIn(line, CHECKS["notes_briefing"]["pass"])
        self.assertIn("says why", CHECKS["four_acts"]["pass"])
        na = next(c for c in RUBRIC["criteria"] if c["id"] == "notes_actionable")
        self.assertIn("briefing", na["question"])
        self.assertIn("tier: recommended", arc.render_moments(RUBRIC))

    def test_must_pass_follows_the_tier(self):
        self.assertTrue(bar(moments())["met"])
        soft = bar(moments(star_moment=1, light_moment=1))
        self.assertTrue(soft["met"])
        self.assertEqual(soft["arc_failing"], [])
        beat = bar(moments(four_acts=1))
        self.assertFalse(beat["met"])
        self.assertEqual(beat["arc_failing"], ["claude:moments.four_acts"])
        # a required check left out of the reply counts as failed
        partial = {k: v for k, v in moments().items() if k != "notes_briefing"}
        self.assertEqual(bar(partial)["arc_failing"], ["claude:moments.notes_briefing"])

    def test_brief_reports_a_recommended_fail_without_failing(self):
        sc = {"bar": {"mechanical_pass": True}, "per_grader": {}, "units": {}, "units_total": 0,
              "self_preference": {"compared_with": "baseline", "excess_vs_baseline": None}}
        row = [r for r in brief.gate_rows(sc, {"claude": {"scores": SCORES, "moments": moments(light_moment=1)}}, None)
               if r[0] == "Moments, claude"][0]
        self.assertIn("light_moment", row[2])
        self.assertEqual(row[3], "passed")

    def test_history_and_changelog(self):
        note = {c["version"]: c["note"] for c in RUBRIC["changelog"]}["0.11"]
        self.assertIn("not comparable", note)
        hist = (HERE / "rubric-history.md").read_text()
        sec = hist[hist.index("## Rubric 0.11"):]
        self.assertIn("experimental", sec)
        self.assertIn("`stage_directions` is retired", sec)
        for f in ("rubric.json", "rubric-history.md", "arc-prompt.md", "grader-prompt.md", "SKILL.md"):
            text = (HERE / f).read_text()
            self.assertNotIn("Andr" + "ew", text, f)  # the public repo names no person
        self.assertNotIn(chr(0x2014), json.dumps([note, RUBRIC["moments"]], ensure_ascii=False) + sec)


if __name__ == "__main__":
    unittest.main()
