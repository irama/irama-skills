"""The first-cut gate: rubric group, reply validation, pass rule and gate.json. No network."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import gate  # noqa: E402
from extract import content_hash  # noqa: E402

RUBRIC = json.loads((HERE / "rubric.json").read_text())
QS = gate.question_ids(RUBRIC)
UNITS = {"kind": "deck", "deck_build_hash": "9a0dddb70cca", "units": [
    {"id": "s1", "text": "Most teams already use the tool", "notes": "The point: start where they are."},
    {"id": "terms", "role": "terms", "hidden": True, "text": "Glossary"},
    {"id": "s2", "text": "Three moves for Monday morning"},
]}
for _u in UNITS["units"]:
    _u["content_hash"] = content_hash(_u)


def units_with(build="9a0dddb70cca", **texts):
    """UNITS at another build, with the named slides' text changed and their content hash recomputed."""
    out = json.loads(json.dumps(UNITS), object_hook=dict)
    out["deck_build_hash"] = build
    for u in out["units"]:
        if u["id"] in texts:
            u["text"] = texts[u["id"]]
            u["content_hash"] = content_hash(u)
    return out
DECK = ('<html><head><meta name="deck-build-hash"  content="9a0dddb70cca">'
        '<meta name="deck-round" content="first-cut"></head><body></body></html>')


def reply(fail=(), quote=None, model="model-x"):
    """fail: (slide, question) pairs answered false."""
    words = {"s1": "Most teams already use", "s2": "Three moves for Monday"}
    return json.dumps({"model": model, "slides": [
        {"unit": s, "answers": {q: {"pass": (s, q) not in fail, "quote": quote if quote is not None else words[s]}
                                for q in QS}} for s in ("s1", "s2")]})


def grades(*replies):
    g = None
    for grader, raw in replies:
        doc, errs = gate.check(raw, UNITS, ["s1", "s2"], RUBRIC)
        assert not errs, errs
        g = gate.merge(g, doc, grader, None, RUBRIC, UNITS)
    return g


class TestGateRubric(unittest.TestCase):
    def test_first_cut_group(self):
        fc = RUBRIC["first_cut"]
        crits = {c["id"] for c in RUBRIC["criteria"]}
        self.assertEqual(fc["kind"], "gate")
        self.assertEqual(len(fc["questions"]), 8)
        for q in fc["questions"]:
            self.assertEqual(q["kind"], "gate")
            self.assertIn(q["overlaps"], crits)
            self.assertTrue(q["question"] and q["pass"] and q["fail"])
        self.assertNotIn("\u2014", json.dumps(fc, ensure_ascii=False))


class TestGateReply(unittest.TestCase):
    def test_good_reply(self):
        doc, errs = gate.check(reply(), UNITS, ["s1", "s2"], RUBRIC)
        self.assertEqual(errs, [])

    def test_reply_with_no_quote_is_rejected(self):
        raw = json.loads(reply())
        del raw["slides"][0]["answers"]["talkable"]["quote"]
        _, errs = gate.check(json.dumps(raw), UNITS, ["s1", "s2"], RUBRIC)
        self.assertTrue(any("quote" in e for e in errs), errs)
        _, errs = gate.check(reply(quote=""), UNITS, ["s1", "s2"], RUBRIC)
        self.assertTrue(errs)

    def test_quote_must_come_from_the_slide(self):
        _, errs = gate.check(reply(quote="words the slide never says"), UNITS, ["s1", "s2"], RUBRIC)
        self.assertTrue(any("not from the slide" in e for e in errs), errs)

    def test_pass_is_boolean_and_every_question_answered(self):
        raw = json.loads(reply())
        raw["slides"][0]["answers"]["talkable"]["pass"] = 4
        del raw["slides"][1]["answers"]["fit_and_finish"]
        _, errs = gate.check(json.dumps(raw), UNITS, ["s1", "s2"], RUBRIC)
        self.assertTrue(any("not boolean" in e for e in errs) and any("fit_and_finish" in e for e in errs), errs)

    def test_batch_coverage(self):
        _, errs = gate.check(reply(), UNITS, ["s1"], RUBRIC)
        self.assertTrue(any("s2: not in this batch" in e for e in errs), errs)


class TestPassRule(unittest.TestCase):
    def test_any_grader_failing_fails_the_slide(self):
        g = grades(("claude", reply()), ("codex", reply(fail={("s2", "one_visual")})))
        self.assertEqual(gate.failing(gate.table(g, UNITS, RUBRIC)), {"s2": ["one_visual"]})

    def test_all_pass_and_hidden_slides_are_not_presented(self):
        tab = gate.table(grades(("claude", reply()), ("codex", reply())), UNITS, RUBRIC)
        self.assertEqual(set(tab), {"s1", "s2"})
        self.assertEqual(gate.failing(tab), {})

    def test_regrade_replaces_only_its_slides(self):
        g = grades(("claude", reply(fail={("s2", "one_visual")})))
        fixed = json.loads(reply())
        fixed["slides"] = fixed["slides"][1:]
        doc, errs = gate.check(json.dumps(fixed), UNITS, ["s2"], RUBRIC)
        self.assertEqual(errs, [])
        g = gate.merge(g, doc, "claude", None, RUBRIC, UNITS)
        self.assertEqual(gate.failing(gate.table(g, UNITS, RUBRIC)), {})

    def test_unanswered_slide_fails(self):
        g = grades(("claude", reply()))
        units = {"kind": "deck", "units": UNITS["units"] + [{"id": "s3", "text": "A new slide"}]}
        self.assertEqual(gate.failing(gate.table(g, units, RUBRIC)), {"s3": QS})

    def test_merge_refuses_another_rubric_version(self):
        g = grades(("claude", reply()))
        g["rubric_version"] = "0.10"
        doc, _ = gate.check(reply(), UNITS, ["s1", "s2"], RUBRIC)
        with self.assertRaises(SystemExit):
            gate.merge(g, doc, "codex", None, RUBRIC, UNITS)


