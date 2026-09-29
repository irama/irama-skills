#!/usr/bin/env python3
"""Build grading packets: one directory per batch of up to 8 units.

    packet.py <units.json> <outdir> [--shots shots.json]

Each batch directory holds, per unit, a folder `<nn>-<id>/` with:
  slide.png  the unit's screenshot (decks)
  text.txt   the unit's visible text
  notes.txt  the unit's notes, when it has any
  prev.png   the previous unit's screenshot (decks, not on the first unit)
  prev.txt   the previous unit's text (not on the first unit)
Articles also get `references.md` at the batch root. Nothing else goes in the
directory: the rendered prompt is written beside it as `batch-NN.prompt.md`,
so a grader running inside the directory can read the packets and nothing else.

Hidden units are skipped, and the previous unit of a unit is the previous
graded unit. Prints the batch list as JSON: dir, prompt, units, pngs.
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BATCH = 8


def template_sha256():
    return hashlib.sha256((HERE / "grader-prompt.md").read_bytes()).hexdigest()


def render_criteria(rubric, kind):
    out = []
    for c in rubric["criteria"]:
        if kind not in c["applies_to"]:
            continue
        na = c["na_allowed"]
        allowed = [f"role {r}" for r in na["roles"]]
        allowed += [rubric["na_conditions"][k] for k in na["conditions"]]
        out.append(f"### `{c['id']}`: {c['name']}\n\n{c['question']}\n")
        out += [f"- {k}: {c['anchors'][k]}" for k in ("1", "3", "5")]
        out.append(f"- N/A allowed: {'; or '.join(allowed) if allowed else 'never'}\n")
    return "\n".join(out)


def render_prompt(rubric, kind, rows):
    text = (HERE / "grader-prompt.md").read_text()
    # Unit ids and roles come from the draft's own markup, so they are untrusted: they go in
    # as JSON inside a fenced data block, never spliced into the prompt's own sentences.
    # json.dumps escapes newlines, so no value can close the fence or start a new line.
    data = [{"folder": r["folder"], "unit": r["id"], "role": r.get("role", "content"),
             "first_unit_of_draft": r["first"], "files": r.get("files", [])} for r in rows]
    units = "```json\n" + json.dumps(data, indent=1) + "\n```"
    for key, val in {"KIND": kind, "RUBRIC_VERSION": rubric["rubric_version"],
                     "CRITERIA": render_criteria(rubric, kind), "UNITS": units}.items():
        text = text.replace("{{" + key + "}}", val)
    return text


def build(units_doc, outdir, shots_path=None, rubric=None, select=None):
    """Build the batches. `select` (a set of unit ids) packs only those units, each still with
    its real previous unit from the draft; calibration uses it."""
    rubric = rubric or json.loads((HERE / "rubric.json").read_text())
    kind = units_doc["kind"]
    shots = {}
    if shots_path:
        shots_path = Path(shots_path)
        for s in json.loads(shots_path.read_text())["shots"]:
            shots[s["id"]] = shots_path.parent / s["file"]
    graded = [u for u in units_doc["units"] if not u.get("hidden")]
    picks = [i for i, u in enumerate(graded) if select is None or u["id"] in select]
    if kind == "deck":
        # spec section 4: a deck packet holds the unit's screenshot; without it `visual` is a guess
        need = [graded[j] for i in picks for j in (i - 1, i) if j >= 0]
        missing = sorted({str(u["id"]) for u in need if u["id"] not in shots})
        if missing:
            raise SystemExit(f"packet.py: no screenshot for deck unit(s): {', '.join(missing)}")
    outdir = Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    batches = []
    for b in range(0, len(picks), BATCH):
        bdir = outdir / f"batch-{b // BATCH + 1:02d}"
        if bdir.exists():
            shutil.rmtree(bdir)
        bdir.mkdir()
        rows, pngs = [], []
        for n, i in enumerate(picks[b:b + BATCH], b):
            u, prev = graded[i], graded[i - 1] if i else None
            # the id is draft markup: keep it out of the path (no "/", no "..")
            folder = f"{n + 1:02d}-" + re.sub(r"[^A-Za-z0-9_-]", "_", str(u["id"]))
            udir = bdir / folder
            udir.mkdir()
            (udir / "text.txt").write_text(u.get("text", ""))
            if u.get("notes"):
                (udir / "notes.txt").write_text(u["notes"])
            if prev:
                (udir / "prev.txt").write_text(prev.get("text", ""))
            for name, src in (("slide.png", u), ("prev.png", prev)):
                if src and src["id"] in shots:
                    shutil.copyfile(shots[src["id"]], udir / name)
                    pngs.append(str(udir / name))
            rows.append({"folder": folder, "id": u["id"], "role": u.get("role", "content"),
                         "first": i == 0, "files": sorted(p.name for p in udir.iterdir())})
        if kind == "article" and units_doc.get("references"):
            (bdir / "references.md").write_text(units_doc["references"])
        prompt = outdir / f"{bdir.name}.prompt.md"
        prompt.write_text(render_prompt(rubric, kind, rows))
        batches.append({"dir": str(bdir), "prompt": str(prompt),
                        "units": [r["id"] for r in rows], "pngs": pngs})
    return batches


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("units")
    ap.add_argument("outdir")
    ap.add_argument("--shots")
    a = ap.parse_args(argv)
    batches = build(json.loads(Path(a.units).read_text()), a.outdir, a.shots)
    json.dump({"prompt_sha256": template_sha256(), "batches": batches}, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
