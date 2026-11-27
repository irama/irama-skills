#!/usr/bin/env python3
"""Hermetic self-check for discover.py. Run: python3 skills/cleanup/test_discover.py

Builds a throwaway HOME with real git repos, runs discover.py with HOME pointed at it,
and checks the JSON. Nothing real on the machine is read or changed.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "discover.py")
FAILS = []
GENV = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null",
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{detail}]"))
    if not cond:
        FAILS.append(name)


def git(cwd, *a):
    r = subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, env=GENV)
    assert r.returncode == 0, (a, r.stderr)
    return r.stdout.strip()


def commit(repo, name):
    open(os.path.join(repo, name), "w").write(name)
    git(repo, "add", name)
    git(repo, "commit", "-qm", name)


def make_repo(path, origin=None):
    os.makedirs(path)
    git(path, "init", "-q", "-b", "main")
    commit(path, "base")
    if origin:
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True, env=GENV)
        git(path, "remote", "add", "origin", origin)
        git(path, "push", "-q", "origin", "main")
        git(path, "fetch", "-q", "origin")
        git(path, "remote", "set-head", "origin", "main")


def refs(repo):
    # origin/HEAD is a symref that follows origin/main, so it is left out.
    return git(repo, "for-each-ref", "--format=%(if)%(symref)%(then)%(else)%(refname) %(objectname)%(end)")


def main():
    tmp = os.path.realpath(tempfile.mkdtemp())
    home = os.path.join(tmp, "home")
    outside = os.path.join(tmp, "outside")  # not under home: only reachable through git
    os.makedirs(home)
    os.makedirs(outside)

    a = os.path.join(home, "proj", "a")
    make_repo(a, os.path.join(tmp, "a-origin.git"))
    # A second clone advances origin/main so the fetch has something to change.
    other = os.path.join(tmp, "other")
    subprocess.run(["git", "clone", "-q", os.path.join(tmp, "a-origin.git"), other], check=True, env=GENV)
    commit(other, "remote-new")
    git(other, "push", "-q", "origin", "main")

    wt_in = os.path.join(home, "proj", "a-wt-in")            # inside the walk
    wt_out = os.path.join(outside, "a-wt-out")                # outside the walk
    wt_nested = os.path.join(wt_in, "inner")                  # nested in wt_in
    wt_locked = os.path.join(outside, "a-wt-locked")
    wt_det = os.path.join(outside, "a-wt-det")
    git(a, "worktree", "add", "-q", "-b", "feat-in", wt_in)
    commit(wt_in, "work")
    git(a, "worktree", "add", "-q", "-b", "feat-out", wt_out)
    git(a, "worktree", "add", "-q", "-b", "feat-nested", wt_nested)
    git(a, "worktree", "add", "-q", "-b", "feat-locked", wt_locked)
    git(a, "worktree", "lock", "--reason", "keep", wt_locked)
    git(a, "worktree", "add", "-q", "--detach", wt_det)
    open(os.path.join(wt_out, "dirty.txt"), "w").write("x")     # untracked
    open(os.path.join(wt_in, "work"), "a").write("more")        # tracked change
    # A corrupt index makes `git status` fail in wt_det: counts must be unknown, not zero.
    gd = git(wt_det, "rev-parse", "--absolute-git-dir")
    open(os.path.join(gd, "index"), "w").write("garbage")
    a_before = refs(a)

    b = os.path.join(home, "b-noorigin")
    make_repo(b)
    c = os.path.join(home, "c-badorigin")
    make_repo(c, os.path.join(tmp, "c-origin.git"))
    git(c, "remote", "set-url", "origin", os.path.join(tmp, "gone.git"))  # fetch must fail
    c_before = refs(c)

    make_repo(os.path.join(home, "node_modules", "skipme"))    # skipped folder
    make_repo(os.path.join(home, "Library", "skipme2"))        # skipped folder
    make_repo(os.path.join(home, "excluded", "skipme3"))       # skipped by cleanup.json
    make_repo(os.path.join(home, "l1", "l2", "l3", "l4", "l5", "l6", "toodeep"))  # past depth cap
    os.makedirs(os.path.join(home, ".claude"))
    json.dump({"exclude": [os.path.join(home, "excluded")]}, open(os.path.join(home, ".claude", "cleanup.json"), "w"))

    orca = os.path.join(tmp, "orca.json")
    json.dump({"result": {"worktrees": [{"path": wt_out, "id": "r::x", "repoId": "r", "isUnread": True,
                                         "isPinned": False, "lastActivityAt": 5}]}}, open(orca, "w"))

    env = dict(GENV, HOME=home)
    r = subprocess.run([sys.executable, TOOL, "--discover-only", "--orca-json", orca],
                       capture_output=True, text=True, env=env, timeout=120)
    check("exits 0", r.returncode == 0, r.stderr[-300:])
    d = json.loads(r.stdout)
    repos = {os.path.basename(x["path"]): x for x in d["repos"]}
    check("exactly the 3 walkable repos", set(repos) == {"a", "b-noorigin", "c-badorigin"}, sorted(repos))
    check("counts", d["counts"] == {"repos": 3, "worktrees": 1 + 5 + 1 + 1, "fetch_failures": 1}, d["counts"])

    ra = repos["a"]
    wts = {w["path"]: w for w in ra["worktrees"]}
    check("outside-walk worktrees found via git", wt_out in wts and wt_locked in wts and wt_det in wts, list(wts))
    check("repo default branch", ra["default_branch"] == "main")
    check("fetch ok on a, failed only on c", not ra["fetch_failed"] and repos["c-badorigin"]["fetch_failed"]
          and not repos["b-noorigin"]["fetch_failed"])
    check("no origin: no remote facts", not repos["b-noorigin"]["has_origin"]
          and repos["b-noorigin"]["worktrees"][0]["on_remote"] is None)
    check("main checkout flagged", wts[a]["is_main"] and not wts[wt_in]["is_main"])
    check("branch and tip", wts[wt_in]["branch"] == "feat-in" and wts[wt_in]["tip"] == git(wt_in, "rev-parse", "HEAD"))
    check("dirty and untracked counts", wts[wt_in]["dirty_count"] == 1 and wts[wt_in]["dirty_files"] == ["work"]
          and wts[wt_out]["untracked_count"] == 1 and wts[wt_out]["dirty_count"] == 0)
    check("failed status -> unknown, not clean", wts[wt_det]["dirty_count"] is None
          and wts[wt_det]["untracked_count"] is None and wts[wt_det]["status_failed"] is True
          and wts[wt_in]["status_failed"] is False)
    check("birthtime recorded where the OS has it", not hasattr(os.stat(wt_in), "st_birthtime")
          or isinstance(wts[wt_in]["folder_birthtime"], float))
    check("ahead of local default", wts[wt_in]["ahead_of_local_default"] == 1 and wts[wt_out]["ahead_of_local_default"] == 0)
    check("fetched remote commit seen: behind origin, not on remote",
          wts[wt_in]["ahead_of_remote_default"] == 1 and wts[wt_in]["on_remote"] is False
          and wts[wt_out]["on_remote"] is True)
    check("cherry counts unmerged patch", wts[wt_in]["unmerged_patches"] == 1 and wts[wt_out]["unmerged_patches"] == 0)
    check("creation point and moved", wts[wt_in]["creation_point"] == git(a, "rev-parse", "main")
          and wts[wt_in]["commits_since_creation"] == 1 and wts[wt_out]["commits_since_creation"] == 0
          and wts[wt_in]["creation_on_default"] is True)
    check("detached has no branch or creation point", wts[wt_det]["detached"] and wts[wt_det]["creation_point"] is None)
    check("locked with reason", wts[wt_locked]["locked"] and wts[wt_locked]["lock_reason"] == "keep"
          and not wts[wt_in]["locked"])
    check("nesting both ways", wts[wt_nested]["nested_in"] == wt_in and wts[wt_in]["has_nested"] == [wt_nested]
          and wts[wt_out]["nested_in"] is None and wts[wt_out]["has_nested"] == [])
    check("orca managed only where listed", wts[wt_out]["orca_managed"] and wts[wt_out]["orca"]["isUnread"] is True
          and not wts[wt_in]["orca_managed"])
    check("folder ctime recorded", isinstance(wts[wt_in]["folder_ctime"], float))
    check("unpushed default commits empty when level", ra["unpushed_default_commits"] == [])

    # Expired reflog: an emptied reflog leaves the creation point unknown, never a guess.
    git(a, "reflog", "expire", "--expire=now", "--all")
    r2 = subprocess.run([sys.executable, TOOL, "--no-orca", "--no-fetch"], capture_output=True, text=True, env=env)
    w2 = {w["path"]: w for x in json.loads(r2.stdout)["repos"] if x["path"] == a for w in x["worktrees"]}
    check("expired reflog -> creation point unknown", w2[wt_in]["creation_point"] is None)

    # Read-only: only origin/main moved in repo a; nothing in c; nothing in b.
    a_after = refs(a)
    changed = {l.split()[0] for l in set(a_after.splitlines()) ^ set(a_before.splitlines())}
    check("only refs/remotes/origin/main changed", changed == {"refs/remotes/origin/main"}, changed)
    check("failed-fetch repo refs untouched", refs(c) == c_before)

    print("PASS" if not FAILS else f"FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
