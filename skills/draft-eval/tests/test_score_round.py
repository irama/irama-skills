import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import score_round as sr  # noqa: E402

RUBRIC = json.loads((HERE / "rubric.json").read_text())
CRITS = [c["id"] for c in RUBRIC["criteria"]]
UNITS = {"kind": "deck", "units": [{"id": i, "hidden": False} for i in "abcd"]}
PASS_MECH = {"pass": True, "gates": {}, "floors": {"breaches": []}}
ARC_OK = {g: {"scores": {c: {"score": 4, "reason": "r"} for c in RUBRIC["bars"]["arc_criteria"]}}
          for g in ("codex", "claude")}


def recs(grader, scores):
    """scores: {unit: int or {crit: int}}"""
    out = []
    for u, s in scores.items():
        per = s if isinstance(s, dict) else {c: s for c in CRITS}
        out.append({"unit": u, "grader": grader, "scores": {c: {"score": v, "reason": "r"} for c, v in per.items()}})
    return out


def score(codex, claude, **kw):
    kw.setdefault("graders", "both")
    kw.setdefault("mechanical", PASS_MECH)
    kw.setdefault("arc", ARC_OK)
    return sr.score(UNITS, {"codex": recs("codex", codex) if codex else [], "claude": recs("claude", claude)},
                    rubric=RUBRIC, **kw)


