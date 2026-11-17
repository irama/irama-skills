#!/usr/bin/env python3
"""The first-cut gate: eight binary questions per presented slide, then the gate record.

    gate.py build <units.json> <outdir> --shots shots.json [--select id,id]
    gate.py validate <raw> --units units.json --batch id,id --grader codex|claude [--model <id>] -o grades.json
    gate.py failing <grades.json> --units units.json
    gate.py record <index.html> --units units.json --grades grades.json --round first-cut|re-outline [-o gate.json]

build writes the same packets as packet.py (batches of 8, each slide with its previous slide in
context/) with the gate prompt beside each batch and the reply schema as <outdir>/gate-schema.json,
and prints {prompt_sha256, schema, batches}.
--select packs only the named slides, for the re-grade after the repair pass.

validate checks one grader reply: every slide of the batch once, every question with a boolean
pass and a quote taken from the slide's text or notes. It merges the answers into grades.json as
graders.<grader>.slides.<id>, with the units' deck_build_hash as graders.<grader>.builds.<id>, the
slide's content_hash (from extract.py) as graders.<grader>.content.<id> and each model the grader
used in graders.<grader>.models, so a re-grade replaces only the slides it covers. A grades file written under another rubric version is refused. Exit 1 on a bad reply.

failing prints the slides that fail, by the pass rule: a slide fails a question when any grader
that ran fails it, or never answered it. The first cut passes when no presented slide fails.
failing and record refuse grades where the graders differ by slide: every slide a grader answered
must be answered by every grader, under the same build. The re-grade uses exactly the first pass's
graders.

record writes <deck folder>/eval-runs/gate.json: the deck's deck-build-hash meta (never the
file's sha256, which changes when the deck is delivered), the round type, the rubric version,
the graders that ran with the models each used, the build each slide was graded under, pass or
fail per question per slide (with each grader's answer) and the date. It refuses unless the
units.json deck_build_hash equals the deck's, and unless every graded presented slide's content_hash
in units.json equals the one it was last graded under: a slide that changed after grading and was
not re-graded, or grades taken from another deck's units, are refused. Prints {pass, failing}. Scripts never call a model: the session runs the graders.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import packet  # noqa: E402
from extract import build_hash as _meta_hash  # noqa: E402
from validate import quotes_unit, schema_errors, sha256, strip_fence  # noqa: E402

ROUNDS = ("first-cut", "re-outline")


def live_rubric():
    return json.loads((HERE / "rubric.json").read_text())


def question_ids(rubric):
    return [q["id"] for q in rubric["first_cut"]["questions"]]


def reply_schema(rubric):
    answer = {"type": "object", "required": ["pass", "quote"], "additionalProperties": False,
              "properties": {"pass": {"type": "boolean"}, "quote": {"type": "string", "minLength": 1}}}
    ids = question_ids(rubric)
    # additionalProperties false at every level, so codex --output-schema accepts it as strict
    return {"type": "object", "required": ["model", "slides"], "additionalProperties": False, "properties": {
        "model": {"type": "string", "minLength": 1},
        "slides": {"type": "array", "items": {"type": "object", "required": ["unit", "answers"],
                                              "additionalProperties": False, "properties": {
            "unit": {"type": "string", "minLength": 1},
            "answers": {"type": "object", "required": ids, "additionalProperties": False,
                        "properties": {i: answer for i in ids}}}}}}}


def render_questions(rubric):
    out = []
    for q in rubric["first_cut"]["questions"]:
        out += [f"### `{q['id']}`: {q['name']}\n", q["question"] + "\n",
                f"- pass: {q['pass']}", f"- fail: {q['fail']}", ""]
    return "\n".join(out)


def render_prompt(rubric, kind, rows, examples=None, terms=None):
    # slide ids and roles are draft markup: data in a fenced JSON block, never prompt sentences
    data = [{"folder": r["folder"], "unit": r["id"], "role": r.get("role", "content"),
             "files": r.get("files", [])} for r in rows]
    text = (HERE / "gate-prompt.md").read_text()
    for k, v in {"RUBRIC_VERSION": rubric["rubric_version"], "QUESTIONS": render_questions(rubric),
                 "UNITS": "```json\n" + json.dumps(data, indent=1) + "\n```",
                 "TERMS": packet.render_terms(terms)}.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def build(units_doc, outdir, shots_path, select=None, rubric=None):
    if units_doc.get("kind") != "deck":
        raise SystemExit("gate.py: the first-cut gate is for decks only")
    rubric = rubric or live_rubric()
    batches = packet.build(units_doc, outdir, shots_path, rubric=rubric, select=select, render=render_prompt)
    schema = Path(outdir).resolve() / "gate-schema.json"  # for codex --output-schema
    schema.write_text(json.dumps(reply_schema(rubric), indent=1) + "\n")
    return {"prompt_sha256": sha256("gate-prompt.md"), "schema": str(schema), "batches": batches}


def presented(units_doc):
    return {str(u["id"]): u for u in units_doc["units"] if not u.get("hidden")}


def check(raw, units_doc, batch, rubric):
    try:
        doc = json.loads(strip_fence(raw))
    except ValueError as e:
        return None, [f"not JSON: {e}"]
    errs = schema_errors(doc, reply_schema(rubric))
    if errs:
        return None, errs
    units = presented(units_doc)
    got = [s["unit"] for s in doc["slides"]]
    for sid in sorted(set(got) - set(batch)):
        errs.append(f"{sid}: not in this batch")
    for sid in sorted(set(batch) - set(got)):
        errs.append(f"{sid}: missing from the reply")
    for sid in sorted({s for s in got if got.count(s) > 1}):
        errs.append(f"{sid}: answered twice")
    for s in doc["slides"]:
        u = units.get(s["unit"])
        if u is None:
            continue
        for q, a in s["answers"].items():
            # the quote is bare; wrap it so quotes_unit reads it as one quoted piece. short_ok: a
            # slide whose only words are short ("Q&A", "AI?") still has a whole-token quote to give
            if not quotes_unit('"' + a["quote"].replace('"', "'") + '"', u, short_ok=True):
                errs.append(f"{s['unit']}.{q}: the quote is not from the slide's text or notes")
    return (None, errs) if errs else (doc, [])


def merge(grades, doc, grader, model, rubric, units_doc):
    """units_doc: the units.json the reply was graded against (its build and per-slide content hashes)."""
    build = units_doc.get("deck_build_hash")
    if not build:
        raise SystemExit("gate.py: units.json has no deck_build_hash; extract the built deck again with extract.py")
    if grades and grades.get("rubric_version") != rubric["rubric_version"]:
        raise SystemExit(f"gate.py: these grades are under rubric {grades.get('rubric_version')} and the skill "
                         f"is now at {rubric['rubric_version']}; grade the deck again into a new file.")
    units = presented(units_doc)
    if any(not units.get(s["unit"], {}).get("content_hash") for s in doc["slides"]):
        raise SystemExit("gate.py: units.json has no content_hash per slide; extract the built deck again with extract.py")
    grades = grades or {"rubric_version": rubric["rubric_version"], "graders": {}}
    g = grades["graders"].setdefault(grader, {"models": [], "slides": {}, "builds": {}})
    g.setdefault("content", {})
    g["prompt_sha256"] = sha256("gate-prompt.md")
    if (model or doc["model"]) not in g["models"]:
        g["models"].append(model or doc["model"])  # a re-grade keeps the first pass's model too
    for s in doc["slides"]:
        g["slides"][s["unit"]] = s["answers"]
        g["builds"][s["unit"]] = build
        g["content"][s["unit"]] = units[s["unit"]]["content_hash"]
    return grades


def check_graders(grades, units_doc):
    """Refuse grades whose grader set differs by slide: a re-grade by fewer graders leaves a stale
    fail that locks the gate, and one by more leaves the other slides unanswered."""
    every = set(grades["graders"])
    errs = []
    for sid in presented(units_doc):
        by = {g: (v.get("builds", {}).get(sid), v.get("content", {}).get(sid))
              for g, v in grades["graders"].items() if sid in v["slides"]}
        if not by:
            continue  # never graded: the pass rule fails it
        if set(by) != every:
            errs.append(f"{sid}: graded by {', '.join(sorted(by))}, but the grades hold {', '.join(sorted(every))}")
        elif len(set(by.values())) > 1 or any(None in h for h in by.values()):
            errs.append(f"{sid}: graders answered under different builds or content "
                        f"({', '.join(f'{g} {b}/{c}' for g, (b, c) in sorted(by.items()))})")
    if errs:
        raise SystemExit("gate.py: the graders differ by slide; re-grade these slides with exactly the first "
                         "pass's graders:\n" + "\n".join(errs))


def graded(grades, units_doc, field):
    """The build (field "builds") or content hash (field "content") each presented slide was graded
    under, None when no grader answered it. check_graders has made the graders agree."""
    return {sid: next((v[field].get(sid) for v in grades["graders"].values() if sid in v.get(field, {})), None)
            for sid in presented(units_doc)}


def check_content(grades, units_doc):
    """Refuse a graded slide whose content moved since it was graded: the grade is of other content."""
    was = graded(grades, units_doc, "content")
    errs = [f"{sid}: graded as content {was[sid]}, now {u.get('content_hash')}"
            for sid, u in presented(units_doc).items()
            if any(sid in v["slides"] for v in grades["graders"].values()) and was[sid] != u.get("content_hash")]
    if errs:
        raise SystemExit("gate.py: these slides changed after they were graded (or the grades are of another "
                         "deck); re-grade them with gate.py build --select:\n" + "\n".join(errs))


def table(grades, units_doc, rubric):
    """Per presented slide and question: pass, and each grader's answer (None when it never answered)."""
    out = {}
    for sid in presented(units_doc):
        out[sid] = {}
        for q in question_ids(rubric):
            by = {g: (v["slides"].get(sid, {}).get(q) or {}).get("pass") for g, v in grades["graders"].items()}
            # the pass rule: any grader that ran failing it fails the slide; an unanswered question fails too
            out[sid][q] = {"pass": bool(by) and all(p is True for p in by.values()), "graders": by}
    return out


