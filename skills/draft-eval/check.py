#!/usr/bin/env python3
"""Mechanical checks on a deck: gates, floors and warnings, as JSON. No model.

    check.py <index.html> <units.json> [--floors floors.json] [--baseline]

Gates: ?audit reports every slide clean; no em dash and no banned term (rubric
banned_terms) in any unit's text or notes; every [hook:x] has a later
[payoff:x]; no filler pattern (rubric filler_patterns) in any unit's visible
text, notes excluded; every `content` unit has an img, svg, canvas or figure.
Floors (no worse than round 0): words on screen and minimum font size, both
from ?export. Warnings: two adjacent units with the same layout; Flesch reading
ease below round 0; a term from the deck's terms list on a visible slide before
the slide that introduces it, or with no introducing slide (a cross-check on the
arc pass's terms_introduced, rubric 0.4.1). Hidden units are skipped, except that ?audit covers the
whole deck. --baseline writes the floors file (default floors.json beside
units.json) from the current deck. Exit 1 when a gate or a floor fails.

?audit and ?export are read with headless Chrome --dump-dom. Set $CHROME to
override the browser path.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

VISUAL = {"img", "svg", "canvas", "figure"}
CHROMES = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
           "google-chrome", "chromium", "chromium-browser"]


# ---- pure checks -----------------------------------------------------------

def banned_hits(units, banned):
    hits = []
    for u in units:
        blob = f"{u.get('text', '')}\n{u.get('notes', '')}"
        for b in banned:
            found = b["term"] in blob if b["case_sensitive"] else b["term"].lower() in blob.lower()
            if found:
                hits.append({"id": u["id"], "term": b["term"]})
    return hits


def filler_hits(units, patterns):
    """Filler patterns in a unit's visible text. Notes are exempt: "do not read the axes as
    precise" is a fair thing to tell the presenter."""
    hits = []
    for u in units:
        for f in patterns:
            m = re.search(f["pattern"], u.get("text", ""), re.I)
            if m:
                hits.append({"id": u["id"], "term": m.group(0)})
    return hits


TAG = re.compile(r"\[(hook|payoff):([^\]\s]+)\]")


def unpaid_hooks(units):
    """Hooks with no [payoff:x] in a later unit. A payoff in the same unit does not count."""
    out = []
    for i, u in enumerate(units):
        for kind, name in TAG.findall(f"{u.get('text', '')}\n{u.get('notes', '')}"):
            if kind != "hook":
                continue
            later = any(("payoff", name) in TAG.findall(f"{v.get('text', '')}\n{v.get('notes', '')}")
                        for v in units[i + 1:])
            if not later:
                out.append({"id": u["id"], "hook": name})
    return out


