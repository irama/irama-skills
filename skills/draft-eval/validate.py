#!/usr/bin/env python3
"""Validate one grader batch and write the stamped records.

    validate.py <raw output> --units units.json --batch <id,id,...> \\
        --grader codex|claude --round N [--model <full id>] [-o records.jsonl]
    validate.py --selftest

Strips a code fence, parses the JSON, checks it against schema.json, then
rejects: a unit missing from the batch or repeated, a missing criterion, a
score out of range, N/A outside the rubric's allowed cases, a reason with
no double-quoted text taken from the unit's text or notes, and a reason that
quotes the previous unit on any criterion but flow and device. The device entry
also names its type: "none" with a score of 1 or N/A, a real type otherwise.

On success, appends one record per unit in the spec's shape, stamped with the
grader, the full model id, rubric_version, round, prompt_sha256 (of
grader-prompt.md) and schema_sha256. Criteria that do not apply to the kind
are dropped. Exit 0 on success, 1 with the errors on stderr.
"""
import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*\n(.*?)\n\s*```\s*$", re.S)
QUOTE = re.compile(r'"([^"]+)"|“([^”]+)”')
# ponytail: word list, not a parser. "one" is left out because "one idea" is not a number.
NUMBER = re.compile(r"\d|\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|"
                    r"forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|"
                    r"trillion|percent|per cent|dozen|half)\b", re.I)


def sha256(name):
    return hashlib.sha256((HERE / name).read_bytes()).hexdigest()


def strip_fence(raw):
    m = FENCE.match(raw)
    return m.group(1) if m else raw.strip()


def schema_errors(value, schema, path="$"):
    """The subset of JSON Schema that schema.json uses."""
    if "anyOf" in schema:
        if all(schema_errors(value, s, path) for s in schema["anyOf"]):
            return [f"{path}: matches no allowed shape"]
        return []
    t = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "null": type(None)}
    if t == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return [f"{path}: not an integer"]
    elif t and not isinstance(value, types[t]):
        return [f"{path}: not {t}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: {value!r} not in {schema['enum']}"]
    if t == "string" and len(value) < schema.get("minLength", 0):
        return [f"{path}: empty"]
    errs = []
    if t == "object":
        for k in schema.get("required", []):
            if k not in value:
                errs.append(f"{path} {k}: missing")
        for k, v in value.items():
            if k in schema.get("properties", {}):
                errs += schema_errors(v, schema["properties"][k], f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}.{k}: not allowed")
    if t == "array":
        for i, v in enumerate(value):
            errs += schema_errors(v, schema["items"], f"{path}[{i}]")
    return errs


def _unescape(s):
    # notes can carry entities, sometimes escaped twice ("&amp;rsquo;"): decode until stable
    while (u := html.unescape(s)) != s:
        s = u
    return s


def _norm(s):
    # Graders swap quote marks when they nest a quote and drop markdown emphasis.
    # Deck text can lose the space between sentences ("fill.That"), so a space is
    # restored only after sentence punctuation; other word boundaries still count.
    s = _unescape(s)
    for ch in "’‘“”\"":
        s = s.replace(ch, "'")
    s = s.replace("*", "").replace("`", "")
    s = re.sub(r"([.!?])(?=[^\W\d_])", r"\1 ", s)
    return " ".join(s.lower().split())


def _found(parts, source):
    pos = 0
    for p in parts:
        # deck text loses the space between two blocks ("AIto it"), so a space in the quote may be
        # missing from the source. Never the reverse: "therapist" must not match "the rapist".
        m = re.compile(" ?".join(re.escape(w) for w in p.split(" "))).search(source, pos)
        if not m:
            return False
        pos = m.end()
    return True


