"""Rubric 0.4.2: curiosity as a device, parallel lists, charts and recommendations that say what they
mean, one emblem treatment, one model per idea. No network."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import arc  # noqa: E402
import validate  # noqa: E402

RUBRIC = json.loads((HERE / "rubric.json").read_text())
CRIT = {c["id"]: c for c in RUBRIC["criteria"]}
ARC = {c["id"]: c for c in RUBRIC["arc"]["criteria"]}
DOC = {"kind": "deck", "units": [
    {"id": "u1", "role": "title", "text": "Welcome to the session", "notes": "Say the opening line"},
    {"id": "u2", "role": "content", "text": "A1 A2 A3 A4 are coming", "notes": "Let them wonder"}]}


def recs(device_type="curiosity", score=4):
    def rec(uid, quote):
        s = {c["id"]: {"score": 4, "reason": f'It says "{quote}".'} for c in RUBRIC["criteria"]}
        s["device"].update(type=device_type, score=score)
        s["clear"].update(point="It makes its point.", guesses=[])
        s["honest_numbers"] = {"score": "n/a", "reason": f'No number in "{quote}".'}
        return {"unit": uid, "scores": s}
    return [rec("u1", "Welcome to the session"), rec("u2", "A1 A2 A3 A4")]


def errors(r):
    return validate.check(json.dumps({"model": "m", "records": r}), DOC, ["u1", "u2"], RUBRIC)[1]


class Rubric042Test(unittest.TestCase):
    def test_version_and_changelog(self):
        self.assertIn(RUBRIC["rubric_version"], ("0.4.2", "0.5", "0.6"))  # 0.5 and 0.6 keep these anchors
        self.assertIn("round-three", {c["version"]: c["note"] for c in RUBRIC["changelog"]}["0.4.2"])

    def test_curiosity_is_a_device_type_the_schema_accepts(self):
        self.assertIn("curiosity", CRIT["device"]["types"])
        self.assertIn("Curiosity counts", CRIT["device"]["anchors"]["5"])
        self.assertEqual(errors(recs("curiosity")), [])
        self.assertTrue(errors(recs("intrigue")))  # an unknown type is still rejected

    def test_clear_wants_parallel_lists_and_plain_charts(self):
        q, a3 = CRIT["clear"]["question"], CRIT["clear"]["anchors"]["3"]
        self.assertIn("parallel in form", q)
        self.assertIn("for whom", q)
        self.assertIn("non-parallel list or sequence counts as one guess", a3)
        self.assertIn("what to do or when", a3)
        self.assertIn("polarity", CRIT["clear"]["anchors"]["5"])

    def test_visual_caps_a_chart_that_does_not_say_what_it_shows(self):
        a3 = CRIT["visual"]["anchors"]["3"]
        self.assertIn("what is measured, for whom) and its takeaway", a3)
        self.assertIn("what to do and in what situation", a3)
        self.assertIn("takeaway", CRIT["visual"]["anchors"]["5"])

    def test_arc_emblem_treatment_and_one_model(self):
        t = ARC["taxonomy_ids"]
        self.assertIn("same visual treatment", t["question"])
        for k in ("1", "3", "5"):
            self.assertIn("visual treatment", t["anchors"][k])
        self.assertIn("one_model", ARC)
        self.assertIn("one_model", RUBRIC["bars"]["arc_criteria"])
        self.assertEqual(set(json.loads((HERE / "arc-schema.json").read_text())
                             ["properties"]["scores"]["required"]), set(RUBRIC["bars"]["arc_criteria"]))
        good = {"model": "m", "scores": {c: {"score": 4, "reason": 'Slide 2 says "x".'}
                                         for c in RUBRIC["bars"]["arc_criteria"]}}
        self.assertEqual(arc.check(json.dumps(good))[1], [])
        del good["scores"]["one_model"]
        self.assertTrue(arc.check(json.dumps(good))[1])

    def test_arc_prompt_names_one_model(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "contact.png").write_bytes(b"png")
            shots = Path(t) / "shots.json"
            shots.write_text(json.dumps({"contact": "contact.png", "shots": []}))
            prompt = Path(arc.build(DOC, t, shots, rubric=RUBRIC)["prompt"]).read_text()
        self.assertIn("`one_model`: One model per idea", prompt)
        self.assertIn('"one_model": {"score"', prompt)


if __name__ == "__main__":
    unittest.main()
