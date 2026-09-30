#!/usr/bin/env python3
"""Aggregate one round's grader records into unit scores, the bar and the stop decision.

    score_round.py <run dir> <n> [--graders claude|both]   writes <run>/rounds/r<n>/score.json and prints it
    score_round.py audit <run dir> <n>                     prints the units Codex grades this round
    score_round.py --selftest

Reads, from <run>/rounds/r<n>/: units.json (the run's fixed unit list),
grading/<grader>.jsonl, grading/<grader>.regrade.jsonl (optional), mechanical.json
(decks) and arc.json (decks). Reads run.json for the calibration baseline gap,
earlier rounds' score.json for the median history, and earlier rounds'
rewrites.json for the set of rewritten units. The first round scored saves its
unit ids as <run>/units.fixed.json; a later round with other ids is refused.
A unit a grader did not score stays out of the median; `coverage` says how
many units each grader scored.

Claude sets the bar; Codex audits (the default, `--graders claude`). A unit's
score is Claude's mean over its applicable criteria, the round's median is the
median unit score, and the bar is: every mechanical gate passes, Claude's arc
pass scores at least arc_min on every arc criterion, and every applicable
criterion on every unit scores at least judged_min from Claude. Each round Codex
grades only the audit set: the units rewritten in the round before, plus the
same number of untouched units as a baseline, picked by a hash of the round and
the unit id (`audit`). The self-preference check compares the Claude-minus-Codex
gap on the rewritten units with the gap on the baseline units (the calibration
baseline gap when there are none); an excess of 0.5 or more, or a rewritten unit
Codex did not grade, blocks "finished": the bar reads as blocked, not met.

`--graders both` is for calibration rounds: both graders grade every unit, a
unit's score is the lower of the two means, the bar needs both graders, the
split re-grade list applies, and the self-preference gap covers every unit
rewritten so far. Per grader, never pooled. Stop on the first of: the bar is
met (or met but blocked); max_rounds done; plateau_rounds rounds in a row where
the median did not rise. Exit 0 always; the decision is in the JSON.
"""
import hashlib
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRADERS = ("codex", "claude")
SELF_PREF = 0.5


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 4) if xs else None


def _numeric(rec):
    return {c: s["score"] for c, s in rec["scores"].items() if isinstance(s.get("score"), int)}


def audit_set(ids, rewritten, round_n):
    """Codex's units for a round: the rewritten units plus as many untouched units, picked by a hash
    of the round and the unit id, so the pick is repeatable and moves from round to round."""
    rew = [u for u in ids if u in set(rewritten)]
    untouched = sorted((u for u in ids if u not in set(rewritten)),
                       key=lambda u: hashlib.sha256(f"r{round_n}:{u}".encode()).hexdigest())
    return {"rewritten": rew, "baseline": sorted(untouched[:len(rew)], key=ids.index)}


def device_variety(ids, records):
    """From one grader's device types: consecutive units that share a type, and the most common type's
    share of the units with a device. A cross-check on the arc pass's variety score, not a gate."""
    types = {}
    for r in records:
        t = (r["scores"].get("device") or {}).get("type")
        if t and t != "none":
            types[r["unit"]] = t
    seq = [u for u in ids if u in types]
    repeats = [[a, b] for a, b in zip(ids, ids[1:]) if a in types and types.get(b) == types[a]]
    counts = {}
    for u in seq:
        counts[types[u]] = counts.get(types[u], 0) + 1
    top = max(counts, key=counts.get) if counts else None
    return {"types": {u: types[u] for u in seq}, "consecutive_repeats": repeats,
            "dominant": top, "dominant_share": round(counts[top] / len(seq), 4) if top else None,
            "dominates": bool(top) and counts[top] * 2 > len(seq)}


