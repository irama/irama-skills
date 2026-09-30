#!/usr/bin/env python3
"""Turn a blind preference test's notes into rulings, and count what the graders missed.

    prefer_rulings.py <prefer-answers.json> <prefer-key.json> --units <round units.json> \\
        --records <grader.jsonl> [<grader.regrade.jsonl> ...] [--label A4-prefer] \\
        [--criteria '{"p28": ["clear"]}'] [-o rulings.jsonl]

Every note the reader left on a pair becomes one ruling line per criterion the note
bears on, in the rulings.jsonl shape packet.py --examples reads (criterion, excerpt,
score, reason) plus: ruling id, unit, version (the side the reader chose: after,
before or none), note, both graders' scores on that criterion from --records, and
missed (the graders that scored 4 or more on a criterion the reader faulted).
score is 3, the ceiling a faulted criterion allows. The note is the reason.

The criteria come from keywords in the note; --criteria overrides them per pair.
A note that matches no keyword and has no override stops the run (exit 2), so no
note is dropped. Later --records files replace earlier ones for the same grader and
unit, so pass a re-grade file after its first pass. With -o, lines append to the file
and a line whose (ruling, criterion) is already there is skipped. The summary, with
the "grader missed" count per grader, goes to stderr as JSON.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# ponytail: keyword map, not a classifier. --criteria fixes a miss; widen the map when a note class recurs.
KEYWORDS = {
    "visual": r"\b(image|picture|mascot|monkey|icons?|chairs?|diagram|funnel|arrow|tick|colou?r\w*|red|visual|"
              r"visible|rungs?|group\w*|columns?|metaphor)\b",
    "economy": r"\b(text heavy|text-heavy|speaker notes|streamline|reduce|too many|fewer)\b",
    "clear": r"\b(names?|title|subtitle|question|word\w*|sounds|violent|means?|understand|plainly|clear|label)\b",
}
CAP = 3


def criteria_for(note):
    return [c for c, pat in KEYWORDS.items() if re.search(pat, note, re.I)]


def excerpt(unit, n=300):
    def cut(s):
        s = " ".join(s.split())
        return s if len(s) <= n else s[:n] + " ..."
    text, notes = cut(unit.get("text", "")), cut(unit.get("notes", ""))
    return f"{text} | Notes: {notes}" if notes else text


def load_records(paths):
    out = {}
    for p in paths:
        for line in Path(p).read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                out[(r["grader"], r["unit"])] = r
    return out


def build(answers, key, units_doc, records, label, overrides=None, rubric_version=None):
    """Return (ruling lines, summary). Raises ValueError on a note with no criterion."""
    overrides = overrides or {}
    units = {u["id"]: u for u in units_doc["units"]}
    graders = sorted({g for g, _ in records})
    lines, unclassified = [], []
    for pair, note in sorted(answers.get("notes", {}).items()):
        if not note.strip():
            continue
        k = key["pairs"][pair]
        crits = overrides.get(pair) or criteria_for(note)
        if not crits:
            unclassified.append(pair)
            continue
        chosen = answers.get("answers", {}).get(pair)
        version = "after" if chosen == k["after"] else "before" if chosen in ("left", "right") else "none"
        for c in crits:
            scores = {}
            for g in graders:
                entry = (records.get((g, k["unit"])) or {}).get("scores", {}).get(c)
                scores[g] = entry.get("score") if isinstance(entry, dict) else None
            lines.append({"criterion": c, "excerpt": excerpt(units.get(k["unit"], {})), "score": CAP,
                          "reason": note, "ruling": f"{label}-{pair}", "unit": k["unit"], "version": version,
                          "note": note, "graders": scores,
                          "missed": [g for g, s in scores.items() if isinstance(s, int) and s >= 4],
                          "source": "preference-note", "rubric_version": rubric_version})
    if unclassified:
        raise ValueError(f"no criterion found for {', '.join(unclassified)}: pass --criteria")
    summary = {"lines": len(lines), "graders": {}}
    for g in graders:
        scored = [ln for ln in lines if isinstance(ln["graders"][g], int)]
        summary["graders"][g] = {"scored": len(scored), "no_record": len(lines) - len(scored),
                                 "missed": sum(g in ln["missed"] for ln in lines)}
    return lines, summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("answers")
    ap.add_argument("key")
    ap.add_argument("--units", required=True)
    ap.add_argument("--records", nargs="+", default=[])
    ap.add_argument("--label", default="prefer")
    ap.add_argument("--criteria", default="{}", help="JSON: pair id -> list of criterion ids")
    ap.add_argument("-o", "--out")
    a = ap.parse_args(argv)
    answers, key = json.loads(Path(a.answers).read_text()), json.loads(Path(a.key).read_text())
    if answers.get("key_id") != key.get("key_id"):
        print("prefer_rulings.py: the answers and the key have different key_id", file=sys.stderr)
        return 2
    version = json.loads((HERE / "rubric.json").read_text())["rubric_version"]
    try:
        lines, summary = build(answers, key, json.loads(Path(a.units).read_text()), load_records(a.records),
                               a.label, json.loads(a.criteria), version)
    except ValueError as e:
        print(f"prefer_rulings.py: {e}", file=sys.stderr)
        return 2
    if a.out:
        out = Path(a.out)
        have = set()
        if out.exists():
            for ln in out.read_text().splitlines():
                if ln.strip():
                    r = json.loads(ln)
                    have.add((r.get("ruling"), r.get("criterion")))
        new = [ln for ln in lines if (ln["ruling"], ln["criterion"]) not in have]
        summary["appended"], summary["skipped_existing"] = len(new), len(lines) - len(new)
        sep = "\n" if out.exists() and out.stat().st_size and not out.read_text().endswith("\n") else ""
        with open(out, "a") as f:
            f.write(sep + "".join(json.dumps(ln, ensure_ascii=False) + "\n" for ln in new))
    else:
        print("".join(json.dumps(ln, ensure_ascii=False) + "\n" for ln in lines), end="")
    print(json.dumps(summary, indent=1), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
