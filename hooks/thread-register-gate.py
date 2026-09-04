#!/usr/bin/env python3
"""Bash gate: refuse a shipping verb another live thread has already claimed.

Two threads deploying one repo is the collision with a real cost, so this is the
one hard gate in the cross-thread work register. Everything else the register
does is reporting.

`PreToolUse(Bash)`: if `git push` or `git merge` is about to run and another live
thread holds `<repo>:push` or `<repo>:merge`, refuse and name the holder. If
nobody holds it, claim it — this is the one place automatic claiming is safe,
because the key is exact and the work is bounded. `PostToolUse(Bash)` signs the
same key off again the moment the command returns.

Exact keys only. A fuzzy match on a work description does not belong here: a
false refusal on a deploy is worse than the collision it prevents. And a push to
a branch that is not the default is this thread's own work by definition, so it
is never gated and never even reads the register.

Refusal shape, wording and escape hatch copied from commit-only-on-my-branch.py.
Override: prefix the command with ALLOW_HELD_SHIPPING_VERB=1.
"""

import io
import json
import os
import re
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "threads" / "assets"))

# Must sit at a command position, not merely appear somewhere in the string --
# otherwise the hook fires on its own test payloads and on any text quoting it.
VERB = re.compile(
    r"(?:^|[;&|]|&&|\|\||\n)\s*(?:[A-Z_]+=\S+\s+)*git\s+(?:-C\s+\S+\s+)?(push|merge)\b")
DEFAULTS = {"main", "master"}
OVERRIDE = "ALLOW_HELD_SHIPPING_VERB=1"


def target_dir(cmd, default):
    """Where the git command will actually run — it commonly is not the session cwd."""
    m = re.search(r"\bgit\s+-C\s+(\S+)", cmd)
    if m:
        return os.path.expanduser(m.group(1).strip("'\""))
    m = re.search(r"(?:^|;|&&|\|\|)\s*cd\s+(\S+)", cmd)
    if m:
        d = os.path.expanduser(m.group(1).strip("'\""))
        if os.path.isdir(d):
            return d
    return default


def head_branch(cwd):
    try:
        r = subprocess.run(["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def gated_key(cmd, cwd):
    """`<repo>:push` / `<repo>:merge`, or None when this command is not gated."""
    m = VERB.search(cmd)
    if not m or OVERRIDE in cmd:
        return None
    verb = m.group(1)
    if verb == "push":
        # A feature-branch push is this thread's own work. Only a push that
        # lands on the default branch can collide with another thread.
        named = set(re.findall(r"\b(main|master)\b", cmd))
        if not named and head_branch(cwd) not in DEFAULTS:
            return None
    import register
    return f"{register.repo_of(cwd)}:{verb}"


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))


def pre(cmd, cwd):
    import register
    key = gated_key(cmd, cwd)
    if not key:
        return
    held = io.StringIO()
    with redirect_stdout(held):
        blocked = register.cmd_check(key)
    if blocked:
        deny("%s — another live thread has claimed this repo's shipping verb, and "
             "two threads shipping one repo is the collision this gate exists to "
             "stop. Ask it what state it is in (`/threads`), or release it "
             "(`/threads clear <name>`). Prefix with %s if you know it is safe."
             % (held.getvalue().strip(), OVERRIDE))
        return
    with redirect_stdout(io.StringIO()):
        register.cmd_claim(key, "shipping verb, claimed automatically")


def post(cmd, cwd, response):
    import register
    key = gated_key(cmd, cwd)
    if not key:
        return
    ok = not response.get("interrupted") and response.get("exit_code", 0) in (0, None)
    with redirect_stdout(io.StringIO()):
        register.cmd_signoff(key, "done" if ok else "incomplete",
                             "shipping verb finished" if ok else "shipping verb did not finish")


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    if not cmd:
        return
    try:
        os.environ["CLAUDE_SESSION_ID"] = payload.get("session_id") or ""
        cwd = target_dir(cmd, payload.get("cwd") or os.getcwd())
        if payload.get("hook_event_name") == "PostToolUse":
            post(cmd, cwd, payload.get("tool_response") or {})
        else:
            pre(cmd, cwd)
    except Exception:
        return                      # fail open: never wedge the shell on a register fault


if __name__ == "__main__":
    main()