def quote_sources(reason, unit, prev=None, short_ok=False):
    """Where each double-quoted piece of the reason comes from: "unit", "prev" or "other".

    short_ok lets a quote under 4 characters count when it is a whole token of the unit
    ("D1"). check_record sets it only for an honest_numbers N/A, where a session label
    is often the only thing there is to quote (rubric 0.2)."""
    source = _norm(unit.get("text", "") + "\n" + unit.get("notes", ""))
    before = _norm((prev or {}).get("text", ""))
    out = []
    for m in QUOTE.finditer(reason):
        # an elided quote ("a ... b") counts when every piece is in the unit, in order
        parts = [_norm(p).strip(" .,;:!?") for p in re.split(r"\.\.\.|…", m.group(1) or m.group(2))]
        parts = [p for p in parts if p]
        if not parts:
            continue
        if len("".join(parts)) < 4:
            if short_ok and len(parts) == 1 and re.search(r"(?<!\w)" + re.escape(parts[0]) + r"(?!\w)", source):
                out.append("unit")
            continue
        out.append("unit" if _found(parts, source) else "prev" if before and _found(parts, before) else "other")
    return out


def quotes_unit(reason, unit, short_ok=False):
    if not _norm(unit.get("text", "") + "\n" + unit.get("notes", "")):
        return True  # nothing to quote; the prompt asks for the screenshot instead
    return "unit" in quote_sources(reason, unit, short_ok=short_ok)


def na_allowed(crit, unit, first, has_number, rubric):
    na = crit["na_allowed"]
    if unit.get("role") in na["roles"]:
        return True
    conds = na["conditions"]
    # no_number is allowed even with digits present: numbers that only describe the session
    # ("90 minutes", "Exercise 3 of 4", C1 to C9) are the grader's call (rubric 0.2).
    return (("first_unit" in conds and first) or ("no_number" in conds)
            or ("planted" in conds and bool(unit.get("planted")))
            or ("no_notes" in conds and not unit.get("notes", "").strip()))


def na_forced(crit, unit, has_number):
    """Why this criterion must be N/A on this unit, or None: no number at all, or a planted fake."""
    conds = crit["na_allowed"]["conditions"]
    if "planted" in conds and unit.get("planted"):
        return "the unit is marked planted"
    if "no_number" in conds and not has_number:
        return "the unit has no number"
    if "no_notes" in conds and not unit.get("notes", "").strip():
        return "the unit has no speaker notes"
    return None


# criteria judged against the previous unit: only these may also quote it
PREV_OK = ("flow", "device")


def check_record(rec, unit, first, kind, rubric, prev=None):
    errs = []
    uid = rec["unit"]
    has_number = bool(NUMBER.search(unit.get("text", "") + " " + unit.get("notes", "")))
    for c in rubric["criteria"]:
        cid, entry = c["id"], rec["scores"].get(c["id"])
        if kind not in c["applies_to"]:
            continue
        if entry is None:
            errs.append(f"{uid} {cid}: missing")
            continue
        score = entry["score"]
        if score == "n/a" and not na_allowed(c, unit, first, has_number, rubric):
            errs.append(f"{uid} {cid}: N/A not allowed here")
        forced = na_forced(c, unit, has_number)
        if score != "n/a" and forced:
            errs.append(f"{uid} {cid}: {forced}, so it must be N/A")
        if cid == "device":
            none = score == "n/a" or score == 1
            if none and entry.get("type") != "none":
                errs.append(f"{uid} device: a score of 1 or N/A has type none")
            elif not none and entry.get("type") == "none":
                errs.append(f"{uid} device: a score above 1 names its device type")
        if not quotes_unit(entry["reason"], unit, short_ok=(cid == "honest_numbers" and score == "n/a")):
            errs.append(f"{uid} {cid}: the reason quotes nothing from the unit")
        elif cid not in PREV_OK and "prev" in quote_sources(entry["reason"], unit, prev):
            errs.append(f"{uid} {cid}: the reason quotes the previous unit")
    return errs


