#!/usr/bin/env python3
"""PreToolUse(Bash): run RTK's rewrite hook, except for git in an isolated worktree.

Since Claude Code 2.1.259, a session isolated with EnterWorktree refuses any
command whose git it cannot trace to the worktree, and it checks the command
AFTER hooks rewrite it. `rtk git status` is a launcher it cannot read, so every
git call RTK rewrote was refused. The check cannot be turned off, and an allow
rule does not reach it.

Git is under 1% of RTK's savings, so git in an isolated session runs plain.
Everything else, and git in every other session, still goes through RTK.
"""

import json
import re
import subprocess
import sys

GIT = re.compile(r"\bgit\b")


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except Exception:
        payload = {}
    cwd = payload.get("cwd") or ""
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    # ponytail: detects isolation by cwd path, so a session that cd's out of its
    # worktree gets the RTK rewrite back. Read the session's worktree binding if that bites.
    if "/.claude/worktrees/" in cwd and GIT.search(cmd):
        return
    try:
        r = subprocess.run(["rtk", "hook", "claude"], input=raw,
                           capture_output=True, text=True, timeout=10)
    except Exception:
        return                      # no RTK: the command runs unrewritten
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
