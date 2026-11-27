#!/usr/bin/env python3
"""Discover every git repo and worktree under the home folder, with raw git facts.

Prints JSON. Read-only except for one `git fetch origin <default>` per repo.
Usage: discover.py [--orca-json FILE] [--no-orca] [--no-fetch] [--report] [--self-cwd DIR]
Facts (spec section 1), then one group and reason per worktree and one push row per repo
(spec section 2, rules 0 to 6).
"""
import argparse
import datetime
import importlib.util
import json
import os
import re
import tempfile
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SKIP_NAMES = {"node_modules", ".next", ".venv", "venv", "dist", "build", ".cache"}
MAX_DEPTH = 5
FETCH_TIMEOUT = 20
GIT_TIMEOUT = 30
MAX_NAMES = 200

ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")


def git(path, *args, timeout=GIT_TIMEOUT):
    """Run git in path; return (returncode, stdout). Never raises."""
    try:
        r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                           env=ENV, timeout=timeout)
        return r.returncode, r.stdout
    except (subprocess.TimeoutExpired, OSError):
        return 124, ""


def out(path, *args):
    rc, o = git(path, *args)
    return o.strip() if rc == 0 else None


def load_config(home):
    try:
        cfg = json.loads((home / ".claude" / "cleanup.json").read_text())
    except (OSError, ValueError):
        cfg = {}
    ex = lambda k: [Path(os.path.expanduser(p)) for p in cfg.get(k, []) if isinstance(p, str)]
    return ex("exclude"), ex("extra_roots")


def find_repos(roots, home, excludes):
    """Folders holding a `.git` directory, depth-capped, with the skip list applied."""
    skip_paths = {home / "Library", home / ".Trash", home / ".claude" / "plugins", *excludes}
    repos, seen = [], set()
    for root in roots:
        base_depth = len(root.parts)
        for cur, dirs, _ in os.walk(root):
            cp = Path(cur)
            if ".git" in dirs and not os.path.islink(cp / ".git") and cp not in seen:
                seen.add(cp)
                repos.append(cp)
            depth = len(cp.parts) - base_depth
            dirs[:] = [d for d in dirs
                       if depth < MAX_DEPTH
                       and d not in SKIP_NAMES
                       and not (d.startswith(".") and not (cp == home and d == ".claude"))
                       and (cp / d) not in skip_paths]
    return repos


def parse_worktrees(repo):
    rc, o = git(repo, "worktree", "list", "--porcelain")
    wts, cur = [], None
    for line in (o.splitlines() if rc == 0 else []) + [""]:
        if not line:
            if cur:
                wts.append(cur)
            cur = None
            continue
        key, _, val = line.partition(" ")
        if key == "worktree":
            cur = {"path": val, "head": None, "branch": None, "detached": False,
                   "locked": False, "lock_reason": "", "prunable": False, "bare": False}
        elif cur is not None:
            if key == "HEAD":
                cur["head"] = val
            elif key == "branch":
                cur["branch"] = val.removeprefix("refs/heads/")
            elif key == "detached":
                cur["detached"] = True
            elif key == "locked":
                cur["locked"], cur["lock_reason"] = True, val
            elif key == "prunable":
                cur["prunable"] = True
            elif key == "bare":
                cur["bare"] = True
    return wts