def score(units_doc, records, regrades=None, mechanical=None, arc=None, round_n=1, history=(),
          rewritten=(), baseline_gap=None, rubric=None, graders="claude"):
    if graders not in ("claude", "both"):
        raise SystemExit(f"score_round.py: --graders is claude or both, not {graders}")
    rubric = rubric or json.loads((HERE / "rubric.json").read_text())
    bars = rubric["bars"]
    ids = [u["id"] for u in units_doc["units"] if not u.get("hidden")]
    kind = units_doc["kind"]

    # per grader, per unit: the regrade record replaces the first one (the second score stands)
    by = {g: {} for g in GRADERS}
    regraded = set()
    for g in GRADERS:
        for r in records.get(g, []):
            by[g][r["unit"]] = _numeric(r)
        for r in (regrades or {}).get(g, []):
            by[g][r["unit"]] = _numeric(r)
            regraded.add((r["unit"], g))
    unknown = sorted({u for g in GRADERS for u in by[g]} - set(ids))
    if unknown:
        # the unit list is fixed for the run: a record for any other unit means the list moved
        raise SystemExit(f"score_round.py: records for units not in the fixed unit list: {unknown}")
    present = [g for g in GRADERS if by[g]]
    # the graders whose scores set the bar and the median: Claude alone, or both in a calibration round
    judges = [g for g in present if graders == "both" or g == "claude"]

    per_grader = {}
    for g in present:
        crits = sorted({c for s in by[g].values() for c in s})
        per_grader[g] = {
            "units_scored": len(by[g]),
            "mean": _mean([_mean(s.values()) for s in by[g].values()]),
            "criteria": {c: _mean([s.get(c) for s in by[g].values()]) for c in crits}}

    units, low, regrade = {}, [], []
    for u in ids:
        means = {g: _mean(by[g][u].values()) for g in present if u in by[g]}
        unit_score = min((means[g] for g in judges if means.get(g) is not None), default=None)
        failing = sorted({f"{g}:{c}" for g in judges for c, v in by[g].get(u, {}).items()
                          if v < bars["judged_min"]})
        missing = [g for g in (GRADERS if graders == "both" else ("claude",)) if u not in by[g]]
        units[u] = {"score": unit_score, "means": means, "failing": failing, "missing": missing}
        # the split re-grade compares two full gradings, so it runs only in a calibration round
        if graders == "both" and len(present) == 2 and u in by["codex"] and u in by["claude"]:
            a, b = by["codex"][u], by["claude"][u]
            for lower, other, g in ((a, b, "codex"), (b, a, "claude")):
                crits = [c for c in a if c in b and lower[c] == 3 and other[c] >= 4]
                if crits and (u, g) not in regraded:
                    regrade.append({"unit": u, "grader": g, "criteria": crits})
    # a unit a present grader did not score (its batch failed) stays out of the median: falling back
    # to the other grader's mean alone would skew the median towards that grader
    scored = [v["score"] for v in units.values()
              if v["score"] is not None and all(g not in v["missing"] for g in judges)]
    median = round(statistics.median(scored), 4) if scored else None
    coverage = {g: {"scored": sum(u in by[g] for u in ids), "of": len(ids)} for g in GRADERS}

    mech_ok = True if mechanical is None and kind != "deck" else bool(mechanical and mechanical.get("pass"))
    arc_fail = []
    if kind == "deck":
        for g in judges:
            sc = ((arc or {}).get(g) or {}).get("scores", {})
            arc_fail += [f"{g}:{c}" for c in bars["arc_criteria"]
                         if not isinstance((sc.get(c) or {}).get("score"), int) or sc[c]["score"] < bars["arc_min"]]
    units_ok = all(not v["failing"] and all(g not in v["missing"] for g in judges) and v["score"] is not None
                   for v in units.values())
    passes = mech_ok and not arc_fail and units_ok and "claude" in judges

    # self-preference: the Claude-minus-Codex gap on rewritten units against untouched units
    def gap(sel):
        return _mean([units[u]["means"].get("claude") - units[u]["means"]["codex"]
                      for u in sel if {"codex", "claude"} <= set(units[u]["means"])])
    audit = audit_set(ids, rewritten, round_n)
    rew = audit["rewritten"]
    # Codex graded only the audit set in a Claude-bar round, so the untouched gap is the baseline's
    g_rew, g_unt = gap(rew), gap([u for u in ids if u not in set(rewritten)])
    unaudited = [u for u in rew if u not in by["codex"]]
    ref = g_unt if g_unt is not None else baseline_gap
    excess = None if g_rew is None or ref is None else round(g_rew - ref, 4)
    flagged = excess is not None and excess >= SELF_PREF
    self_pref = {"rewritten": rew, "gap_rewritten": g_rew, "gap_untouched": g_unt,
                 "baseline_gap": baseline_gap,
                 "excess_vs_untouched": None if g_rew is None or g_unt is None else round(g_rew - g_unt, 4),
                 "excess_vs_baseline": None if g_rew is None or baseline_gap is None
                 else round(g_rew - baseline_gap, 4),
                 "compared_with": "untouched" if g_unt is not None else "baseline",
                 "baseline_units": audit["baseline"], "unaudited": unaudited,
                 "threshold": SELF_PREF, "flag": flagged, "at_threshold": excess == SELF_PREF}

    if not passes:
        status = "not met"
    elif graders == "both" and "codex" not in judges:
        status = "met by Claude only"
    elif flagged:
        status = "blocked: possible self-preference"
    elif unaudited:
        status = "blocked: rewrites not audited by Codex"
    else:
        status = "met"

    medians = list(history) + [median]
    k = bars["plateau_rounds"]
    tail = medians[-(k + 1):]
    plateau = len(tail) == k + 1 and None not in tail and all(b <= a for a, b in zip(tail, tail[1:]))
    if status == "met":
        reason = "bar_met"
    elif status != "not met":
        # nothing left to rewrite against the bar, but the run is not finished: the brief shows both
        # graders' scores for the rewritten units and lists the rewrites as not yet passed
        reason = "bar_met_blocked"
    elif round_n >= bars["max_rounds"]:
        reason = "max_rounds"
    elif plateau:
        reason = "plateau"
    else:
        reason = None

    # rewrite list: mechanical failures first, then the lowest unit scores
    mech_ids = []
    for gate in ((mechanical or {}).get("gates") or {}).values():
        for x in gate.get("hits", []) + gate.get("unpaid", []) + gate.get("missing", []):
            mech_ids.append(x["id"] if isinstance(x, dict) else x)
    mech_ids += [b["id"] for b in ((mechanical or {}).get("floors") or {}).get("breaches", [])]
    mech_ids = [u for u in dict.fromkeys(mech_ids) if u in units]
    below = sorted((u for u, v in units.items() if v["failing"] and u not in mech_ids),
                   key=lambda u: (units[u]["score"] if units[u]["score"] is not None else 99, ids.index(u)))
    rewrite = (mech_ids + below)[:bars["max_rewrites_per_round"]]

    return {"round": round_n, "kind": kind, "graders": present, "mode": graders, "bar_graders": judges,
            "audit": audit, "per_grader": per_grader,
            "units": units, "median": median, "units_scored": len(scored), "units_total": len(ids),
            "coverage": coverage, "median_over": len(scored),
            "history": list(history),
            "bar": {"met": status == "met", "status": status, "mechanical_pass": mech_ok,
                    "arc_failing": arc_fail, "units_below": [u for u, v in units.items() if v["failing"]]},
            "regrade": regrade, "self_preference": self_pref,
            "device_variety": {g: device_variety(ids, records.get(g, [])) for g in present},
            "stop": {"stop": reason is not None, "reason": reason}, "rewrite": rewrite}