class _Visual(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sections, self.depth = [], 0

    def handle_starttag(self, tag, attrs):
        if tag == "section":
            if self.depth == 0:
                self.sections.append(set())
            self.depth += 1
        elif self.depth and tag in VISUAL:
            self.sections[-1].add(tag)

    def handle_startendtag(self, tag, attrs):
        if tag != "section":
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "section" and self.depth:
            self.depth -= 1


def visual_tags(html):
    """Visual tags per top-level <section>, indexed like extract.py's sections."""
    p = _Visual()
    p.feed(html.split("<deck-stage", 1)[-1])
    return p.sections


def missing_visual(units, tags):
    return [u["id"] for u in units if u["role"] == "content" and not tags[u["primary_index"]]]


def terms_before_intro(units, terms):
    out = []
    for t in terms or []:
        at = t.get("introduced_at")
        pat = re.compile(r"(?<!\w)" + re.escape(t["term"]) + r"(?!\w)", re.I)
        early = [u["id"] for u in units if (at is None or u["ordinal"] < at) and pat.search(u.get("text", ""))]
        if early or at is None:
            out.append({"term": t["term"], "introduced_by": t.get("introduced_by"), "used_before": early})
    return out


def same_layout(units):
    return [[a["id"], b["id"]] for a, b in zip(units, units[1:]) if a["layout"] and a["layout"] == b["layout"]]


def _syllables(word):
    # ponytail: vowel-group count with a silent-e rule; a dictionary would be exact, this only has to be consistent across rounds.
    w = word.lower()
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and not w.endswith(("le", "ee")) and n > 1:
        n -= 1
    return max(n, 1)


def flesch(text):
    words = re.findall(r"[A-Za-z']+", text)
    if not words:
        return None
    sentences = max(len(re.findall(r"[.!?]+", text)), 1)
    syl = sum(_syllables(w) for w in words)
    return round(206.835 - 1.015 * len(words) / sentences - 84.6 * syl / len(words), 1)


def floor_breaches(now, floors):
    """More words, or a smaller minimum font, than the floor. Units without a floor pass."""
    out = []
    for uid, m in now.items():
        f = floors.get(uid)
        if not f:
            continue
        if m["words"] > f["words"]:
            out.append({"id": uid, "metric": "words", "floor": f["words"], "now": m["words"]})
        if f.get("min_font") is not None and m["min_font"] is not None and m["min_font"] < f["min_font"]:
            out.append({"id": uid, "metric": "min_font", "floor": f["min_font"], "now": m["min_font"]})
    return out


# ---- browser reads ---------------------------------------------------------

def _chrome():
    for c in [os.environ.get("CHROME")] + CHROMES:
        if c and (Path(c).exists() or shutil.which(c)):
            return c
    sys.exit("check.py: no Chrome found; set $CHROME")


def dump_dom(index, query):
    url = Path(index).resolve().as_uri() + "?" + query
    return subprocess.run(
        [_chrome(), "--headless=new", "--disable-gpu", "--window-size=1920,1080",
         "--virtual-time-budget=5000", "--dump-dom", url],
        capture_output=True, text=True, timeout=120, check=True).stdout


def audit(index):
    m = re.search(r"<pre[^>]*>(.*?)</pre>", dump_dom(index, "audit"), re.S)
    if not m:
        return {"pass": False, "problems": ["no ?audit report in the DOM"]}
    return audit_verdict(m.group(1))


def audit_verdict(report):
    """Judge a ?audit report by its final summary line only. Slide lines carry the
    screen label, so a label containing "PROBLEM" must not fail a clean deck."""
    lines = [ln.strip() for ln in report.splitlines() if ln.strip()]
    ok = bool(lines) and re.fullmatch(r"all \d+ slides clean", lines[-1]) is not None
    problems = [ln for ln in lines[:-1] if re.match(r"\d+ OVERFLOW", ln)]
    return {"pass": ok, "problems": problems}


def screen_metrics(index, units):
    m = re.search(r'<script[^>]*id="layout"[^>]*>(.*?)</script>', dump_dom(index, "export"), re.S)
    if not m:
        sys.exit("check.py: no ?export layout in the DOM")
    slides = json.loads(m.group(1))
    out = {}
    for u in units:
        texts = [i for i in slides[u["primary_index"]]["items"] if i["type"] == "text"]
        joined = " ".join(i["text"] for i in texts)
        out[u["id"]] = {"words": len(joined.split()),
                        "min_font": min((i["size"] for i in texts), default=None),
                        "flesch": flesch(joined)}
    return out


# ---- main ------------------------------------------------------------------

def run(index, units_path, floors_path=None, baseline=False):
    doc = json.loads(Path(units_path).read_text())
    units = [u for u in doc["units"] if not u["hidden"]]
    rubric = json.loads((Path(__file__).parent / "rubric.json").read_text())
    html = Path(index).read_text(encoding="utf-8")
    metrics = screen_metrics(index, units)
    floors_path = Path(floors_path or Path(units_path).with_name("floors.json"))
    if baseline:
        floors_path.write_text(json.dumps(metrics, indent=2) + "\n")
    floors = json.loads(floors_path.read_text()) if floors_path.exists() else None

    hits = banned_hits(units, rubric["banned_terms"])
    filler = filler_hits(units, rubric.get("filler_patterns", []))
    unpaid = unpaid_hooks(units)
    missing = missing_visual(units, visual_tags(html))
    gates = {
        "audit": audit(index),
        "banned": {"pass": not hits, "hits": hits},
        "filler": {"pass": not filler, "hits": filler},
        "hook_payoff": {"pass": not unpaid, "unpaid": unpaid},
        "visual": {"pass": not missing, "missing": missing},
    }
    breaches = floor_breaches(metrics, floors) if floors else []
    flesch_drops = [] if not floors else [
        {"id": uid, "floor": floors[uid]["flesch"], "now": m["flesch"]}
        for uid, m in metrics.items()
        if uid in floors and None not in (m["flesch"], floors[uid].get("flesch"))
        and m["flesch"] < floors[uid]["flesch"]]
    return {
        "pass": all(g["pass"] for g in gates.values()) and not breaches,
        "gates": gates,
        "floors": {"file": floors_path.name if floors else None, "pass": not breaches,
                   "breaches": breaches, "metrics": metrics},
        "warnings": {"same_layout": same_layout(units), "flesch_below_floor": flesch_drops,
                     "terms_before_intro": terms_before_intro(units, doc.get("terms"))},
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("index")
    ap.add_argument("units")
    ap.add_argument("--floors", help="floors file (default: floors.json beside units.json)")
    ap.add_argument("--baseline", action="store_true", help="write the floors file from this deck")
    a = ap.parse_args(argv)
    result = run(a.index, a.units, a.floors, a.baseline)
    json.dump(result, sys.stdout, indent=2)
    print()
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
