#!/usr/bin/env python3
"""PostToolUse(Bash): remember branches this session created.

Feeds commit-only-on-my-branch.py. A branch this session made is one it may
commit to; anything else in a shared checkout belongs to another thread.
"""

import json
import os
import re
import sys

STATE = os.path.expanduser("~/.claude/state/session-branches")
NEW_BRANCH = re.compile(
    r"\bgit\s+(?:-C\s+\S+\s+)?(?:switch\s+-c|checkout\s+-b|worktree\s+add\s+(?:-q\s+)?-b)\s+(\S+)"
)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    names = NEW_BRANCH.findall(cmd)
    if not names:
        return
    sid = payload.get("session_id")
    if not sid:
        return
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, sid), "a", encoding="utf-8") as fh:
        for n in names:
            fh.write(n.strip("'\"") + "\n")


if __name__ == "__main__":
    main()
