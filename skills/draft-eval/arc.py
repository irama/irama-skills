#!/usr/bin/env python3
"""The arc pass: one whole-deck grading call per round per grader.

    arc.py build <units.json> <outdir> --shots shots.json [--run-sheet run-sheet.md]
    arc.py validate <raw> --grader codex|claude --round N [--model <full id>] -o arc.json

build writes <outdir>/arc/ (units.md, contact.png from render.mjs, run-sheet.md)
and the rendered prompt beside it as <outdir>/arc.prompt.md, then prints
{dir, prompt, pngs}. The grader runs inside <outdir>/arc/ and can read nothing else.

validate strips a code fence, checks the reply against arc-schema.json, and
merges it into arc.json as graders.<grader>, stamped with model, rubric_version,
round, prompt_sha256 (of arc-prompt.md) and schema_sha256. Exit 1 on a bad reply.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from validate import schema_errors, sha256, strip_fence  # noqa: E402


def render_criteria(rubric):
    out = []
    for c in rubric["arc"]["criteria"]:
        out.append(f"### `{c['id']}`: {c['name']}\n\n{c['question']}\n")
        out += [f"- {k}: {v}" for k, v in sorted(c.get("anchors", {}).items())]
        out.append("")
    return "\n".join(out)


def build(units_doc, outdir, shots_path, run_sheet=None, rubric=None):
    rubric = rubric or json.loads((HERE / "rubric.json").read_text())
    shots_path = Path(shots_path)
    shots = json.loads(shots_path.read_text())
    if not shots.get("contact"):
        raise SystemExit("arc.py: shots.json has no contact sheet; re-run render.mjs")
    adir = Path(outdir).resolve() / "arc"
    if adir.exists():
        shutil.rmtree(adir)
    adir.mkdir(parents=True)
    graded = [u for u in units_doc["units"] if not u.get("hidden")]
    lines = []
    for n, u in enumerate(graded, 1):
        # json.dumps keeps draft markup (ids, roles) on one quoted line, as data
        lines.append(f"## Slide {n}\n\nid and role: {json.dumps([u['id'], u.get('role', 'content')])}\n")
        lines.append("Text:\n\n" + "\n".join("    " + x for x in (u.get("text") or "").splitlines() or [""]))
        if u.get("notes"):
            lines.append("\nNotes:\n\n" + "\n".join("    " + x for x in u["notes"].splitlines()))
        lines.append("")
    (adir / "units.md").write_text("\n".join(lines))
    shutil.copyfile(shots_path.parent / shots["contact"], adir / "contact.png")
    if run_sheet:
        shutil.copyfile(run_sheet, adir / "run-sheet.md")
    prompt = adir.parent / "arc.prompt.md"
    text = (HERE / "arc-prompt.md").read_text()
    for k, v in {"RUBRIC_VERSION": rubric["rubric_version"], "CRITERIA": render_criteria(rubric)}.items():
        text = text.replace("{{" + k + "}}", v)
    prompt.write_text(text)
    return {"dir": str(adir), "prompt": str(prompt), "pngs": [str(adir / "contact.png")]}


def check(raw):
    try:
        doc = json.loads(strip_fence(raw))
    except ValueError as e:
        return None, [f"not JSON: {e}"]
    errs = schema_errors(doc, json.loads((HERE / "arc-schema.json").read_text()))
    return (None, errs) if errs else (doc, [])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("units")
    b.add_argument("outdir")
    b.add_argument("--shots", required=True)
    b.add_argument("--run-sheet")
    v = sub.add_parser("validate")
    v.add_argument("raw")
    v.add_argument("--grader", choices=["codex", "claude"], required=True)
    v.add_argument("--round", type=int, required=True)
    v.add_argument("--model")
    v.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        print(json.dumps(build(json.loads(Path(a.units).read_text()), a.outdir, a.shots, a.run_sheet), indent=1))
        return 0
    doc, errs = check(Path(a.raw).read_text())
    if errs:
        print("\n".join(errs), file=sys.stderr)
        return 1
    out = Path(a.out)
    arc = json.loads(out.read_text()) if out.exists() else {"graders": {}}
    rubric = json.loads((HERE / "rubric.json").read_text())
    arc["graders"][a.grader] = {"model": a.model or doc["model"], "rubric_version": rubric["rubric_version"],
                                "round": a.round, "prompt_sha256": sha256("arc-prompt.md"),
                                "schema_sha256": sha256("arc-schema.json"), "scores": doc["scores"]}
    out.write_text(json.dumps(arc, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