def failing(tab):
    return {sid: [q for q, v in qs.items() if not v["pass"]] for sid, qs in tab.items()
            if any(not v["pass"] for v in qs.values())}


def build_hash(html):
    found = _meta_hash(html)
    if not found:
        raise SystemExit("gate.py: the deck has no deck-build-hash meta; rebuild it with the deck builder")
    return found


def record(html, units_doc, grades, round_type, rubric=None, now=None):
    rubric = rubric or live_rubric()
    if round_type not in ROUNDS:
        raise SystemExit(f"gate.py: round must be one of {', '.join(ROUNDS)}")
    if grades.get("rubric_version") != rubric["rubric_version"]:
        raise SystemExit(f"gate.py: these grades are under rubric {grades.get('rubric_version')} and the skill "
                         f"is now at {rubric['rubric_version']}; grade the deck again.")
    if not grades.get("graders"):
        raise SystemExit("gate.py: no grader has answered; run the graders first")
    current = build_hash(html)
    if units_doc.get("deck_build_hash") != current:
        raise SystemExit(f"gate.py: units.json was extracted from build {units_doc.get('deck_build_hash')} and the "
                         f"deck is now build {current}; extract, render and grade the current build.")
    check_graders(grades, units_doc)
    check_content(grades, units_doc)
    tab = table(grades, units_doc, rubric)
    fails = failing(tab)
    return {"kind": "draft-eval-gate", "deck_build_hash": current, "round": round_type,
            "rubric_version": rubric["rubric_version"],
            "graders": {g: v["models"] for g, v in grades["graders"].items()},
            "graded_builds": graded(grades, units_doc, "builds"),
            "content_hashes": graded(grades, units_doc, "content"),
            "date": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pass": not fails, "failing": fails, "slides": tab}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("units")
    b.add_argument("outdir")
    b.add_argument("--shots", required=True)
    b.add_argument("--select", help="comma-separated slide ids: the re-grade after the repair pass")
    v = sub.add_parser("validate")
    v.add_argument("raw")
    v.add_argument("--units", required=True)
    v.add_argument("--batch", required=True)
    v.add_argument("--grader", choices=["codex", "claude"], required=True)
    v.add_argument("--model")
    v.add_argument("-o", "--out", required=True)
    f = sub.add_parser("failing")
    f.add_argument("grades")
    f.add_argument("--units", required=True)
    r = sub.add_parser("record")
    r.add_argument("deck")
    r.add_argument("--units", required=True)
    r.add_argument("--grades", required=True)
    r.add_argument("--round", required=True, choices=ROUNDS)
    r.add_argument("-o", "--out", help="default: <deck folder>/eval-runs/gate.json")
    a = ap.parse_args(argv)
    rubric = live_rubric()
    if a.cmd == "build":
        out = build(json.loads(Path(a.units).read_text()), a.outdir, a.shots,
                    select=set(a.select.split(",")) if a.select else None, rubric=rubric)
        print(json.dumps(out, indent=1))
        return 0
    units_doc = json.loads(Path(a.units).read_text())
    if a.cmd == "validate":
        out = Path(a.out)
        grades = json.loads(out.read_text()) if out.exists() else None
        doc, errs = check(Path(a.raw).read_text(), units_doc, a.batch.split(","), rubric)
        if errs:
            print("\n".join(errs), file=sys.stderr)
            return 1
        merged = merge(grades, doc, a.grader, a.model, rubric, units_doc)
        out.write_text(json.dumps(merged, indent=1) + "\n")
        return 0
    if a.cmd == "failing":
        grades = json.loads(Path(a.grades).read_text())
        check_graders(grades, units_doc)
        print(json.dumps(failing(table(grades, units_doc, rubric)), indent=1))
        return 0
    deck = Path(a.deck)
    rec = record(deck.read_text(), units_doc, json.loads(Path(a.grades).read_text()), a.round, rubric)
    out = Path(a.out) if a.out else deck.resolve().parent / "eval-runs" / "gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1) + "\n")
    print(json.dumps({"pass": rec["pass"], "failing": rec["failing"], "record": str(out)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
