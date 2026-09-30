#!/usr/bin/env python3
"""The blind preference test: before and after pairs of every rewritten slide.

    prefer.py <before shots.json> <after shots.json> --units <id,id,...> -o <dir> [--seed N]
    prefer.py --score <answers.json> <key.json>

Build writes <dir>/prefer.html and <dir>/prefer-key.json. The page shows each
pair side by side, in shuffled order, with the before and after sides shuffled
and unlabelled. The reader picks the left slide, the right slide or "no
difference"; answers save in the browser, and Download JSON writes
prefer-answers.json. Images are embedded, so the page is one file. The key
(which side is after) lives only in prefer-key.json, never in the page.

--score applies the 70% rule: after must win at least 70% of the pairs where
the reader chose a side. Prints the tally as JSON; exit 0 on pass, 1 on fail.
A rate of exactly 70% passes and is reported as at_threshold (a tie with the gate).
"""
import argparse
import base64
import hashlib
import json
import os
import random
import sys
from pathlib import Path

RULE = 0.7


def build(before_path, after_path, ids, outdir, seed=None):
    before_path, after_path = Path(before_path), Path(after_path)
    before = {s["id"]: before_path.parent / s["file"] for s in json.loads(before_path.read_text())["shots"]}
    after = {s["id"]: after_path.parent / s["file"] for s in json.loads(after_path.read_text())["shots"]}
    missing = [i for i in ids if i not in before or i not in after]
    if missing:
        raise SystemExit(f"prefer.py: no before or after screenshot for: {', '.join(missing)}")
    seed = seed if seed is not None else int.from_bytes(os.urandom(4), "big")
    rng = random.Random(seed)
    order = list(ids)
    rng.shuffle(order)
    pairs, key = [], {}
    for n, uid in enumerate(order, 1):
        pid = f"p{n:02d}"
        after_side = rng.choice(["left", "right"])
        imgs = {after_side: after[uid], ("right" if after_side == "left" else "left"): before[uid]}
        pairs.append({"pair": pid, **{side: "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
                                      for side, p in imgs.items()}})
        key[pid] = {"unit": uid, "after": after_side}
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    key_id = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:12]
    (outdir / "prefer-key.json").write_text(json.dumps({"key_id": key_id, "seed": seed, "pairs": key}, indent=1) + "\n")
    data = json.dumps({"key_id": key_id, "pairs": pairs}).replace("</", "<\\/")
    (outdir / "prefer.html").write_text(PAGE.replace("__DATA__", data))
    return outdir / "prefer.html"


def score(answers, key):
    if answers.get("key_id") != key["key_id"]:
        raise SystemExit("prefer.py: the answers are for a different page (key_id differs)")
    tally = {"after": 0, "before": 0, "none": 0, "unanswered": 0}
    for pid, k in key["pairs"].items():
        choice = answers.get("answers", {}).get(pid)
        if choice == "none":
            tally["none"] += 1
        elif choice in ("left", "right"):
            tally["after" if choice == k["after"] else "before"] += 1
        else:
            tally["unanswered"] += 1
    sided = tally["after"] + tally["before"]
    rate = round(tally["after"] / sided, 4) if sided else None
    return {**tally, "sided": sided, "after_rate": rate, "rule": RULE,
            "pass": rate is not None and rate >= RULE, "at_threshold": rate == RULE,
            "verdict": "after preferred" if rate is not None and rate >= RULE else
                       "back to calibration: the rubric is optimising for the graders, not the reader"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs=2, metavar=("BEFORE_OR_ANSWERS", "AFTER_OR_KEY"))
    ap.add_argument("--score", action="store_true", help="score answers.json against key.json")
    ap.add_argument("--units", help="comma-separated rewritten unit ids")
    ap.add_argument("-o", "--out")
    ap.add_argument("--seed", type=int)
    a = ap.parse_args(argv)
    if a.score:
        result = score(*(json.loads(Path(f).read_text()) for f in a.files))
        print(json.dumps(result, indent=1))
        return 0 if result["pass"] else 1
    if not (a.units and a.out):
        ap.error("--units and -o are required to build the page")
    print(build(a.files[0], a.files[1], a.units.split(","), a.out, a.seed))
    return 0


