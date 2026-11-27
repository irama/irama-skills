#!/usr/bin/env python3
"""Hermetic self-check for prune_auto.py. Run: python3 skills/cleanup/test_prune_auto.py

Synthetic repos in a temp folder. `orca` and `localhost-dev.sh kill-repo` are stubbed, so nothing real is touched.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import discover as D  # noqa: E402
import make_brief as MB  # noqa: E402
import prune_auto as PA  # noqa: E402

FAILS = []
GENV = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null",
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{detail}]"))
    if not cond:
        FAILS.append(name)


def git(cwd, *a, ok=True):
    r = subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, env=GENV)
    assert r.returncode == 0 or not ok, (a, r.stderr)
    return r.stdout.strip()


def commit(repo, name):
    open(os.path.join(repo, name), "w").write(name)
    git(repo, "add", name)
    git(repo, "commit", "-qm", name)


def main():
    tmp = os.path.realpath(tempfile.mkdtemp())
    a, origin = os.path.join(tmp, "a"), os.path.join(tmp, "a-origin.git")
    os.makedirs(a)
    git(a, "init", "-q", "-b", "main")
    commit(a, "base")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True, env=GENV)
    git(a, "remote", "add", "origin", origin)
    git(a, "push", "-q", "origin", "main")
    git(a, "fetch", "-q", "origin")
    git(a, "remote", "set-head", "origin", "main")
    P = lambda n: os.path.join(tmp, "wt-" + n)

    def wt(n):
        git(a, "worktree", "add", "-q", "-b", n, P(n), "main")
        return P(n)

    names = ["done", "orcadone", "orcafail", "extra", "live", "dirty", "unmerged", "never", "parent", "racer"]
    for n in names:
        wt(n)
    child = os.path.join(P("parent"), "inner")
    git(a, "worktree", "add", "-q", "-b", "child", child, "main")
    open(git(a, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"), "a").write("inner/\n")
    for n in ("done", "orcadone", "orcafail", "extra", "live", "dirty", "unmerged", "parent", "racer"):
        commit(P(n), "f-" + n)
    open(os.path.join(P("dirty"), "f-dirty"), "a").write("more")
    for n in ("done", "orcadone", "orcafail", "extra", "live", "dirty", "parent", "racer"):
        git(a, "merge", "--no-ff", "-q", "-m", "merge " + n, n)
    git(a, "push", "-q", "origin", "main", "done", "extra")  # done and extra exist on the remote
    # another clone advances origin/extra; this repo never fetches it
    other = os.path.join(tmp, "other")
    subprocess.run(["git", "clone", "-q", origin, other], check=True, env=GENV)
    git(other, "checkout", "-q", "extra")
    commit(other, "late")
    git(other, "push", "-q", "origin", "extra")
    git(a, "fetch", "-q", "origin", "+refs/heads/main:refs/remotes/origin/main")

    state = {"procs": []}
    ctx_fn = lambda ok: {"now": time.time(), "sessions": [], "proc_cwds": list(state["procs"]), "parked": [],
                         "self_cwd": "/nonexistent", "orca_ok": ok, "tmp": tmp}
    orca_map = {os.path.realpath(P(n)): {"id": "card-" + n, "repoId": "r", "isUnread": False, "isPinned": False,
                                         "lastActivityAt": (time.time() - 5 * 3600) * 1000}
                for n in ("orcadone", "orcafail")}
    calls = {"kill": [], "orca": []}

    def orca_rm(path):
        calls["orca"].append(path)
        if path.endswith("orcafail"):
            return 1, '{"ok": false, "error": {"message": "archive hook failed"}}'
        # the stub removes the folder but, like a keep-by-default host, leaves the branch behind
        git(a, "worktree", "remove", path)
        return 0, '{"ok": true, "result": {}}'

    tools = {"orca_rm": orca_rm, "kill_repo": lambda p: (calls["kill"].append(p), (0, ""))[1]}

    def discover():
        r = D.process_repo(Path(a), orca_map, False, lambda r_, rows: [])
        D.mark_nesting([r])
        D.classify_all([r], ctx_fn(True))
        return {"repos": [r], "groups": {}, "counts": {"repos": 1, "worktrees": len(r["worktrees"]), "fetch_failures": 0}}

    d = discover()
    G = lambda dd, n: next(w for w in dd["repos"][0]["worktrees"] if w["path"] == P(n))
    before = {n: G(d, n)["group"] for n in names}
    check("setup: done, orcadone, orcafail, extra, racer classify Pruned",
          all(before[n] == "Pruned" for n in ("done", "orcadone", "orcafail", "extra", "racer")), before)
    check("setup: dirty, unmerged, never, parent are not Pruned",
          all(before[n] != "Pruned" for n in ("dirty", "unmerged", "never", "parent")), before)

    # dry run changes nothing
    snap = subprocess.run(["git", "-C", a, "worktree", "list"], capture_output=True, text=True).stdout
    dry = PA.prune_auto(discover(), ctx_fn, lambda: (orca_map, True), lambda r_, rows: [], tools, dry_run=True)
    check("dry run lists would-remove rows and removes nothing",
          len(dry["pruned"]) == 6 and not calls["kill"] and not calls["orca"]
          and subprocess.run(["git", "-C", a, "worktree", "list"], capture_output=True, text=True).stdout == snap, dry)

    # a thread enters "live" and "racer" after classification
    state["procs"] = [P("live"), os.path.join(P("racer"), "sub")]
    res = PA.prune_auto(d, ctx_fn, lambda: (orca_map, True), lambda r_, rows: [], tools)
    names_done = {x["name"] for x in res["pruned"]}
    check("clean merged moved branches are removed", names_done == {"a/wt-done", "a/wt-orcadone", "a/wt-extra"}, res["pruned"])
    check("a worktree that went live after classification is re-checked and survives",
          os.path.isdir(P("racer")) and any(s["name"] == "a/wt-racer" for s in res["skipped"]), res["skipped"])
    survivors = ("dirty", "unmerged", "never", "parent", "live", "racer")
    check("dirty, unmerged, never-moved, nested-parent and live worktrees survive",
          all(os.path.isdir(P(n)) for n in survivors) and os.path.isdir(child))
    check("no survivor got a dev-server kill or an Orca removal",
          not any(os.path.realpath(k) in {os.path.realpath(P(n)) for n in survivors} for k in calls["kill"] + calls["orca"]),
          calls)
    check("done: worktree and branch gone", not os.path.isdir(P("done")) and git(a, "branch", "--list", "done") == "")
    check("orca row went through orca and its stub left the branch; -d then deleted it",
          calls["orca"].count(P("orcadone")) == 1 and git(a, "branch", "--list", "orcadone") == "",
          (calls["orca"], git(a, "branch", "--list", "orcadone")))
    od = next(x for x in res["pruned"] if x["name"] == "a/wt-orcadone")
    check("result names the Orca card closed", od["orca_card"] == "card-orcadone" and "card-orcadone" in od["did"], od)
    check("remote branch with the same tip as default is deleted",
          git(a, "ls-remote", "--heads", "origin", "done") == "")
    check("remote branch with an extra commit is kept (even though the local ref is stale)",
          git(a, "ls-remote", "--heads", "origin", "extra") != ""
          and next(x for x in res["pruned"] if x["name"] == "a/wt-extra")["remote_deleted"] is False)
    check("forced removal failure lands in Abandoned with the error text",
          G(d, "orcafail")["group"] == "Abandoned" and "archive hook failed" in G(d, "orcafail")["reason"]
          and res["failed"][0]["error"].startswith("orca worktree rm failed") and os.path.isdir(P("orcafail")), res["failed"])
    check("every kill-repo targeted a removed or failed worktree only",
          set(calls["kill"]) <= {P("done"), P("orcadone"), P("extra"), P("orcafail")}, calls["kill"])

    # branch -D is never used: an unmerged-to-HEAD branch survives its worktree
    git(a, "worktree", "add", "-q", "-b", "squashy", P("squashy"), "main")
    commit(P("squashy"), "s")
    commit(a, "unrelated")  # main moves on, so the cherry-pick below is a different commit (not a fast-forward)
    git(a, "cherry-pick", git(P("squashy"), "rev-parse", "HEAD"))
    git(a, "push", "-q", "origin", "main")
    git(a, "fetch", "-q", "origin", "+refs/heads/main:refs/remotes/origin/main")
    d2 = discover()
    res2 = PA.prune_auto(d2, ctx_fn, lambda: (orca_map, True), lambda r_, rows: [], tools)
    sq = next((x for x in res2["pruned"] if x["name"] == "a/wt-squashy"), None)
    check("squash-merged worktree removed, branch kept (never -D) and reported as kept",
          sq is not None and sq["branch_deleted"] is False and git(a, "branch", "--list", "squashy") != ""
          and "kept" in sq["did"], sq)

    # review fixes: ignored secrets, nested parent in another repo, non-dict Orca reply
    open(git(a, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"), "a").write(".env.local\nnode_modules/\n")
    open(os.path.join(a, ".env.local"), "w").write("SAME=1\n")
    for n in ("secret", "twin", "nest", "orcalist"):
        wt(n)
        commit(P(n), "f-" + n)
        git(a, "merge", "--no-ff", "-q", "-m", "merge " + n, n)
    git(a, "push", "-q", "origin", "main")
    git(a, "fetch", "-q", "origin", "+refs/heads/main:refs/remotes/origin/main")
    open(os.path.join(P("secret"), ".env.local"), "w").write("UNIQUE=1\n")
    open(os.path.join(P("twin"), ".env.local"), "w").write("SAME=1\n")
    os.makedirs(os.path.join(P("twin"), "node_modules"))
    open(os.path.join(P("twin"), "node_modules", "x.js"), "w").write("x")
    orca_map[os.path.realpath(P("orcalist"))] = {"id": "card-orcalist", "repoId": "r", "isUnread": False, "isPinned": False,
                                                 "lastActivityAt": (time.time() - 5 * 3600) * 1000}

    def orca_rm2(path):
        if path.endswith("orcalist"):
            git(a, "worktree", "remove", path)
            return 0, "[]"  # valid JSON, not an object
        return orca_rm(path)

    tools2 = dict(tools, orca_rm=orca_rm2)
    d3 = discover()
    G(d3, "nest")["nested_in"] = os.path.join(tmp, "other-repo-wt")  # the parent lives in a repo this run does not rebuild
    res3 = PA.prune_auto(d3, ctx_fn, lambda: (orca_map, True), lambda r_, rows: [], tools2)
    check("clean merged worktree with a unique ignored .env.local is kept as Abandoned with a reason",
          os.path.isdir(P("secret")) and G(d3, "secret")["group"] == "Abandoned" and ".env.local" in G(d3, "secret")["reason"], G(d3, "secret"))
    check("identical .env.local plus node_modules does not block removal",
          not os.path.isdir(P("twin")) and any(x["name"] == "a/wt-twin" for x in res3["pruned"]), res3)
    check("a candidate nested in a worktree of another repo is kept",
          os.path.isdir(P("nest")) and any(x["name"] == "a/wt-nest" for x in res3["skipped"]), res3["skipped"])
    check("a non-dict Orca reply does not crash and the removal is recorded",
          not os.path.isdir(P("orcalist")) and any(x["name"] == "a/wt-orcalist" for x in res3["pruned"]), res3)

    # brief rows: Pruned lists actual removals, failure is an Abandoned row
    run_dir = Path(tmp) / "run"
    (run_dir / "abandoned").mkdir(parents=True)
    rows = MB.build_rows(d, run_dir, "t", "/nonexistent", home=Path(tmp))
    pr = {p["name"]: p["why"] for p in rows["pruned"]}
    check("brief Pruned group lists the actual removals, naming the Orca card",
          set(pr) == {"wt-done", "wt-orcadone", "wt-extra"} and "card-orcadone" in pr["wt-orcadone"]
          and "Removed:" in pr["wt-done"], pr)
    check("brief marks pruning as done", rows["pruned_done"] is True)
    check("failed prune is an Abandoned row with the error",
          any(x["name"] == "wt-orcafail" and "archive hook failed" in x["reason"] for x in rows["abandoned"]))
    md = MB.render(rows, True)
    check("rendered Pruned part says pruned, not would prune", "Pruned automatically" in md and "Would prune" not in md)

    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nPASS")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