def default_branch(repo, has_origin):
    if has_origin:
        ref = out(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        if ref:
            return ref.removeprefix("origin/")
    for name in ("main", "master"):
        for ref in (f"refs/remotes/origin/{name}", f"refs/heads/{name}"):
            if git(repo, "rev-parse", "--verify", "-q", ref)[0] == 0:
                return name
    return "main"


def ref_exists(repo, ref):
    return git(repo, "rev-parse", "--verify", "-q", ref)[0] == 0


def count(path, rng):
    o = out(path, "rev-list", "--count", rng)
    return int(o) if o is not None else None


def worktree_facts(wt, default, remote_ref, orca):
    p = wt["path"]
    exists = os.path.isdir(p)
    f = {"path": p, "branch": wt["branch"], "tip": wt["head"], "detached": wt["detached"],
         "locked": wt["locked"], "lock_reason": wt["lock_reason"], "prunable": wt["prunable"],
         "exists": exists}
    o = orca.get(os.path.realpath(p))
    f["orca_managed"] = o is not None
    f["orca"] = o
    if not exists:
        return f
    stt = os.stat(p)
    f["folder_ctime"] = stt.st_ctime
    # Where the OS keeps a true creation time (macOS), record it too; consumers prefer it for age.
    if hasattr(stt, "st_birthtime"):
        f["folder_birthtime"] = stt.st_birthtime
    src, st = git(p, "status", "--porcelain")
    if src != 0:
        # A failed status is unknown, never clean.
        f.update(dirty_count=None, dirty_files=[], untracked_count=None, status_failed=True)
    else:
        lines = [l for l in st.splitlines() if l]
        dirty = [l[3:] for l in lines if not l.startswith("??")]
        f.update(dirty_count=len(dirty), dirty_files=dirty[:MAX_NAMES],
                 untracked_count=sum(1 for l in lines if l.startswith("??")), status_failed=False)
    tip = wt["head"]
    f["last_commit_ts"] = int(out(p, "log", "-1", "--format=%ct") or 0) or None
    local = default if ref_exists(p, f"refs/heads/{default}") else None
    f["ahead_of_local_default"] = count(p, f"{local}..{tip}") if local and tip else None
    if remote_ref and tip:
        f["ahead_of_remote_default"] = count(p, f"{remote_ref}..{tip}")
        f["on_remote"] = git(p, "merge-base", "--is-ancestor", tip, remote_ref)[0] == 0
        ch = out(p, "cherry", remote_ref, tip)
        f["unmerged_patches"] = sum(1 for l in ch.splitlines() if l.startswith("+")) if ch is not None else None
        # git cherry skips merge commits, so a merge in the range makes an empty cherry untrustworthy.
        mg = out(p, "rev-list", "--merges", "--count", f"{remote_ref}..{tip}")
        f["range_has_merges"] = None if mg is None else int(mg) > 0
        # Content already on default: merging the tip into default changes nothing (covers multi-commit squashes).
        mt, tree = git(p, "merge-tree", "--write-tree", remote_ref, tip)
        want = out(p, "rev-parse", f"{remote_ref}^{{tree}}")
        f["content_in_default"] = mt == 0 and want is not None and tree.splitlines()[0] == want
    else:
        f.update(ahead_of_remote_default=None, on_remote=None, unmerged_patches=None,
                 range_has_merges=None, content_in_default=None)
    # Creation point: the oldest reflog entry, only if it says "Created from" (else expired: unknown).
    f["creation_point"] = f["commits_since_creation"] = f["creation_on_default"] = None
    if wt["branch"]:
        rc, rl = git(p, "reflog", "show", "--format=%H%x1f%gs", f"refs/heads/{wt['branch']}")
        last = rl.splitlines()[-1] if rc == 0 and rl.strip() else ""
        sha, _, subj = last.partition("\x1f")
        if subj.startswith("branch: Created from"):
            f["creation_point"] = sha
            f["commits_since_creation"] = count(p, f"{sha}..{tip}")
            if local:
                f["creation_on_default"] = git(p, "merge-base", "--is-ancestor", sha, local)[0] == 0
    return f


def process_repo(repo, orca, do_fetch, claims_fn):
    wts = parse_worktrees(repo)
    has_origin = out(repo, "remote", "get-url", "origin") is not None
    default = default_branch(repo, has_origin)
    fetch_failed = False
    if has_origin and do_fetch:
        try:
            r = subprocess.run(["git", "-C", str(repo), "fetch", "--no-tags", "--no-write-fetch-head",
                                "--no-recurse-submodules", "--no-auto-maintenance", "origin",
                                f"+refs/heads/{default}:refs/remotes/origin/{default}"],
                               capture_output=True, stdin=subprocess.DEVNULL,
                               env=dict(ENV, GIT_SSH_COMMAND="ssh -o BatchMode=yes"),
                               timeout=FETCH_TIMEOUT)
            fetch_failed = r.returncode != 0
        except (subprocess.TimeoutExpired, OSError):
            fetch_failed = True
    remote_ref = f"origin/{default}" if has_origin and ref_exists(repo, f"refs/remotes/origin/{default}") else None
    rows = [worktree_facts(w, default, remote_ref, orca) for w in wts if not w["bare"]]
    for r, w in zip(rows, [w for w in wts if not w["bare"]]):
        r["is_main"] = w is wts[0]
    unpushed = []
    if remote_ref and ref_exists(repo, f"refs/heads/{default}"):
        _, lg = git(repo, "log", "--format=%H%x1f%s%x1f%aI", f"{remote_ref}..refs/heads/{default}")
        # Oldest first: the order a push would ship them.
        unpushed = [dict(zip(("sha", "subject", "author_date"), l.split("\x1f"))) for l in reversed(lg.splitlines()) if l]
    return {"path": str(repo), "default_branch": default, "has_origin": has_origin,
            "fetch_failed": fetch_failed, "unpushed_default_commits": unpushed,
            "claims": claims_fn(repo, rows), "worktrees": rows}


def mark_nesting(repos):
    """Set nested_in / has_nested across every worktree on the machine."""
    allw = [(os.path.realpath(w["path"]), w) for r in repos for w in r["worktrees"]]
    for rp, w in allw:
        parents = [(o, ow) for o, ow in allw if o != rp and rp.startswith(o + os.sep)]
        w["nested_in"] = max(parents, key=lambda x: len(x[0]))[1]["path"] if parents else None
        w["has_nested"] = [ow["path"] for o, ow in allw if o != rp and o.startswith(rp + os.sep)]


def load_orca(args):
    if args.no_orca:
        return {}, False
    try:
        if args.orca_json:
            data = json.loads(Path(args.orca_json).read_text())
        else:
            r = subprocess.run(["orca", "worktree", "list", "--json", "--limit", "1000"],
                               capture_output=True, text=True, timeout=20)
            data = json.loads(r.stdout)
        rows = data["result"]["worktrees"]
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return {}, False
    keep = ("id", "repoId", "isUnread", "isPinned", "lastActivityAt")
    return {os.path.realpath(w["path"]): {k: w.get(k) for k in keep} for w in rows}, True


def load_claims(home):
    """Conductor claims by thread; returns a function matching them to a repo (best effort)."""
    reg = home / ".claude" / "skills" / "threads" / "assets" / "register.py"
    threads = []
    try:
        r = subprocess.run([sys.executable, str(reg), "list", "--json"], capture_output=True,
                           text=True, timeout=20, env=ENV)
        threads = json.loads(r.stdout)["threads"] if r.returncode == 0 else []
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        pass

    def for_repo(repo, rows):
        roots = [os.path.realpath(str(repo))] + [os.path.realpath(w["path"]) for w in rows]
        res = []
        for t in threads:
            cwd = os.path.realpath(t.get("cwd") or "")
            under = any(cwd == x or cwd.startswith(x + os.sep) for x in roots)
            for c in t.get("claims", []):
                if under or Path(repo).name == (c.get("key") or "").split(":")[0]:
                    res.append({"thread": t.get("thread"), "session": t.get("session"),
                                "cwd": t.get("cwd"), **c})
        return res
    return for_repo


# ── classification (spec section 2) ──────────────────────────────────────────

LIVE_MINUTES = 30
DRIVER_HOURS = 24
LANDING_HOURS = 24
NEVER_MOVED_DAYS = 3
TAIL_BYTES = 512 * 1024
CWD_RE = re.compile(r'"cwd":"([^"]*)"')
OPEN_STATES = {"claimed", "in-progress", "waiting-on-user", "waiting-on-machine", "blocked"}  # register.py OPEN | HELD
ACTIVE_TICKETS = {"pending", "in-progress", "blocked"}  # skipped and merged are terminal


def under(path, root):
    return path == root or path.startswith(root + os.sep)


def home_rel(p):
    h = str(Path.home())
    return "~" + p[len(h):] if p.startswith(h + os.sep) else p


def latest_cwd(transcript):
    """Last `cwd` field in the tail of a transcript. Streams one seek, never the whole file."""
    try:
        with open(transcript, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - TAIL_BYTES))
            m = CWD_RE.findall(fh.read().decode("utf-8", "ignore"))
        return m[-1] if m else None
    except OSError:
        return None


