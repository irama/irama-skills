#!/usr/bin/env python3
"""Extract scoring units from a deck (index.html) or an article (.md).

    extract.py <index.html | article.md> [--at <git-rev>] [-o units.json]
    extract.py --selftest

Deck: one unit per LOGICAL slide. Consecutive <section>s that share a
data-state-group are animation states of one slide; the one marked
data-state-primary (else the first) is the slide scored. A <section> is not a
slide. Speaker notes are index-aligned with PHYSICAL sections, hidden ones
included, so a unit's note is the note at its primary_index.

hash_index is primary_index + 1. The runtime (deck-stage.js _collectSlides and
_restoreIndex) counts EVERY slotted <section> for its 1-based #N: hidden
sections and animation states each take a number, so #N is the physical
section index plus one. Verified by render.mjs's id assertion on A3 (38
sections, 30 units, 3 hidden, one 9-state group) and A4.

Article: one unit per `##` section (text before the first `##` is section 0),
split at paragraph boundaries into parts of at most 400 words. A top-level
`---` rule or a References/Sources heading starts the back matter, which is
returned as `references` and never scored. Ids are s<section>-p<part>.
"""
import argparse
import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

MAX_WORDS = 400


class _Sections(HTMLParser):
    """Collects each top-level <section>: its attributes and its visible text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections, self.depth, self.skip = [], 0, 0

    def handle_starttag(self, tag, attrs):
        if tag == "section":
            if self.depth == 0:
                self.sections.append({"attrs": dict(attrs), "text": []})
            self.depth += 1
        elif tag in ("style", "script") and self.depth:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag == "section" and self.depth:
            self.depth -= 1
        elif tag in ("style", "script") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if self.depth and not self.skip:
            self.sections[-1]["text"].append(data)


PLANTED = "[planted]"  # in a slide's speaker notes: a deliberate fake, honest_numbers is N/A


def _notes(html):
    m = re.search(r'<script[^>]*id="speaker-notes"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    raw = json.loads(m.group(1))
    return [n["note"] if isinstance(n, dict) else n for n in raw]


# reference and evidence appendix slides: checked, not presented (rubric 0.2)
EVIDENCE = ("evidence", "references", "reference", "provenance", "sources")


def _role(attrs, sid, cls, note, ordinal):
    if attrs.get("data-role"):
        return attrs["data-role"], False
    # ponytail: name-based guesses, marked role_inferred; a generator that emits data-role replaces them.
    if ordinal == 1 or sid == "title":
        role = "title"
    elif "divider" in cls or sid.startswith("divider"):
        role = "divider"
    elif "exercise" in cls or "Exercise" in note:
        role = "exercise"
    elif set(cls.split()) & set(EVIDENCE) or sid.startswith(EVIDENCE):
        role = "evidence"
    elif "close" in cls or sid == "close":
        role = "close"
    else:
        role = "content"
    return role, True


def extract_deck(html):
    parser = _Sections()
    parser.feed(html.split("<deck-stage", 1)[-1])
    secs, notes = parser.sections, _notes(html)
    groups = []
    for i, s in enumerate(secs):
        g = s["attrs"].get("data-state-group")
        if g and groups and groups[-1][0] == g:
            groups[-1][1].append(i)
        else:
            groups.append((g, [i]))
    units = []
    for ordinal, (g, idx) in enumerate(groups, 1):
        primary = next((i for i in idx if "data-state-primary" in secs[i]["attrs"]), idx[0])
        a = secs[primary]["attrs"]
        cls = a.get("class") or ""
        sid = a.get("data-slide-id") or f"section-{primary + 1}"
        note = notes[primary] if primary < len(notes) else ""
        role, inferred = _role(a, sid, cls, note, ordinal)
        units.append({
            "id": sid,
            "label": a.get("data-screen-label", ""),
            "ordinal": ordinal,
            "section_indices": idx,
            "primary_index": primary,
            "hash_index": primary + 1,  # every section counts, see the docstring
            "hidden": "data-hidden-src" in a or "hidden" in a,
            "role": role,
            "role_inferred": inferred,
            "layout": a.get("data-layout") or cls,
            "text": " ".join("".join(secs[primary]["text"]).split()),
            "notes": note,
            "planted": PLANTED in note,
        })
    return {
        "kind": "deck",
        "counts": {"sections": len(secs), "notes": len(notes), "units": len(units),
                   "hidden": sum(u["hidden"] for u in units)},
        "units": units,
    }


FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def _outside_fences(lines):
    """top[i] is True when line i sits outside any fenced block (CommonMark rules: a fence
    opens with 3+ backticks or tildes and closes only on the same character, at least as long,
    with nothing after it)."""
    top, opener = [], None
    for line in lines:
        m = FENCE.match(line)
        if opener is None:
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                opener = m.group(1)
                top.append(False)
            else:
                top.append(True)
        else:
            top.append(False)
            if m and m.group(1)[0] == opener[0] and len(m.group(1)) >= len(opener) and not m.group(2).strip():
                opener = None
    return top


def _paragraphs(lines):
    """Blank-line separated paragraphs; a blank line inside a fence does not split."""
    paras, cur = [], []
    for line, top in zip(lines, _outside_fences(lines)):
        if not line.strip() and top:
            if cur:
                paras.append("\n".join(cur))
            cur = []
        else:
            cur.append(line)
    if cur:
        paras.append("\n".join(cur))
    return paras


def _pack(items, sep):
    """Greedy-pack items (each at most MAX_WORDS words) into strings of at most MAX_WORDS words."""
    parts, cur, n = [], [], 0
    for it in items:
        w = len(it.split())
        if cur and n + w > MAX_WORDS:
            parts.append(sep.join(cur))
            cur, n = [], 0
        cur.append(it)
        n += w
    if cur:
        parts.append(sep.join(cur))
    return parts


def _fit(p):
    """Split a paragraph over MAX_WORDS at sentence ends (lines, for a fence), then at words."""
    if len(p.split()) <= MAX_WORDS:
        return [p]
    # ponytail: a split fence loses its closing marker in the first part; fine for scoring text.
    fenced = bool(FENCE.match(p.splitlines()[0]))
    bits = p.splitlines() if fenced else re.split(r"(?<=[.!?])\s+", p)
    small = []
    for b in bits:
        w = b.split()
        small += [" ".join(w[i:i + MAX_WORDS]) for i in range(0, len(w), MAX_WORDS)] if len(w) > MAX_WORDS else [b]
    return _pack(small, "\n" if fenced else " ")


def extract_article(md):
    lines = md.splitlines()
    if lines and lines[0].strip() == "---":  # front matter
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), 0)
        lines = lines[end + 1:]
    top = _outside_fences(lines)
    # A `---` rule is back matter only when no `##` heading follows it; mid-body rules stay.
    last_h2 = max([i for i, l in enumerate(lines) if top[i] and l.startswith("## ")], default=-1)
    title, sections, back = "", [["", []]], []
    for i, line in enumerate(lines):
        if top[i]:
            if (line.strip() == "---" and i > last_h2) or re.match(r"##\s+(References|Sources)\b", line, re.I):
                back = lines[i:]
                break
            if line.startswith("# ") and not title:
                title = line[2:].strip()
                continue
            if line.startswith("## "):
                sections.append([line[3:].strip(), []])
                continue
        sections[-1][1].append(line)
    units = []
    for s, (heading, body) in enumerate(sections):
        parts = _pack([q for p in _paragraphs(body) for q in _fit(p)], "\n\n")
        for k, text in enumerate(parts, 1):
            label = heading or "Introduction"
            units.append({
                "id": f"s{s}-p{k}",
                "label": label + (f" (part {k})" if len(parts) > 1 else ""),
                "ordinal": len(units) + 1,
                "section": s,
                "part": k,
                "words": len(text.split()),
                "text": text,
            })
    return {"kind": "article", "title": title, "units": units,
            "references": "\n".join(back).strip(),
            "counts": {"sections": len(sections), "units": len(units)}}


def read_source(path, rev=None):
    if not rev:
        return Path(path).read_text(encoding="utf-8")
    p = Path(path)
    return subprocess.run(["git", "-C", str(p.parent or "."), "show", f"{rev}:./{p.name}"],
                          check=True, capture_output=True, text=True).stdout


def extract(path, rev=None):
    text = read_source(path, rev)
    doc = extract_deck(text) if Path(path).suffix.lower() in (".html", ".htm") else extract_article(text)
    doc["source"] = Path(path).name
    doc["rev"] = rev
    return doc


_FIXTURE = """<html><body>
<deck-stage>
<section class="meta" data-slide-id="title" data-screen-label="Title"><h1>Opening</h1><style>.x{}</style></section>
<section class="meta" data-slide-id="s-a" data-screen-label="A" data-state-group="g">State A</section>
<section class="meta" data-slide-id="s-b" data-screen-label="B" data-state-group="g" data-state-primary>State <b>B</b></section>
<section class="meta" data-slide-id="s-c" data-screen-label="C" data-state-group="g">State C</section>
<section class="paper" data-slide-id="spare" data-screen-label="Spare" data-hidden-src>Spare</section>
<section class="exercise" data-slide-id="x1" data-screen-label="X1">Do it</section>
<section class="meta" data-slide-id="t-a" data-screen-label="TA" data-state-group="h">First state</section>
<section class="meta" data-slide-id="t-b" data-screen-label="TB" data-state-group="h">Second state</section>
<section class="meta" data-slide-id="provenance" data-screen-label="Provenance">Sources</section>
<section class="meta divider" data-slide-id="close" data-screen-label="Close" data-role="close" data-layout="end">Bye</section>
</deck-stage>
<script type="application/json" id="speaker-notes">
[{"index":1,"note":"n1"},{"index":2,"note":"n2"},{"index":3,"note":"n3"},{"index":4,"note":"n4"},
{"index":5,"note":"n5"},{"index":6,"note":"n6 [planted]"},{"index":7,"note":"n7"},{"index":8,"note":"n8"},{"index":9,"note":"n9"},{"index":10,"note":"n10"}]
</script></body></html>"""


def selftest():
    doc = extract_deck(_FIXTURE)
    u = doc["units"]
    assert doc["counts"]["sections"] == 10 and len(u) == 7, doc["counts"]
    assert [x["id"] for x in u] == ["title", "s-b", "spare", "x1", "t-a", "provenance", "close"]
    assert u[1]["section_indices"] == [1, 2, 3] and u[1]["primary_index"] == 2
    assert u[1]["notes"] == "n3", "note must come from the primary's physical index"
    assert u[4]["primary_index"] == 6 and u[4]["notes"] == "n7", "no primary marked: first state"
    assert u[6]["notes"] == "n10" and u[6]["ordinal"] == 7
    assert u[5]["role"] == "evidence" and u[3]["planted"] and not u[1]["planted"]
    assert u[2]["hidden"] and not u[1]["hidden"] and doc["counts"]["hidden"] == 1
    assert u[1]["text"] == "State B" and u[0]["text"] == "Opening"
    assert (u[0]["role"], u[3]["role"], u[1]["role"]) == ("title", "exercise", "content")
    assert (u[6]["role"], u[6]["role_inferred"], u[6]["layout"]) == ("close", False, "end")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?")
    ap.add_argument("--at", help="read the file at this git revision")
    ap.add_argument("-o", "--out", help="write units.json here (default: stdout)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        selftest()
        print("selftest ok")
        return 0
    if not a.path:
        ap.error("path is required")
    doc = extract(a.path, a.at)
    out = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if a.out:
        Path(a.out).write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)
    print(json.dumps(doc["counts"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
