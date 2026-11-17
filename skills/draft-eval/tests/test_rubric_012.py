"""Rubric 0.12: pain_before_solution counts talk time in a training session. No network."""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import arc  # noqa: E402

RUBRIC = json.loads((HERE / "rubric.json").read_text())
CHECK = next(c for c in RUBRIC["moments"]["checks"] if c["id"] == "pain_before_solution")


class TestRubric012(unittest.TestCase):
    def test_training_session_reads_talk_time(self):
        self.assertEqual(RUBRIC["rubric_version"], "0.12")
        p = CHECK["pass"]
        # talks keep the 0.11 sentence word for word
        self.assertIn("that first fix arrives at or after 40% of the running time, read from the "
                      "planning slide's clock times where it has them.", p)
        for s in ("at least 20% of its running time is hands-on", "leaving out practice and writing",
                  "facilitator cards", "36 talk minutes", "talk minute 14.4", "keeps the running time"):
            self.assertIn(s, p)
        self.assertAlmostEqual(0.4 * (60 - 24), 14.4)  # the worked case in the pass text
        self.assertIn("of talk time, in a training session", CHECK["fail"])
        self.assertIn("talk time", arc.render_moments(RUBRIC))

    def test_history_and_changelog(self):
        note = {c["version"]: c["note"] for c in RUBRIC["changelog"]}["0.12"]
        self.assertIn("not comparable", note)
        sec = (HERE / "rubric-history.md").read_text().split("## Rubric 0.12")[1]
        self.assertIn("18 November 2026", sec)
        self.assertIn("comparable on everything else", sec)
        self.assertNotIn(chr(0x2014), json.dumps([note, CHECK], ensure_ascii=False) + sec)


if __name__ == "__main__":
    unittest.main()
