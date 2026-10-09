#!/usr/bin/env python3
"""PostToolUse(Bash|EnterWorktree): remember branches this session created.

Feeds commit-only-on-my-branch.py. A branch this session made is one it may
commit to; anything else in a shared checkout belongs to another thread.

EnterWorktree creates its branch without a Bash call, so for that tool the
branch is read from HEAD of the payload cwd, which is already the new worktree.
"""

import json
import os
import re
import subprocess
import sys

STATE = os.path.expanduser("~/.claude/state/session-branches")
# Git accepts options in any order, so `worktree add <path> -b <name>` is as common as
# `worktree add -b <name> <path>`. Skip other tokens up to the flag, but never across ; & |.
NEW_BRANCH = re.compile(
    r"\bgit\s+(?:-C\s+\S+\s+)?"
    r"(?:switch\s+(?:[^\s;&|]+\s+)*?-[cC]|checkout\s+(?:[^\s;&|]+\s+)*?-[bB]"
    r"|worktree\s+add\s+(?:[^\s;&|]+\s+)*?-[bB])\s+([^\s;&|]+)"
)


def worktree_branch(cwd):
    try:
        r = subprocess.run(["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    if payload.get("tool_name") == "EnterWorktree":
        names = [worktree_branch(payload.get("cwd") or "")]
        names = [n for n in names if n and n != "HEAD"]
    else:
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
