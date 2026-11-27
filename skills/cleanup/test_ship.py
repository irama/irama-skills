#!/usr/bin/env python3
"""Hermetic self-check for ship.py and the shipping rows of apply.py. Run: python3 skills/cleanup/test_ship.py

Synthetic repos in a temp folder, each with a bare-repo origin in the same folder. The /push and /merge
steps are stubs that run plain git against that origin, so nothing real is pushed, merged or deployed,
and no Monitor starts. xagent-ask is a list append.
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
import apply as A  # noqa: E402
import discover as D  # noqa: E402
import make_brief as MB  # noqa: E402
import ship as SH  # noqa: E402

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


class World:
    """One repo `<tmp>/<name>` with origin, a Ready worktree (its commit sits unpushed on main) and an Abandoned `m` worktree."""

    def __init__(self, tmp, name, running=False):
        self.tmp, self.name = tmp, name
        self.a, self.origin = os.path.join(tmp, name), os.path.join(tmp, name + "-origin.git")
        self.home = Path(tmp, name + "-home")
        (self.home / ".claude" / "cleanup").mkdir(parents=True)
        self.run_dir = self.home / ".claude" / "cleanup" / "2026-01-02-0304"
        self.run_dir.mkdir()
        os.makedirs(self.a)
        git(self.a, "init", "-q", "-b", "main")
        commit(self.a, "base")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.origin], check=True, env=GENV)
        git(self.a, "remote", "add", "origin", self.origin)
        git(self.a, "push", "-q", "origin", "main")
        git(self.a, "fetch", "-q", "origin")
        git(self.a, "remote", "set-head", "origin", "main")
        self.P = lambda n: os.path.join(tmp, f"{name}-wt-{n}")
        git(self.a, "worktree", "add", "-q", "-b", "r", self.P("r"), "main")
        commit(self.P("r"), "ready-work")
        git(self.a, "merge", "-q", "--ff-only", "r")  # r is merged into local main, not pushed: Ready
        for n in (["m", "wr"] if running else ["m"]):
            git(self.a, "worktree", "add", "-q", "-b", n, self.P(n), "main")
            commit(self.P(n), "f-" + n)
        self.state = {"procs": []}
        self.ctx_fn = lambda ok: {"now": time.time(), "sessions": [], "proc_cwds": list(self.state["procs"]), "parked": D.load_parked(self.home),
                                  "self_cwd": "/nonexistent", "orca_ok": ok, "tmp": tmp}
        r = D.process_repo(Path(self.a), {}, False, lambda r_, rows: [])
        D.mark_nesting([r])
        D.classify_all([r], self.ctx_fn(True))
        self.d = {"repos": [r], "groups": {}, "counts": {"repos": 1, "worktrees": len(r["worktrees"]), "fetch_failures": 0}}
        self.rows = MB.build_rows(self.d, self.run_dir, self.run_dir.name, "/nonexistent", home=self.home)
        MB.render(self.rows)
        (self.run_dir / "rows.json").write_text(json.dumps(self.rows))
        self.push = self.rows["push"][0]
        self.mrow = next(r_ for r_ in self.rows["abandoned"] if r_["name"].endswith("-m"))
        self.asks, self.calls = [], {"push": 0, "prompts": [], "merge": 0, "orca": [], "kill": []}

    def group(self, n):
        return next(w for w in self.d["repos"][0]["worktrees"] if w["path"] == self.P(n))["group"]

    def tools(self, merge=None, push_rc=0):
        def push(main, prompt=None):
            self.calls["push"] += 1
            self.calls["prompts"].append(prompt)
            r = subprocess.run(["git", "-C", main, "push", "-q", "origin", "main"], capture_output=True, text=True, env=GENV)
            return r.returncode or push_rc, r.stderr + (f"\nCLEANUP-RESULT: pushed {git(main, 'rev-parse', 'main')}" if r.returncode == 0 else "")
        def mrg(wt, branch):
            self.calls["merge"] += 1
            return (merge or self.squash_merge)(wt, branch)
        return {"push": push, "merge": mrg, "sleep": lambda s: None, "now": time.time,
                "orca_rm": lambda p: (self.calls["orca"].append(p), (1, "no"))[1],
                "kill_repo": lambda p: (self.calls["kill"].append(p), (0, ""))[1]}

    def squash_merge(self, wt, branch):
        """What /merge does: squash on the branch (reset --soft + commit), then a --no-ff merge onto the default branch."""
        base = git(self.a, "merge-base", branch, "main")
        git(wt, "reset", "-q", "--soft", base)
        git(wt, "commit", "-qm", "squashed " + branch)
        git(self.a, "merge", "-q", "--no-ff", "-m", "land " + branch, branch)
        return 0, "CLEANUP-RESULT: merged " + git(self.a, "rev-parse", "main")

    def apply(self, notes, tools, **kw):
        payload = {"brief": self.rows["brief_id"], "notes": [{"id": k, "label": k, "note": v} for k, v in notes.items()]}
        return A.apply_all(self.rows, self.d, payload, self.run_dir, self.home, self.ctx_fn, lambda: ({}, True), lambda r_, rw: [], tools,
                           lambda **x: self.asks.append(x), **kw)

    def remote(self):
        return git(self.origin, "rev-parse", "main")


def main():
    tmp = os.path.realpath(tempfile.mkdtemp())

    # ── Push now: range check ────────────────────────────────────────────────
    w = World(tmp, "same")
    check("setup: Ready and Abandoned worktrees, one push row with the commit", w.group("r") == "Ready" and w.group("m") == "Abandoned"
          and len(w.push["commits"]) == 1 and MB.MERGE in w.mrow["options"], (w.group("r"), w.group("m"), w.push["commits"]))
    check("setup: unpushed so far", w.remote() != git(w.a, "rev-parse", "main"))
    res = w.apply({w.push["key"]: MB.PUSH_NOW, w.mrow["key"]: "none"}, w.tools())
    pr = res[w.push["key"]]
    check("identical range: push called once, origin has the tip", pr["status"] == "pushed" and w.calls["push"] == 1 and w.remote() == git(w.a, "rev-parse", "main") and not w.asks, (pr, w.asks))
    check("Ready worktree is pruned after the push, and only then", not os.path.exists(w.P("r")) and git(w.a, "branch", "--list", "r") == "" and os.path.isdir(w.P("m")), pr["text"])

    w = World(tmp, "extra")
    commit(w.a, "late-on-main")  # one more commit after the brief
    res = w.apply({w.push["key"]: MB.PUSH_NOW, w.mrow["key"]: "none"}, w.tools())
    pr = res[w.push["key"]]
    check("one extra commit: ask, no push, origin untouched", pr["status"] == "asked" and w.calls["push"] == 0 and len(w.asks) == 1
          and "late-on-main" in w.asks[0]["question"] and w.remote() != git(w.a, "rev-parse", "main"), (pr, w.asks))
    check("no push means the Ready worktree stays", os.path.isdir(w.P("r")) and git(w.a, "branch", "--list", "r") != "")
    check("the ask fits Agent X limits", all(len(x["question"]) <= 500 and 2 <= len(x["choices"]) <= 6 for x in w.asks))

    w = World(tmp, "failpush")
    res = w.apply({w.push["key"]: MB.PUSH_NOW, w.mrow["key"]: "none"}, w.tools(push_rc=1) | {"push": lambda m, p=None: (1, "boom")})
    check("a push that did not reach origin is a failure and prunes nothing", res[w.push["key"]]["status"] == "failed" and os.path.isdir(w.P("r")), res[w.push["key"]])

    w = World(tmp, "offmain")
    git(w.a, "switch", "-q", "-c", "side")
    res = w.apply({w.push["key"]: MB.PUSH_NOW, w.mrow["key"]: "none"}, w.tools())
    check("main checkout not on default: skipped with a reason, no push", res[w.push["key"]]["status"] == "skipped" and "not main" in res[w.push["key"]]["text"] and w.calls["push"] == 0, res[w.push["key"]])

    # ── Merge and push ───────────────────────────────────────────────────────
    w = World(tmp, "merge")
    shown = {c["sha"] for c in w.push["commits"]}
    res = w.apply({w.push["key"]: MB.PUSH_NOW, w.mrow["key"]: MB.MERGE}, w.tools())
    landed = git(w.a, "rev-list", "origin/main..main")
    mr = res[w.mrow["key"]]
    check("merge and push: the squashed commit is new and the push proceeds", mr["status"] == "merged and pushed" and w.calls["merge"] == 1 and w.calls["push"] == 1
          and w.remote() == git(w.a, "rev-parse", "main") and landed == "", (mr, res[w.push["key"]]))
    check("merge and push: one push covers the push row and the merge", res[w.push["key"]]["status"] == "pushed", res[w.push["key"]])
    check("merge and push: both rows' ranges were widened by exactly the landed span", len(subprocess.run(["git", "-C", w.a, "rev-list", "--count", "main", "^" + git(w.a, "rev-parse", "main~2")], capture_output=True, text=True).stdout.split()) == 1)

    # approved range itself: shown + landed span, nothing more
    w = World(tmp, "approved")
    before = git(w.a, "rev-parse", "main")
    w.squash_merge(w.P("m"), "m")
    span = git(w.a, "rev-list", "--reverse", f"{before}..main").split()
    approved = {c["sha"] for c in w.push["commits"]} | set(span)
    out = SH.push_range(w.d["repos"][0], approved, w.tools(), lambda **k: w.asks.append(k))
    check("approved = shown + landed span: push proceeds", out["status"] == "pushed" and len(span) == 2, out)
    w = World(tmp, "approved2")
    before = git(w.a, "rev-parse", "main")
    w.squash_merge(w.P("m"), "m")
    span = git(w.a, "rev-list", "--reverse", f"{before}..main").split()
    out = SH.push_range(w.d["repos"][0], set(span[:1]) | {c["sha"] for c in w.push["commits"]}, w.tools(), lambda **k: w.asks.append(k))
    check("approving less than the landed span asks", out["status"] == "asked" and w.calls["push"] == 0, out)

    w = World(tmp, "foreign")
    def merge_with_foreign(wt, branch):
        w.squash_merge(wt, branch)
        commit(w.a, "someone-elses")  # another thread lands during /merge
        return 0, "CLEANUP-RESULT: merged x"
    res = w.apply({w.push["key"]: "none", w.mrow["key"]: MB.MERGE}, w.tools(merge=merge_with_foreign))
    check("a foreign commit during the merge: no push, nothing approved for it", res[w.mrow["key"]]["status"] == "landed-foreign" and w.calls["push"] == 0
          and w.remote() != git(w.a, "rev-parse", "main"), res[w.mrow["key"]])

    w = World(tmp, "hold")
    res = w.apply({w.push["key"]: MB.HOLD, w.mrow["key"]: MB.MERGE}, w.tools())
    check("Hold on the push row never approves its range for a merge's push: ask, no push", res[w.mrow["key"]]["status"] == "merged" and w.calls["push"] == 0 and len(w.asks) == 1
          and w.remote() != git(w.a, "rev-parse", "main"), (res[w.mrow["key"]], w.asks))

    w = World(tmp, "mfail")
    res = w.apply({w.push["key"]: "none", w.mrow["key"]: MB.MERGE}, w.tools(merge=lambda wt, b: (1, "conflict")))
    check("a merge that does not land is a failure, and nothing is pushed", res[w.mrow["key"]]["status"] == "failed" and w.calls["push"] == 0, res[w.mrow["key"]])

    w = World(tmp, "mflip")
    git(w.a, "switch", "-q", "-c", "side")
    res = w.apply({w.push["key"]: "none", w.mrow["key"]: MB.MERGE}, w.tools())
    check("merge: a main checkout off default is skipped", res[w.mrow["key"]]["status"] == "skipped" and w.calls["merge"] == 0, res[w.mrow["key"]])

    # ── order: merges, then pushes now ───────────────────────────────────────
    order = []
    w = World(tmp, "order")
    t = w.tools()
    t["merge"] = lambda wt, b: (order.append("merge"), w.squash_merge(wt, b))[1]
    inner = t["push"]
    t["push"] = lambda m, p=None: (order.append("push"), inner(m, p))[1]
    w.apply({w.push["key"]: MB.PUSH_NOW, w.mrow["key"]: MB.MERGE}, t)
    check("order: merge before push", order == ["merge", "push"], order)

    # ── deferred push ────────────────────────────────────────────────────────
    def deferred(name, land):
        w = World(tmp, name, running=True)
        w.push["running"] = ["%s-wt-wr" % name]
        w.push["options"] = [MB.PUSH_NOW, MB.PUSH_LATER, MB.HOLD]
        (w.run_dir / "rows.json").write_text(json.dumps(w.rows))
        res = w.apply({w.push["key"]: MB.PUSH_LATER, w.mrow["key"]: "none"}, w.tools())
        return w, res[w.push["key"]]
    w, pr = deferred("def-ok", None)
    st = json.loads((w.run_dir / "deferred.json").read_text())[w.push["key"]]
    check("deferred: result is waiting, nothing pushed, 24 h deadline and the named branch recorded",
          pr["status"] == "waiting" and w.calls["push"] == 0 and st["branches"] == ["wr"] and st["deadline"] - st["started"] == 24 * 3600, (pr, st))
    git(w.a, "merge", "-q", "--no-ff", "-m", "land wr", "wr")  # the running work lands after approval
    seq = iter(["Running", "Running", "Abandoned"])
    slept = []
    t = w.tools()
    t["sleep"] = slept.append
    out = SH.watch(w.run_dir, w.push["key"], w.d, t, lambda **k: w.asks.append(k), lambda repo, wt: next(seq), emit=lambda s: None)
    check("deferred: every extra commit from the named branch means push", out["status"] == "pushed" and w.calls["push"] == 1 and len(slept) == 2
          and w.remote() == git(w.a, "rev-parse", "main"), (out, slept))

    w, pr = deferred("def-foreign", None)
    git(w.a, "merge", "-q", "--no-ff", "-m", "land wr", "wr")
    commit(w.a, "foreign-commit")
    out = SH.watch(w.run_dir, w.push["key"], w.d, w.tools(), lambda **k: w.asks.append(k), lambda repo, wt: "Abandoned", emit=lambda s: None)
    check("deferred: one foreign commit means ask, no push", out["status"] == "asked" and w.calls["push"] == 0 and "foreign-commit" in w.asks[0]["question"]
          and w.remote() != git(w.a, "rev-parse", "main"), (out, w.asks))

    w, pr = deferred("def-late", None)
    clock = {"t": time.time()}
    t = w.tools()
    t["now"] = lambda: clock["t"]
    t["sleep"] = lambda s: clock.update(t=clock["t"] + 8 * 3600)  # eight hours per poll
    out = SH.watch(w.run_dir, w.push["key"], w.d, t, lambda **k: w.asks.append(k), lambda repo, wt: "Running", emit=lambda s: None)
    check("deferred: the 24 hour limit means ask, no push", out["status"] == "asked" and w.calls["push"] == 0 and "24-hour" in out["text"] and len(w.asks) == 1, (out, w.asks))

    # late update: result, prune after the push, brief rebuilt
    w, pr = deferred("def-late2", None)
    git(w.a, "merge", "-q", "--no-ff", "-m", "land wr", "wr")
    A.merge_results(w.run_dir, {w.push["key"]: pr, **{r_["key"]: {"q": 2, "label": "Left alone", "status": "none", "text": "Left alone."} for r_ in w.rows["abandoned"]}})
    asks = []
    out = SH.watch(w.run_dir, w.push["key"], w.d, w.tools(), lambda **k: asks.append(k), lambda repo, wt: "Abandoned", emit=lambda s: None)
    rc = A.record_late(w.run_dir, w.d, w.push["key"], out, asks, w.home, w.ctx_fn, lambda: ({}, True), lambda r_, rw: [], w.tools())
    late = json.loads((w.run_dir / "results.json").read_text())[w.push["key"]]
    check("deferred landed: result updated and Ready worktrees pruned only after the push", rc == 0 and late["status"] == "pushed" and "Pruned 1 Ready" in late["text"]
          and not os.path.exists(w.P("r")), late)

    w_keep = w
    # ── review fixes ─────────────────────────────────────────────────────────
    # i) the prompt carries the tip, the approved list and the marker lines
    w = World(tmp, "prompt")
    w.apply({w.push["key"]: MB.PUSH_NOW, w.mrow["key"]: "none"}, w.tools())
    pt, approved_sha = w.calls["prompts"][0], w.push["commits"][0]["sha"]
    check("P1 prompt: exact tip, approved SHAs, refuse and pushed markers", git(w.a, "rev-parse", "main") in pt and approved_sha in pt
          and "CLEANUP-RESULT: refused" in pt and "CLEANUP-RESULT: pushed" in pt and "rev-list origin/main..main" in pt, pt)

    # i) another thread lands F between the check and the session, and the session pushes it
    w = World(tmp, "alarm")
    inner = w.tools()["push"]
    def push_with_f(main, prompt=None):
        commit(w.a, "unapproved-F")
        return inner(main, prompt)
    t = w.tools()
    t["push"] = push_with_f
    res = w.apply({w.push["key"]: MB.PUSH_NOW, w.mrow["key"]: "none"}, t)
    pr = res[w.push["key"]]
    check("P1 alarm: an extra pushed commit is an alarm naming it, never success, nothing pruned",
          pr["status"] == "alarm" and "unapproved-F" in pr["text"] and "ALARM" in pr["text"] and os.path.isdir(w.P("r")), pr)

    # iv) a session that exits 0 without the marker is a failure
    w = World(tmp, "nomarker")
    t = w.tools()
    t["push"] = lambda m, p=None: (0, "all done, honest")
    res = w.apply({w.push["key"]: MB.PUSH_NOW, w.mrow["key"]: "none"}, t)
    check("P4 push: rc 0 with no marker is a failure that mentions migrations", res[w.push["key"]]["status"] == "failed" and "migrations" in res[w.push["key"]]["text"], res[w.push["key"]])
    t["push"] = lambda m, p=None: (0, "CLEANUP-RESULT: refused tip moved")
    w = World(tmp, "refusedpush")
    t = w.tools()
    t["push"] = lambda m, p=None: (0, "CLEANUP-RESULT: refused tip moved")
    res = w.apply({w.push["key"]: MB.PUSH_NOW, w.mrow["key"]: "none"}, t)
    check("P4 push: a refused marker is a failure with the reason", res[w.push["key"]]["status"] == "failed" and "tip moved" in res[w.push["key"]]["text"], res[w.push["key"]])

    # iv) /merge: no marker or a stop means refused even when the default branch moved; nothing is pushed
    w = World(tmp, "mrefuse")
    def moved_but_asked(wt, branch):
        w.squash_merge(wt, branch)
        return 0, "I found a problem and need to ask you something"
    res = w.apply({w.push["key"]: MB.PUSH_NOW, w.mrow["key"]: MB.MERGE}, w.tools(merge=moved_but_asked))
    mr = res[w.mrow["key"]]
    check("P4 merge: output with no marker is refused though main moved, the moved range is reported, no push",
          mr["status"] == "refused" and "moved" in mr["text"] and w.calls["push"] == 0 and w.remote() != git(w.a, "rev-parse", "main"), (mr, res[w.push["key"]]))

    # iv) timeout kills the whole process group and says so
    pidf = os.path.join(tmp, "child.pid")
    rc, txt = SH.sh(["sh", "-c", f"sleep 300 & echo $! > {pidf}; wait"], tmp, timeout=1)
    time.sleep(0.3)
    pid = int(open(pidf).read())
    try:
        os.kill(pid, 0)
        alive = True
    except OSError:
        alive = False
    check("P4 timeout: rc 124, the child is dead, the text says state unknown, check migrations", rc == 124 and not alive and "timed out, state unknown, check migrations" in txt, (rc, alive, txt))
    w = World(tmp, "timeout")
    t = w.tools()
    t["push"] = lambda m, p=None: (124, "timed out, state unknown, check migrations. partial")
    res = w.apply({w.push["key"]: MB.PUSH_NOW, w.mrow["key"]: "none"}, t)
    check("P4 timeout: the result records it", res[w.push["key"]]["status"] == "failed" and "state unknown, check migrations" in res[w.push["key"]]["text"], res[w.push["key"]])

    # iv) the headless command carries an explicit permission mode and the marker prompt
    seen = []
    real_sh, SH.sh = SH.sh, lambda cmd, cwd, timeout=0: (seen.append(cmd), (0, ""))[1]
    try:
        rt_ = SH.real_tools()
        rt_["push"]("/x", "PROMPT"), rt_["merge"]("/x", "b")
    finally:
        SH.sh = real_sh
    check("P4 real runner: --permission-mode is explicit on both runners", all(c[:4] == ["claude", "-p", "--permission-mode", "bypassPermissions"] for c in seen) and len(seen) == 2 and seen[0][-1] == "PROMPT", seen)

    # ii) a Push when the running work lands row keeps its watcher even when the repo also has a merge row
    w = World(tmp, "later-merge", running=True)
    w.push["running"] = ["later-merge-wt-wr"]
    w.push["options"] = [MB.PUSH_NOW, MB.PUSH_LATER, MB.HOLD]
    (w.run_dir / "rows.json").write_text(json.dumps(w.rows))
    res = w.apply({w.push["key"]: MB.PUSH_LATER, w.mrow["key"]: MB.MERGE}, w.tools())
    check("P2 push-later + merge: the push row waits, its range is not shipped by the merge push",
          res[w.push["key"]]["status"] == "waiting" and res[w.mrow["key"]]["status"] == "merged" and w.calls["push"] == 0
          and w.remote() != git(w.a, "rev-parse", "main") and (w.run_dir / "deferred.json").exists(), (res[w.push["key"]], res[w.mrow["key"]]))

    # iii) the running session crashed and its work never landed: ask, no push
    w, pr = deferred("def-crash", None)
    out = SH.watch(w.run_dir, w.push["key"], w.d, w.tools(), lambda **k: w.asks.append(k), lambda repo, wt: "Abandoned", emit=lambda s: None)
    check("P2 deferred: no longer Running but never landed means ask, no push", out["status"] == "asked" and w.calls["push"] == 0 and "wr" in w.asks[0]["question"]
          and w.remote() != git(w.a, "rev-parse", "main"), (out, w.asks))
    # ...and a squash landing (new SHA, same files) counts as landed
    w, pr = deferred("def-squash", None)
    w.squash_merge(w.P("wr"), "wr")
    out = SH.watch(w.run_dir, w.push["key"], w.d, w.tools(), lambda **k: w.asks.append(k), lambda repo, wt: "Abandoned", emit=lambda s: None)
    check("P2 deferred: a squash-merged branch counts as landed", out["status"] == "pushed" and w.calls["push"] == 1, (out, w.asks))

    # v) only the work's own commits count, not older commits the tip happens to descend from
    w5 = World(tmp, "scope")
    mt = git(w5.a, "rev-parse", "m")
    base = git(w5.a, "rev-parse", "main")
    old, own = git(w5.a, "rev-parse", "main"), mt
    check("P3 scope: an older commit under the tip is not the work's; the tip's own commit is",
          not SH.reachable_from_work(w5.a, old, [mt], base) and SH.reachable_from_work(w5.a, own, [mt], base))

    w = w_keep
    # ── brief and public-repo hygiene ────────────────────────────────────────
    md = MB.render(w.rows, False, json.loads((w.run_dir / "results.json").read_text()), "r2-x")
    check("round two shows the deferred row", "## Your Q" in md and "Pushed" in md)
    src = Path(HERE, "ship.py").read_text() + Path(HERE, "test_ship.py").read_text()
    check("no absolute user path in the new files", "/Users/" not in src.replace('"/Users/" not in', ""))
    print("\nall checks pass" if not FAILS else f"\n{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
