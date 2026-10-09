#!/usr/bin/env python3
"""Self-check for record-session-branches.py + commit-only-on-my-branch.py.

Run: python3 hooks/test_session_branches.py  (exits non-zero on failure)
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def run_hook(name, payload, home):
    r = subprocess.run([sys.executable, os.path.join(HERE, name)],
                       input=json.dumps(payload), capture_output=True, text=True,
                       env={**os.environ, "HOME": home})
    return r.stdout


def denied(out):
    return '"deny"' in out


def main():
    home = tempfile.mkdtemp()
    repo = os.path.join(home, "repo")
    wt = os.path.join(home, "wt")
    g = lambda *a: subprocess.run(["git", *a], check=True, capture_output=True)
    g("init", "-q", "-b", "main", repo)
    g("-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
      "--allow-empty", "-m", "init")
    g("-C", repo, "worktree", "add", "-q", "-b", "worktree-ew", wt)
    g("-C", repo, "branch", "foreign")

    def commit(cmd, sid, cwd):
        return run_hook("commit-only-on-my-branch.py",
                        {"session_id": sid, "cwd": cwd, "tool_input": {"command": cmd}}, home)

    # Gap 1: before EnterWorktree is recorded the branch is foreign; after, it passes.
    assert denied(commit("git commit -m x", "s1", wt))
    run_hook("record-session-branches.py",
             {"session_id": "s1", "tool_name": "EnterWorktree", "cwd": wt, "tool_input": {}}, home)
    assert not denied(commit("git commit -m x", "s1", wt))
    assert denied(commit("git commit -m x", "s2", wt)), "other sessions stay refused"

    # Bash recording still works.
    run_hook("record-session-branches.py",
             {"session_id": "s3", "tool_name": "Bash",
              "tool_input": {"command": "git switch -c mine"}}, home)
    with open(os.path.join(home, ".claude/state/session-branches/s3")) as fh:
        assert fh.read().split() == ["mine"]

    # Any option order: the path before -b was missed, and a background /jobs run lost its branch.
    for i, (cmd, want) in enumerate([
            ("git worktree add $W -b job/2-smoke main", "job/2-smoke"),
            ("git -C r worktree add -q /p -b x2 main", "x2"),
            ("git switch -C y2", "y2"),
            ("git checkout -B z2 origin/main", "z2"),
            ("git worktree add /p main && ls -b q", None),
            ("git switch -c 'feature&api'", "feature&api")]):
        sid = "order%d" % i
        run_hook("record-session-branches.py",
                 {"session_id": sid, "tool_name": "Bash", "tool_input": {"command": cmd}}, home)
        path = os.path.join(home, ".claude/state/session-branches", sid)
        got = open(path).read().split() if os.path.exists(path) else []
        assert got == ([want] if want else []), (cmd, got)

    # Gap 2: launchers no longer skip the guard.
    g("-C", repo, "switch", "-q", "foreign")
    for cmd in ["command git commit -m x", "env git commit -m x", "rtk git commit -m x",
                "\\git commit -m x", "A=1 command git -C %s commit -m x" % repo,
                "cd %s && command git commit -m x" % repo]:
        assert denied(commit(cmd, "s1", repo)), cmd
    assert not denied(commit("ALLOW_FOREIGN_BRANCH_COMMIT=1 command git commit -m x", "s1", repo))
    assert not denied(commit("echo 'command git commit'", "s1", repo)), "quoted text ignored"
    g("-C", repo, "switch", "-q", "main")
    assert not denied(commit("command git commit -m x", "s1", repo)), "default branch allowed"
    print("ok")


if __name__ == "__main__":
    main()
