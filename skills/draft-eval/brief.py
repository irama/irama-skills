#!/usr/bin/env python3
"""Fill the review brief's data placeholders from the run record.

    brief.py <run dir> -o <brief.md> [--prefer prefer-result.json] [--figures <dir>] [--after shots.json]
    brief.py --check <brief.md>

Copies review-brief.md and fills everything that is data: the run ids, the grader
table (per grader, never pooled), the gate table with each margin, the units
still under the bar with their quoted reasons, the stop reason, the
self-preference line, the preference line, the model ids and the Recommended
tag on Q1. Q1 carries "Recommended" only when the bar is met by both graders,
no self-preference flag stands, no gate the recommendation rests on passed
at a tie or failed, and (decks) a --prefer result is given. With --figures, copies each rewritten slide's before and
after screenshot into that folder (beside the brief) and embeds them. Before is
round 1; after is the last round, or --after when the run ended on a rewrite.

Prints the placeholders still open, which the orchestrator writes by hand (the
call and its price, the answers, the Q1 assumption and crux, proposals,
failures, limitations). --check exits 1 while any placeholder is open.
"""
import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OPEN = re.compile(r"\{\{[A-Z0-9_]+\}\}")


def _json(p, default=None):
    p = Path(p)
    return json.loads(p.read_text()) if p.exists() else default


def _fmt(x):
    return "none" if x is None else (f"{x:+.2f}" if isinstance(x, float) else str(x))


def gate_rows(sc, arc, prefer):
    rows = []
    mech = sc["bar"]["mechanical_pass"]
    rows.append(("Mechanical gates", "all pass", "pass" if mech else "fail", "passed" if mech else "failed"))
    for g, pg in sc["per_grader"].items():
        low_units = [u for u, v in sc["units"].items() if any(f.startswith(g + ":") for f in v["failing"])]
        rows.append((f"Every judged score, {g}", "4 or more on every unit",
                     f"{len(low_units)} of {sc['units_total']} units below" if low_units else "none below",
                     "failed" if low_units else "passed"))
    for g, ga in (arc or {}).items():
        s = ga.get("scores", {})
        if s:
            vals = ", ".join(f"{c} {v['score']}" for c, v in s.items())
            fail = any(v["score"] < 4 for v in s.values())
            rows.append((f"Arc pass, {g}", "4 or more on each", vals, "failed" if fail else "passed"))
    sp = sc["self_preference"]
    ex = sp["excess_vs_untouched"] if sp["compared_with"] == "untouched" else sp["excess_vs_baseline"]
    if ex is not None:
        res = "flagged at a tie" if sp["at_threshold"] else ("flagged" if sp["flag"] else "passed")
        rows.append(("Self-preference", f"excess under {sp['threshold']}", _fmt(ex), res))
    if prefer:
        res = "passed at a tie" if prefer["at_threshold"] else ("passed" if prefer["pass"] else "failed")
        rate = prefer["after_rate"]
        rows.append(("Blind preference test", "after wins 70% of sided pairs",
                     f"{prefer['after']} of {prefer['sided']} ({rate:.0%})" if rate is not None
                     else "no sided pairs", res))
    return rows


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    return "\n".join(out + ["| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |" for r in rows])


