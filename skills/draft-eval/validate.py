#!/usr/bin/env python3
"""Validate one grader batch and write the stamped records.

    validate.py <raw output> --units units.json --batch <id,id,...> \\
        --grader codex|claude --round N [--model <full id>] [-o records.jsonl]
    validate.py --selftest

Strips a code fence, parses the JSON, checks it against schema.json, then
rejects: a unit missing from the batch or repeated, a missing criterion, a
score out of range, N/A outside the rubric's allowed cases, and a reason with
no double-quoted text taken from the unit's text or notes.

On success, appends one record per unit in the spec's shape, stamped with the
grader, the full model id, rubric_version, round, prompt_sha256 (of
grader-prompt.md) and schema_sha256. Criteria that do not apply to the kind
are dropped. Exit 0 on success, 1 with the errors on stderr.
"""
import argparse
import hashlib
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


def _norm(s):
    # Graders swap quote marks when they nest a quote, drop markdown emphasis,
    # and deck text can lose the space between sentences. Compare with whitespace removed.
    for ch in "’‘“”\"":
        s = s.replace(ch, "'")
    s = s.replace("*", "").replace("`", "")
    return "".join(s.lower().split())


def quotes_unit(reason, unit):
    source = _norm(unit.get("text", "") + "\n" + unit.get("notes", ""))
    if not source:
        return True  # nothing to quote; the prompt asks for the screenshot instead
    for m in QUOTE.finditer(reason):
        # an elided quote ("a ... b") counts when every piece is in the unit
        parts = [_norm(p).strip(" .,;:!?") for p in re.split(r"\.\.\.|…", m.group(1) or m.group(2))]
        parts = [p for p in parts if p]
        if parts and len("".join(parts)) >= 4 and all(p in source for p in parts):
            return True
    return False


def na_allowed(crit, unit, first, has_number, rubric):
    na = crit["na_allowed"]
    if unit.get("role") in na["roles"]:
        return True
    conds = na["conditions"]
    return (("first_unit" in conds and first) or ("reveals_nothing" in conds)
            or ("no_number" in conds and not has_number))


def check_record(rec, unit, first, kind, rubric):
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
        if cid == "honest_numbers" and score != "n/a" and "no_number" in c["na_allowed"]["conditions"] \
                and not has_number:
            errs.append(f"{uid} {cid}: the unit has no number, so it must be N/A")
        if not quotes_unit(entry["reason"], unit):
            errs.append(f"{uid} {cid}: the reason quotes nothing from the unit")
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
        errs += check_record(rec, by_id[uid], uid == first_id, kind, rubric)
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
        return {"unit": uid, "scores": {c["id"]: {"score": 4, "reason": f'It says "{quote}".'}
                                        for c in rubric["criteria"]}}
    good = [rec("a", "Welcome to the session"), rec("b", "Nine in ten")]
    good[0]["scores"]["honest_numbers"] = {"score": "n/a", "reason": 'Only "Welcome to the session".'}
    ok, errs = check(json.dumps({"model": "m", "records": good}), units, ["a", "b"], rubric)
    assert not errs and len(ok) == 2, errs
    bad = [rec("a", "Welcome to the session"), rec("b", "Nine in ten")]
    bad[0]["scores"]["honest_numbers"] = {"score": "n/a", "reason": 'Only "Welcome to the session".'}
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
