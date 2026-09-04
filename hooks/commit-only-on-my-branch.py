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

# Must sit at a command position, not merely appear somewhere in the string --
# otherwise the hook fires on its own test payloads and on any text quoting it.
COMMIT = re.compile(
    r"(?:^|[;&|]|&&|\|\||\n)\s*(?:[A-Z_]+=\S+\s+)*git\s+(?:-C\s+\S+\s+)?commit\b")
DEFAULTS = {"main", "master"}


def target_dir(cmd, default):
    """Where the git command will actually run.

    The hook is handed the session's cwd, but a command commonly changes it
    first (`cd /path && ...`) or targets another tree (`git -C /path`). Reading
    the session cwd instead blocks correct work in other repos -- which is
    exactly what this hook did the first time it fired.
    """
    m = re.search(r"\bgit\s+-C\s+(\S+)", cmd)
    if m:
        return os.path.expanduser(m.group(1).strip("'\""))
    m = re.search(r"(?:^|;|&&|\|\|)\s*cd\s+(\S+)", cmd)
    if m:
        d = os.path.expanduser(m.group(1).strip("'\""))
        if os.path.isdir(d):
            return d
    return default


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

    cwd = target_dir(cmd, payload.get("cwd") or os.getcwd())
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
