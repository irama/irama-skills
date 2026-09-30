#!/usr/bin/env python3
"""Build the calibration set: select units, build their packets, write score.html.

    calibrate.py -o <outdir> \\
        --deck <name> <units.json> <shots.json> <n> [--deck ...] \\
        --article <name> <units.json> <n> [--article ...]

Each set is one extracted draft (extract.py output). calibrate.py picks n units
from it, builds their packets with packet.build (the same packets the graders
get, each unit with its real previous unit), and writes into <outdir>:

  sources/<name>.units.json   the full extraction, for validate.py --units
  packets/<name>/batch-NN/    the packets, and batch-NN.prompt.md beside each
  units.json                  the sets, the selected ids and the batches
  packets.sha256              sha256 of every file under packets/
  score.html                  the scoring page: one row of radio buttons per
                              criterion, N/A only where the rubric allows it,
                              a comment per unit, localStorage, Download JSON

Deck picks spread across roles, layouts and position, prefer units with no
animation states, and hold non-content roles to a third of the set. Article
picks are evenly spaced. Both are deterministic.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

import packet
import validate

HERE = Path(__file__).resolve().parent
FILES = ("text.txt", "notes.txt", "context/prev.txt")


def pick_deck(units, n, avoid_roles=()):
    """avoid_roles: non-content roles an earlier deck set already covers."""
    cands = [u for u in units if not u.get("hidden")]
    chosen = []
    cap = n // 3  # ponytail: fixed share for title, divider, exercise and the like
    while len(chosen) < min(n, len(cands)):
        roles = [c.get("role") or "content" for c in chosen]
        layouts = [str(c.get("layout")) for c in chosen]
        non_content = sum(r != "content" for r in roles)

        def key(u):
            role = u.get("role") or "content"
            blocked = role != "content" and (role in roles or role in avoid_roles or non_content >= cap)
            dist = min((abs(u["ordinal"] - c["ordinal"]) for c in chosen), default=0)
            return (blocked, len(u.get("section_indices", [0])) > 1,
                    layouts.count(str(u.get("layout"))), -dist, u["ordinal"])

        chosen.append(min((u for u in cands if u not in chosen), key=key))
    return [u["id"] for u in sorted(chosen, key=lambda u: u["ordinal"])]


def pick_article(units, n):
    if len(units) <= n:
        return [u["id"] for u in units]
    return [units[round(k * (len(units) - 1) / max(n - 1, 1))]["id"] for k in range(n)]


def criteria_for(unit, first, kind, rubric):
    has_number = bool(validate.NUMBER.search(unit.get("text", "") + " " + unit.get("notes", "")))
    out = []
    for c in rubric["criteria"]:
        if kind not in c["applies_to"]:
            continue
        # the same N/A rule validate.py holds the graders to
        forced = bool(validate.na_forced(c, unit, has_number))
        out.append({"id": c["id"], "name": c["name"], "question": c["question"],
                    "anchors": c["anchors"], "forced": forced,
                    "na": forced or validate.na_allowed(c, unit, first, has_number, rubric)})
    return out


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def page_data(outdir):
    outdir = Path(outdir)
    cal = json.loads((outdir / "units.json").read_text())
    rubric = json.loads((HERE / "rubric.json").read_text())
    sets, units = [], []
    for s in cal["sets"]:
        doc = json.loads((outdir / s["units_file"]).read_text())
        graded = [u for u in doc["units"] if not u.get("hidden")]
        by_id = {u["id"]: u for u in graded}
        sets.append({"name": s["name"], "kind": s["kind"], "references": doc.get("references", "")})
        for b in s["batches"]:
            # packet.build numbers the folders in unit order, so sorted folders pair with `units`
            folders = sorted(p for p in (outdir / b["dir"]).iterdir() if p.is_dir())
            for folder, uid in zip(folders, b["units"], strict=True):
                u = by_id[uid]
                read = {f: (folder / f).read_text() if (folder / f).exists() else "" for f in FILES}
                units.append({
                    "key": f"{s['name']}/{uid}", "set": s["name"], "kind": s["kind"], "id": uid,
                    "role": u.get("role"), "ordinal": u.get("ordinal"),
                    "folder": str(folder.relative_to(outdir)),
                    "slide": (folder / "slide.png").exists(), "prev": (folder / "context" / "prev.png").exists(),
                    "text": read["text.txt"], "notes": read["notes.txt"], "prev_text": read["context/prev.txt"],
                    "criteria": criteria_for(u, uid == graded[0]["id"], s["kind"], rubric)})
    return {"rubric_version": rubric["rubric_version"],
            "packets_sha256": sha256_file(outdir / "packets.sha256"), "sets": sets, "units": units}


def write_page(outdir):
    data = json.dumps(page_data(outdir)).replace("</", "<\\/")
    (Path(outdir) / "score.html").write_text(PAGE.replace("__DATA__", data))


def build(outdir, decks, articles):
    outdir = Path(outdir)
    (outdir / "sources").mkdir(parents=True, exist_ok=True)
    if (outdir / "packets").exists():
        shutil.rmtree(outdir / "packets")
    sets, deck_roles = [], set()
    for kind, name, units_path, shots, n in ([("deck", *d) for d in decks]
                                             + [("article", a[0], a[1], None, a[2]) for a in articles]):
        doc = json.loads(Path(units_path).read_text())
        if doc["kind"] != kind:
            raise SystemExit(f"calibrate.py: {units_path} is a {doc['kind']}, not a {kind}")
        units_file = f"sources/{name}.units.json"
        (outdir / units_file).write_text(json.dumps(doc, indent=1))
        if kind == "deck":
            ids = pick_deck(doc["units"], int(n), deck_roles)
            deck_roles |= {u.get("role") for u in doc["units"] if u["id"] in ids}
        else:
            ids = pick_article(doc["units"], int(n))
        batches = packet.build(doc, outdir / "packets" / name, shots, select=set(ids))
        rel = lambda p: str(Path(p).relative_to(outdir.resolve()))  # noqa: E731
        sets.append({"name": name, "kind": kind, "source": doc.get("source"), "rev": doc.get("rev"),
                     "units_file": units_file, "selected": ids,
                     "batches": [{"dir": rel(b["dir"]), "prompt": rel(b["prompt"]), "units": b["units"],
                                  "pngs": [rel(p) for p in b["pngs"]]} for b in batches]})
    rubric = json.loads((HERE / "rubric.json").read_text())
    (outdir / "units.json").write_text(json.dumps(
        {"rubric_version": rubric["rubric_version"], "prompt_sha256": packet.template_sha256(),
         "sets": sets}, indent=1) + "\n")
    files = sorted(p for p in (outdir / "packets").rglob("*") if p.is_file())
    (outdir / "packets.sha256").write_text(
        "".join(f"{sha256_file(p)}  {p.relative_to(outdir)}\n" for p in files))
    write_page(outdir)
    return sets


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-o", "--outdir", required=True)
    ap.add_argument("--deck", nargs=4, action="append", default=[],
                    metavar=("NAME", "UNITS", "SHOTS", "N"))
    ap.add_argument("--article", nargs=3, action="append", default=[], metavar=("NAME", "UNITS", "N"))
    a = ap.parse_args(argv)
    sets = build(a.outdir, a.deck, a.article)
    for s in sets:
        print(f"{s['name']}: {len(s['selected'])} units, {len(s['batches'])} batch(es)")


PAGE = r"""<!doctype html>
<html lang="en-AU"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>draft-eval calibration scoring</title>
<style>
:root { --ink:#1d2330; --muted:#5b6475; --line:#d9dde5; --bg:#f6f7f9; --accent:#2f5bd3; }
* { box-sizing:border-box; }
body { margin:0; font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color:var(--ink); background:var(--bg); }
header { position:sticky; top:0; z-index:5; background:#fff; border-bottom:1px solid var(--line);
  padding:10px 24px; display:flex; gap:16px; align-items:center; flex-wrap:wrap; }
header h1 { font-size:17px; margin:0; }
#progress { color:var(--muted); }
button { font:inherit; padding:6px 14px; border:1px solid var(--accent); background:var(--accent); color:#fff;
  border-radius:6px; cursor:pointer; }
button.ghost { background:#fff; color:var(--accent); }
main { max-width:1200px; margin:0 auto; padding:16px 24px 80px; }
.intro { background:#fff; border:1px solid var(--line); border-radius:8px; padding:12px 16px; }
h2.set { margin:32px 0 8px; font-size:20px; }
.unit { background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px; margin:16px 0; }
.unit.done { border-color:#9bc59d; }
.unit h3 { margin:0 0 10px; font-size:16px; }
.unit h3 small { color:var(--muted); font-weight:normal; }
.cols { display:grid; grid-template-columns:1fr 2fr; gap:16px; }
.cols h4 { margin:0 0 6px; font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }
.cols img { width:100%; border:1px solid var(--line); border-radius:4px; }
.txt { white-space:pre-wrap; background:var(--bg); border-radius:4px; padding:8px 10px; font-size:14px; }
.article .txt { font-size:15px; max-height:none; }
details summary { cursor:pointer; color:var(--accent); }
table { width:100%; border-collapse:collapse; margin-top:12px; }
td { border-top:1px solid var(--line); padding:6px 8px; vertical-align:top; }
td.q { width:55%; }
td.q b { display:block; }
td.q span { color:var(--muted); font-size:13px; }
td.q ol { margin:4px 0 0; padding-left:20px; font-size:13px; color:var(--muted); }
label.r { display:inline-flex; align-items:center; gap:3px; margin-right:10px; cursor:pointer; white-space:nowrap; }
label.r input { cursor:pointer; }
.forced { color:var(--muted); font-style:normal; }
textarea { width:100%; min-height:48px; font:inherit; margin-top:10px; border:1px solid var(--line); border-radius:4px; padding:6px; }
@media (max-width:800px) { .cols { grid-template-columns:1fr; } td.q { width:auto; } }
</style></head>
<body>
<header><h1>draft-eval calibration</h1><span id="progress"></span>
<button id="next" class="ghost" type="button">Next unscored</button>
<button id="download" type="button">Download JSON</button></header>
<main>
<div class="intro"><p>Score each unit on each criterion, 1 to 5. N/A shows only where the rubric allows it.
Each unit shows the same packet the graders saw: this unit, its notes, and the unit before it.
Your answers save in this browser as you go. When every row is scored, press <b>Download JSON</b>
and file it as <code>andrew-scores.json</code> beside this page. A comment per unit is optional.</p>
<p id="stamp"></p></div>
<div id="units"></div>
</main>
<script type="application/json" id="data">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const KEY = 'draft-eval-calibration-' + D.packets_sha256.slice(0, 12);
let S = {scores: {}, comments: {}};
try { S = Object.assign(S, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (e) {}
const total = D.units.reduce((n, u) => n + u.criteria.length, 0);
const el = (tag, attrs, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) { if (k === 'text') e.textContent = v; else e.setAttribute(k, v); }
  for (const k of kids) if (k) e.append(k);
  return e;
};
const scoreOf = (u, c) => c.forced ? 'n/a' : (S.scores[u.key + '::' + c.id] ?? null);
function progress() {
  let done = 0;
  for (const u of D.units) {
    const n = u.criteria.filter(c => scoreOf(u, c) !== null).length;
    done += n;
    document.getElementById('u-' + u.key).classList.toggle('done', n === u.criteria.length);
  }
  document.getElementById('progress').textContent = done + ' of ' + total + ' scores';
}
function save() { localStorage.setItem(KEY, JSON.stringify(S)); progress(); }
document.getElementById('stamp').textContent =
  'Rubric ' + D.rubric_version + ', packets ' + D.packets_sha256.slice(0, 12) + ', ' + D.units.length + ' units.';
const root = document.getElementById('units');
let lastSet = null;
D.units.forEach((u, i) => {
  if (u.set !== lastSet) {
    lastSet = u.set;
    root.append(el('h2', {class: 'set', text: u.set}));
    const s = D.sets.find(s => s.name === u.set);
    if (s.references) root.append(el('details', {}, el('summary', {text: 'References for ' + u.set}),
                                         el('div', {class: 'txt', text: s.references})));
  }
  const card = el('section', {class: 'unit ' + u.kind, id: 'u-' + u.key});
  card.append(el('h3', {text: (i + 1) + '. ' + u.id + ' '},
    el('small', {text: '(' + u.set + (u.role ? ', ' + u.role : '') + ')'})));
  const prev = el('div', {}, el('h4', {text: 'Previous unit'}));
  if (u.prev) prev.append(el('img', {src: u.folder + '/context/prev.png', alt: 'Previous slide', loading: 'lazy'}));
  if (u.prev_text) prev.append(el('details', {}, el('summary', {text: 'Previous text'}), el('div', {class: 'txt', text: u.prev_text})));
  if (!u.prev && !u.prev_text) prev.append(el('p', {text: 'None: this is the first unit of the draft.'}));
  const cur = el('div', {}, el('h4', {text: 'This unit'}));
  if (u.slide) cur.append(el('img', {src: u.folder + '/slide.png', alt: 'This slide', loading: 'lazy'}));
  cur.append(el('div', {class: 'txt', text: u.text}));
  if (u.notes) cur.append(el('details', {open: ''}, el('summary', {text: 'Notes'}), el('div', {class: 'txt', text: u.notes})));
  card.append(el('div', {class: 'cols'}, prev, cur));
  const table = el('table');
  for (const c of u.criteria) {
    const name = u.key + '::' + c.id;
    const anchors = el('ol');
    for (const k of ['1', '3', '5']) anchors.append(el('li', {value: k, text: c.anchors[k]}));
    const q = el('td', {class: 'q'}, el('b', {text: c.name}), el('span', {text: c.question}),
                 el('details', {}, el('summary', {text: 'Anchors'}), anchors));
    const opts = el('td');
    if (c.forced) opts.append(el('span', {class: 'forced', text: 'N/A: the unit has no number, or is marked planted'}));
    else for (const v of [1, 2, 3, 4, 5].concat(c.na ? ['n/a'] : [])) {
      const input = el('input', {type: 'radio', name: name, value: String(v)});
      if (S.scores[name] === v) input.checked = true;
      input.addEventListener('change', () => { S.scores[name] = v; save(); });
      opts.append(el('label', {class: 'r'}, input, v === 'n/a' ? 'N/A' : String(v)));
    }
    table.append(el('tr', {}, q, opts));
  }
  card.append(table);
  const ta = el('textarea', {placeholder: 'Optional comment on this unit'});
  ta.value = S.comments[u.key] || '';
  ta.addEventListener('input', () => { S.comments[u.key] = ta.value; save(); });
  card.append(ta);
  root.append(card);
});
progress();
document.getElementById('next').addEventListener('click', () => {
  const u = D.units.find(u => u.criteria.some(c => scoreOf(u, c) === null));
  if (u) document.getElementById('u-' + u.key).scrollIntoView({behavior: 'smooth'});
});
document.getElementById('download').addEventListener('click', () => {
  const out = {kind: 'draft-eval-calibration-scores', scorer: 'andrew', rubric_version: D.rubric_version,
    packets_sha256: D.packets_sha256, saved_at: new Date().toISOString(), entries: [], comments: []};
  for (const u of D.units) {
    for (const c of u.criteria) out.entries.push({set: u.set, unit: u.id, criterion: c.id, score: scoreOf(u, c)});
    if ((S.comments[u.key] || '').trim()) out.comments.push({set: u.set, unit: u.id, comment: S.comments[u.key].trim()});
  }
  const a = el('a', {href: URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], {type: 'application/json'})),
                     download: 'andrew-scores.json'});
  document.body.append(a); a.click(); a.remove();
});
</script>
</body></html>
"""

if __name__ == "__main__":
    main()