class TestGateRecord(unittest.TestCase):
    def test_record_from_fixture_replies(self):
        g = grades(("claude", reply(model="claude-model")), ("codex", reply(fail={("s1", "plain_stance")}, model="codex-model")))
        rec = gate.record(DECK, UNITS, g, "first-cut", RUBRIC, now=datetime(2026, 11, 17, tzinfo=timezone.utc))
        self.assertEqual(rec["deck_build_hash"], "9a0dddb70cca")  # from the meta, never a file hash
        self.assertEqual(rec["round"], "first-cut")
        self.assertEqual(rec["rubric_version"], RUBRIC["rubric_version"])
        self.assertEqual(rec["graders"], {"claude": ["claude-model"], "codex": ["codex-model"]})
        self.assertEqual(rec["graded_builds"], {"s1": "9a0dddb70cca", "s2": "9a0dddb70cca"})
        self.assertEqual(rec["content_hashes"], {s: u["content_hash"] for s, u in gate.presented(UNITS).items()})
        self.assertEqual(rec["date"], "2026-11-17T00:00:00Z")
        self.assertFalse(rec["pass"])
        self.assertEqual(rec["failing"], {"s1": ["plain_stance"]})
        self.assertEqual(rec["slides"]["s1"]["plain_stance"], {"pass": False, "graders": {"claude": True, "codex": False}})
        self.assertEqual(set(rec["slides"]["s2"]), set(QS))

    def test_hash_survives_a_rewritten_file(self):
        g = grades(("claude", reply()))
        injected = DECK.replace("<body>", "<body><script>/* loader */</script>")
        self.assertEqual(gate.record(injected, UNITS, g, "re-outline", RUBRIC)["deck_build_hash"], "9a0dddb70cca")

    def test_refusals(self):
        g = grades(("claude", reply()))
        with self.assertRaises(SystemExit):
            gate.record("<html></html>", UNITS, g, "first-cut", RUBRIC)
        with self.assertRaises(SystemExit):
            gate.record(DECK, UNITS, g, "comment", RUBRIC)
        with self.assertRaises(SystemExit):
            gate.record(DECK, UNITS, dict(g, rubric_version="0.10"), "first-cut", RUBRIC)

    def test_record_refuses_another_build(self):
        # graded against build A, the deck is now build C: the grades are not of this deck
        g = grades(("claude", reply()))
        with self.assertRaises(SystemExit) as e:
            gate.record(DECK.replace("9a0dddb70cca", "c0ffee000000"), UNITS, g, "first-cut", RUBRIC)
        self.assertIn("c0ffee000000", str(e.exception))

    def test_merge_refuses_units_with_no_build_hash(self):
        doc, _ = gate.check(reply(), UNITS, ["s1", "s2"], RUBRIC)
        with self.assertRaises(SystemExit):
            gate.merge(None, doc, "claude", None, RUBRIC, dict(UNITS, deck_build_hash=None))
        no_content = json.loads(json.dumps(UNITS))
        del no_content["units"][2]["content_hash"]
        with self.assertRaises(SystemExit):
            gate.merge(None, doc, "claude", None, RUBRIC, no_content)

    def test_regrade_keeps_every_model(self):
        g = grades(("claude", reply(model="m1")))
        doc, _ = gate.check(reply(model="m2"), UNITS, ["s1", "s2"], RUBRIC)
        g = gate.merge(g, doc, "claude", None, RUBRIC, UNITS)
        self.assertEqual(g["graders"]["claude"]["models"], ["m1", "m2"])
        self.assertEqual(gate.record(DECK, UNITS, g, "first-cut", RUBRIC)["graders"], {"claude": ["m1", "m2"]})

    def test_grader_set_must_match_by_slide(self):
        # first pass by two graders, re-grade of s2 by one: codex's stale answer would lock the gate
        g = grades(("claude", reply()), ("codex", reply(fail={("s2", "one_visual")})))
        doc, _ = gate.check(json.dumps(dict(json.loads(reply()), slides=json.loads(reply())["slides"][1:])),
                            UNITS, ["s2"], RUBRIC)
        g = gate.merge(g, doc, "claude", None, RUBRIC, units_with("b2"))
        with self.assertRaises(SystemExit) as e:
            gate.record(DECK, UNITS, g, "first-cut", RUBRIC)
        self.assertIn("s2", str(e.exception))
        with self.assertRaises(SystemExit):
            gate.check_graders(g, UNITS)
        # first pass by one grader, a second grader joins only for s2: s1 has fewer graders
        g = grades(("claude", reply()))
        g = gate.merge(g, doc, "codex", None, RUBRIC, UNITS)
        with self.assertRaises(SystemExit) as e:
            gate.check_graders(g, UNITS)
        self.assertIn("s1: graded by claude", str(e.exception))

    def test_changed_slide_not_regraded_is_refused(self):
        # s2 is repaired and re-graded; s1 also changed in the rebuild but was never re-graded
        g = grades(("claude", reply(fail={("s2", "one_visual")})))
        new = units_with("b2", s1="Most teams already use the tool daily", s2="Three moves for Monday")
        doc, errs = gate.check(json.dumps(dict(json.loads(reply()), slides=json.loads(reply())["slides"][1:])),
                               new, ["s2"], RUBRIC)
        self.assertEqual(errs, [])
        g = gate.merge(g, doc, "claude", None, RUBRIC, new)
        with self.assertRaises(SystemExit) as e:
            gate.record(DECK.replace("9a0dddb70cca", "b2"), new, g, "first-cut", RUBRIC)
        self.assertIn("s1", str(e.exception))
        self.assertNotIn("s2:", str(e.exception))

    def test_grades_from_another_units_set_are_refused(self):
        # another deck's units at the same build id: same slide ids, other content
        other = units_with(s1="Most teams already use another tool", s2="Three moves for Monday afternoon")
        g = None
        doc, errs = gate.check(reply(), other, ["s1", "s2"], RUBRIC)
        self.assertEqual(errs, [])
        g = gate.merge(g, doc, "claude", None, RUBRIC, other)
        with self.assertRaises(SystemExit) as e:
            gate.record(DECK, UNITS, g, "first-cut", RUBRIC)
        self.assertIn("s1", str(e.exception))
        self.assertIn("s2", str(e.exception))

    def test_repair_then_regrade_of_only_the_failing_slides_passes(self):
        g = grades(("claude", reply(fail={("s2", "one_visual")})), ("codex", reply()))
        new = units_with("b2", s2="Three moves for Monday")  # the repair rewrites s2 only
        regrade = json.dumps(dict(json.loads(reply()), slides=json.loads(reply())["slides"][1:]))
        for grader in ("claude", "codex"):
            doc, errs = gate.check(regrade, new, ["s2"], RUBRIC)
            self.assertEqual(errs, [])
            g = gate.merge(g, doc, grader, None, RUBRIC, new)
        rec = gate.record(DECK.replace("9a0dddb70cca", "b2"), new, g, "first-cut", RUBRIC)
        self.assertTrue(rec["pass"])
        self.assertEqual(rec["graded_builds"], {"s1": "9a0dddb70cca", "s2": "b2"})
        self.assertEqual(rec["content_hashes"], {"s1": UNITS["units"][0]["content_hash"],
                                                 "s2": new["units"][2]["content_hash"]})

    def test_slide_of_short_words_can_validate(self):
        units = {"kind": "deck", "deck_build_hash": "h", "units": [{"id": "q", "text": "Q&A"}]}
        raw = json.dumps({"model": "m", "slides": [{"unit": "q", "answers": {q: {"pass": True, "quote": "Q&A"} for q in QS}}]})
        doc, errs = gate.check(raw, units, ["q"], RUBRIC)
        self.assertEqual(errs, [])

    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "deck").mkdir()
            (t / "deck" / "index.html").write_text(DECK)
            (t / "units.json").write_text(json.dumps(UNITS))
            (t / "shots").mkdir()
            for s in ("s1", "s2"):
                (t / "shots" / f"{s}.png").write_bytes(b"png")
            (t / "shots" / "shots.json").write_text(json.dumps({"shots": [{"id": s, "file": f"{s}.png"} for s in ("s1", "s2")]}))
            out = gate.build(UNITS, t / "packets", t / "shots" / "shots.json")
            prompt = Path(out["batches"][0]["prompt"]).read_text()
            self.assertIn("`fit_and_finish`", prompt)
            self.assertNotIn("{{", prompt)
            self.assertEqual(out["batches"][0]["units"], ["s1", "s2"])
            (t / "raw.txt").write_text("```json\n" + reply() + "\n```")
            self.assertEqual(gate.main(["validate", str(t / "raw.txt"), "--units", str(t / "units.json"), "--batch", "s1,s2",
                                        "--grader", "claude", "-o", str(t / "grades.json")]), 0)
            self.assertEqual(gate.main(["record", str(t / "deck" / "index.html"), "--units", str(t / "units.json"),
                                        "--grades", str(t / "grades.json"), "--round", "first-cut"]), 0)
            rec = json.loads((t / "deck" / "eval-runs" / "gate.json").read_text())
            self.assertTrue(rec["pass"])
            self.assertEqual(rec["deck_build_hash"], "9a0dddb70cca")


if __name__ == "__main__":
    unittest.main()