def _jsonl(p):
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def _json(p):
    return json.loads(p.read_text()) if p.exists() else None


def _rewritten(run, n, graders):
    """Units whose rewrite this round is the first to grade (the round before), or, in a calibration
    round, every unit rewritten so far."""
    out = []
    for k in range(1 if graders == "both" else max(n - 1, 1), n):
        rw = _json(run / "rounds" / f"r{k}" / "rewrites.json") or {}
        out += [r["unit"] for r in rw.get("rewrites", [])]
    return out


def audit_for(run, n):
    run = Path(run)
    ids = [u["id"] for u in json.loads((run / "rounds" / f"r{n}" / "units.json").read_text())["units"]
           if not u.get("hidden")]
    a = audit_set(ids, _rewritten(run, n, "claude"), n)
    return {**a, "select": ",".join(a["rewritten"] + a["baseline"])}


def from_run(run, n, graders="claude"):
    run = Path(run)
    rd = run / "rounds" / f"r{n}"
    history = []
    for k in range(1, n):
        prev = _json(run / "rounds" / f"r{k}" / "score.json")
        # one entry per round, so a round with no score.json cannot shift the plateau window
        history.append(prev["median"] if prev else None)
    rewritten = _rewritten(run, n, graders)
    units_doc = json.loads((rd / "units.json").read_text())
    ids = [u["id"] for u in units_doc["units"] if not u.get("hidden")]
    fixed = run / "units.fixed.json"
    if not fixed.exists():
        fixed.write_text(json.dumps({"round": n, "units": ids}, indent=1) + "\n")
    elif json.loads(fixed.read_text())["units"] != ids:
        # the unit list is fixed for the run: a round whose extraction moved it is refused
        raise SystemExit(f"score_round.py: round {n} units differ from the fixed list in {fixed}")
    arc = _json(rd / "arc.json") or {}
    rubric = _json(run / "rubric.json") or json.loads((HERE / "rubric.json").read_text())
    return score(units_doc,
                 {g: _jsonl(rd / "grading" / f"{g}.jsonl") for g in GRADERS},
                 regrades={g: _jsonl(rd / "grading" / f"{g}.regrade.jsonl") for g in GRADERS},
                 mechanical=_json(rd / "mechanical.json"), arc=arc.get("graders"), round_n=n,
                 history=history, rewritten=rewritten,
                 baseline_gap=(_json(run / "run.json") or {}).get("baseline_gap"), rubric=rubric, graders=graders)