def check(raw, units_doc, batch_ids, rubric=None, schema=None):
    """Return (records in spec shape, errors)."""
    rubric = rubric or json.loads((HERE / "rubric.json").read_text())
    schema = schema or json.loads((HERE / "schema.json").read_text())
    try:
        doc = json.loads(strip_fence(raw))
    except ValueError as e:
        return [], [f"not JSON: {e}"]
    if not isinstance(doc, dict):
        return [], ["$: not an object"]
    errs = schema_errors({**doc, "records": []}, schema)
    if not isinstance(doc.get("records"), list):
        errs.append("$.records: missing or not a list")
    if errs:
        return [], errs
    item = schema["properties"]["records"]["items"]
    kind = units_doc["kind"]
    graded = [u for u in units_doc["units"] if not u.get("hidden")]
    by_id = {u["id"]: u for u in graded}
    first_id = graded[0]["id"] if graded else None
    seen, out = set(), []
    for i, rec in enumerate(doc["records"]):
        uid = rec.get("unit") if isinstance(rec, dict) else None
        if uid not in batch_ids or uid in seen:
            errs.append(f"{uid or f'records[{i}]'}: not in this batch, or repeated")
            continue
        seen.add(uid)
        shape = schema_errors(rec, item, uid)
        if shape:
            errs += shape
            continue
        idx = graded.index(by_id[uid])
        errs += check_record(rec, by_id[uid], uid == first_id, kind, rubric, graded[idx - 1] if idx else None)
        scores = {c["id"]: rec["scores"][c["id"]] for c in rubric["criteria"] if kind in c["applies_to"]}
        out.append({"unit": uid, "model": doc["model"], "scores": scores})
    errs += [f"{u}: no record" for u in batch_ids if u not in seen]
    return (out if not errs else []), errs


def selftest():
    units = {"kind": "deck", "units": [
        {"id": "a", "role": "title", "text": "Welcome to the session", "notes": ""},
        {"id": "b", "role": "content", "text": "Nine in ten projects slip", "notes": "Source: survey"}]}
    rubric = json.loads((HERE / "rubric.json").read_text())

    def rec(uid, quote):
        s = {c["id"]: {"score": 4, "reason": f'It says "{quote}".'} for c in rubric["criteria"]}
        s["device"]["type"] = "surprise"
        return {"unit": uid, "scores": s}
    good = [rec("a", "Welcome to the session"), rec("b", "Nine in ten")]
    good[0]["scores"]["honest_numbers"] = {"score": "n/a", "reason": 'Only "Welcome to the session".'}
    good[0]["scores"]["notes_actionable"] = {"score": "n/a", "reason": 'No notes: "Welcome to the session".'}
    ok, errs = check(json.dumps({"model": "m", "records": good}), units, ["a", "b"], rubric)
    assert not errs and len(ok) == 2, errs
    bad = [rec("a", "Welcome to the session"), rec("b", "Nine in ten")]
    bad[0]["scores"]["honest_numbers"] = {"score": "n/a", "reason": 'Only "Welcome to the session".'}
    bad[0]["scores"]["notes_actionable"] = {"score": "n/a", "reason": 'No notes: "Welcome to the session".'}
    bad[1]["scores"]["visual"] = {"score": "n/a", "reason": "No picture on it."}
    ok, errs = check("```json\n" + json.dumps({"model": "m", "records": bad}) + "\n```", units, ["a", "b"], rubric)
    assert ok == [] and "b visual: N/A not allowed here" in errs \
        and "b visual: the reason quotes nothing from the unit" in errs, errs
    print("selftest ok: good batch accepted; N/A outside the allowed cases and a quote-less reason rejected")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("raw", nargs="?")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--units")
    ap.add_argument("--batch", help="comma-separated unit ids in this batch")
    ap.add_argument("--grader", choices=["codex", "claude"])
    ap.add_argument("--round", type=int)
    ap.add_argument("--model", help="full model id; overrides the one the grader reported")
    ap.add_argument("-o", "--out", help="append records here as JSON lines (default stdout)")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not (a.raw and a.units and a.batch and a.grader and a.round is not None):
        ap.error("raw, --units, --batch, --grader and --round are required")
    rubric = json.loads((HERE / "rubric.json").read_text())
    records, errs = check(Path(a.raw).read_text(), json.loads(Path(a.units).read_text()),
                          a.batch.split(","), rubric)
    if errs:
        print("\n".join(errs), file=sys.stderr)
        return 1
    stamp = {"grader": a.grader, "rubric_version": rubric["rubric_version"], "round": a.round,
             "prompt_sha256": sha256("grader-prompt.md"), "schema_sha256": sha256("schema.json")}
    lines = [json.dumps({"unit": r["unit"], **stamp, "model": a.model or r["model"],
                         "scores": r["scores"]}) for r in records]
    if a.out:
        with open(a.out, "a") as f:
            f.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
