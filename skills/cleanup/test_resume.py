#!/usr/bin/env python3
"""Hermetic self-check for resume.py and its place in apply.py. Run: python3 skills/cleanup/test_resume.py

Synthetic repo in a temp folder and a temp HOME. `orca` launches and the done bubbles are stubs: nothing real starts or posts.
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
import resume as R  # noqa: E402

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


def main():
    tmp = os.path.realpath(tempfile.mkdtemp())
    home = Path(tmp, "home")
    run_dir = home / ".claude" / "cleanup" / "2026-01-02-0304"
    run_dir.mkdir(parents=True)
    a, origin = os.path.join(tmp, "a"), os.path.join(tmp, "a-origin.git")
    os.makedirs(a)
    git(a, "init", "-q", "-b", "main")
    open(os.path.join(a, "base"), "w").write("base")
    git(a, "add", "base")
    git(a, "commit", "-qm", "base")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True, env=GENV)
    git(a, "remote", "add", "origin", origin)
    git(a, "push", "-q", "origin", "main")
    git(a, "fetch", "-q", "origin")
    git(a, "remote", "set-head", "origin", "main")
    P = lambda n: os.path.join(tmp, "wt-" + n)
    names = ["r1", "r2", "r3", "r4", "busy", "plain"]
    for n in names:
        git(a, "worktree", "add", "-q", "-b", n, P(n), "main")
        open(os.path.join(P(n), "HANDOFF.md"), "w").write(
            f"# Handoff for branch {n}\n\nDone: part one.\n\nNext step, run in a new thread:\n\n`/to-driver {P(n)}/HANDOFF.md`\n")
        git(P(n), "add", "HANDOFF.md")
        git(P(n), "commit", "-qm", "handoff " + n)
    now = time.time()
    orca = {os.path.realpath(P(n)): {"id": f"repo-1::{P(n)}", "repoId": "repo-1", "isUnread": False, "isPinned": False,
                                     "lastActivityAt": int((now - (2 * 3600 if n == "busy" else 5 * 86400)) * 1000)}
            for n in names if n != "plain"}  # "plain" is not an Orca worktree
    ctx_fn = lambda ok: {"now": time.time(), "sessions": [], "proc_cwds": [], "parked": D.load_parked(home),
                         "self_cwd": "/nonexistent", "orca_ok": ok, "tmp": tmp}
    r = D.process_repo(Path(a), orca, False, lambda r_, rows: [])
    D.mark_nesting([r])
    D.classify_all([r], ctx_fn(True))
    d = {"repos": [r], "groups": {}, "counts": {"repos": 1, "worktrees": len(r["worktrees"]), "fetch_failures": 0}}
    G = lambda n: next(w for w in d["repos"][0]["worktrees"] if w["path"] == P(n))
    check("setup: every fixture worktree is Abandoned", all(G(n)["group"] == "Abandoned" for n in names), {n: (G(n)["group"], G(n)["reason"]) for n in names})
    rows = MB.build_rows(d, run_dir, run_dir.name, "/nonexistent", home=home)
    MB.render(rows)
    (run_dir / "rows.json").write_text(json.dumps(rows, indent=1))
    rowof = {x["name"]: x for x in rows["abandoned"]}
    k = lambda n: rowof["wt-" + n]["key"]
    check("setup: Resume is offered on every row", all(MB.RESUME in rowof["wt-" + n]["options"] for n in names), [rowof["wt-" + n]["options"] for n in names])

    # ── the handoff's own command ───────────────────────────────────────────
    check("prompt is the handoff's own next command", R.handoff_command(f"{P('r1')}/HANDOFF.md") == f"/to-driver {P('r1')}/HANDOFF.md", R.handoff_command(f"{P('r1')}/HANDOFF.md"))
    open(os.path.join(tmp, "bare.md"), "w").write("No command here. See /tmp/x and the folder named above.\n")
    check("a handoff with no command gets /to-driver and its path", R.handoff_command(os.path.join(tmp, "bare.md")) == f"/to-driver {os.path.join(tmp, 'bare.md')}")

    # ── three launches, the rest get bubbles ────────────────────────────────
    launches, asks, dones = [], [], []

    def orca_launch(sel, prompt):
        launches.append((sel, prompt))
        return 0, json.dumps({"id": "x", "ok": True, "result": {"launch": {"outcome": {"kind": "structured", "handle": f"h{len(launches)}"},
                                                                             "prompt": {"outcome": "journaled"}}}})

    tools = {"orca_rm": lambda p: (1, "no"), "kill_repo": lambda p: (0, ""), "orca_launch": orca_launch}
    payload = {"brief": rows["brief_id"], "notes": [{"id": k(n), "label": n, "note": MB.RESUME} for n in names]}
    res = A.apply_all(rows, d, payload, run_dir, home, ctx_fn, lambda: (orca, True), lambda r_, rw: [], tools,
                      lambda **x: asks.append(x), now=now, done_fn=lambda **x: dones.append(x))
    st = lambda n: res[k(n)]["status"]
    check("exactly three launches ran", len(launches) == 3, launches)
    check("launch uses id:<repoId>::<path> and the handoff command",
          all(s.startswith("id:repo-1::" + tmp) and p.startswith("/to-driver ") and p.endswith("/HANDOFF.md") for s, p in launches), launches)
    launched = [n for n in names if st(n) == "launched"]
    check("three rows read launched, with a receipt", len(launched) == 3 and all(res[k(n)]["receipt"]["handle"] for n in launched), launched)
    check("the fourth ready row got a done bubble, not a launch", st("r4") == "bubble" and "most it starts" in res[k("r4")]["text"], res[k("r4")])
    check("the worktree active 2 hours ago was not launched and got a bubble",
          st("busy") == "bubble" and "active in the last 24 hours" in res[k("busy")]["text"] and not any("wt-busy" in s for s, _ in launches), res[k("busy")])
    check("the non-Orca worktree got a bubble", st("plain") == "bubble" and "cannot target" in res[k("plain")]["text"], res[k("plain")])
    check("three bubbles, each carries the same command as its prompt would", len(dones) == 3 and all(x["copy"].startswith("/to-driver ") and len(x["note"]) <= 200 for x in dones), dones)
    check("no thread was started for a bubbled row", len(launches) == 3)
    check("nothing else changed: folders still there", all(os.path.isdir(P(n)) for n in names))

    # ── a failed launch becomes a bubble, a prior launch counts toward the cap ──
    one = rowof["wt-r1"]
    out = R.resume(one, {"orca": orca[os.path.realpath(P("r1"))]}, {"orca_launch": lambda s, p: (1, "orca: boom")}, now, 0)
    check("failed launch -> launch uncertain, no bubble, retry hint", out["status"] == "launch uncertain" and "bubble" not in out and "--retry-launch" in out["text"], out)
    out = R.resume(one, {"orca": orca[os.path.realpath(P("r1"))]}, {"orca_launch": lambda s, p: (0, json.dumps({"ok": True, "result": {"launch": {"prompt": {"outcome": "dropped"}}}}))}, now, 0)
    check("a prompt that was not delivered is uncertain, not a success", out["status"] == "launch uncertain" and "bubble" not in out, out)
    out = R.resume(one, {"orca": orca[os.path.realpath(P("r1"))]}, {"orca_launch": lambda s, p: (0, json.dumps({"ok": False, "operationId": "op-9"}))}, now, 0)
    check("uncertain launch carries the operationId", "op-9" in out["text"], out)
    out = R.resume(one, {"orca": orca[os.path.realpath(P("r1"))]}, {"orca_launch": orca_launch}, now, 3)
    check("already three this run -> bubble", out["status"] == "bubble")
    check("activity exactly inside 24 h blocks, just outside does not",
          R.active_recently({"lastActivityAt": int((now - 23.9 * 3600) * 1000)}, now) and not R.active_recently({"lastActivityAt": int((now - 24.1 * 3600) * 1000)}, now))

    # ── a fresh live card (under 30 min) is an ask through the re-check, not a launch ──
    orca[os.path.realpath(P("r1"))]["lastActivityAt"] = int((now - 60) * 1000)
    (run_dir / "results.json").unlink(missing_ok=True)
    launches.clear()
    asks.clear()
    res = A.apply_all(rows, d, {"brief": rows["brief_id"], "notes": [{"id": k("r1"), "label": "r1", "note": MB.RESUME}]}, run_dir, home, ctx_fn,
                      lambda: (orca, True), lambda r_, rw: [], tools, lambda **x: asks.append(x), now=now, only=k("r1"))
    check("a card active a minute ago: re-check asks, no launch", res[k("r1")]["status"] == "asked" and not launches and asks, res[k("r1")])

    # ── review fixes ────────────────────────────────────────────────────────
    def hf(name, body):
        p = os.path.join(tmp, name)
        open(p, "w").write(body)
        return p
    real = hf("real.md", "x")
    for verb in ("/flush", "/push"):
        p = hf("h-" + verb[1:] + ".md", f"# h\n\n- `{verb}` ships it\n")
        check(f"a last line of {verb} falls back", R.handoff_command(p) == f"/to-driver {p}", R.handoff_command(p))
    p = hf("h-tmp.md", "`/to-driver /tmp/x-does-not-exist`\n")
    check("a to-driver line whose file does not exist falls back", R.handoff_command(p) == f"/to-driver {p}", R.handoff_command(p))
    p = hf("h-rel.md", "`/to-driver docs/x.md`\n")
    check("a relative argument falls back", R.handoff_command(p) == f"/to-driver {p}")
    p = hf("h-ok.md", f"`/driver {real}`\n")
    check("/driver with an existing file is kept", R.handoff_command(p) == f"/driver {real}")
    runs = os.path.join(tmp, "x", ".scratch", "driver-runs", "r9")
    os.makedirs(runs)
    p = hf("h-dir.md", f"`/driver {runs}`\n")
    check("/driver with a driver-runs folder is kept", R.handoff_command(p) == f"/driver {runs}")
    p = hf("h-dir2.md", f"`/driver {tmp}`\n")
    check("/driver with another folder falls back", R.handoff_command(p) == f"/to-driver {p}")
    check("the brief row shows the exact command", f"/to-driver {P('r1')}/HANDOFF.md" in MB.road_costs(rowof["wt-r1"])[MB.RESUME], MB.road_costs(rowof["wt-r1"])[MB.RESUME])

    # handoff choice
    o1, o2 = hf("o1.md", "a"), hf("o2.md", "b")
    outside = {"repo": "a", "name": "n", "path": os.path.join(tmp, "nowhere"), "handoffs": [o1, o2]}
    out = R.resume(outside, {"orca": orca[os.path.realpath(P("r2"))]}, {"orca_launch": orca_launch}, now, 0)
    check("two outside handoffs -> an ask, no launch", out["status"] == "asked" and out["ask"]["choices"] == ["o1.md", "o2.md"], out)
    inside = dict(outside, path=P("r2"), handoffs=[o1, f"{P('r2')}/HANDOFF.md", o2])
    check("a handoff inside the worktree wins over a newer outside one", R.pick_handoff(inside)[0] == f"{P('r2')}/HANDOFF.md")
    check("one outside handoff is used", R.pick_handoff(dict(outside, handoffs=[o1]))[0] == o1)

    # uncertain launch counts toward the cap, and --only never re-runs launched or uncertain rows
    def apply_with(tools_, keys, **kw):
        notes = [{"id": k(n), "label": n, "note": MB.RESUME} for n in keys]
        sub = dict(rows, push=[], abandoned=[rowof["wt-" + n] for n in keys])
        return A.apply_all(sub, d, {"brief": rows["brief_id"], "notes": notes}, run_dir, home, ctx_fn, lambda: (orca, True),
                           lambda r_, rw: [], tools_, lambda **x: asks.append(x), now=now, done_fn=lambda **x: dones.append(x), **kw)
    for n in [x for x in names if x != "plain"]:
        orca[os.path.realpath(P(n))]["lastActivityAt"] = int((now - 5 * 86400) * 1000)
    (run_dir / "results.json").unlink(missing_ok=True)
    launches.clear(); dones.clear()
    uncertain = dict(tools, orca_launch=lambda s, p: (launches.append((s, p)) or (1, "timeout")))
    res = apply_with(uncertain, ["r1", "r2", "r3", "r4"])
    check("three uncertain launches fill the cap, the fourth is bubbled", [res[k(n)]["status"] for n in ("r1", "r2", "r3", "r4")] == ["launch uncertain"] * 3 + ["bubble"], {n: res[k(n)]["status"] for n in ("r1", "r2", "r3", "r4")})
    check("an uncertain row posts no bubble (only the capped row did)", len(dones) == 1, dones)
    n0 = len(launches)
    apply_with(tools, ["r1"], only=k("r1"))
    check("--only does not re-run an uncertain row", len(launches) == n0)
    apply_with(tools, ["r2"], only=k("r2"), retry_launch=True)
    check("--retry-launch re-runs an uncertain row", len(launches) == n0 + 1 and "r2" in launches[-1][0], launches[-2:])
    (run_dir / "results.json").unlink(missing_ok=True)
    launches.clear()
    apply_with(tools, ["r1"])
    apply_with(tools, ["r1"], only=k("r1"))
    check("--only does not re-run a launched row", len(launches) == 1, launches)

    # an interrupted apply keeps the first launch's result
    (run_dir / "results.json").unlink(missing_ok=True)
    launches.clear()

    def boom(sel, prompt):
        if launches:
            raise RuntimeError("interrupted")
        return orca_launch(sel, prompt)
    try:
        apply_with(dict(tools, orca_launch=boom), ["r1", "r2"])
    except RuntimeError:
        pass
    saved = json.loads((run_dir / "results.json").read_text())
    check("the first launch was saved before the interruption", [v["status"] for v in saved.values()] == ["launched"], saved)
    launches.clear()
    apply_with(tools, ["r1", "r2"])
    check("a re-run launches only the row that never ran", len(launches) == 1, launches)
    check("no temp file left behind", not (run_dir / "results.json.tmp").exists())
    print("FAILED: " + ", ".join(FAILS) if FAILS else "all checks pass")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