def fill(run, prefer=None, figures=None, after=None):
    run = Path(run)
    meta = _json(run / "run.json")
    rounds = sorted((run / "rounds").glob("r*"), key=lambda p: int(p.name[1:]))
    last = rounds[-1]
    sc = _json(last / "score.json")
    arc = (_json(last / "arc.json", {}) or {}).get("graders")
    rec = _json(last / "record.json", {})
    models = rec.get("models", {})

    grader_rows = [(g, pg["units_scored"], pg["mean"], ", ".join(f"{c} {v}" for c, v in pg["criteria"].items()))
                   for g, pg in sc["per_grader"].items()]
    gates = gate_rows(sc, arc, prefer)
    tie = any("tie" in r[3] for r in gates)
    failed = any(r[3] in ("failed", "flagged") for r in gates)
    # a deck's rewrites are recommended only after the blind preference test has passed
    needs_prefer = sc.get("kind", "deck") == "deck"
    rec_a = ("(Recommended)" if sc["bar"]["status"] == "met" and not tie and not failed
             and (prefer or not needs_prefer) else "")

    under = []
    for u in sc["bar"]["units_below"]:
        reasons = []
        for g in sc["graders"]:
            for x in (last / "grading" / f"{g}.jsonl").read_text().splitlines() if (
                    last / "grading" / f"{g}.jsonl").exists() else []:
                r = json.loads(x)
                if r["unit"] != u:
                    continue
                reasons += [f"{g} {c} {s['score']}: {s['reason']}" for c, s in r["scores"].items()
                            if isinstance(s["score"], int) and s["score"] < 4]
        under.append(f"- **{u}** (unit score {sc['units'][u]['score']}): " + " ".join(reasons))

    figs = []
    rewritten = list(dict.fromkeys(r["unit"] for rd in rounds
                                   for r in _json(rd / "rewrites.json", {}).get("rewrites", [])))
    if figures and rewritten:
        figures = Path(figures)
        figures.mkdir(parents=True, exist_ok=True)
        first = _json(rounds[0] / "shots" / "shots.json", {"shots": []})
        now_path = Path(after) if after else last / "shots" / "shots.json"
        now = _json(now_path, {"shots": []})
        for u in rewritten:
            pair = []
            # the id is draft markup: keep it out of the path and escape it in the html
            safe, esc = re.sub(r"[^A-Za-z0-9_-]", "_", str(u)), html.escape(str(u))
            for label, doc, base in (("before", first, rounds[0] / "shots"), ("after", now, now_path.parent)):
                s = next((s for s in doc["shots"] if s["id"] == u), None)
                if s:
                    shutil.copyfile(base / s["file"], figures / f"{safe}-{label}.png")
                    src = html.escape(f"{figures.name}/{safe}-{label}.png")
                    pair.append(f'<figure><img src="{src}" alt="{esc}, {label}">'
                                f"<figcaption>{esc}, {label}</figcaption></figure>")
            figs.append(":::html\n<div class=\"pair\">" + "".join(pair) + "</div>\n:::")

    sp = sc["self_preference"]
    sp_line = ("no rewritten units yet" if not sp["rewritten"] else
               f"gap on rewritten units {_fmt(sp['gap_rewritten'])}, on untouched units {_fmt(sp['gap_untouched'])}, "
               f"calibration baseline {_fmt(sp['baseline_gap'])}"
               + (", possible self-preference" if sp["flag"] else ""))
    values = {
        "TARGET": meta["target"], "RUN_ID": Path(run).name, "DATE": meta["started"][:8],
        "RUBRIC_VERSION": rec.get("rubric_version", ""), "STOP_REASON": sc["stop"]["reason"] or "none, the run was cut short",
        "VERDICT_LINE": f"Bar {sc['bar']['status']} after {len(rounds)} round(s); median unit score {sc['median']}.",
        "SELF_PREFERENCE_LINE": sp_line,
        "PREFER_LINE": ("not taken yet" if not prefer else
                        f"after won {prefer['after']} of {prefer['sided']} sided pairs, {prefer['verdict']}"),
        "GRADER_TABLE": table(("Grader", "Units scored", "Mean", "Mean per criterion"), grader_rows),
        "GATE_TABLE": table(("Gate", "Threshold", "Measured", "Result"), gates),
        "UNDER_BAR": "\n".join(under) or "None: every unit meets the bar from both graders.",
        "REWRITE_FIGURES": "\n\n".join(figs) or "No slide was rewritten.",
        "Q1_REC_A": rec_a, "PAIR_COUNT": str(len(rewritten)),
        "CODEX_MODEL": ", ".join(models.get("codex", ["not run"])),
        "CLAUDE_MODEL": ", ".join(models.get("claude", ["not run"])),
        "RUN_RECORD": f"eval-runs/{Path(run).name}/",
    }
    text = (HERE / "review-brief.md").read_text()
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run", nargs="?")
    ap.add_argument("-o", "--out")
    ap.add_argument("--prefer")
    ap.add_argument("--figures")
    ap.add_argument("--check")
    ap.add_argument("--after", help="shots.json of the final state, when the run ended on a rewrite")
    a = ap.parse_args(argv)
    if a.check:
        left = sorted(set(OPEN.findall(Path(a.check).read_text())))
        print("\n".join(left) if left else "no open placeholders")
        return 1 if left else 0
    if not (a.run and a.out):
        ap.error("<run dir> and -o are required")
    text = fill(a.run, _json(a.prefer) if a.prefer else None, a.figures, a.after)
    Path(a.out).write_text(text)
    print("\n".join(sorted(set(OPEN.findall(text)))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
