#!/usr/bin/env python3
"""Hermetic self-check for apply.py. Run: python3 skills/cleanup/test_apply.py

Synthetic repos and a temp HOME. orca, kill-repo and xagent-ask are stubbed, so nothing real is touched or posted.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import apply as A  # noqa: E402
import discover as D  # noqa: E402
import make_brief as MB  # noqa: E402

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
    home = Path(tmp, "home")
    (home / ".claude" / "cleanup").mkdir(parents=True)
    run_dir = home / ".claude" / "cleanup" / "2026-01-02-0304"
    run_dir.mkdir()
    a, origin = os.path.join(tmp, "a"), os.path.join(tmp, "a-origin.git")
    os.makedirs(a)
    git(a, "init", "-q", "-b", "main")
    commit(a, "base")
    open(os.path.join(a, ".gitignore"), "w").write(".env*\n*.pem\nnode_modules/\n")
    git(a, "add", ".gitignore")
    git(a, "commit", "-qm", "ignore")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True, env=GENV)
    git(a, "remote", "add", "origin", origin)
    git(a, "push", "-q", "origin", "main")
    git(a, "fetch", "-q", "origin")
    git(a, "remote", "set-head", "origin", "main")
    P = lambda n: os.path.join(tmp, "wt-" + n)
    names = ["del", "park", "moved", "two", "none", "untouched", "dirtied", "parent"]
    for n in names:
        git(a, "worktree", "add", "-q", "-b", n, P(n), "main")
        commit(P(n), "f-" + n)
    child = os.path.join(P("parent"), "inner")
    git(a, "worktree", "add", "-q", "-b", "child", child, "main")
    open(git(a, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"), "a").write("inner/\n")
    commit(child, "f-child")
    # secrets and a build folder in the worktree to delete
    open(os.path.join(P("del"), ".env.local"), "w").write("SECRET=1")
    os.makedirs(os.path.join(P("del"), "sub"))
    open(os.path.join(P("del"), "sub", "key.pem"), "w").write("PEM")
    os.makedirs(os.path.join(P("del"), "node_modules", "x"))
    open(os.path.join(P("del"), "node_modules", "x", ".env"), "w").write("not a secret worth keeping")
    commit(a, "unpushed-on-main")  # a push row

    state = {"procs": []}
    ctx_fn = lambda ok: {"now": time.time(), "sessions": [], "proc_cwds": list(state["procs"]), "parked": D.load_parked(home),
                         "self_cwd": "/nonexistent", "orca_ok": ok, "tmp": tmp}

    def discover():
        r = D.process_repo(Path(a), {}, False, lambda r_, rows: [])
        D.mark_nesting([r])
        D.classify_all([r], ctx_fn(True))
        return {"repos": [r], "groups": {}, "counts": {"repos": 1, "worktrees": len(r["worktrees"]), "fetch_failures": 0}}

    d = discover()
    G = lambda n: next(w for w in d["repos"][0]["worktrees"] if w["path"] == P(n))
    check("setup: every fixture worktree is Abandoned", all(G(n)["group"] == "Abandoned" for n in names), {n: G(n)["group"] for n in names})
    rows = MB.build_rows(d, run_dir, run_dir.name, "/nonexistent", home=home)
    md = MB.render(rows)  # round one records each row's recommendation
    rowof = {r["name"]: r for r in rows["abandoned"]}
    push = rows["push"][0]
    check("setup: the push row and abandoned rows exist", push and all(f"wt-{n}" in rowof for n in names), list(rowof))
    (run_dir / "rows.json").write_text(json.dumps(rows, indent=1))

    # ── reading the responses ────────────────────────────────────────────────
    row = rowof["wt-del"]
    check("absent group takes the recommendation", A.resolve(row, {}) == ("run", MB.read_answer(row)[1]), A.resolve(row, {}))
    check("`none` does nothing", A.resolve(row, {row["key"]: "none"}) == ("none", None))
    check("one tick is that option", A.resolve(row, {row["key"]: MB.DELETE}) == ("run", MB.DELETE))
    check("two ticks ask", A.resolve(row, {row["key"]: f"{MB.PARK},{MB.DELETE}"}) == ("ask", [MB.PARK, MB.DELETE]), A.resolve(row, {row["key"]: f"{MB.PARK},{MB.DELETE}"}))
    check("a label that holds a comma still reads as one tick", A.resolve(push, {push["key"]: MB.HOLD}) == ("run", MB.HOLD))
    check("notes list and dict both read", A.read_notes({"notes": [{"id": "k", "label": "l", "note": "v"}]}) == {"k": "v"} and A.read_notes({"notes": {"k": "v"}}) == {"k": "v"})

    # ── apply ────────────────────────────────────────────────────────────────
    asks, calls = [], {"kill": [], "orca": []}
    tools = {"orca_rm": lambda p: (calls["orca"].append(p), (1, "no"))[1],
             "kill_repo": lambda p: (calls["kill"].append(p), (0, ""))[1]}
    k = lambda n: rowof["wt-" + n]["key"]
    notes = {k("del"): MB.DELETE, k("park"): MB.PARK, k("moved"): MB.DELETE, k("two"): f"{MB.PARK},{MB.DELETE}",
             k("none"): "none", k("dirtied"): MB.PARK, k("parent"): MB.DELETE, push["key"]: MB.HOLD,
             k("untouched"): MB.RESUME if MB.RESUME in rowof["wt-untouched"]["options"] else MB.MERGE}
    # the brief sits for days: one tip moves, one folder gets edited, one thread starts in the parked folder
    commit(P("moved"), "late")
    open(os.path.join(P("dirtied"), "scratch.txt"), "w").write("x")
    payload = {"brief": rows["brief_id"], "notes": [{"id": i, "label": i, "note": n} for i, n in notes.items()]}
    # `untouched` has no entry for its options beyond the one above; remove it to take its recommendation instead
    payload["notes"] = [n for n in payload["notes"] if n["id"] != k("untouched")]
    del_tip = G("del")["tip"]
    res = A.apply_all(rows, d, payload, run_dir, home, ctx_fn, lambda: ({}, True), lambda r_, rw: [], tools,
                      lambda **x: asks.append(x), now=time.mktime((2026, 1, 2, 3, 4, 0, 0, 0, -1)))
    st = lambda n: res[k(n)]["status"]
    check("none: nothing ran", st("none") == "none" and os.path.isdir(P("none")))
    check("two ticks: nothing ran and an ask went out offering the two boxes",
          st("two") == "asked" and os.path.isdir(P("two")) and any(x["choices"] == [MB.PARK, MB.DELETE] for x in asks), asks)
    check("hold: nothing pushed", res[push["key"]]["status"] == "held" and git(a, "rev-parse", "origin/main") != git(a, "rev-parse", "main"))
    check("recommendation taken for an absent group (not Delete)", res[k("untouched")]["status"] in ("parked", "unsupported", "asked", "held"), res[k("untouched")])

    # Delete
    tag = "cleanup/deleted/del-20260102"
    check("delete: tag created at the old tip", git(a, "rev-parse", tag) == del_tip, git(a, "tag", "--list"))
    check("delete: folder and branch gone", not os.path.exists(P("del")) and git(a, "branch", "--list", "del") == "" and st("del") == "deleted", res[k("del")])
    kept = home / ".claude" / "cleanup" / run_dir.name / "kept" / "a" / ("wt-del-" + __import__("hashlib").sha1(os.path.realpath(P("del")).encode()).hexdigest()[:8])
    check("delete: secret files kept with mode 600",
          (kept / ".env.local").read_text() == "SECRET=1" and (kept / "sub" / "key.pem").exists()
          and all(stat.S_IMODE(os.stat(f).st_mode) == 0o600 for f in (kept / ".env.local", kept / "sub" / "key.pem")), os.listdir(kept) if kept.exists() else "no kept")
    check("delete: a build folder's .env was not kept", not (kept / "node_modules").exists())
    check("delete: tag is local only", git(a, "ls-remote", "--tags", "origin") == "")
    undo = res[k("del")]["undo"]
    subprocess.run(undo, shell=True, check=True, capture_output=True, env=GENV)
    check("delete: the undo instructions restore branch, worktree and secrets",
          git(a, "rev-parse", "del") == del_tip and os.path.isdir(P("del")) and open(os.path.join(P("del"), ".env.local")).read() == "SECRET=1", undo)
    check("delete: a nested parent is not offered Delete, and a stray tick asks", MB.DELETE not in rowof["wt-parent"]["options"] and st("parent") == "asked" and os.path.isdir(child), res[k("parent")])
    pw = next(w for w in d["repos"][0]["worktrees"] if w["path"] == P("parent"))
    refused = A.delete(rowof["wt-parent"], d["repos"][0], pw, run_dir, home, tools, __import__("datetime").date(2026, 1, 2))
    check("delete: apply itself refuses a parent of nested worktrees", pw["has_nested"] and refused["status"] == "refused" and os.path.isdir(P("parent")), refused)
    check("delete: stops when its tag already exists", A.delete(rowof["wt-del"], d["repos"][0], dict(G("del"), tip=del_tip, branch="del", has_nested=False),
                                                              run_dir, home, tools, __import__("datetime").date(2026, 1, 2))["status"] == "refused")

    # Re-check
    check("re-check: tip moved after the brief means no action and an ask",
          st("moved") == "asked" and os.path.isdir(P("moved")) and git(a, "branch", "--list", "moved") != ""
          and any("tip moved" in x["question"] and "moved" in x["question"] for x in asks), (res[k("moved")], asks))
    check("re-check: changed cleanliness means no action and an ask", st("dirtied") == "asked" and "untracked file count changed" in res[k("dirtied")]["text"], res[k("dirtied")])
    asks.clear()
    state["procs"] = [os.path.join(P("park"), "sub")]
    res2 = A.apply_all(rows, d, {"notes": {k("park"): MB.PARK}}, run_dir, home, ctx_fn, lambda: ({}, True), lambda r_, rw: [], tools,
                       lambda **x: asks.append(x), only=k("park"))
    pf = home / ".claude/cleanup/parked.json"
    pf.unlink()
    check("re-check: a live session blocks the row and posts an ask",
          res2[k("park")]["status"] == "asked" and "Running" in asks[0]["question"]
          and not any(p["path"] == P("park") for p in (json.loads(pf.read_text()) if pf.exists() else [])), (res2, asks))
    state["procs"] = []
    check("ask text fits the Agent X limits", all(len(x["question"]) <= 500 and 2 <= len(x["choices"]) <= 6 and all(len(c) <= 60 for c in x["choices"]) for x in asks))

    # Park
    res3 = A.apply_all(rows, d, {"notes": {k("park"): MB.PARK}}, run_dir, home, ctx_fn, lambda: ({}, True), lambda r_, rw: [], tools,
                       lambda **x: asks.append(x), only=k("park"))
    pj = json.loads((home / ".claude/cleanup/parked.json").read_text())
    mine = next(p for p in pj if p["path"] == P("park"))
    check("park: recorded with a 30 day end and nothing changed on disk",
          res3[k("park")]["status"] == "parked" and mine["until"] == (__import__("datetime").date.today() + __import__("datetime").timedelta(days=30)).isoformat() and mine["tip"] == G("park")["tip"] and os.path.isdir(P("park")), pj)
    now = time.time()
    hidden = discover()
    check("park: the row is hidden next run", next(w for w in hidden["repos"][0]["worktrees"] if w["path"] == P("park"))["group"] == "Parked")
    mine["until"] = "2020-01-01"
    (home / ".claude/cleanup/parked.json").write_text(json.dumps(pj))
    back = discover()
    bw = next(w for w in back["repos"][0]["worktrees"] if w["path"] == P("park"))
    check("park: back after expiry, marked park expired", bw["group"] == "Abandoned" and bw.get("park_expired"), bw["group"])
    brow = MB.abandoned_row(back["repos"][0], bw, home, [])
    check("park: the returned row says so", brow["reason"].startswith("park expired."), brow["reason"])
    mine["until"] = "2099-01-01"
    (home / ".claude/cleanup/parked.json").write_text(json.dumps(pj))
    commit(P("park"), "moved-on")
    moved = discover()
    check("park: unparked when the tip moves", next(w for w in moved["repos"][0]["worktrees"] if w["path"] == P("park"))["group"] == "Abandoned")

    # Round two
    allres = A.merge_results(run_dir, res)
    allres.update(A.merge_results(run_dir, res3))
    md2 = MB.render(rows, False, allres, "r2-test")
    check("round two: same brief-id, fresh consumed, answered rows named", f"brief-id: {rows['brief_id']}" in md2 and "consumed: r2-test" in md2
          and md2.count("## Your Q") == len(rows["push"]) + len(rows["abandoned"]) and "\n## Q" not in md2, md2[:400])
    sub = [l for l in md2.splitlines() if l.startswith("sub:")][0]
    check("round two: the first sentence states the call and its price",
          sub.startswith("sub: Cleanup parked ") and "secret file" in sub.split("; nothing")[0] and "nothing was pushed" in sub, sub)
    check("round two: the undo instructions are in the brief", "To undo:" in md2 and "branch del cleanup/deleted/del-20260102" in md2)
    assets = Path.home() / ".claude" / "skills" / "peakstate-brief" / "assets"
    if (assets / "build-brief.mjs").exists():
        out = run_dir / "cleanup.html"
        (run_dir / "cleanup.md").write_text(md)
        b1 = subprocess.run(["node", str(assets / "build-brief.mjs"), str(run_dir / "cleanup.md"), str(out)], capture_output=True, text=True)
        (run_dir / "cleanup.md").write_text(md2)
        b2 = subprocess.run(["node", str(assets / "build-brief.mjs"), str(run_dir / "cleanup.md"), str(out)], capture_output=True, text=True)
        check("round two builds over round one", b1.returncode == 0 and b2.returncode == 0, (b1.stderr + b2.stderr)[-600:])
        lint = subprocess.run([sys.executable, str(assets / "brief-lint.py"), str(out)], capture_output=True, text=True)
        check("round two passes brief-lint.py", lint.returncode == 0, lint.stdout[-800:] + lint.stderr[-300:])
        (run_dir / "responses.json").write_text(json.dumps(payload))
        cov = subprocess.run([sys.executable, str(assets / "check-coverage.py"), str(run_dir / "cleanup.md"), str(run_dir / "responses.json")], capture_output=True, text=True)
        check("round two passes check-coverage.py", cov.returncode == 0, cov.stdout[-600:])
    else:
        print("SKIP peakstate-brief assets not installed: build, lint and coverage checks not run")

    # ── review fixes ─────────────────────────────────────────────────────────
    import datetime as _dt
    # i, iv) a second pass on the same responses (round two: no ticks) runs nothing and keeps the deleted result
    A.merge_results(run_dir, res)
    asks.clear()
    tags_before = git(a, "tag", "--list")
    again = A.apply_all(rows, d, {"notes": []}, run_dir, home, ctx_fn, lambda: ({}, True), lambda r_, rw: [], tools,
                        lambda **x: asks.append(x), now=time.mktime((2026, 1, 2, 3, 4, 0, 0, 0, -1)))
    kept_res = json.loads((run_dir / "results.json").read_text())
    check("rerun: rows with a result do not run again (none row, deleted row, no asks)",
          again == {} and not asks and os.path.isdir(P("none")) and git(a, "tag", "--list") == tags_before, (again, asks))
    check("rerun: the deleted result keeps its undo and kept_dir", kept_res[k("del")]["status"] == "deleted" and kept_res[k("del")].get("undo") and kept_res[k("del")].get("kept_dir"))
    (run_dir / "cleanup.html.rounds.json").write_text(json.dumps({"rounds": [{"builds": ["b1"]}, {"builds": ["b2"]}]}))
    check("round two responses are refused", A.round_one_refusal(run_dir, {"build": "b2"}) and A.round_one_refusal(run_dir, {}))
    check("round one responses pass", A.round_one_refusal(run_dir, {"build": "b1"}) is None)
    (run_dir / "responses-r2.json").write_text(json.dumps({"brief": rows["brief_id"], "build": "b2", "notes": []}))
    (run_dir / "discover.json").write_text(json.dumps(d))
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        rc = A.main([str(run_dir), str(run_dir / "responses-r2.json")])
    finally:
        os.environ["HOME"] = old_home
    check("main refuses round two with exit 2 and runs nothing", rc == 2 and os.path.isdir(P("none")) and git(a, "tag", "--list") == tags_before, rc)
    (run_dir / "cleanup.html.rounds.json").unlink()

    # ii, iii) the re-check reads the fresh group, status and availability
    base = dict(tip="t", dirty_count=0, untracked_count=0, group="Abandoned", status_failed=False, path="/nonexistent/x")
    okctx = {"now": time.time(), "sessions": [], "proc_cwds": [], "orca_ok": True}
    prow = {"tip": "t", "dirty_count": 0, "untracked_count": 0}
    check("re-check: clean fresh row passes", A.problem_with(prow, dict(base), okctx) is None, A.problem_with(prow, dict(base), okctx))
    check("re-check: a changed group asks", "Running" in (A.problem_with(prow, dict(base, group="Running", reason="r"), okctx) or ""))
    check("re-check: Orca unavailable asks", A.problem_with(prow, dict(base), dict(okctx, orca_ok=False)) is not None)
    check("re-check: process check unavailable asks", A.problem_with(prow, dict(base), dict(okctx, proc_cwds=None)) is not None)
    check("re-check: failed git status asks", "git status failed" in (A.problem_with(prow, dict(base, status_failed=True, dirty_count=None, untracked_count=None), okctx) or ""))
    check("re-check: a None count asks even with the flag unset", "git status failed" in (A.problem_with({"tip": "t"}, dict(base, dirty_count=None), okctx) or ""))
    asks.clear()
    ra = A.apply_all(rows, d, {"notes": {k("park"): MB.PARK}}, Path(tmp, "emptyrun"), home, ctx_fn, lambda: ({}, False), lambda r_, rw: [], tools,
                     lambda **x: asks.append(x), only=k("park"))
    check("re-check: Orca down at apply time means an ask, not an action", ra[k("park")]["status"] == "asked" and asks, ra[k("park")])

    # v, vi) kept paths, symlinked secrets
    def mkrepo(base_dir, name="same"):
        r = os.path.join(base_dir, name)
        os.makedirs(r)
        git(r, "init", "-q", "-b", "main")
        open(os.path.join(r, ".gitignore"), "w").write(".env*\n")
        commit(r, "base")
        git(r, "add", ".gitignore")
        git(r, "commit", "-qm", "ign")
        wt = os.path.join(base_dir, "wt-feat")
        git(r, "worktree", "add", "-q", "-b", "feat", wt, "main")
        commit(wt, "x")
        rr = D.process_repo(Path(r), {}, False, lambda r_, rows_: [])
        return r, wt, rr, next(w for w in rr["worktrees"] if w["path"] == wt)
    today = _dt.date(2026, 3, 4)
    r1, wt1, rr1, w1 = mkrepo(os.path.join(tmp, "x1"))
    r2, wt2, rr2, w2 = mkrepo(os.path.join(tmp, "x2"))
    open(os.path.join(wt1, ".env"), "w").write("ONE")
    open(os.path.join(wt2, ".env"), "w").write("TWO")
    o1 = A.delete({}, rr1, w1, run_dir, home, tools, today)
    o2 = A.delete({}, rr2, w2, run_dir, home, tools, today)
    check("kept: same repo and folder names in two places do not collide",
          o1["status"] == o2["status"] == "deleted" and o1["kept_dir"] != o2["kept_dir"]
          and Path(o1["kept_dir"], ".env").read_text() == "ONE" and Path(o2["kept_dir"], ".env").read_text() == "TWO", (o1, o2))
    r3, wt3, rr3, w3 = mkrepo(os.path.join(tmp, "x3"))
    open(os.path.join(wt3, ".env"), "w").write("THREE")
    pre = Path(home, ".claude", "cleanup", run_dir.name, "kept", "same", Path(wt3).name + "-" + __import__("hashlib").sha1(os.path.realpath(wt3).encode()).hexdigest()[:8])
    pre.mkdir(parents=True)
    (pre / ".env").write_text("OLD")
    o3 = A.delete({}, rr3, w3, run_dir, home, tools, today)
    check("kept: an existing kept file aborts the Delete and rolls back", o3["status"] == "failed" and os.path.isdir(wt3)
          and open(os.path.join(wt3, ".env")).read() == "THREE" and (pre / ".env").read_text() == "OLD"
          and git(r3, "tag", "--list") == "" and git(r3, "branch", "--list", "feat") != "", o3)
    r4, wt4, rr4, w4 = mkrepo(os.path.join(tmp, "x4"))
    real = os.path.join(tmp, "x4-real-secret")
    open(real, "w").write("REAL")
    os.chmod(real, 0o644)
    os.symlink(real, os.path.join(wt4, ".env.live"))
    os.symlink(os.path.join(tmp, "does-not-exist"), os.path.join(wt4, ".env.dangling"))
    o4 = A.delete({}, rr4, w4, run_dir, home, tools, today)
    kd = Path(o4.get("kept_dir", "/nonexistent"))
    check("symlinked secrets: both links kept, deleted, real target mode untouched",
          o4["status"] == "deleted" and sorted(o4["kept"]) == [".env.dangling", ".env.live"]
          and all(os.path.islink(kd / n) for n in o4["kept"]) and stat.S_IMODE(os.stat(real).st_mode) == 0o644 and not os.path.exists(wt4), o4)

    check("the real home was never written", not any(str(Path.home() / ".claude" / "cleanup" / "kept") in c for c in calls["kill"]))
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        sys.exit(1)
    print("\nall checks pass")


if __name__ == "__main__":
    main()
