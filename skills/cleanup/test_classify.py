#!/usr/bin/env python3
"""Hermetic self-check for the classifier in discover.py. Run: python3 skills/cleanup/test_classify.py

Real git repos in a temp folder, a hand-built liveness context. Nothing real is read or changed.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import discover as D  # noqa: E402

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


def main():
    tmp = os.path.realpath(tempfile.mkdtemp())
    a = os.path.join(tmp, "a")
    origin = os.path.join(tmp, "a-origin.git")
    os.makedirs(a)
    git(a, "init", "-q", "-b", "main")
    commit(a, "base")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True, env=GENV)
    git(a, "remote", "add", "origin", origin)
    git(a, "push", "-q", "origin", "main")
    git(a, "fetch", "-q", "origin")
    git(a, "remote", "set-head", "origin", "main")

    P = lambda n: os.path.join(tmp, "wt-" + n)

    def wt(n, base="main", detach=False):
        if detach:
            git(a, "worktree", "add", "-q", "--detach", P(n), base)
        else:
            git(a, "worktree", "add", "-q", "-b", n, P(n), base)
        return P(n)

    done, squash, ready = wt("done"), wt("squash"), wt("ready")
    never, abandon, dirty, unknown = wt("never"), wt("abandon"), wt("dirty"), wt("unknown")
    det, locked = wt("det", detach=True), wt("locked")
    git(a, "worktree", "lock", "--reason", "keep", locked)
    parent = wt("parent")
    child = os.path.join(parent, "inner")
    git(a, "worktree", "add", "-q", "-b", "child", child, "main")
    open(os.path.join(git(parent, "rev-parse", "--git-common-dir") and git(parent, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude")), "a").write("inner/\n")
    land = os.path.join(tmp, "driver-land-1")
    git(a, "worktree", "add", "-q", "--detach", land, "main")
    for w, f in ((done, "d"), (squash, "s"), (ready, "r"), (abandon, "x"), (parent, "p")):
        commit(w, f)
    commit(dirty, "y")
    open(os.path.join(dirty, "y"), "a").write("more")
    # unknown: a moved, merged branch whose reflog has expired -> creation point unknown (set up below)
    commit(unknown, "u")
    # driver run: an integration branch with one commit, a ticket cut from it
    git(a, "branch", "drv")
    drv = wt("drvint", base="drv")  # branch drvint; make the integration branch drv itself instead
    git(a, "worktree", "remove", "--force", drv)
    git(a, "worktree", "add", "-q", P("drvwork"), "drv")
    commit(P("drvwork"), "i")
    ticket = wt("worktree-t1", base="drv")
    base_sha = git(a, "rev-parse", "main")
    rundir = os.path.join(a, ".scratch", "driver-runs", "r1")
    os.makedirs(rundir)
    state = {"_run": {"base": base_sha, "integration_branch": "drv", "run_id": "r1", "work": P("drvwork")},
             "1": {"status": "in-progress"}, "2": {"status": "pending"}}
    json.dump(state, open(os.path.join(rundir, "state.json"), "w"))
    open(os.path.join(rundir, "journal.ndjson"), "w").write("{}\n")
    # main: merge done, parent, unknown; cherry-pick squash; push; then merge ready locally (unpushed)
    for b in ("done", "parent", "unknown"):
        git(a, "merge", "--no-ff", "-q", "-m", "merge " + b, b)
    git(a, "cherry-pick", git(squash, "rev-parse", "HEAD"))
    # evil merge: a --no-ff merge of an already-landed feat, plus an extra file inside the merge commit
    ftmp = os.path.join(tmp, "feat-tmp")
    git(a, "worktree", "add", "-q", "-b", "feat", ftmp, base_sha)
    commit(ftmp, "f")
    git(a, "worktree", "remove", "--force", ftmp)
    mrg, sq2 = wt("mrg", base=base_sha), wt("sq2", base=base_sha)
    git(mrg, "merge", "--no-ff", "--no-commit", "feat")
    open(os.path.join(mrg, "extra"), "w").write("extra")
    git(mrg, "add", "extra")
    git(mrg, "commit", "-qm", "merge feat with extra")
    commit(sq2, "s1")
    commit(sq2, "s2")
    git(a, "cherry-pick", git(a, "rev-parse", "feat"))
    git(a, "merge", "--squash", "-q", "sq2")
    git(a, "commit", "-qm", "squash sq2")
    git(a, "push", "-q", "origin", "main")
    git(a, "fetch", "-q", "origin")
    git(a, "merge", "--no-ff", "-q", "-m", "merge ready", "ready")
    # expire only the unknown branch's reflog
    rl = git(a, "rev-parse", "--git-path", "logs/refs/heads/unknown")
    os.remove(rl if os.path.isabs(rl) else os.path.join(a, rl))
    open(os.path.join(git(a, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude")), "a").write(".scratch/\n")

    def run(now=None, sessions=(), procs=(), parked=(), self_cwd="/nonexistent", orca=None, orca_ok=True):
        r = D.process_repo(Path(a), orca or {}, False, lambda r_, rows: [])
        D.mark_nesting([r])
        ctx = {"now": now or time.time(), "sessions": None if sessions is None else list(sessions),
               "proc_cwds": list(procs), "parked": list(parked), "self_cwd": self_cwd, "orca_ok": orca_ok, "tmp": tmp}
        D.classify_all([r], ctx)
        return r, {w["path"]: w for w in r["worktrees"]}

    def is_(name, w, group, reason=None, rec=None):
        ok = w["group"] == group and (reason is None or w["reason"] == reason) and w["recommendation"] == rec
        check(name, ok, f"{w['group']!r} {w['reason']!r} {w['recommendation']!r}")

    r, W = run()
    is_("rule 0: locked worktree is skipped", W[locked], "Skipped", "locked (keep)")
    is_("rule 0: fresh landing scratch is left alone", W[land], "Landing", "landing scratch: left alone")
    _, W2 = run(now=time.time() + 2 * 86400)
    is_("rule 0: old landing scratch with no process is removed", W2[land], "Landing",
        "landing scratch older than 24 hours with no process inside: remove")
    check("rule 0: landing_action is remove", W2[land]["landing_action"] == "remove")
    _, W2b = run(now=time.time() + 2 * 86400, procs=[land])
    is_("rule 0: old landing scratch with a process inside stays", W2b[land], "Landing", "landing scratch: left alone")

    is_("rule 1: parent with a nested worktree is never auto-pruned and gets no Delete", W[parent], "Abandoned",
        "holds nested worktrees (no Delete option)")
    _, Wc = run(sessions=[{"session": "s", "thread": "t1", "cwd": child, "loc": child, "claims": []}])
    is_("rule 1: a live child makes its clean parent Running, not prunable", Wc[parent], "Running",
        "live session t1 is in it")
    _, Wp = run(procs=[parent])
    is_("rule 1: child of a Running parent inherits Running", Wp[child], "Running",
        f"inside Running worktree {D.home_rel(parent)}")

    is_("rule 2: integration branch worktree belongs to its active run", W[P("drvwork")], "Running",
        "driver run r1 is active (2 tickets open)")
    is_("rule 2: a ticket worktree cut from the integration branch belongs to it", W[ticket], "Running",
        "driver run r1 is active (2 tickets open)")
    state["1"]["status"] = "merged"
    state["2"]["status"] = "skipped"
    json.dump(state, open(os.path.join(rundir, "state.json"), "w"))
    _, Wt = run()
    check("rule 2: a run with only terminal tickets owns nothing", not Wt[ticket]["reason"].startswith("driver run"),
          Wt[ticket]["reason"])
    state["1"]["status"] = "pending"
    json.dump(state, open(os.path.join(rundir, "state.json"), "w"))
    _, Wo = run(now=time.time() + 2 * 86400)
    check("rule 2: an open run with a stale journal and no claim owns nothing",
          not Wo[ticket]["reason"].startswith("driver run"), Wo[ticket]["reason"])

    is_("rule 3: a live session that entered the worktree blocks it", run(
        sessions=[{"session": "s", "thread": "t2", "cwd": a, "loc": done, "claims": []}])[1][done], "Running",
        "live session t2 is in it")
    is_("rule 3: a process working directory inside blocks it", run(procs=[os.path.join(done, "sub")])[1][done],
        "Running", "a process has its working directory inside it")
    o = {os.path.realpath(done): {"id": "x", "repoId": "r", "isUnread": False, "isPinned": False,
                                  "lastActivityAt": (time.time() - 60) * 1000}}
    is_("rule 3: Orca activity in the last 30 minutes blocks it", run(orca=o)[1][done], "Running",
        "its Orca card is unread, pinned or active in the last 30 minutes")
    o[os.path.realpath(done)]["lastActivityAt"] = (time.time() - 3 * 3600) * 1000
    check("rule 3: old Orca activity does not", run(orca=o)[1][done]["group"] == "Pruned")
    held = {"session": "s", "thread": "t3", "cwd": done, "loc": a, "claims": [{"key": "a:x", "state": "waiting-on-user"}]}
    is_("rule 3: a held claim makes the worktree its session record points at Running", run(sessions=[held])[1][done],
        "Running", "open claim a:x (waiting-on-user) held by live session t3")
    held["claims"][0]["state"] = "abandoned"
    check("rule 3: a claim in status abandoned does not make it Running", run(sessions=[held])[1][done]["group"] == "Pruned")
    held["claims"][0]["state"] = "incomplete"
    check("rule 3: nor does incomplete", run(sessions=[held])[1][done]["group"] == "Pruned")

    is_("rule 4: moved, merged, on the remote, clean -> auto-prune", W[done], "Pruned",
        "moved, merged and on the remote, clean, no live session")
    check("rule 4: squash-merged branch (cherry shows no unmerged patch) is auto-prune, not Abandoned",
          W[squash]["group"] == "Pruned" and W[squash]["on_remote"] is False and W[squash]["unmerged_patches"] == 0,
          (W[squash]["group"], W[squash]["reason"]))
    is_("review: a merge commit with an extra file is not trusted via cherry -> Abandoned", W[mrg], "Abandoned",
        "2 commit(s) on no default branch (no Delete option)")
    check("review: evil merge has empty cherry yet is not merged", W[mrg]["unmerged_patches"] == 0
          and W[mrg]["range_has_merges"] is True and not W[mrg]["content_in_default"], W[mrg]["reason"])
    check("review: 2-commit squash merge is Pruned by tree equivalence",
          W[sq2]["group"] == "Pruned" and W[sq2]["unmerged_patches"] == 2 and W[sq2]["content_in_default"],
          (W[sq2]["group"], W[sq2]["reason"], W[sq2]["unmerged_patches"]))
    check("review: unreadable conductor register blocks a prune",
          run(sessions=None)[1][done]["group"] == "Abandoned"
          and "conductor register unavailable" in run(sessions=None)[1][done]["reason"])
    check("review: Orca unavailable blocks a prune",
          run(orca_ok=False)[1][done]["group"] == "Abandoned"
          and "Orca unavailable" in run(orca_ok=False)[1][done]["reason"])
    is_("rule 4: unmerged commits with no live session are Abandoned", W[abandon], "Abandoned",
        "1 commit(s) on no default branch (no Delete option)")
    check("rule 4: dirty work is Abandoned with no Delete", W[dirty]["group"] == "Abandoned"
          and W[dirty]["recommendation"] is None and "changed" in W[dirty]["reason"], W[dirty]["reason"])
    is_("rule 4: never moved and young -> Abandoned, no Delete", W[never], "Abandoned",
        "never moved: tip equals its creation point; never auto-pruned; folder not older than 3 days")
    _, Wn = run(now=time.time() + 4 * 86400)
    is_("rule 4: never moved, clean, creation on default, older than 3 days -> Delete", Wn[never], "Abandoned",
        "never moved, clean, creation point on default, folder older than 3 days: Delete loses no commit", "Delete")
    check("rule 1: an aged parent with a nested worktree gets no Delete",
          Wn[parent]["recommendation"] is None)
    is_("rule 4: unknown creation point never yields Delete or auto-prune", Wn[unknown], "Abandoned",
        "creation point unknown (reflog expired): cannot show the branch moved (no Delete option)")

    is_("rule 4a: detached with no live session -> Abandoned, no Delete", W[det], "Abandoned",
        "detached HEAD with no live session (no Delete option)")
    is_("rule 4a: detached and live -> Running", run(procs=[det])[1][det], "Running",
        "a process has its working directory inside it")

    is_("rule 5: merged locally, not pushed -> Ready", W[ready], "Ready", "clean, tip is in local default but not pushed")

    check("rule 6: push row lists every unpushed commit, oldest first",
          r["push"] and [c["subject"] for c in r["push"]["commits"]] == ["r", "merge ready"], r["push"])
    check("rule 6: push row names the Running work in the repo",
          set(r["push"]["running"]) == {P("drvwork"), ticket}, r["push"]["running"])

    is_("main checkout is not classified for prune", W[a], "Main",
        "main checkout: never pruned; its push is the repo's push row")
    is_("the run's own worktree is always Running", run(self_cwd=os.path.join(abandon, "sub"))[1][abandon], "Running",
        "this run's own worktree")
    tip = git(never, "rev-parse", "HEAD")
    pk = {"path": never, "tip": tip, "until": "2999-01-01T00:00:00"}
    is_("parked and unchanged -> left out", run(parked=[pk])[1][never], "Parked", "parked until 2999-01-01T00:00:00")
    check("parked with a moved tip comes back", run(parked=[dict(pk, tip="0" * 40)])[1][never]["group"] == "Abandoned")
    check("expired park comes back", run(parked=[dict(pk, until="2000-01-01")])[1][never]["group"] == "Abandoned")

    print("PASS" if not FAILS else f"FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
