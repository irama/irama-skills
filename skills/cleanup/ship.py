#!/usr/bin/env python3
"""Shipping rows for /cleanup: push now, merge and push, push when the running work lands.

Spec: docs/specs/cleanup.md section 6; ADR 0001 decision 3. The returned brief counts as the owner
invoking /push for one repo and one commit range, and nothing else. Any change to the range goes
back as an Agent X ask. Every outside effect is injected (`tools`), so tests use synthetic repos
with a bare-repo origin and never run a real /push or /merge.

    tools = {"push": f(main_path) -> (rc, text),         # runs the /push skill's steps in that repo
             "merge": f(worktree_path, branch) -> (rc, text),  # runs the /merge skill's steps there
             "sleep": f(seconds), "now": f() -> epoch}

CLI (started under a Monitor by the thread, 24 h limit):
    ship.py deferred <run-dir> <row-key> [--self-cwd DIR]
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import discover as D  # noqa: E402

LIMIT = 24 * 3600
POLL = 60
FETCH_TIMEOUT = 60
RUN_TIMEOUT = 3 * 3600


def main_of(repo):
    return next((x["path"] for x in repo["worktrees"] if x.get("is_main")), repo["path"])


MARKER = re.compile(r"^CLEANUP-RESULT: (pushed|merged|refused)\b(.*)$", re.M)
TIMED_OUT = "timed out, state unknown, check migrations"


def parse_marker(text):
    """(verb, rest) of the LAST CLEANUP-RESULT line, or (None, ""). Nothing else in the output counts."""
    m = MARKER.findall(text or "")
    return (m[-1][0], m[-1][1].strip()) if m else (None, "")


def sh(cmd, cwd, timeout=RUN_TIMEOUT):
    """Run cmd in its own process group; on timeout kill the whole group. Returns (rc, tail of output)."""
    try:
        p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    except OSError as e:
        return 127, str(e)
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, (out or "")[-2000:]
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        out, _ = p.communicate()
        return 124, f"{TIMED_OUT}. " + (out or "")[-1500:]


def push_prompt(default, tip, shas):
    return (f"/push\n\nThis run is a /cleanup shipping step. The owner approved pushing exactly these {len(shas)} commit(s) of {default}: "
            f"{' '.join(shas)}. The expected tip of local {default} is {tip}.\n"
            f"First run `git fetch origin {default}` and `git rev-list origin/{default}..{default}`. If that list differs in any way from the approved commits "
            f"(extra, missing or a different tip), push nothing, stop, and print as the last line `CLEANUP-RESULT: refused <reason>`. "
            f"Otherwise run /push's steps. If you finish with the push done, print as the last line `CLEANUP-RESULT: pushed <sha>`. "
            f"If anything stops or asks you, print `CLEANUP-RESULT: refused <reason>`. Never ask a question.")


def merge_prompt(branch):
    return (f"/merge\n\nThis run is a /cleanup shipping step for branch {branch} only. If /merge would stop, ask a question or report a finding, "
            f"do not work around it: print as the last line `CLEANUP-RESULT: refused <reason>`. If the merge lands, print `CLEANUP-RESULT: merged <sha>`. Never ask a question.")


def real_tools():
    """A headless Claude run of the skill, with the repo's own folder as cwd (claims are keyed by it). Not run by tests."""
    base = ["claude", "-p", "--permission-mode", "bypassPermissions"]  # nobody can answer a prompt; the prompt text and the post-run remote check bound the run
    return {"push": lambda main, prompt: sh([*base, prompt], main),
            "merge": lambda wt, branch: sh([*base, merge_prompt(branch)], wt),
            "sleep": time.sleep, "now": time.time}


# ── ranges ───────────────────────────────────────────────────────────────────

def ahead(main, default):
    """Commits on local <default> that origin/<default> lacks, oldest first."""
    rc, o = D.git(main, "rev-list", "--reverse", f"origin/{default}..{default}")
    return o.split() if rc == 0 else None


