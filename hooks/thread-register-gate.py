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

Exact keys only. A fuzzy match on a work description does not belong here, and
neither does a loose read of the command: a false refusal on a deploy is worse
than the collision it prevents. So the verb must OPEN a command, the repo is read
from the verb's own segment of a compound command, and a push is gated only when
its refspec actually lands on the default branch.

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

SEPARATOR = re.compile(r"[;&|\n]+")

# `(?=\s|$)` and not `\b`, because `-` is a word boundary and `git merge-base` is
# a read-only command that must never be gated.
VERB = re.compile(
    r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*git\s+"
    r"(?:(?:-C|-c)\s+\S+\s+|--[\w-]+(?:=\S+)?\s+)*"
    r"(push|merge)(?=\s|$)")
DEFAULTS = {"main", "master"}
OVERRIDE = "ALLOW_HELD_SHIPPING_VERB=1"


def segments(cmd):
    return SEPARATOR.split(cmd)


def find_verb(cmd):
    """(index of the segment that runs the verb, its match), or (None, None)."""
    for i, seg in enumerate(segments(cmd)):
        m = VERB.match(seg)
        if m:
            return i, m
    return None, None


def target_dir(cmd, default, upto):
    """Where the git command will actually run — commonly not the session cwd.

    Scoped to the verb's own segment plus whatever `cd` ran before it, so
    `git -C /elsewhere status && git push` reads the push's repo, not the
    status's."""
    segs = segments(cmd)
    m = re.search(r"\bgit\s+-C\s+(\S+)", segs[upto])
    if m:
        return os.path.expanduser(m.group(1).strip("'\""))
    for seg in reversed(segs[:upto + 1]):
        m = re.match(r"\s*cd\s+(\S+)", seg)
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


def push_destinations(seg, cwd):
    """The branches a `git push` lands on: its refspec targets, else HEAD's branch.

    Read from the refspec arguments only. Searching the whole command for `main`
    gates `git push -u origin feature/domain-main`, which is a false refusal on
    somebody's ordinary feature branch."""
    args = seg.split()
    args = args[args.index("push") + 1:]
    words = [a for a in args if not a.startswith("-")]
    refspecs = words[1:]                       # words[0] is the remote
    if not refspecs:
        return {head_branch(cwd)}
    out = set()
    for spec in refspecs:
        dst = spec.split(":")[-1].lstrip("+").rsplit("/", 1)[-1]
        out.add(head_branch(cwd) if dst == "HEAD" else dst)
    return out


def gated_key(cmd, cwd_default):
    """(`<repo>:push` / `<repo>:merge`, cwd), or (None, None) when not gated."""
    i, m = find_verb(cmd)
    if not m or OVERRIDE in cmd:
        return None, None
    verb = m.group(1)
    cwd = target_dir(cmd, cwd_default, i)
    if verb == "push" and not (push_destinations(segments(cmd)[i], cwd) & DEFAULTS):
        # A feature-branch push is this thread's own work by definition. It
        # cannot collide, so it never even reads the register.
        return None, None
    import register
    return f"{register.repo_of(cwd)}:{verb}", cwd


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))


def pre(cmd, cwd_default):
    import register
    key, _ = gated_key(cmd, cwd_default)
    if not key:
        return
    held = io.StringIO()
    with redirect_stdout(held):
        blocked = register.cmd_check(key) or register.cmd_claim(
            key, "shipping verb, claimed automatically")
    if blocked:
        # cmd_claim is checked as well as cmd_check because the two are not one
        # atomic step: another thread can win the key in between, and its claim
        # must not be silently overwritten.
        deny("%s — another live thread has claimed this repo's shipping verb, and "
             "two threads shipping one repo is the collision this gate exists to "
             "stop. Ask it what state it is in (`/threads`), or release it "
             "(`/threads clear <name>`). Prefix with %s if you know it is safe."
             % (held.getvalue().strip(), OVERRIDE))


def post(cmd, cwd_default, response, session_id):
    import register
    key, _ = gated_key(cmd, cwd_default)
    if not key:
        return
    _, _, open_claims, _ = register.picture()
    mine = open_claims.get(key)
    if not mine or mine.get("session") != session_id:
        return          # not ours to close: a chained `switch && push` can reach
                        # here on a key this thread never claimed
    ok = not response.get("interrupted") and response.get("exit_code", 0) in (0, None)
    with redirect_stdout(io.StringIO()):
        register.cmd_signoff(key, "done" if ok else "incomplete",
                             "shipping verb finished" if ok else "shipping verb did not finish")


def selftest():
    """The key-derivation table, over a real repo and a real linked worktree.

    Every `None` row here was a false refusal or a bypass found in review. This
    is the check that keeps them fixed; there is nothing else to test in a hook
    whose other job is to not raise."""
    import register, shutil, tempfile
    root = tempfile.mkdtemp()
    repo = os.path.join(root, "scratch")
    wt = os.path.join(root, "scratch-feature")
    os.makedirs(repo)
    env = dict(os.environ, ALLOW_FOREIGN_BRANCH_COMMIT="1",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t.t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t.t")
    for args in (["init", "-q", "-b", "main", "."],
                 ["commit", "-q", "--allow-empty", "-m", "x"],
                 ["worktree", "add", "-q", "-b", "feature/domain-main", wt]):
        subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True)

    cases = [
        ("git push", repo, "scratch:push"),
        ("git push origin main", repo, "scratch:push"),
        ("git push origin HEAD", repo, "scratch:push"),
        ("git merge --no-ff feature/x", repo, "scratch:merge"),
        ("git merge-base main feature/x", repo, None),          # `-` is a word boundary
        ("git push -u origin feature/domain-main", wt, None),   # `main` inside a branch name
        ("git push", wt, None),                                 # feature branch
        ("git -c core.pager=cat push origin main", repo, "scratch:push"),   # a global option
        ('echo "git push origin main"', repo, None),            # quoted, not run
        ("git -C /tmp status && git push", repo, "scratch:push"),  # the verb's own segment
        ("cd %s && git push" % wt, repo, None),
        ("ALLOW_HELD_SHIPPING_VERB=1 git push", repo, None),
        ("git commit -m x", repo, None),
    ]
    ok = True
    for cmd, cwd, want in cases:
        got, _ = gated_key(cmd, cwd)
        if got != want:
            print("FAIL %r -> %r, want %r" % (cmd, got, want))
            ok = False
    if register.repo_of(repo) != register.repo_of(wt):
        print("FAIL a linked worktree must share its repo's key")
        ok = False
    shutil.rmtree(root, ignore_errors=True)
    print("selftest passed" if ok else "selftest FAILED")
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    if not cmd:
        return
    try:
        session_id = payload.get("session_id") or ""
        os.environ["CLAUDE_SESSION_ID"] = session_id
        cwd = payload.get("cwd") or os.getcwd()
        if payload.get("hook_event_name") == "PostToolUse":
            post(cmd, cwd, payload.get("tool_response") or {}, session_id)
        else:
            pre(cmd, cwd)
    except Exception:
        return                      # fail open: never wedge the shell on a register fault


if __name__ == "__main__":
    sys.exit(main() or 0)
