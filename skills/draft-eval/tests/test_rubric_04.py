"""Rubric 0.4: clear as a cold-reader test, visual that works, economy for text-heavy slides. No network."""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import packet  # noqa: E402
import validate  # noqa: E402

RUBRIC = json.loads((HERE / "rubric.json").read_text())
DOC = {"kind": "deck", "units": [
    {"id": "u1", "role": "title", "text": "Welcome to the session", "notes": "Say the opening line"},
    {"id": "u2", "role": "content", "text": "Step one Sort it, step two Route it", "notes": "Walk the steps"}]}


def recs(score=5, guesses=(), point="Two steps take an idea from sorted to routed."):
    def rec(uid, quote):
        s = {c["id"]: {"score": 4, "reason": f'It says "{quote}".'} for c in RUBRIC["criteria"]}
        s["device"]["type"] = "plain_rule"
        s["honest_numbers"] = {"score": "n/a", "reason": f'No number in "{quote}".'}
        s["clear"].update(point="The session opens.", guesses=[])
        return {"unit": uid, "scores": s}
    r = [rec("u1", "Welcome to the session"), rec("u2", "Sort it")]
    r[1]["scores"]["clear"] = {"score": score, "point": point, "guesses": list(guesses),
                               "reason": 'A cold reader asks what "Sort it" does.'}
    return r


def errors(r):
    return validate.check(json.dumps({"model": "m", "records": r}), DOC, ["u1", "u2"], RUBRIC)[1]


class Rubric04Test(unittest.TestCase):
    def test_version_phase_and_changelog_disclose_the_fit(self):
        self.assertIn(RUBRIC["rubric_version"], ("0.4", "0.4.1", "0.4.2"))  # 0.4.1 keeps these anchors
        self.assertEqual(RUBRIC["phase"], "experimental")
        note = {c["version"]: c["note"] for c in RUBRIC["changelog"]}["0.4"]
        self.assertIn("Fitted to the 17 notes", note)

    def test_clear_score_follows_the_guesses(self):
        self.assertEqual(errors(recs(5)), [])
        self.assertEqual(errors(recs(3, ["\"Sort it\" does not say what the step is"])), [])
        self.assertEqual(errors(recs(4, ["\"Sort it\""])), ["u2 clear: 1 guess allows at most 3"])
        self.assertEqual(errors(recs(2, ["a", "b"])), ["u2 clear: 2 guesses allows at most 1"])
        self.assertEqual(errors(recs(1, ["a", "b"])), [])
        self.assertEqual(errors(recs(3, point="")), ["u2 clear: an empty point allows at most 1"])

    def test_clear_needs_point_and_guesses(self):
        r = recs()
        del r[1]["scores"]["clear"]["guesses"]
        self.assertTrue(any("u2.scores.clear" in e for e in errors(r)))

    def test_anchors_carry_the_decided_design(self):
        c = {x["id"]: x for x in RUBRIC["criteria"]}
        self.assertIn("reasonable reading", c["clear"]["anchors"]["5"])
        self.assertIn("ordering label", c["clear"]["question"])
        for phrase in ("never explain", "incomplete visual", "grouped visibly",
                       "mascot used as decoration", "metaphor is unclear"):
            self.assertIn(phrase, c["visual"]["anchors"]["3"])
        self.assertIn("text-heavy", c["economy"]["anchors"]["3"])
        self.assertIn("list items beyond what the idea needs", c["economy"]["question"])

    def test_prompt_asks_for_the_cold_read(self):
        prompt = packet.render_prompt(RUBRIC, "deck", [])
        self.assertIn("Read it cold first", prompt)
        self.assertIn('"guesses"', prompt)


if __name__ == "__main__":
    unittest.main()
