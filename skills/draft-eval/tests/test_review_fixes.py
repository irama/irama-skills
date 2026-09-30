"""Tests for the DE-05 review fixes. No model, no network."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import brief  # noqa: E402
import packet  # noqa: E402
import run  # noqa: E402
import score_round as sr  # noqa: E402
import validate  # noqa: E402

RUBRIC = json.loads((HERE / "rubric.json").read_text())
CRITS = [c["id"] for c in RUBRIC["criteria"]]
UNITS = {"kind": "deck", "units": [
    {"id": "u1", "role": "content", "text": "Robots learn slowly at first", "notes": ""},
    {"id": "u2", "role": "content", "text": "Then the apprentices take over", "notes": ""}]}


def record(uid, reasons):
    return {"unit": uid, "scores": {c: {"score": 4, "reason": reasons.get(c, reasons["*"])} for c in CRITS}}


class PrevQuoteTest(unittest.TestCase):
    """P1: a reason may quote the previous unit only for flow and guess_reveal, beside a unit quote."""

    def errs(self, reasons):
        raw = json.dumps({"model": "m", "records": [record("u1", {"*": 'Says "Robots learn slowly".'}),
                                                    record("u2", reasons)]})
        # these units hold no number, so honest_numbers must be N/A; that rule is tested elsewhere
        return [e for e in validate.check(raw, UNITS, ["u1", "u2"], RUBRIC)[1] if "honest_numbers" not in e]

    def test_prev_quote_rules(self):
        unit = 'Says "the apprentices take over".'
        both = 'After "Robots learn slowly" it says "the apprentices take over".'
        prev_only = 'Says "Robots learn slowly".'
        self.assertEqual(self.errs({"*": unit, "flow": both, "guess_reveal": both}), [])
        self.assertIn("u2 clear: the reason quotes the previous unit", self.errs({"*": unit, "clear": both}))
        self.assertIn("u2 flow: the reason quotes nothing from the unit", self.errs({"*": unit, "flow": prev_only}))
        self.assertIn("u2 clear: the reason quotes nothing from the unit", self.errs({"*": prev_only}))

    def test_quote_may_restore_a_space_lost_between_blocks(self):
        unit = {"text": "90 minutes Should we do AIto it? Seven acts", "notes": ""}
        self.assertTrue(validate.quotes_unit('Asks "Should we do AI to it?" plainly.', unit))
        self.assertFalse(validate.quotes_unit('Says "therapist" here.', {"text": "The rapist was caught"}))

    def test_entities_decode_on_both_sides(self):
        # A4 notes kept "&amp;rsquo;": an accurate quote with an apostrophe must still match
        unit = {"text": "Slide", "notes": "that person&amp;rsquo;s capacity sets the ceiling"}
        self.assertTrue(validate.quotes_unit('Notes say "that person’s capacity sets the ceiling".', unit))
        self.assertTrue(validate.quotes_unit('Notes say "that person&rsquo;s capacity".', unit))

    def test_extract_decodes_double_escaped_notes(self):
        import extract
        page = '<script id="speaker-notes" type="application/json">["that person&amp;rsquo;s turn"]</script>'
        self.assertEqual(extract._notes(page), ["that person’s turn"])

    def test_previous_unit_sits_in_context_folder(self):
        with tempfile.TemporaryDirectory() as d:
            b = packet.build({"kind": "article", "units": UNITS["units"]}, Path(d))[0]
            u2 = Path(b["dir"]) / "02-u2"
            self.assertFalse((u2 / "prev.txt").exists())
            self.assertEqual((u2 / "context" / "prev.txt").read_text(), "Robots learn slowly at first")
            self.assertIn('"context/prev.txt"', Path(b["prompt"]).read_text())


def recs(scores):
    return [{"unit": u, "scores": {c: {"score": v} for c in CRITS}} for u, v in scores.items()]


ARC = {g: {"scores": {c: {"score": 4} for c in RUBRIC["bars"]["arc_criteria"]}} for g in sr.GRADERS}


class ScoreRoundFixTest(unittest.TestCase):
    def test_unit_missing_a_grader_stays_out_of_the_median(self):
        units = {"kind": "deck", "units": [{"id": u} for u in "abcd"]}
        # codex's batch holding d failed; claude alone would put d at 5 and lift the median
        r = sr.score(units, {"codex": recs(dict(a=2, b=2, c=3)), "claude": recs(dict(a=2, b=2, c=3, d=5))},
                     mechanical={"pass": True}, arc=ARC, rubric=RUBRIC)
        self.assertEqual(r["median"], 2)
        self.assertEqual(r["median_over"], 3)
        self.assertEqual(r["coverage"]["codex"], {"scored": 3, "of": 4})
        self.assertFalse(r["bar"]["met"])

    def write_round(self, runp, n, ids, median=None):
        rd = runp / "rounds" / f"r{n}"
        (rd / "grading").mkdir(parents=True)
        (rd / "units.json").write_text(json.dumps({"kind": "article", "units": [{"id": u} for u in ids]}))
        for g in sr.GRADERS:
            (rd / "grading" / f"{g}.jsonl").write_text(
                "\n".join(json.dumps(x) for x in recs({u: 3 for u in ids})) + "\n")
        if median is not None:
            (rd / "score.json").write_text(json.dumps({"median": median}))

    def test_fixed_unit_list_is_enforced(self):
        with tempfile.TemporaryDirectory() as t:
            runp = Path(t)
            self.write_round(runp, 1, ["a", "b"])
            sr.from_run(runp, 1)
            self.assertEqual(json.loads((runp / "units.fixed.json").read_text())["units"], ["a", "b"])
            self.write_round(runp, 2, ["a", "b", "c"])
            with self.assertRaises(SystemExit):
                sr.from_run(runp, 2)

    def test_history_keeps_one_entry_per_round(self):
        with tempfile.TemporaryDirectory() as t:
            runp = Path(t)
            self.write_round(runp, 1, ["a"])  # no score.json
            self.write_round(runp, 2, ["a"], median=3.0)
            self.write_round(runp, 3, ["a"])
            self.assertEqual(sr.from_run(runp, 3)["history"], [None, 3.0])


def brief_run(t, kind="deck", rewritten=None):
    runp = Path(t) / "run"
    rd = runp / "rounds" / "r1"
    (rd / "shots").mkdir(parents=True)
    (runp / "run.json").write_text(json.dumps({"target": "x", "started": "20260101T000000Z"}))
    sp = {"rewritten": [], "gap_rewritten": None, "gap_untouched": None, "baseline_gap": None,
          "excess_vs_untouched": None, "excess_vs_baseline": None, "compared_with": "baseline",
          "threshold": 0.5, "flag": False, "at_threshold": False}
    (rd / "score.json").write_text(json.dumps({
        "kind": kind, "graders": ["codex", "claude"], "units_total": 1, "median": 4.5, "units": {},
        "per_grader": {}, "bar": {"status": "met", "mechanical_pass": True, "arc_failing": [], "units_below": []},
        "self_preference": sp, "stop": {"reason": "bar_met"}}))
    if rewritten:
        (rd / "rewrites.json").write_text(json.dumps({"rewrites": [{"unit": rewritten}]}))
        (rd / "shots" / "s.png").write_bytes(b"png")
        (rd / "shots" / "shots.json").write_text(json.dumps({"shots": [{"id": rewritten, "file": "s.png"}]}))
    return runp


class BriefFixTest(unittest.TestCase):
    def test_no_recommended_on_a_deck_without_a_preference_result(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertNotIn("(Recommended)", brief.fill(brief_run(t)))
        with tempfile.TemporaryDirectory() as t:
            self.assertIn("(Recommended)", brief.fill(brief_run(t, kind="article")))

    def test_no_sided_pairs(self):
        prefer = {"after": 0, "before": 0, "sided": 0, "after_rate": None, "pass": False,
                  "at_threshold": False, "verdict": "back to calibration"}
        with tempfile.TemporaryDirectory() as t:
            self.assertIn("no sided pairs", brief.fill(brief_run(t), prefer))

    def test_unit_id_is_escaped_and_kept_out_of_the_path(self):
        bad = '../<img src=x onerror=alert(1)>'
        with tempfile.TemporaryDirectory() as t:
            figs = Path(t) / "figs"
            text = brief.fill(brief_run(t, rewritten=bad), figures=figs)
            self.assertNotIn("<img src=x", text)
            self.assertIn("&lt;img", text)
            self.assertEqual({p.parent for p in Path(t).rglob("*-before.png")}, {figs})


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class RunFixTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        sh(self.repo, "git", "init", "-q")
        sh(self.repo, "git", "config", "user.email", "t@example.com")
        sh(self.repo, "git", "config", "user.name", "t")
        self.deck = self.repo / "deck"
        self.deck.mkdir()
        (self.deck / "_gen.py").write_text("x = 1\n")
        sh(self.repo, "git", "add", ".")
        sh(self.repo, "git", "commit", "-qm", "init")
        self.run = run.start(self.deck, "a4", "s", versions={"codex_cli": "c", "chrome": "c"})
        (self.run / "rounds" / "r1").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_exclude_patterns_are_anchored(self):
        text = (self.repo / ".git" / "info" / "exclude").read_text()
        self.assertIn("/deck/eval-runs/\n", text)
        self.assertIn("/deck/.draft-eval.lock\n", text)

    def test_relative_path_is_taken_from_the_folder(self):
        (self.deck / "_gen.py").write_text("x = 2\n")
        sha = run.commit(self.run, 1, ["_gen.py"])
        self.assertEqual(sh(self.repo, "git", "show", "--name-only", "--format=", sha), "deck/_gen.py")

    def test_git_failure_exits_2_and_releases_the_lock(self):
        (self.deck / "new.txt").write_text("x\n")
        sh(self.repo, "git", "config", "core.hooksPath", str(self.repo / "hooks"))
        (self.repo / "hooks").mkdir()
        hook = self.repo / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.assertEqual(run.main(["commit", str(self.run), "1", "new.txt"]), 2)
        self.assertFalse((self.deck / run.LOCK).exists())


if __name__ == "__main__":
    unittest.main()
