#!/usr/bin/env python3
"""PreToolUse(Bash): refuse `git commit` on a branch this session did not create.

Twice in one session a commit intended for `main` landed on another session's
active `/driver` branch, because that session switched HEAD in the shared
checkout between the state check and the commit. Reading `git status` first does
not help: the gap between reading and committing is exactly where it moves.

Allowed: the default branch, and any branch this session created itself (recorded
by the companion PostToolUse hook when `git switch -c` / `git checkout -b` /
`git worktree add -b` runs). Everything else is somebody else's branch.

Escape hatch: set ALLOW_FOREIGN_BRANCH_COMMIT=1 in the command when the commit
really does belong on a branch another session made.
"""

import json
import os
import re
import subprocess
import sys

STATE = os.path.expanduser("~/.claude/state/session-branches")

COMMIT = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?commit\b")
DEFAULTS = {"main", "master"}


def git(cwd, *args):
    try:
        r = subprocess.run(["git", "-C", cwd, *args],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def mine(session_id):
    try:
        with open(os.path.join(STATE, session_id), encoding="utf-8") as fh:
            return {l.strip() for l in fh if l.strip()}
    except OSError:
        return set()


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    if not COMMIT.search(cmd) or "ALLOW_FOREIGN_BRANCH_COMMIT=1" in cmd:
        return

    cwd = payload.get("cwd") or os.getcwd()
    branch = git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD":       # detached: not a shared-branch risk
        return
    if branch in DEFAULTS or branch in mine(payload.get("session_id", "")):
        return

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "HEAD in %s is on `%s`, a branch this session did not create — "
                "very likely another session's live /driver run, which can switch "
                "HEAD in a shared checkout at any moment. Commit in your own "
                "worktree, or cherry-pick onto the branch you meant. Prefix with "
                "ALLOW_FOREIGN_BRANCH_COMMIT=1 if it really belongs here."
                % (os.path.basename(cwd), branch)
            ),
        }
    }))


if __name__ == "__main__":
    main()