class ScoreRoundTest(unittest.TestCase):
    def test_selftest(self):
        self.assertEqual(sr.selftest(), 0)

    def test_unit_score_is_lower_grader_mean_and_median(self):
        r = score({"a": 4, "b": 3, "c": 5, "d": 2}, {"a": 5, "b": 4, "c": 4, "d": 2})
        self.assertEqual(r["units"]["a"]["score"], 4)
        self.assertEqual(r["units"]["c"]["score"], 4)
        self.assertEqual(r["median"], 3.5)
        self.assertEqual(r["per_grader"]["codex"]["mean"], 3.5)
        self.assertNotIn("pooled", json.dumps(r))

    def test_bar_met_needs_both_graders_mechanical_and_arc(self):
        self.assertTrue(score({u: 4 for u in "abcd"}, {u: 5 for u in "abcd"})["bar"]["met"])
        claude_only = score(None, {u: 5 for u in "abcd"})
        self.assertFalse(claude_only["bar"]["met"])
        self.assertEqual(claude_only["bar"]["status"], "met by Claude only")
        self.assertFalse(score({u: 4 for u in "abcd"}, {u: 4 for u in "abcd"},
                               mechanical={"pass": False, "gates": {}})["bar"]["met"])
        low_arc = json.loads(json.dumps(ARC_OK))
        low_arc["codex"]["scores"]["delight"]["score"] = 3
        self.assertFalse(score({u: 4 for u in "abcd"}, {u: 4 for u in "abcd"}, arc=low_arc)["bar"]["met"])

    def test_split_regrade_lists_lower_grader_and_regrade_stands(self):
        r = score({"a": 3, "b": 4, "c": 4, "d": 4}, {u: 4 for u in "abcd"})
        self.assertEqual(r["regrade"], [{"unit": "a", "grader": "codex", "criteria": CRITS}])
        again = sr.score(UNITS, {"codex": recs("codex", {"a": 3, "b": 4, "c": 4, "d": 4}),
                                 "claude": recs("claude", {u: 4 for u in "abcd"})},
                         regrades={"codex": recs("codex", {"a": 4})}, rubric=RUBRIC,
                         mechanical=PASS_MECH, arc=ARC_OK, graders="both")
        self.assertEqual(again["regrade"], [])
        self.assertTrue(again["bar"]["met"])

    def test_claude_sets_the_bar_and_codex_only_audits(self):
        # Codex's low score on an untouched unit and a missing Codex arc do not hold the bar back
        claude_arc = {"claude": ARC_OK["claude"]}
        r = score({"a": 2}, {u: 4 for u in "abcd"}, graders="claude", arc=claude_arc)
        self.assertTrue(r["bar"]["met"], r["bar"])
        self.assertEqual((r["bar_graders"], r["regrade"]), (["claude"], []))
        self.assertEqual(r["units"]["a"]["score"], 4)
        # the median follows Claude alone
        self.assertEqual(score({u: 1 for u in "abcd"}, {u: 5 for u in "abcd"}, graders="claude")["median"], 5)

    def test_audit_set_is_rewritten_plus_as_many_untouched_and_repeatable(self):
        ids = list("abcdefgh")
        a = sr.audit_set(ids, ["c", "f"], 3)
        self.assertEqual(a["rewritten"], ["c", "f"])
        self.assertEqual(len(a["baseline"]), 2)
        self.assertFalse(set(a["baseline"]) & {"c", "f"})
        self.assertEqual(a, sr.audit_set(ids, ["f", "c"], 3))
        self.assertEqual(sr.audit_set(ids, [], 1), {"rewritten": [], "baseline": []})

    def test_self_preference_on_audited_units_blocks_finished(self):
        # Claude rates rewritten unit a a point over Codex; baseline unit b level
        r = score({"a": 4, "b": 4}, {u: 4 for u in "bcd"} | {"a": 5}, graders="claude", rewritten=["a"])
        self.assertEqual(r["self_preference"]["excess_vs_untouched"], 1.0)
        self.assertFalse(r["bar"]["met"])
        self.assertEqual(r["bar"]["status"], "blocked: possible self-preference")
        self.assertEqual(r["stop"]["reason"], "bar_met_blocked")
        # under the threshold the audited run finishes
        ok = score({"a": 4, "b": 4}, {u: 4 for u in "abcd"}, graders="claude", rewritten=["a"])
        self.assertTrue(ok["bar"]["met"])
        # a rewritten unit Codex never graded blocks it too
        miss = score({"b": 4}, {u: 4 for u in "abcd"}, graders="claude", rewritten=["a"])
        self.assertEqual(miss["self_preference"]["unaudited"], ["a"])
        self.assertEqual(miss["bar"]["status"], "blocked: rewrites not audited by Codex")

    def test_stop_rules(self):
        low = ({u: 3 for u in "abcd"}, {u: 3 for u in "abcd"})
        self.assertEqual(score(*low, round_n=1, history=[])["stop"]["reason"], None)
        self.assertEqual(score(*low, round_n=2, history=[3.0])["stop"]["reason"], None)
        self.assertEqual(score(*low, round_n=3, history=[3.0, 3.0])["stop"]["reason"], "plateau")
        self.assertEqual(score(*low, round_n=3, history=[2.0, 3.0])["stop"]["reason"], None)
        self.assertEqual(score(*low, round_n=5, history=[1, 2, 2.5, 2.8])["stop"]["reason"], "max_rounds")

    def test_rewrite_candidates_mechanical_first_then_lowest(self):
        mech = {"pass": False, "gates": {"banned": {"pass": False, "hits": [{"id": "c", "term": "x"}]}},
                "floors": {"breaches": []}}
        r = score({"a": 2, "b": 3, "c": 4, "d": 4}, {"a": 2, "b": 3, "c": 4, "d": 4}, mechanical=mech)
        self.assertEqual(r["rewrite"], ["c", "a", "b"])

    def test_unknown_unit_is_rejected(self):
        with self.assertRaises(SystemExit):
            score({"a": 4, "z": 4}, {"a": 4})

    def test_cli_reads_run_layout(self):
        with tempfile.TemporaryDirectory() as t:
            run = Path(t)
            (run / "run.json").write_text(json.dumps({"baseline_gap": 0.1}))
            for n, s in ((1, 3), (2, 4)):
                rd = run / "rounds" / f"r{n}"
                (rd / "grading").mkdir(parents=True)
                (rd / "units.json").write_text(json.dumps(UNITS))
                (rd / "mechanical.json").write_text(json.dumps(PASS_MECH))
                (rd / "arc.json").write_text(json.dumps({"graders": ARC_OK}))
                for g in ("codex", "claude"):
                    (rd / "grading" / f"{g}.jsonl").write_text(
                        "\n".join(json.dumps(x) for x in recs(g, {u: s for u in "abcd"})) + "\n")
            (run / "rounds" / "r1" / "rewrites.json").write_text(json.dumps({"rewrites": [{"unit": "a"}]}))
            self.assertEqual(sr.main([str(run), "1"]), 0)
            self.assertEqual(sr.main([str(run), "2"]), 0)
            out = json.loads((run / "rounds" / "r2" / "score.json").read_text())
            self.assertEqual(out["history"], [3.0])
            self.assertEqual(out["self_preference"]["rewritten"], ["a"])
            self.assertEqual(out["mode"], "claude")
            self.assertEqual(out["stop"]["reason"], "bar_met")
            self.assertEqual(sr.main([str(run), "2", "--graders", "both"]), 0)
            self.assertEqual(json.loads((run / "rounds" / "r2" / "score.json").read_text())["mode"], "both")
            audit = sr.audit_for(run, 2)
            self.assertEqual(audit["rewritten"], ["a"])
            self.assertEqual(audit["select"].split(",")[0], "a")
            self.assertEqual(len(audit["select"].split(",")), 2)


if __name__ == "__main__":
    unittest.main()
