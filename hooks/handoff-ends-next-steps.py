#!/usr/bin/env python3
"""Stop hook: refuse to offer back work that was just handed off.

CLAUDE.md already says a handoff ends this thread's next steps, and says it twice.
Writing it a third time would not have helped -- the rule was clear and got broken
anyway, three responses running, because nothing checked. This checks.

Blocks only when a handoff document written recently in this repo is named again
inside the *Next steps for us (options)* block. Mentioning it in the body is fine
and expected: the point is to stop the work being offered as a fresh task, not to
stop it being discussed.
"""

import json
import os
import re
import sys
import time

WINDOW_HOURS = 18
STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "docs", "handoff", "handoffs",
    "notes", "md", "plan", "spec", "todo", "scratch", "fix", "bug",
}


def recent_handoffs(root):
    """Handoff docs in this repo touched inside the window: (path, tokens)."""
    cutoff = time.time() - WINDOW_HOURS * 3600
    out = []
    for sub in ("docs/handoffs", ".scratch", "docs/plans"):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if not name.endswith(".md"):
                continue
            if "handoff" not in name.lower() and "handoff" not in sub:
                continue
            p = os.path.join(d, name)
            try:
                if os.path.getmtime(p) < cutoff:
                    continue
            except OSError:
                continue
            stem = os.path.splitext(name)[0].lower()
            tokens = {t for t in re.split(r"[^a-z0-9]+", stem)
                      if len(t) > 3 and t not in STOPWORDS}
            if tokens:
                out.append((os.path.join(sub, name), tokens))
    return out


def options_block(text):
    """Just the numbered options section, or '' if there isn't one."""
    m = re.search(r"###\s*Next steps for us.*?$(.*)", text,
                  re.IGNORECASE | re.MULTILINE | re.DOTALL)
    return m.group(1) if m else ""


def last_assistant_text(transcript_path):
    try:
        with open(transcript_path, encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("type") != "assistant":
            continue
        content = (rec.get("message") or {}).get("content") or []
        parts = [c.get("text", "") for c in content
                 if isinstance(c, dict) and c.get("type") == "text"]
        if parts:
            return "\n".join(parts)
    return ""


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    if payload.get("stop_hook_active"):
        return                      # already looping; do not stack another block

    root = payload.get("cwd") or os.getcwd()
    handoffs = recent_handoffs(root)
    if not handoffs:
        return

    block = options_block(last_assistant_text(payload.get("transcript_path", "")))
    if not block:
        return
    low = block.lower()

    for path, tokens in handoffs:
        hits = sorted(t for t in tokens if re.search(r"\b%s\b" % re.escape(t), low))
        if hits:
            print(json.dumps({
                "decision": "block",
                "reason": (
                    "Next steps for us offers work already handed off in %s "
                    "(matched: %s). CLAUDE.md: a handoff ENDS this thread's next "
                    "steps. Remove that option and re-send. Discussing it in the "
                    "body is fine; offering it as a task is not."
                    % (path, ", ".join(hits))
                ),
            }))
            return


if __name__ == "__main__":
    main()