def selftest():
    rubric = json.loads((HERE / "rubric.json").read_text())
    crits = [c["id"] for c in rubric["criteria"]]
    units = {"kind": "deck", "units": [{"id": u} for u in "abc"]}
    arc = {g: {"scores": {c: {"score": 4} for c in rubric["bars"]["arc_criteria"]}} for g in GRADERS}

    def recs(g, vals):
        return [{"unit": u, "scores": {c: {"score": v} for c in crits}} for u, v in vals.items()]

    def run(cx, cl, **kw):
        kw.setdefault("graders", "both")
        return score(units, {"codex": recs("codex", cx), "claude": recs("claude", cl)},
                     mechanical={"pass": True}, arc=arc, rubric=rubric, **kw)
    # the bar, both graders (a calibration round)
    assert run(dict(a=4, b=4, c=4), dict(a=4, b=5, c=4))["bar"]["met"]
    assert not run(dict(a=4, b=2, c=4), dict(a=4, b=5, c=4))["bar"]["met"]
    assert run({}, dict(a=5, b=5, c=5))["bar"]["status"] == "met by Claude only"
    # the bar, Claude sets it: a low Codex score does not hold it back, and round 1 needs no audit
    assert run({}, dict(a=4, b=4, c=4), graders="claude")["bar"]["met"]
    assert run(dict(a=2), dict(a=4, b=4, c=4), graders="claude")["bar"]["met"]
    # stop rule: two rounds in a row with no rise in the median; one flat round is noise
    low = (dict(a=3, b=3, c=3), dict(a=3, b=3, c=3))
    assert run(*low, round_n=2, history=[3.0])["stop"]["reason"] is None
    assert run(*low, round_n=3, history=[3.0, 3.0])["stop"]["reason"] == "plateau"
    # stop rule: max rounds
    assert run(*low, round_n=5, history=[1.0, 2.0, 2.5, 2.9])["stop"]["reason"] == "max_rounds"
    # self-preference: Claude rates rewritten units 1 point over Codex, untouched units level
    sp = run(dict(a=4, b=4, c=4), dict(a=5, b=4, c=4), rewritten=["a"], baseline_gap=0.2)
    assert sp["self_preference"]["flag"] and sp["self_preference"]["excess_vs_untouched"] == 1.0, sp
    assert not sp["bar"]["met"] and sp["bar"]["status"] == "blocked: possible self-preference"
    ok = run(dict(a=4, b=4, c=4), dict(a=4, b=4, c=4), rewritten=["a"])
    assert not ok["self_preference"]["flag"] and ok["bar"]["met"]
    # the audit: a rewritten unit Codex never graded blocks "finished"
    assert run({}, dict(a=4, b=4, c=4), graders="claude", rewritten=["a"])["bar"]["status"] == \
        "blocked: rewrites not audited by Codex"
    print("selftest ok: bar (Claude alone and both), both stop rules, the audit and the self-preference flag")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--selftest"]:
        return selftest()
    if argv[:1] == ["audit"] and len(argv) == 3:
        print(json.dumps(audit_for(argv[1], int(argv[2])), indent=1))
        return 0
    graders = "claude"
    if "--graders" in argv:
        i = argv.index("--graders")
        graders = argv[i + 1] if i + 1 < len(argv) else ""
        argv = argv[:i] + argv[i + 2:]
    if len(argv) != 2:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    out = from_run(argv[0], int(argv[1]), graders)
    text = json.dumps(out, indent=1)
    (Path(argv[0]) / "rounds" / f"r{argv[1]}" / "score.json").write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