def load_sessions(home):
    """Alive conductor sessions: where each one is now, and which open claims it holds."""
    path = home / ".claude" / "skills" / "threads" / "assets" / "register.py"
    try:
        spec = importlib.util.spec_from_file_location("cleanup_register", path)
        reg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reg)
        records = reg.read()
        cl = list(reg.claims(records).values())
        out = []
        for sid, s in reg.sessions(records).items():
            if not reg.alive(s.get("pid")):
                continue
            tr = reg.transcript_of(s)
            loc = (latest_cwd(tr) if tr else None) or s.get("cwd")
            out.append({"session": sid, "thread": s.get("thread"), "cwd": s.get("cwd"), "loc": loc,
                        "claims": [{"key": c["key"], "state": c["state"]} for c in cl if c.get("session") == sid]})
        return out
    except Exception:  # a broken register must not stop discovery; None makes classify block prunes
        return None


def load_proc_cwds():
    """Working directory of every process (lsof). None when lsof fails: liveness is then unknown."""
    try:
        r = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fpn"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not r.stdout:
        return None
    me, pid, res = str(os.getpid()), None, set()
    for l in r.stdout.splitlines():
        if l.startswith("p"):
            pid = l[1:]
        elif l.startswith("n") and pid != me:
            res.add(os.path.realpath(l[1:]))
    return sorted(res)


