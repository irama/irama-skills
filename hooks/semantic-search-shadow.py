#!/usr/bin/env python3
"""PostToolUse(Bash): log searches that came back empty, as candidates for semantic search.

An empty literal search usually means the reader's words differ from the author's,
which is the gap semtools (documents) and semble (code) exist to close. A prose
rule naming them fired ~4 times in 300 sessions, so this hook watches the moment
instead.

Grep and bare grep/rg are blocked globally, so the searches that reach here are
the three routes the block messages offer: `sg` (code structure), a python
`os.walk` one-off (literal text across many files) and `cat file | grep`.

Shadow by default: it only appends to the log. Create the LIVE flag file to make
it also suggest the semantic tool to the model.
"""

import json
import os
import re
import sys
import time

STATE_DIR = os.path.expanduser("~/.claude/state/semantic-search")
LOG = os.path.join(STATE_DIR, "shadow.jsonl")
LIVE = os.path.join(STATE_DIR, "live")

DOC_HINT = re.compile(r"\.(md|mdx|txt|html)\b|docs/|research/|podcast/md|Obsidian|PRIMA \(iCloud\)")
CODE_HINT = re.compile(r"\.(ts|tsx|js|jsx|mjs|py|sql|go|rs|sh)\b|src/|lib/|app/")


def classify(cmd):
    """(route, needle, path) for a search command, or None."""
    c = re.sub(r"^\s*rtk\s+", "", cmd)
    m = re.search(r"(?:^|[;&|]\s*)sg\s+(?:run\s+)?(?:--pattern|-p)\s+(['\"])(.+?)\1\s*(?:--lang\s+\S+\s*)?([^\s|;&]*)", c)
    if m:
        return "sg", m.group(2), m.group(3) or "."
    if "os.walk" in c:
        n = re.search(r"NEEDLES?\s*=\s*[\[(]?\s*(['\"])(.+?)\1", c) or re.search(r"if\s+(['\"])(.+?)\1\s+in\s+(?!dp\b)\w", c)
        root = re.search(r"os\.walk\(\s*(['\"])(.+?)\1", c)
        return "walk", n.group(2) if n else "", root.group(2) if root else "."
    m = re.search(r"^\s*cat\s+(['\"]?)([^\s|'\"]+)\1[^|]*\|\s*grep\b((?:\s+-\S+)*)\s+(['\"]?)(.+?)\4\s*(?:$|[|;&])", c)
    if m:
        return "pipe", m.group(5), m.group(2)
    return None


def domain(route, cmd, path):
    if route == "sg":
        return "code"
    text = path if route == "pipe" else cmd
    doc, code = bool(DOC_HINT.search(text)), bool(CODE_HINT.search(text))
    return "doc" if doc and not code else "code" if code and not doc else "unknown"


def suggestion(dom, needle, path, cwd):
    has_agent = os.path.exists(os.path.join(cwd, ".claude/agents/semble-search.md"))
    doc = f'semtools search "<{needle or "the question"}, in plain words>" <the .md files under {path}> --top-k 5'
    code = ("the semble-search subagent" if has_agent
            else f'semble search "<{needle or "what the code does"}, in plain words>" {path}')
    if dom == "doc":
        return f"Literal search found nothing. If the wording may differ, try: {doc}"
    if dom == "code":
        return f"Literal search found nothing. If the wording may differ, try {code}"
    return f"Literal search found nothing. If the wording may differ: documents -> {doc}; code -> {code}"


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if data.get("tool_name") != "Bash":
        return
    cmd = (data.get("tool_input") or {}).get("command", "")
    hit = classify(cmd)
    if not hit:
        return
    resp = data.get("tool_response") or {}
    if not isinstance(resp, dict) or resp.get("interrupted") or (resp.get("stdout") or "").strip():
        return
    route, needle, path = hit
    cwd = data.get("cwd") or os.getcwd()
    dom = domain(route, cmd, path)
    live = os.path.exists(LIVE)
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "session": data.get("session_id"),
            "transcript": data.get("transcript_path"), "cwd": cwd, "route": route,
            "domain": dom, "needle": needle, "path": path, "live": live, "command": cmd[:600],
        }) + "\n")
    if live:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": suggestion(dom, needle, path, cwd),
        }}))


if __name__ == "__main__":
    main()
