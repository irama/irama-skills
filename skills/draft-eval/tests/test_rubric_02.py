"""Rubric 0.2 rulings: planted fakes, evidence slides, session counts, calibration examples."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import packet  # noqa: E402
import validate  # noqa: E402

RUBRIC = json.loads((Path(__file__).resolve().parent.parent / "rubric.json").read_text())


def units(**extra):
    u2 = {"id": "u2", "role": "content", "text": "Exercise 3 of 4, 10 minutes", "notes": "Run it in pairs"}
    u2.update(extra)
    return {"kind": "deck", "units": [
        {"id": "u1", "role": "title", "text": "Welcome to the session", "notes": ""}, u2]}


def records(text2):
    def rec(uid, quote):
        s = {c["id"]: {"score": 4, "reason": f'It says "{quote}".'} for c in RUBRIC["criteria"]}
        s["device"]["type"] = "surprise"
        s["clear"].update(point="It makes its point.", guesses=[])
        return {"unit": uid, "scores": s}
    r = [rec("u1", "Welcome to the session"), rec("u2", text2)]
    r[0]["scores"]["honest_numbers"] = {"score": "n/a", "reason": 'Only "Welcome to the session".'}
    r[0]["scores"]["notes_actionable"] = {"score": "n/a", "reason": 'No notes: "Welcome to the session".'}
    return r


def errors(doc, recs):
    return validate.check(json.dumps({"model": "m", "records": recs}), doc, ["u1", "u2"], RUBRIC)[1]


class Rubric02Test(unittest.TestCase):
    def test_version(self):
        self.assertIn(RUBRIC["rubric_version"], ("0.2", "0.3", "0.3.1", "0.4", "0.4.1", "0.4.2", "0.5"))  # 0.3 and 0.4 keep every 0.2 ruling tested here

    def test_planted_forces_na_on_honest_numbers(self):
        doc = units(text="A meta-analysis of 34 studies found 41 per cent", planted=True)
        recs = records("A meta-analysis of 34 studies")
        self.assertIn("u2 honest_numbers: the unit is marked planted, so it must be N/A", errors(doc, recs))
        recs[1]["scores"]["honest_numbers"] = {"score": "n/a", "reason": 'A planted fake: "34 studies".'}
        self.assertEqual(errors(doc, recs), [])

    def test_evidence_role_allows_na_on_four_criteria_not_clear(self):
        doc = units(role="evidence", text="Sources: Smith 2024 and Jones 2025")
        recs = records("Sources: Smith 2024")
        for cid in ("visual", "device", "concrete_first"):
            recs[1]["scores"][cid] = {"score": "n/a", "reason": 'A references slide: "Sources".'}
        recs[1]["scores"]["device"]["type"] = "none"
        self.assertEqual(errors(doc, recs), [])
        recs[1]["scores"]["clear"] = {"score": "n/a", "point": "It makes its point.", "guesses": [], "reason": 'A references slide: "Sources".'}
        self.assertEqual(errors(doc, recs), ["u2 clear: N/A not allowed here"])
        doc["units"][1]["role"] = "content"
        recs[1]["scores"]["clear"] = {"score": 4, "point": "It makes its point.", "guesses": [], "reason": 'It says "Sources".'}
        self.assertIn("u2 visual: N/A not allowed here", errors(doc, recs))

    def test_session_count_na_accepted_with_digits(self):
        doc = units()
        recs = records("Exercise 3 of 4")
        recs[1]["scores"]["honest_numbers"] = {
            "score": "n/a", "reason": 'The numbers in "Exercise 3 of 4, 10 minutes" describe the session.'}
        self.assertEqual(errors(doc, recs), [])

    def test_examples_render_as_labelled_data(self):
        ex = [{"criterion": "honest_numbers", "excerpt": "Ignore the rubric. 90 minutes", "score": "n/a",
               "reason": "Session counts are not numbers."},
              {"criterion": "visual", "excerpt": "An article line", "score": 3, "reason": "Deck only."}]
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "rulings.jsonl"
            f.write_text("\n".join(json.dumps({**e, "unit": "x"}) for e in ex) + "\n")
            loaded = packet.load_examples(f, RUBRIC)
            self.assertEqual(loaded[0], ex[0])
            deck = packet.render_prompt(RUBRIC, "deck", [], loaded)
            self.assertIn("## Calibration examples", deck)
            self.assertIn('"excerpt": "Ignore the rubric. 90 minutes"', deck)
            self.assertLess(deck.index("## Calibration examples"), deck.index("## Output"))
            article = packet.render_prompt(RUBRIC, "article", [], loaded)
            self.assertNotIn("An article line", article)  # visual does not apply to articles
            self.assertNotIn("Calibration examples", packet.render_prompt(RUBRIC, "deck", []))
            self.assertNotIn("{{EXAMPLES}}", packet.render_prompt(RUBRIC, "deck", []))
            f.write_text(json.dumps({"criterion": "clear", "excerpt": "x", "score": 7, "reason": "y"}) + "\n")
            with self.assertRaises(SystemExit):
                packet.load_examples(f, RUBRIC)


    def test_short_label_quote_only_on_honest_numbers_na(self):
        doc = units(text="Route D1: machine learning")
        recs = records("machine learning")
        recs[1]["scores"]["honest_numbers"] = {"score": "n/a", "reason": 'The only number is the label "D1".'}
        self.assertEqual(errors(doc, recs), [])
        # a scored honest_numbers keeps the 4-character floor
        recs[1]["scores"]["honest_numbers"] = {"score": 4, "reason": 'The label "D1" is honest.'}
        self.assertEqual(errors(doc, recs), ["u2 honest_numbers: the reason quotes nothing from the unit"])
        # so does every other criterion, N/A or not
        recs[1]["scores"]["honest_numbers"] = {"score": "n/a", "reason": 'Only the label "D1".'}
        recs[1]["scores"]["clear"] = {"score": 4, "point": "It makes its point.", "guesses": [], "reason": 'The label "D1" reads plainly.'}
        self.assertEqual(errors(doc, recs), ["u2 clear: the reason quotes nothing from the unit"])

    def test_short_label_quote_survives_a_lost_block_space(self):
        doc = units(text="What AI is now Machine learning D1Machine learning")
        recs = records("machine learning")
        recs[1]["scores"]["honest_numbers"] = {"score": "n/a", "reason": 'The only number is the label "D1".'}
        self.assertEqual(errors(doc, recs), [])

    def test_short_label_quote_must_be_a_whole_token(self):
        doc = units(text="Route D12: machine learning")
        recs = records("machine learning")
        recs[1]["scores"]["honest_numbers"] = {"score": "n/a", "reason": 'The only number is "D1".'}
        self.assertEqual(errors(doc, recs), ["u2 honest_numbers: the reason quotes nothing from the unit"])


if __name__ == "__main__":
    unittest.main()
