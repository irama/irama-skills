#!/usr/bin/env python3
"""PreToolUse(Bash): refuse `git push` to main or master unless /push authorised it.

The rule "never push the default branch without being asked" lived in prose only. This
hook makes it a gate: a push to main/master (or --all/--mirror, or a push whose repo
cannot be resolved) is refused unless /push wrote a marker for that repo in the last
10 minutes. /push, and /flush and /ship through it, write the marker just before their
push step:

    python3 ~/.claude/hooks/push-main-guard.py --authorise [repo-dir]

It fails closed: a push it cannot read is refused unless a marker is fresh. Repo and
args come from push_guard_targets.py, the parser the pre-push gate already uses.

Exit 0 = allow. Exit 2 + stderr = block, message goes to the model.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import push_guard_targets as pgt  # noqa: E402

STATE = os.path.expanduser("~/.claude/state/push-authorised")
WINDOW = 600  # seconds a /push marker stays valid
DEFAULT = {"main", "master"}


def git(target, *args):
    r = subprocess.run(["git", "-C", target, *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def marker(top):
    return os.path.join(STATE, hashlib.sha1(top.encode()).hexdigest()[:16])


def fresh(path):
    try:
        return time.time() - os.path.getmtime(path) < WINDOW
    except OSError:
        return False


def any_fresh():
    try:
        return any(fresh(os.path.join(STATE, f)) for f in os.listdir(STATE))
    except OSError:
        return False


def hits_default(target, args):
    """True if this push could update main/master. Unknown counts as yes."""
    if "--all" in args or "--mirror" in args:
        return True
    positional = [a for a in args if not a.startswith("-")]
    refspecs = positional[1:]  # the first positional is the remote
    if not refspecs or any(r.lstrip("+") == "HEAD" for r in refspecs):
        if target is None:
            return True
        return git(target, "branch", "--show-current") in DEFAULT
    for r in refspecs:
        dest = r.lstrip("+").split(":")[-1].removeprefix("refs/heads/")
        if dest in DEFAULT or "$" in dest:
            return True
    return False


def authorise(path):
    top = git(path, "rev-parse", "--show-toplevel")
    if not top:
        print(f"push-main-guard: {path} is not a git repo", file=sys.stderr)
        return 1
    os.makedirs(STATE, mode=0o700, exist_ok=True)
    with open(marker(top), "w") as f:
        f.write(top + "\n")
    print(f"push to the default branch authorised for {top} for {WINDOW // 60} minutes")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--authorise":
        return authorise(sys.argv[2] if len(sys.argv) > 2 else os.getcwd())
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    cmd = payload.get("tool_input", {}).get("command", "") or ""
    if "push" not in cmd:
        return 0
    pgt.PUSHES.clear()
    out = []
    pgt.plan(cmd, payload.get("cwd") or os.getcwd(), out)
    unreadable = not pgt.PUSHES and any(l.startswith("UNRESOLVED") for l in out)
    bare = pgt.strip_heredocs(cmd)  # heredoc bodies are data, never a push
    if not pgt.PUSHES and not out and re.search(r"\bgit\b.*\bpush\b", bare):
        unreadable = not pgt.lex(pgt.substitute(bare))  # unbalanced quotes: the parser saw nothing
    for target, args in pgt.PUSHES:
        if {"--dry-run", "-n", "--delete", "-d"} & set(args):
            continue
        if not hits_default(target, args):
            continue
        top = git(target, "rev-parse", "--show-toplevel") if target else ""
        if (top and fresh(marker(top))) or (not top and any_fresh()):
            continue
        return deny(top or "an unresolved repo")
    if unreadable and not any_fresh():
        return deny("a push this guard cannot read")
    return 0


def deny(what):
    print(
        f"Blocked: this pushes the default branch ({what}) and /push has not authorised it.\n"
        "Only /push (or /flush and /ship through it) pushes main, and only when the user asked.\n"
        "Push the feature branch instead, or run /push if the user asked to deploy.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
