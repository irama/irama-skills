import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import brief  # noqa: E402


def run_dir(t, status="met", at_threshold=False):
    run = Path(t)
    rd = run / "rounds" / "r1"
    rd.mkdir(parents=True)
    (run / "run.json").write_text(json.dumps({"target": "x", "started": "20260101T000000Z"}))
    sp = {"rewritten": [], "gap_rewritten": None, "gap_untouched": None, "baseline_gap": None,
          "excess_vs_untouched": None, "excess_vs_baseline": None, "compared_with": "baseline",
          "threshold": 0.5, "flag": False, "at_threshold": False}
    (rd / "score.json").write_text(json.dumps({
        "graders": ["codex", "claude"], "units_total": 1, "median": 4.5, "units": {"a": {"failing": [], "score": 4.5}},
        "per_grader": {g: {"units_scored": 1, "mean": 4.5, "criteria": {}} for g in ("codex", "claude")},
        "bar": {"status": status, "mechanical_pass": True, "arc_failing": [], "units_below": []},
        "self_preference": sp, "stop": {"reason": "bar_met"}}))
    return run


PREFER = {"after": 7, "before": 3, "sided": 10, "after_rate": 0.7, "pass": True, "verdict": "after preferred"}


class BriefTest(unittest.TestCase):
    def test_recommended_only_when_met_and_no_tie(self):
        with tempfile.TemporaryDirectory() as t:
            text = brief.fill(run_dir(t), {**PREFER, "after_rate": 0.8, "after": 8, "at_threshold": False})
            self.assertIn("Keep every rewrite. (Recommended)", text)
        with tempfile.TemporaryDirectory() as t:
            text = brief.fill(run_dir(t), {**PREFER, "at_threshold": True})
            self.assertIn("passed at a tie", text)
            self.assertNotIn("(Recommended)", text)
        with tempfile.TemporaryDirectory() as t:
            self.assertNotIn("(Recommended)", brief.fill(run_dir(t, status="met by Claude only")))

    def test_moments_row_reads_the_run_snapshot_and_lists_a_missing_required_check(self):
        with tempfile.TemporaryDirectory() as t:
            run = run_dir(t)
            live = json.loads((Path(brief.__file__).parent / "rubric.json").read_text())
            live["moments"]["checks"].append({"id": "snapshot_only", "name": "n", "tier": "required", "pass": "p", "fail": "f"})
            (run / "rubric.json").write_text(json.dumps(live))
            moments = {c["id"]: {"pass": True, "reason": "r"} for c in live["moments"]["checks"] if c["id"] != "snapshot_only"}
            (run / "rounds" / "r1" / "arc.json").write_text(json.dumps({"graders": {"claude": {"scores": {}, "moments": moments}}}))
            row = next(r for r in brief.gate_rows(json.loads((run / "rounds" / "r1" / "score.json").read_text()),
                                                  {"claude": {"moments": moments}}, None, live) if r[0] == "Moments, claude")
            self.assertEqual((row[2], row[3]), ("snapshot_only", "failed"))
            self.assertIn("snapshot_only", brief.fill(run))

    def test_check_reports_open_placeholders(self):
        with tempfile.TemporaryDirectory() as t:
            md = Path(t) / "b.md"
            md.write_text(brief.fill(run_dir(t)))
            self.assertEqual(brief.main(["--check", str(md)]), 1)
            md.write_text("done")
            self.assertEqual(brief.main(["--check", str(md)]), 0)


if __name__ == "__main__":
    unittest.main()