def preflight(repo, tools=None):
    """(main, why): why is a one-line reason to skip the repo, else None. Also refreshes origin/<default>."""
    main, default = main_of(repo), repo["default_branch"]
    if not repo.get("has_origin"):
        return main, "it has no origin remote"
    rc, o = D.git(main, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0 or o.strip() != default:
        return main, f"its main checkout is on {o.strip() or 'an unknown branch'}, not {default}"
    rc, _ = D.git(main, "fetch", "--no-tags", "-q", "origin", default, timeout=FETCH_TIMEOUT)
    if rc != 0:
        return main, "fetching origin failed, so the range cannot be checked"
    return main, None


def work_commits(main, tips, base):
    """The named work's own commits: reachable from a tip, not from `base` (the default branch's tip before the work landed)."""
    out = set()
    for t in tips:
        rc, o = D.git(main, "rev-list", t, f"^{base}")
        out |= set(o.split()) if rc == 0 else set()
    return out


def reachable_from_work(main, c, tips, base):
    """True if commit c is one of the work's own commits (tip ^base), or the merge commit that landed them."""
    own = work_commits(main, tips, base)
    if c in own:
        return True
    rc, o = D.git(main, "rev-list", "--parents", "-n", "1", c)
    parents = o.split()[1:] if rc == 0 else []
    return len(parents) > 1 and any(p in own for p in parents[1:])


def branch_landed(main, default, tip):
    """True if the branch tip's work is on local <default>: an ancestor, patch-equivalent per commit (git cherry), or, for a squash, every file it touched reads the same on both."""
    if D.git(main, "merge-base", "--is-ancestor", tip, default)[0] == 0:
        return True
    rc, o = D.git(main, "cherry", default, tip)
    if rc == 0 and not any(l.startswith("+") for l in o.splitlines()):
        return True
    rc, mb = D.git(main, "merge-base", default, tip)
    if rc != 0:
        return False
    rc, o = D.git(main, "diff", "--name-only", mb.strip(), tip)
    files = o.split("\n") if rc == 0 else []
    files = [f for f in files if f]
    return bool(files) and D.git(main, "diff", "--quiet", default, tip, "--", *files)[0] == 0


def short(c):
    return c[:7]


def range_text(main, shas):
    out = []
    for c in shas[:12]:
        rc, o = D.git(main, "log", "-1", "--format=%h %s", c)
        out.append(o.strip() if rc == 0 else short(c))
    return "; ".join(out) + (f"; and {len(shas) - 12} more" if len(shas) > 12 else "")


def remote_tip(main, default):
    """Fresh tip of <default> on the remote (ls-remote, not the cached ref), or None."""
    rc, o = D.git(main, "ls-remote", "origin", f"refs/heads/{default}", timeout=FETCH_TIMEOUT)
    return o.split()[0] if rc == 0 and o.split() else None


def push_range(repo, approved, tools, ask_fn, named_tips=None, label="push", base=None):
    """Push the repo only when local <default> holds nothing beyond `approved` (a set of SHAs) except commits from `named_tips`.
    The headless session is told the exact tip and range; afterwards the remote tip must equal that tip.
    Returns {"status", "text", "pushed": [shas]}; status is pushed, asked, failed, alarm or skipped."""
    main, why = preflight(repo, tools)
    name = Path(repo["path"]).name
    if why:
        return {"status": "skipped", "text": f"Skipped: {why}. Nothing was pushed.", "pushed": []}
    default = repo["default_branch"]
    now = ahead(main, default)
    if now is None:
        return {"status": "failed", "text": "Stopped: could not read the range to push. Nothing was pushed.", "pushed": []}
    if not now:
        return {"status": "pushed", "text": "Nothing to push: the remote already has every commit.", "pushed": []}
    work_base = base or (D.git(main, "merge-base", f"origin/{default}", default)[1].strip() or f"origin/{default}")
    extra = [c for c in now if c not in approved and not (named_tips and reachable_from_work(main, c, named_tips, work_base))]
    if extra:
        txt = (f"{name}: {len(extra)} commit(s) on {default} were not in the range you approved ({range_text(main, extra)}). "
               f"The whole range is now {len(now)} commits. Push it?")
        ask_fn(question=txt[:500], choices=["Leave it for next cleanup", "Re-check and apply now"])
        return {"status": "asked", "text": f"Nothing was pushed: {len(extra)} commit(s) not in the approved range ({range_text(main, extra)}). An Agent X ask went out.", "pushed": []}
    tip = D.git(main, "rev-parse", default)[1].strip()
    before = D.git(main, "rev-parse", f"origin/{default}")[1].strip()
    rc, out = tools["push"](main, push_prompt(default, tip, now))
    verb, rest = parse_marker(out)
    D.git(main, "fetch", "--no-tags", "-q", "origin", default, timeout=FETCH_TIMEOUT)
    rt = remote_tip(main, default)  # success is read from the remote, never from the exit code or the session's words
    timed = f" The run {TIMED_OUT}." if rc == 124 else ""
    if rt is None:
        return {"status": "failed", "text": f"Could not read the remote tip after /push (exit {rc}), so the result is unknown.{timed} {out.strip()[-200:]}", "pushed": []}
    if rt != tip and rt != before:
        # The remote moved to something other than the approved tip: another thread's commit went out with ours, or instead of it.
        rc2, o = D.git(main, "rev-list", "--reverse", f"{before}..{rt}")
        unapproved = [c for c in (o.split() if rc2 == 0 else []) if c not in approved and not (named_tips and reachable_from_work(main, c, named_tips, work_base))]
        names = range_text(main, unapproved) if unapproved else "could not be listed"
        return {"status": "alarm", "text": f"ALARM: origin/{default} is at {short(rt)}, not the approved tip {short(tip)}. Unapproved commit(s) may have been pushed: {names}.{timed} Check origin now.", "pushed": []}
    if rt == tip and verb == "pushed":
        return {"status": "pushed", "text": f"Pushed {len(now)} commit(s) to origin/{default} ({short(now[0])}..{short(now[-1])}) through /push's steps.", "pushed": now}
    if rt == tip:
        return {"status": "failed", "text": f"origin/{default} holds the approved tip, but the session did not report a CLEANUP-RESULT of pushed (exit {rc}, saw {verb or 'no marker'}), so this is not counted as a success.{timed} Check it, and check migrations.", "pushed": []}
    why = rest if verb == "refused" else f"no CLEANUP-RESULT marker (exit {rc})" if verb is None else f"exit {rc}"
    return {"status": "failed", "text": f"/push did not finish: {why}; origin/{default} is unchanged.{timed} /push may have applied migrations before it failed: check them. {out.strip()[-200:]}", "pushed": []}


# ── merge and push ───────────────────────────────────────────────────────────

def merge_branch(repo, w, tools):
    """Run /merge's steps from the worktree. Returns {"status", "text", "landed": [shas]}.
    /merge squashes, so the landed SHAs are new: the span is <default>'s tip before to after."""
    main, why = preflight(repo, tools)
    if why:
        return {"status": "skipped", "text": f"Skipped: {why}. Nothing was merged.", "landed": []}
    default, branch = repo["default_branch"], w["branch"]
    before = D.git(main, "rev-parse", default)[1].strip()
    rc, out = tools["merge"](w["path"], branch)
    after = D.git(main, "rev-parse", default)[1].strip()
    verb, rest = parse_marker(out)
    timed = f" The run {TIMED_OUT}." if rc == 124 else ""
    if verb != "merged":
        if after == before:
            return {"status": "failed", "text": f"/merge did not land the branch ({rest or 'no CLEANUP-RESULT marker'}; exit {rc}).{timed} {out.strip()[-200:]}", "landed": []}
        _, o = D.git(main, "rev-list", "--reverse", f"{before}..{after}")
        return {"status": "refused", "text": f"/merge stopped or asked ({rest or 'no CLEANUP-RESULT marker'}; exit {rc}) but {default} moved: {range_text(main, o.split())}. Nothing will be pushed; check that range.{timed}", "landed": []}
    if after == before:
        return {"status": "failed", "text": "/merge reported success but the default branch did not move, so nothing was landed.", "landed": []}
    rc, o = D.git(main, "rev-list", "--reverse", f"{before}..{after}")
    span = o.split() if rc == 0 else []
    tip = D.git(main, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")[1].strip()
    # A foreign commit that landed during the merge must not ride in on this approval.
    foreign = [c for c in span if not (tip and reachable_from_work(main, c, [tip], before))]
    if foreign:
        return {"status": "landed-foreign", "text": f"Merged, but {len(foreign)} other commit(s) landed on {default} meanwhile ({range_text(main, foreign)}), so nothing will be pushed.", "landed": span, "foreign": foreign}
    return {"status": "merged", "text": f"Merged {branch} onto {default} through /merge's steps ({len(span)} new commit(s), {short(span[0])}..{short(span[-1])}).", "landed": span}


# ── deferred push ────────────────────────────────────────────────────────────

def start_deferred(run_dir, row, repo, ctx, now):
    """Record what the Monitor will wait for. The state file is the contract with `ship.py deferred`."""
    names = set(row.get("running") or [])
    named = [w for w in repo["worktrees"] if Path(w["path"]).name in names]
    branches = sorted({w["branch"] for w in named if w.get("branch")})
    for r in D.load_runs(repo, ctx):  # a driver run's integration branch counts as the work it lands
        if r.get("branch") and (r["branch"] in branches or any(os.path.realpath(w["path"]) in r["work"] for w in named)):
            branches.append(r["branch"])
    st = {"key": row["key"], "repo": repo["path"], "approved": [c["sha"] for c in row["commits"]], "running": sorted(names),
          "branches": sorted(set(branches)), "base": D.git(main_of(repo), "rev-parse", repo["default_branch"])[1].strip(), "started": now, "deadline": now + LIMIT}
    f = Path(run_dir) / "deferred.json"
    try:
        data = json.loads(f.read_text())
    except (OSError, ValueError):
        data = {}
    data[row["key"]] = st
    f.write_text(json.dumps(data, indent=1))
    return st


def work_landed(st, repo, fresh_group_fn):
    """The named running work is done when none of its worktrees still reads Running (claims cleared, run finished)."""
    for w in repo["worktrees"]:
        if Path(w["path"]).name in set(st["running"]) and fresh_group_fn(repo, w) == "Running":
            return False
    return True


def finish_deferred(st, repo, tools, ask_fn, timed_out=False):
    """The Monitor ended. Push only if every extra commit is reachable from the work the row named; else ask."""
    name = Path(repo["path"]).name
    if timed_out:
        main = main_of(repo)
        now = ahead(main, repo["default_branch"]) or []
        txt = f"{name}: the running work had not landed after 24 hours, so nothing was pushed. {len(now)} commits wait on {repo['default_branch']}. Push them now?"
        ask_fn(question=txt[:500], choices=["Leave it for next cleanup", "Re-check and apply now"])
        return {"status": "asked", "text": "Nothing was pushed: the 24-hour limit passed before the running work landed. An Agent X ask went out.", "pushed": []}
    main = main_of(repo)
    tips = [t for t in (D.git(main, "rev-parse", "--verify", "-q", f"refs/heads/{b}")[1].strip() for b in st["branches"]) if t]
    default = repo["default_branch"]
    unlanded = [b for b in st["branches"] if not branch_landed(main, default, D.git(main, "rev-parse", "--verify", "-q", f"refs/heads/{b}")[1].strip() or "missing")]
    if unlanded or (st["running"] and not st["branches"]):
        what = ", ".join(unlanded) or "the named work"
        txt = f"{name}: the running work stopped, but {what} is not on {default}, so nothing was pushed. Push anyway, or leave it?"
        ask_fn(question=txt[:500], choices=["Leave it for next cleanup", "Re-check and apply now"])
        return {"status": "asked", "text": f"Nothing was pushed: {what} stopped running without landing on {default}. An Agent X ask went out.", "pushed": []}
    return push_range(repo, set(st["approved"]), tools, ask_fn, named_tips=tips, base=st.get("base"))


def watch(run_dir, key, d, tools, ask_fn, fresh_group_fn, emit=print):
    """Blocking loop for the Monitor: wait for the named work, then finish. Returns the result dict."""
    st = json.loads((Path(run_dir) / "deferred.json").read_text())[key]
    repo = next(r for r in d["repos"] if r["path"] == st["repo"])
    while True:
        if work_landed(st, repo, fresh_group_fn):
            emit(f"{key}: the running work landed; checking the range")
            return finish_deferred(st, repo, tools, ask_fn)
        if tools["now"]() >= st["deadline"]:
            emit(f"{key}: 24-hour limit reached")
            return finish_deferred(st, repo, tools, ask_fn, timed_out=True)
        tools["sleep"](POLL)


def main(argv=None):
    import apply as A  # noqa: E402  (the apply module owns results.json and the round-two rebuild)
    import make_brief as MB
    import prune_auto as PA
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["deferred"])
    ap.add_argument("run_dir")
    ap.add_argument("key")
    ap.add_argument("--self-cwd", default=os.getcwd())
    a = ap.parse_args(argv)
    run_dir, home = Path(a.run_dir), Path.home()
    d = json.loads((run_dir / "discover.json").read_text())
    ctx_fn = lambda ok: D.build_ctx(home, ok, a.self_cwd)
    orca_fn = lambda: D.load_orca(argparse.Namespace(no_orca=False, orca_json=None))
    claims_fn = D.load_claims(home)

    def fresh_group(repo, w):
        f = PA.fresh_facts(repo, w, ctx_fn, orca_fn, claims_fn)
        return f["group"] if f else "gone"
    asks = []
    res = watch(run_dir, a.key, d, real_tools(), lambda **k: asks.append(k), fresh_group)
    A.record_late(run_dir, d, a.key, res, asks, home, ctx_fn, orca_fn, claims_fn)
    print(f"{a.key}: {res['status']}: {res['text']}")
    print("asks to post: " + str(len(asks)) + " (in asks.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