def load_parked(home):
    try:
        data = json.loads((home / ".claude" / "cleanup" / "parked.json").read_text())
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else data.get("parked", []) if isinstance(data, dict) else []


def parked_until(v, now):
    """`until` as epoch seconds; an ISO date or an epoch number. Unreadable means expired."""
    try:
        if isinstance(v, (int, float)):
            return float(v)
        return datetime.datetime.fromisoformat(str(v)).timestamp()
    except ValueError:
        return 0.0


def build_ctx(home, orca_ok, self_cwd, now=None):
    return {"now": now or time.time(), "sessions": load_sessions(home), "proc_cwds": load_proc_cwds(),
            "parked": load_parked(home), "self_cwd": os.path.realpath(self_cwd), "orca_ok": orca_ok,
            "tmp": os.path.realpath(tempfile.gettempdir())}


def load_runs(repo, ctx):
    """Active driver runs of a repo, from its main checkout's .scratch/driver-runs."""
    main = next((w["path"] for w in repo["worktrees"] if w.get("is_main")), repo["path"])
    runs = []
    base = Path(main) / ".scratch" / "driver-runs"
    for sp in sorted(base.glob("*/state.json")) if base.is_dir() else []:
        try:
            st = json.loads(sp.read_text())
            run = st["_run"]
        except (OSError, ValueError, KeyError):
            continue
        tickets = [v["status"] for k, v in st.items() if k != "_run" and isinstance(v, dict) and "status" in v]
        jr = sp.parent / "journal.ndjson"
        try:
            written = os.path.getmtime(jr if jr.exists() else sp)
        except OSError:
            continue
        held = any(run.get("run_id") and run["run_id"] in c["key"] and c["state"] in OPEN_STATES
                   for s in ctx["sessions"] or [] for c in s["claims"])
        recent = ctx["now"] - written < DRIVER_HOURS * 3600
        if (any(t in ACTIVE_TICKETS for t in tickets) and recent) or held:
            tip = out(main, "rev-parse", "--verify", "-q", f"refs/heads/{run.get('integration_branch')}")
            base_sha = run.get("base")
            work = run.get("work")
            runs.append({"id": run.get("run_id"), "branch": run.get("integration_branch"),
                         "work": [os.path.realpath(x) for x in ([work] if isinstance(work, str) else work or [])],
                         # ancestor test is ambiguous while the integration branch still sits on the base
                         "tip": tip if tip and tip != base_sha else None,
                         "open": sum(t in ACTIVE_TICKETS for t in tickets), "main": main})
    return runs


def live_reason(w, ctx):
    rp = os.path.realpath(w["path"])
    for s in ctx["sessions"] or []:
        if s["loc"] and under(os.path.realpath(s["loc"]), rp):
            return f"live session {s['thread']} is in it"
    for c in ctx["proc_cwds"] or []:
        if under(c, rp):
            return "a process has its working directory inside it"
    o = w.get("orca")
    if o:
        la = o.get("lastActivityAt")
        la = (la / 1000 if la and la > 1e11 else la)
        if o.get("isUnread") or o.get("isPinned") or (la and ctx["now"] - la < LIVE_MINUTES * 60):
            return "its Orca card is unread, pinned or active in the last 30 minutes"
    for s in ctx["sessions"] or []:
        if s["cwd"] and under(os.path.realpath(s["cwd"]), rp):
            for c in (c for c in s["claims"] if c["state"] in OPEN_STATES):
                return f"open claim {c['key']} ({c['state']}) held by live session {s['thread']}"
    return None


