"""Rubric 0.3: one device per unit, economy, actionable notes, flow 4, device variety. No network."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import check  # noqa: E402
import packet  # noqa: E402
import score_round as sr  # noqa: E402
import validate  # noqa: E402

RUBRIC = json.loads((HERE / "rubric.json").read_text())


def doc(role="content", notes="Ask the room for one agentic opportunity"):
    return {"kind": "deck", "units": [
        {"id": "u1", "role": "title", "text": "Welcome to the session", "notes": "Say the opening line"},
        {"id": "u2", "role": role, "text": "Most ideas belong one rung lower", "notes": notes}]}


def recs():
    def rec(uid, quote):
        s = {c["id"]: {"score": 4, "reason": f'It says "{quote}".'} for c in RUBRIC["criteria"]}
        s["device"]["type"] = "plain_rule"
        s["clear"].update(point="It makes its point.", guesses=[])
        s["honest_numbers"] = {"score": "n/a", "reason": f'No number in "{quote}".'}
        return {"unit": uid, "scores": s}
    return [rec("u1", "Welcome to the session"), rec("u2", "Most ideas belong")]


def errors(d, r):
    return validate.check(json.dumps({"model": "m", "records": r}), d, ["u1", "u2"], RUBRIC)[1]


class DeviceTest(unittest.TestCase):
    def test_version_and_retired_criteria(self):
        ids = [c["id"] for c in RUBRIC["criteria"]]
        self.assertIn(RUBRIC["rubric_version"], ("0.3.1", "0.4", "0.4.1", "0.4.2", "0.5", "0.6"))  # 0.4 keeps these lessons
        self.assertNotIn("guess_reveal", ids)
        self.assertNotIn("delight", ids)
        self.assertIn("variety", [c["id"] for c in RUBRIC["arc"]["criteria"]])

    def test_031_lessons_in_the_anchors(self):
        c = {x["id"]: x for x in RUBRIC["criteria"]}
        self.assertIn("mascot used as decoration", c["visual"]["anchors"]["3"])
        self.assertIn("metaphor is unclear", c["visual"]["anchors"]["3"])
        self.assertIn('"kill"', c["clear"]["anchors"]["3"])
        # kill is a clear-criterion note, never a banned term: banned terms also gate the notes
        self.assertNotIn("kill", [b["term"].lower() for b in RUBRIC["banned_terms"]])

    def test_device_with_type_validates_and_keeps_the_type(self):
        r = recs()
        out, errs = validate.check(json.dumps({"model": "m", "records": r}), doc(), ["u1", "u2"], RUBRIC)
        self.assertEqual(errs, [])
        self.assertEqual(out[1]["scores"]["device"]["type"], "plain_rule")

    def test_device_type_must_match_the_score(self):
        r = recs()
        del r[1]["scores"]["device"]["type"]
        self.assertTrue(any("u2.scores.device" in e for e in errors(doc(), r)))
        r[1]["scores"]["device"] = {"score": 4, "type": "none", "reason": 'It says "Most ideas belong".'}
        self.assertEqual(errors(doc(), r), ["u2 device: a score above 1 names its device type"])
        r[1]["scores"]["device"] = {"score": 1, "type": "surprise", "reason": 'It says "Most ideas belong".'}
        self.assertEqual(errors(doc(), r), ["u2 device: a score of 1 or N/A has type none"])
        r[1]["scores"]["device"]["type"] = "made_up"
        self.assertTrue(any("u2.scores.device" in e for e in errors(doc(), r)))

    def test_device_na_on_title_and_evidence_only(self):
        na = {"score": "n/a", "type": "none", "reason": 'It says "Most ideas belong".'}
        r = recs()
        r[0]["scores"]["device"] = {**na, "reason": 'It says "Welcome to the session".'}
        r[1]["scores"]["device"] = na
        self.assertEqual(errors(doc(role="evidence"), r), [])
        self.assertEqual(errors(doc(role="content"), r), ["u2 device: N/A not allowed here"])
        self.assertEqual(errors(doc(role="exercise"), r), ["u2 device: N/A not allowed here"])


class NotesActionableTest(unittest.TestCase):
    def test_na_only_without_notes(self):
        r = recs()
        r[1]["scores"]["notes_actionable"] = {"score": "n/a", "reason": 'It says "Most ideas belong".'}
        self.assertEqual(errors(doc(), r), ["u2 notes_actionable: N/A not allowed here"])
        self.assertEqual(errors(doc(notes=""), r), [])
        r[1]["scores"]["notes_actionable"] = {"score": 3, "reason": 'It says "Most ideas belong".'}
        self.assertEqual(errors(doc(notes="  "), r),
                         ["u2 notes_actionable: the unit has no speaker notes, so it must be N/A"])

    def test_article_has_no_notes_criterion(self):
        self.assertEqual([c for c in RUBRIC["criteria"] if c["id"] == "notes_actionable"][0]["applies_to"], ["deck"])


class EconomyTest(unittest.TestCase):
    PATTERNS = RUBRIC["filler_patterns"]

    def hits(self, text, notes=""):
        return [h["term"].lower() for h in check.filler_hits([{"id": "u", "text": text, "notes": notes}], self.PATTERNS)]

    def test_listed_patterns_are_caught(self):
        for line, term in [("Do not read all nine out. Find the one your candidate sits in.", "do not read"),
                           ("Don't read the list aloud.", "don't read"),
                           ("Don’t read every card.", "don’t read"),
                           ("Everything on this slide is a claim.", "on this slide"),
                           ("Nine rules on the page.", "on the page"),
                           ("Three pressures. Read them together.", "read them together")]:
            self.assertEqual(self.hits(line), [term], line)

    def test_normal_prose_passes(self):
        for line in ["Most ideas belong one rung lower than the room wants.",
                     "Readers who read the fine print catch the limit.",
                     "The page count fell from nine to four.",
                     "The dread of reading them together fades."]:
            self.assertEqual(self.hits(line), [], line)

    def test_notes_are_exempt(self):
        self.assertEqual(self.hits("Posture is a place", notes="Do not read the axes as precise."), [])


class RenderTest(unittest.TestCase):
    def test_prompt_shows_flow_4_and_device_types(self):
        text = packet.render_criteria(RUBRIC, "deck")
        self.assertIn("- 4: A change of topic that the narrative supports", text)
        self.assertIn("`live_challenge`", text)
        self.assertNotIn("notes_actionable", packet.render_criteria(RUBRIC, "article"))

    def test_rulings_on_retired_criteria_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "rulings.jsonl"
            f.write_text("\n".join(json.dumps(e) for e in [
                {"criterion": "guess_reveal", "excerpt": "x", "score": "n/a", "reason": "y"},
                {"criterion": "device", "excerpt": "x", "score": 4, "reason": "y"}]) + "\n")
            self.assertEqual([e["criterion"] for e in packet.load_examples(f, RUBRIC)], ["device"])


class VarietyTest(unittest.TestCase):
    def test_consecutive_repeat_and_dominance(self):
        def r(u, t, s=4):
            return {"unit": u, "scores": {"device": {"score": s, "type": t, "reason": "r"}}}
        ids = list("abcde")
        v = sr.device_variety(ids, [r("a", "surprise"), r("b", "surprise"), r("c", "none", 1),
                                    r("d", "surprise"), r("e", "callback")])
        self.assertEqual(v["consecutive_repeats"], [["a", "b"]])
        self.assertEqual((v["dominant"], v["dominant_share"], v["dominates"]), ("surprise", 0.75, True))
        v = sr.device_variety(ids, [r("a", "surprise"), r("b", "callback"), r("c", "surprise"), r("d", "callback")])
        self.assertEqual((v["consecutive_repeats"], v["dominates"]), ([], False))


if __name__ == "__main__":
    unittest.main()