PAGE = r"""<!doctype html>
<html lang="en-AU"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>draft-eval blind preference test</title>
<style>
:root { --ink:#1d2330; --muted:#5b6475; --line:#d9dde5; --bg:#f6f7f9; --accent:#2f5bd3; }
* { box-sizing:border-box; }
body { margin:0; font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color:var(--ink); background:var(--bg); }
header { position:sticky; top:0; z-index:5; background:#fff; border-bottom:1px solid var(--line);
  padding:10px 24px; display:flex; gap:16px; align-items:center; }
header h1 { font-size:17px; margin:0; }
#progress { color:var(--muted); }
button { font:inherit; padding:6px 14px; border:1px solid var(--accent); background:var(--accent); color:#fff;
  border-radius:6px; cursor:pointer; }
main { max-width:1400px; margin:0 auto; padding:16px 24px 80px; }
.intro, .pair { background:#fff; border:1px solid var(--line); border-radius:8px; padding:12px 16px; margin:16px 0; }
.pair.done { border-color:#9bc59d; }
.pair h2 { font-size:16px; margin:0 0 8px; }
.sides { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.sides img { width:100%; border:1px solid var(--line); border-radius:4px; }
.pick { margin-top:10px; display:flex; gap:24px; }
.pick label { cursor:pointer; }
.pick input { cursor:pointer; }
.pair textarea { width:100%; min-height:3.2em; margin-top:10px; font:inherit; padding:6px 8px;
  border:1px solid var(--line); border-radius:6px; resize:vertical; }
.sides img { cursor:zoom-in; }
#lb { position:fixed; inset:0; z-index:20; background:rgba(15,18,25,.92); display:none; flex-direction:column;
  align-items:center; justify-content:center; padding:16px; cursor:zoom-out; }
#lb.open { display:flex; }
#lb img { max-width:100%; max-height:calc(100vh - 70px); object-fit:contain; background:#fff; }
#lb p { color:#fff; margin:10px 0 0; font-size:14px; }
@media (max-width:800px) { .sides { grid-template-columns:1fr; } }
</style></head>
<body>
<header><h1>Blind preference test</h1><span id="progress"></span>
<button id="download" type="button">Download JSON</button></header>
<main>
<div class="intro"><p>Each pair shows the same slide twice: one before the rewrite and one after, in a
random order. Pick the slide you would rather present, or "No difference", and leave a note under any pair if you want to say why. Your answers save in this
browser. When every pair is answered, press <b>Download JSON</b> and file it as
<code>prefer-answers.json</code> beside this page.</p></div>
<div id="pairs"></div>
</main>
<div id="lb" role="dialog" aria-modal="true" aria-label="Enlarged slide"><img alt=""><p></p></div>
<script type="application/json" id="data">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const KEY = 'draft-eval-prefer-' + D.key_id;
let S = {}, N = {};
try { S = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) {}
try { N = JSON.parse(localStorage.getItem(KEY + '-notes') || '{}'); } catch (e) {}
const root = document.getElementById('pairs');
function progress() {
  const done = D.pairs.filter(p => S[p.pair]).length;
  document.getElementById('progress').textContent = done + ' of ' + D.pairs.length + ' pairs';
  for (const p of D.pairs) document.getElementById(p.pair).classList.toggle('done', !!S[p.pair]);
}
D.pairs.forEach((p, i) => {
  const sec = document.createElement('section');
  sec.className = 'pair'; sec.id = p.pair;
  sec.innerHTML = '<h2></h2><div class="sides"><img alt="Left slide"><img alt="Right slide"></div><div class="pick"></div>';
  sec.querySelector('h2').textContent = 'Pair ' + (i + 1) + ' of ' + D.pairs.length;
  const [l, r] = sec.querySelectorAll('img');
  l.src = p.left; r.src = p.right;
  for (const [v, text] of [['left', 'Left is better'], ['right', 'Right is better'], ['none', 'No difference']]) {
    const lab = document.createElement('label');
    const inp = document.createElement('input');
    inp.type = 'radio'; inp.name = p.pair; inp.value = v; inp.checked = S[p.pair] === v;
    inp.addEventListener('change', () => { S[p.pair] = v; localStorage.setItem(KEY, JSON.stringify(S)); progress(); });
    lab.append(inp, ' ' + text);
    sec.querySelector('.pick').append(lab);
  }
  const note = document.createElement('textarea');
  note.placeholder = 'Notes on this pair (optional). Say left or right if you mean one side.';
  note.setAttribute('aria-label', 'Notes on pair ' + (i + 1));
  note.value = N[p.pair] || '';
  note.addEventListener('input', () => {
    if (note.value.trim()) N[p.pair] = note.value; else delete N[p.pair];
    localStorage.setItem(KEY + '-notes', JSON.stringify(N));
  });
  sec.append(note);
  root.append(sec);
});
progress();
// Lightbox: click a slide to enlarge it; the arrow keys switch between the pair's two sides, Esc closes.
const lb = document.getElementById('lb'), lbImg = lb.querySelector('img'), lbCap = lb.querySelector('p');
let lbPair = null, lbSide = 0;
function lbShow() {
  lbImg.src = lbSide ? lbPair.right : lbPair.left;
  lbCap.textContent = (lbSide ? 'Right' : 'Left') + ' slide. Arrow keys switch sides, Esc closes.';
}
root.addEventListener('click', e => {
  if (e.target.tagName !== 'IMG') return;
  lbPair = D.pairs.find(p => p.pair === e.target.closest('.pair').id);
  lbSide = e.target === e.target.parentNode.lastElementChild ? 1 : 0;
  lbShow(); lb.classList.add('open');
});
lb.addEventListener('click', () => lb.classList.remove('open'));
document.addEventListener('keydown', e => {
  if (!lb.classList.contains('open')) return;
  if (e.key === 'Escape') lb.classList.remove('open');
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { lbSide = e.key === 'ArrowRight' ? 1 : 0; lbShow(); }
});
document.getElementById('download').addEventListener('click', () => {
  const out = {kind: 'draft-eval-preference', key_id: D.key_id, saved_at: new Date().toISOString(), answers: S, notes: N};
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], {type: 'application/json'}));
  a.download = 'prefer-answers.json';
  document.body.append(a); a.click(); a.remove();
});
</script>
</body></html>
"""

if __name__ == "__main__":
    sys.exit(main())