def folder_age_days(w, now):
    t = w.get("folder_birthtime") or w.get("folder_ctime")
    return (now - t) / 86400 if t else None


def schedule_dir():
    """The permanent folder workspace the weekly automation runs in. Never pruned."""
    return Path.home() / ".claude" / "cleanup" / "scheduled"


def classify_one(repo, w, ctx, by_path, runs):
    """Return (group, reason, recommendation) by spec section 2, rules in order."""
    rp = os.path.realpath(w["path"])
    now = ctx["now"]
    w["landing_action"] = None
    if under(ctx["self_cwd"], rp) and not w.get("is_main"):
        return "Running", "this run's own worktree", None
    if w.get("is_main"):
        return "Main", "main checkout: never pruned; its push is the repo's push row", None
    if under(rp, os.path.realpath(schedule_dir())):
        return "Skipped", "scheduled-run folder workspace: never pruned", None
    if w["locked"]:  # rule 0
        return "Skipped", f"locked ({w['lock_reason'] or 'no reason given'})", None
    if not w["exists"]:
        return "Skipped", "folder is gone; git worktree prune clears it", None
    if w["detached"] and os.path.basename(rp).startswith("driver-land-") and under(rp, ctx["tmp"]):
        age = folder_age_days(w, now)
        busy = any(under(c, rp) for c in ctx["proc_cwds"] or [])
        if age is not None and age * 24 > LANDING_HOURS and not busy and ctx["proc_cwds"] is not None:
            w["landing_action"] = "remove"
            return "Landing", "landing scratch older than 24 hours with no process inside: remove", None
        return "Landing", "landing scratch: left alone", None
    for p in ctx["parked"]:
        if (p.get("path") and os.path.realpath(p["path"]) == rp and p.get("tip") == w["tip"]
                and parked_until(p.get("until"), now) > now):
            return "Parked", f"parked until {p.get('until')}", None
    for p in ctx["parked"]:  # an expired park of this very tip comes back marked
        if p.get("path") and os.path.realpath(p["path"]) == rp and p.get("tip") == w["tip"]:
            w["park_expired"] = True
    for run in runs:  # rule 2
        cut = run["tip"] and w["tip"] and git(repo["path"], "merge-base", "--is-ancestor", run["tip"], w["tip"])[0] == 0
        if w["branch"] == run["branch"] or rp in run["work"] or cut:
            return "Running", f"driver run {run['id']} is active ({run['open']} tickets open)", None
    why = live_reason(w, ctx)  # rule 3
    if why:
        return "Running", why, None
    parent = by_path.get(w.get("nested_in"))  # rule 1
    if parent and parent["group"] == "Running":
        return "Running", f"inside Running worktree {home_rel(parent['path'])}", None
    if w["detached"]:  # rule 4a
        return "Abandoned", "detached HEAD with no live session (no Delete option)", None
    if w.get("status_failed"):
        return "Abandoned", "git status failed, so cleanliness is unknown (no Delete option)", None
    clean = w["dirty_count"] == 0 and w["untracked_count"] == 0
    moved = w["commits_since_creation"]
    remote = repo["has_origin"]
    cherry_clean = w["unmerged_patches"] == 0 and w.get("range_has_merges") is False
    merged_remote = bool(remote and (w["on_remote"] or cherry_clean or w.get("content_in_default")))
    blockers = []
    if w["has_nested"]:
        blockers.append("holds nested worktrees")
    if ctx["proc_cwds"] is None:
        blockers.append("process check unavailable")
    if ctx["sessions"] is None:
        blockers.append("conductor register unavailable")
    if not ctx["orca_ok"]:
        blockers.append("Orca unavailable")
    if repo["fetch_failed"]:
        blockers.append("fetch failed")
    if not clean:
        blockers.append(f"{w['dirty_count']} changed and {w['untracked_count']} untracked files")
    if clean and moved and merged_remote:  # rule 4
        if not blockers:
            return "Pruned", "moved, merged and on the remote, clean, no live session", None
    elif clean and moved == 0 and not repo["fetch_failed"]:  # never moved
        age = folder_age_days(w, now)
        if not blockers and w["creation_on_default"] and age is not None and age > NEVER_MOVED_DAYS:
            return "Abandoned", "never moved, clean, creation point on default, folder older than 3 days: Delete loses no commit", "Delete"
        return "Abandoned", "never moved: tip equals its creation point; never auto-pruned" + (
            f" ({'; '.join(blockers)})" if blockers else "") + ("" if w["creation_on_default"] else "; creation point not on default"
            ) + ("" if age is not None and age > NEVER_MOVED_DAYS else "; folder not older than 3 days"), None
    elif clean and w["ahead_of_local_default"] == 0 and remote and w["on_remote"] is False:  # rule 5
        if not blockers:
            return "Ready", "clean, tip is in local default but not pushed", None
    if repo["fetch_failed"] and clean:
        return "Skipped", "fetch failed: remote state unknown", None
    if not blockers and moved is None:
        blockers.append("creation point unknown (reflog expired): cannot show the branch moved")
    if not blockers:
        n = w["ahead_of_remote_default"]
        blockers.append(f"{n} commit(s) on no default branch" if n else "work not on the remote")
    return "Abandoned", "; ".join(blockers) + " (no Delete option)", None


