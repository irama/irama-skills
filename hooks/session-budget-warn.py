#!/usr/bin/env python3
"""PostToolUse: say once when a session passes its tool-call / context budget.

CLAUDE.md § Session length is the cost driver already asks for this in prose:
"At ~150 tool calls or ~150k context, say so once — one line offering /handoff".
Measured 2026-09-05 it fired ZERO times in a 372-call, 540k-token session. A rule
in a 67 KB instruction file is read once and drifts; a hook fires every time. That
difference — not the wording — is why this exists.

Warns at most twice per session (a soft mark, then a hard one) and never blocks.
Cost matters: this runs after EVERY tool call, so it tails the transcript rather
than parsing it whole, and stops early once both marks are spent.
"""

import json
import os
import sys

STATE_DIR = os.path.expanduser("~/.claude/state/session-budget")
SOFT_CALLS, SOFT_CTX = 150, 150_000
HARD_CALLS, HARD_CTX = 250, 400_000


def counts(path: str):
    """(tool calls, peak context tokens) — one pass, no full-file load."""
    calls = 0
    peak = 0
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if '"tool_use"' not in line and '"usage"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("type") != "assistant":
                    continue
                msg = rec.get("message") or {}
                for b in msg.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        calls += 1
                u = msg.get("usage") or {}
                ctx = (
                    u.get("input_tokens", 0)
                    + u.get("cache_read_input_tokens", 0)
                    + u.get("cache_creation_input_tokens", 0)
                )
                peak = max(peak, ctx)
    except OSError:
        return None, None
    return calls, peak


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    transcript = payload.get("transcript_path")
    sid = payload.get("session_id")
    if not transcript or not sid or not os.path.exists(transcript):
        return 0

    os.makedirs(STATE_DIR, exist_ok=True)
    mark = os.path.join(STATE_DIR, sid)
    spent = ""
    if os.path.exists(mark):
        with open(mark, encoding="utf-8") as f:
            spent = f.read().strip()
    if spent == "hard":
        return 0

    calls, peak = counts(transcript)
    if calls is None:
        return 0

    level = None
    if calls >= HARD_CALLS or peak >= HARD_CTX:
        level = "hard"
    elif (calls >= SOFT_CALLS or peak >= SOFT_CTX) and spent != "soft":
        level = "soft"
    if not level:
        return 0

    with open(mark, "w", encoding="utf-8") as f:
        f.write(level)

    where = f"{calls} tool calls, peak context {peak // 1000}k"
    if level == "hard":
        msg = (
            f"SESSION BUDGET EXCEEDED — {where}. CLAUDE.md calls past "
            f"{HARD_CALLS} calls / {HARD_CTX // 1000}k context a defect, not a long session. "
            "Finish the edit in flight, write a /handoff, and stop. Say this to the user "
            "in one line; do not silently continue."
        )
    else:
        msg = (
            f"Session budget: {where}. CLAUDE.md asks you to say so ONCE at this point "
            "and offer /handoff or a ticket split. Tell the user in one line, then carry on "
            "— this is a nudge, not a stop."
        )
    print(json.dumps({"systemMessage": msg, "hookSpecificOutput":
                      {"hookEventName": "PostToolUse", "additionalContext": msg}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
