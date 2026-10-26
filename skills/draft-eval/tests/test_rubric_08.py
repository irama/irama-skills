"""Rubric 0.8: the arc flow criterion asks for a but or therefore at every join. No network."""
import json
import unittest
from pathlib import Path

RUBRIC = json.loads((Path(__file__).resolve().parent.parent / "rubric.json").read_text())


class TestRubric08(unittest.TestCase):
    def test_flow_names_the_link(self):
        self.assertIn(RUBRIC["rubric_version"], ("0.8", "0.9"))  # 0.9 keeps the flow criterion unchanged
        flow = next(c for c in RUBRIC["arc"]["criteria"] if c["id"] == "flow")
        for word in ("but", "therefore", "and then", "parallel"):
            self.assertIn(word, flow["question"])


if __name__ == "__main__":
    unittest.main()