def classify_all(repos, ctx):
    items = [(r, w) for r in repos for w in r["worktrees"]]
    items.sort(key=lambda x: len(os.path.realpath(x[1]["path"])))  # parents before nested children
    by_path = {w["path"]: w for _, w in items}
    runs = {r["path"]: load_runs(r, ctx) for r in repos}
    for r, w in items:
        w["group"], w["reason"], w["recommendation"] = classify_one(r, w, ctx, by_path, runs[r["path"]])
    held = {"waiting-on-user", "blocked"}
    for r in repos:
        r["push"] = None
        if r["unpushed_default_commits"] and not r["fetch_failed"]:
            r["push"] = {"commits": r["unpushed_default_commits"],
                         "running": [w["path"] for w in r["worktrees"] if w["group"] == "Running"],
                         "held_claims": [c for c in r["claims"] if c.get("state") in held]}
    groups = {}
    for _, w in items:
        groups[w["group"]] = groups.get(w["group"], 0) + 1
    return groups


def report(d):
    order = ["Running", "Pruned", "Ready", "Abandoned", "Parked", "Landing", "Skipped", "Main"]
    lines = [f"{d['counts']['repos']} repos, {d['counts']['worktrees']} worktrees, {d['seconds']} s"]
    for g in order:
        rows = [(r, w) for r in d["repos"] for w in r["worktrees"] if w["group"] == g]
        if rows:
            lines.append(f"\n{g}: {len(rows)}")
            lines += [f"  {home_rel(w['path'])} [{w['branch']}]: {w['reason']}" for _, w in rows]
    pushes = [r for r in d["repos"] if r["push"]]
    lines.append(f"\nPush rows: {len(pushes)}")
    lines += [f"  {home_rel(r['path'])}: {len(r['push']['commits'])} commits beyond origin" for r in pushes]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover-only", action="store_true", help="accepted; discovery is all this does")
    ap.add_argument("--orca-json")
    ap.add_argument("--no-orca", action="store_true")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--report", action="store_true", help="print groups, counts and reasons as text")
    ap.add_argument("--self-cwd", default=os.getcwd(), help="the run's own folder (always Running)")
    args = ap.parse_args(argv)
    t0 = time.time()
    home = Path.home()
    excludes, extra = load_config(home)
    repos = find_repos([home, *extra], home, excludes)
    # A repo found by two roots (or via a symlink) is one repo.
    uniq = {}
    for r in repos:
        uniq.setdefault(os.path.realpath(r), r)
    orca, orca_ok = load_orca(args)
    claims_fn = load_claims(home)
    with ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(lambda r: process_repo(r, orca, not args.no_fetch, claims_fn), sorted(uniq.values())))
    # Repos reached only through another repo's worktree list are already inside that repo's rows.
    mark_nesting(results)
    groups = classify_all(results, build_ctx(home, orca_ok, args.self_cwd))
    nwt = sum(len(r["worktrees"]) for r in results)
    d = {"orca_available": orca_ok, "seconds": round(time.time() - t0, 1),
         "counts": {"repos": len(results), "worktrees": nwt,
                    "fetch_failures": sum(r["fetch_failed"] for r in results)},
         "groups": groups, "repos": results}
    print(report(d) if args.report else json.dumps(d, indent=1))


if __name__ == "__main__":
    main()
