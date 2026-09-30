"""prefer_rulings.py: preference notes become rulings and a grader-missed count. No network."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import packet  # noqa: E402
import prefer_rulings as pr  # noqa: E402

RUBRIC = json.loads((HERE / "rubric.json").read_text())
KEY = {"key_id": "k", "pairs": {"p01": {"unit": "u1", "after": "left"}, "p02": {"unit": "u2", "after": "right"},
                                "p03": {"unit": "u3", "after": "left"}}}
ANSWERS = {"key_id": "k", "answers": {"p01": "left", "p02": "left", "p03": "right"},
           "notes": {"p01": "But the subtitle makes no sense and it is too text heavy, move it to the speaker notes.",
                     "p02": "Why are 2 of the regions red?", "p03": "Oldest to newest does not fit."}}
UNITS = {"kind": "deck", "units": [{"id": f"u{i}", "text": f"Slide {i} text", "notes": "Say it"} for i in (1, 2, 3)]}


def rec(grader, unit, **scores):
    return {"grader": grader, "unit": unit, "scores": {c: {"score": s, "reason": "r"} for c, s in scores.items()}}


RECORDS = {("codex", "u1"): rec("codex", "u1", clear=5, economy=3), ("claude", "u1"): rec("claude", "u1", clear=4, economy=4),
           ("codex", "u2"): rec("codex", "u2", visual=4)}


class PreferRulingsTest(unittest.TestCase):
    def test_note_keywords_pick_criteria(self):
        self.assertEqual(pr.criteria_for(ANSWERS["notes"]["p01"]), ["economy", "clear"])
        self.assertEqual(pr.criteria_for(ANSWERS["notes"]["p02"]), ["visual"])
        self.assertEqual(pr.criteria_for(ANSWERS["notes"]["p03"]), [])

    def test_unclassified_note_stops_unless_overridden(self):
        with self.assertRaises(ValueError):
            pr.build(ANSWERS, KEY, UNITS, RECORDS, "T")
        lines, _ = pr.build(ANSWERS, KEY, UNITS, RECORDS, "T", {"p03": ["clear"]})
        self.assertEqual([ln["criterion"] for ln in lines if ln["unit"] == "u3"], ["clear"])

    def test_lines_scores_versions_and_missed_count(self):
        lines, summary = pr.build(ANSWERS, KEY, UNITS, RECORDS, "T", {"p03": ["clear"]})
        by = {(ln["unit"], ln["criterion"]): ln for ln in lines}
        clear = by[("u1", "clear")]
        self.assertEqual((clear["version"], clear["graders"], clear["missed"]),
                         ("after", {"claude": 4, "codex": 5}, ["claude", "codex"]))
        self.assertEqual(by[("u1", "economy")]["missed"], ["claude"])
        self.assertEqual(by[("u2", "visual")]["version"], "before")
        self.assertEqual(by[("u2", "visual")]["graders"], {"claude": None, "codex": 4})
        self.assertEqual(summary["graders"]["codex"], {"scored": 3, "no_record": 1, "missed": 2})
        self.assertEqual(summary["graders"]["claude"], {"scored": 2, "no_record": 2, "missed": 2})

    def test_output_is_a_valid_examples_file_and_append_skips_repeats(self):
        with tempfile.TemporaryDirectory() as d:
            ans, key, units, recs, out = (Path(d) / n for n in ("a.json", "k.json", "u.json", "r.jsonl", "rul.jsonl"))
            ans.write_text(json.dumps(ANSWERS)); key.write_text(json.dumps(KEY)); units.write_text(json.dumps(UNITS))
            recs.write_text("".join(json.dumps(r) + "\n" for r in RECORDS.values()))
            args = [str(ans), str(key), "--units", str(units), "--records", str(recs), "--label", "T",
                    "--criteria", '{"p03": ["clear"]}', "-o", str(out)]
            self.assertEqual(pr.main(args), 0)
            n = len(out.read_text().splitlines())
            self.assertEqual(n, 4)
            self.assertEqual(pr.main(args), 0)
            self.assertEqual(len(out.read_text().splitlines()), n)
            self.assertEqual(len(packet.load_examples(out, RUBRIC)), 4)


if __name__ == "__main__":
    unittest.main()
