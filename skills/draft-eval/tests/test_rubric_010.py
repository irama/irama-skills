"""Rubric 0.10: the moments group gains pain_before_solution, graded in the arc pass. No network."""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import arc  # noqa: E402

RUBRIC = json.loads((HERE / "rubric.json").read_text())
SCHEMA = json.loads((HERE / "arc-schema.json").read_text())


class TestRubric010(unittest.TestCase):
    def test_check_is_in_rubric_schema_and_prompt(self):
        self.assertEqual(RUBRIC["rubric_version"], "0.10")
        check = next(c for c in RUBRIC["moments"]["checks"] if c["id"] == "pain_before_solution")
        self.assertIn("40%", check["pass"])
        self.assertIn("40%", check["fail"])
        self.assertIn("pain_before_solution", SCHEMA["properties"]["moments"]["required"])
        self.assertIn("pain_before_solution", (HERE / "arc-prompt.md").read_text())
        self.assertIn("pain_before_solution", arc.render_moments(RUBRIC))
        note = {c["version"]: c["note"] for c in RUBRIC["changelog"]}["0.10"]
        self.assertIn("not comparable", note)
        self.assertNotIn("—", json.dumps([note, check], ensure_ascii=False))

    def test_reply_without_the_check_is_rejected(self):
        ids = SCHEMA["properties"]["moments"]["required"]
        doc = {"model": "m",
               "scores": {c: {"score": 4, "reason": 'Slide 2 says "x".'} for c in RUBRIC["bars"]["arc_criteria"]},
               "moments": {c: {"pass": True, "reason": 'Slide 2 says "x".'} for c in ids if c != "pain_before_solution"}}
        self.assertTrue(any("pain_before_solution" in e for e in arc.check(json.dumps(doc))[1]))


if __name__ == "__main__":
    unittest.main()
