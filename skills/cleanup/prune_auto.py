#!/usr/bin/env python3
"""Auto-prune: remove every worktree discover.py classified as safe, with the /prune guards.

Usage: prune_auto.py DISCOVER.json [--dry-run] [--self-cwd DIR]
Rewrites DISCOVER.json (groups, per-worktree `prune` result). --dry-run changes nothing on disk and prints
what would be removed. Orca and the dev-server killer are injected (`tools`) so tests never touch the real ones.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import discover as D  # noqa: E402


def sh(argv, cwd=None):
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           env=D.ENV, timeout=120)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def real_tools(home=None):
    home = home or Path.home()
    return {"orca_rm": lambda path: sh(["orca", "worktree", "rm", "--worktree", f"path:{path}", "--delete-branch", "--json"]),
            "kill_repo": lambda path: sh(["bash", str(home / ".claude/scripts/localhost-dev.sh"), "kill-repo", path])}


def real_orca():
    return D.load_orca(SimpleNamespace(no_orca=False, orca_json=None))


def fresh_facts(repo, w, ctx_fn, orca_fn, claims_fn):
    """Rebuild this repo's facts and classification now (no fetch). Returns the worktree's fresh row or None."""
    orca, ok = orca_fn()
    r = D.process_repo(Path(repo["path"]), orca, False, claims_fn)
    r["fetch_failed"] = r["fetch_failed"] or repo["fetch_failed"]  # the run's fetch state still holds
    for x in r["worktrees"]:  # nesting across repos is not rebuilt here: keep what discover saw
        old = next((o for o in repo["worktrees"] if o["path"] == x["path"]), None)
        x["nested_in"], x["has_nested"] = (old or {}).get("nested_in"), (old or {}).get("has_nested", False)
    D.mark_nesting([r])
    for x in r["worktrees"]:
        old = next((o for o in repo["worktrees"] if o["path"] == x["path"]), None)
        x["has_nested"] = x["has_nested"] or bool(old and old.get("has_nested"))
        x["nested_in"] = x.get("nested_in") or (old or {}).get("nested_in")
    D.classify_all([r], ctx_fn(ok))
    row = next((x for x in r["worktrees"] if x["path"] == w["path"]), None)
    if row and row.get("nested_in") and row["nested_in"] not in {x["path"] for x in r["worktrees"]}:
        # the parent lives in another repo, so the Running-parent guard cannot be re-checked here: keep it
        row["group"], row["reason"] = "Running", "inside a worktree of another repo; not re-checked, kept"
    return row


def branch_exists(main, branch):
    return D.git(main, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")[0] == 0


def remote_branch_safe(main, branch, default):
    """True only if origin's CURRENT branch tip is an ancestor of origin/<default> (a stale local ref could miss commits)."""
    rc, o = D.git(main, "ls-remote", "--heads", "origin", f"refs/heads/{branch}")
    sha = o.split()[0] if rc == 0 and o.strip() else None
    if not sha:
        return None  # no remote branch
    return D.git(main, "merge-base", "--is-ancestor", sha, f"origin/{default}")[0] == 0


ARTEFACT_DIRS = {"node_modules", ".next", "dist", "build", ".cache", "__pycache__", ".venv", "venv", ".turbo", "coverage"}


def unsafe_ignored(main, path):
    """Ignored files that removal would lose: not a build artefact and not byte-identical to the main checkout's copy."""
    rc, o = D.git(path, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory")
    if rc != 0:
        return ["(could not list ignored files)"]
    bad = []
    for rel in filter(None, o.split("\0")):
        parts = Path(rel.rstrip("/")).parts
        if set(parts) & ARTEFACT_DIRS or parts[-1] in (".DS_Store",) or parts[-1].endswith(".pyc"):
            continue
        a, b = Path(path, rel), Path(main, rel)
        try:
            if a.is_file() and b.is_file() and a.read_bytes() == b.read_bytes():
                continue
        except OSError:
            pass
        bad.append(rel)
    return bad


def remove_one(repo, w, tools):
    """Remove one worktree. Returns (did_text, result dict) or raises RuntimeError(error text)."""
    main = next((x["path"] for x in repo["worktrees"] if x.get("is_main")), repo["path"])
    path, branch, did = w["path"], w["branch"], []
    bad = unsafe_ignored(main, path)
    if bad:
        raise RuntimeError("kept: it holds ignored files that exist nowhere else (" + ", ".join(bad[:3]) + "); check them, then remove by hand")
    tools["kill_repo"](path)
    if w.get("orca_managed"):
        rc, o = tools["orca_rm"](path)
        try:
            j = json.loads(o)
            ok = rc == 0 and (j.get("ok", True) if isinstance(j, dict) else True)  # non-dict reply: trust the exit code
        except ValueError:
            ok = rc == 0
        if not ok:
            raise RuntimeError(f"orca worktree rm failed: {o[:300]}")
        did.append(f"Orca card closed ({w['orca'].get('id')})")
    else:
        rc, o = D.git(main, "worktree", "remove", path)
        if rc != 0:
            raise RuntimeError(f"git worktree remove failed: {o[:300]}")
        did.append("worktree removed")
    if os.path.exists(path) or any(os.path.realpath(x["path"]) == os.path.realpath(path) for x in D.parse_worktrees(main)):
        raise RuntimeError("removal reported success but the worktree is still there")
    res = {"orca_card": w["orca"].get("id") if w.get("orca_managed") else None, "branch": branch,
           "branch_deleted": None, "remote_deleted": False}
    if branch:
        # Orca's result is not branch evidence: read the refs.
        if branch_exists(main, branch):
            D.git(main, "branch", "-d", branch)  # never -D
        res["branch_deleted"] = not branch_exists(main, branch)
        did.append(f"branch {branch} deleted" if res["branch_deleted"] else f"branch {branch} kept (not provably merged)")
        if res["branch_deleted"] and repo["has_origin"]:
            safe = remote_branch_safe(main, branch, repo["default_branch"])
            if safe:
                rc, o = D.git(main, "push", "origin", "--delete", branch)
                res["remote_deleted"] = rc == 0
                did.append(f"remote branch {branch} deleted" if rc == 0 else f"remote branch kept (delete failed: {o[:120]})")
            elif safe is False:
                did.append("remote branch kept (it holds commits not on default)")
    return "; ".join(did), res


def prune_auto(d, ctx_fn, orca_fn=real_orca, claims_fn=None, tools=None, dry_run=False, ready_too=False):
    """ctx_fn(orca_ok) -> fresh liveness context. Mutates d; returns {"pruned": [...], "failed": [...], "skipped": [...]}."""
    tools = tools or real_tools()
    claims_fn = claims_fn or D.load_claims(Path.home())
    out = {"pruned": [], "failed": [], "skipped": []}
    for repo in d["repos"]:
        for w in repo["worktrees"]:
            if not (w["group"] == "Pruned" or (ready_too and w["group"] == "Ready") or (w["group"] == "Landing" and w.get("landing_action") == "remove")):
                continue
            name = f"{Path(repo['path']).name}/{Path(w['path']).name}"
            fresh = fresh_facts(repo, w, ctx_fn, orca_fn, claims_fn)  # liveness may have changed in minutes
            if fresh is None or not (fresh["group"] == "Pruned" or (fresh["group"] == "Landing" and fresh.get("landing_action") == "remove")):
                why = "folder gone" if fresh is None else f"{fresh['group']}: {fresh['reason']}"
                if fresh is not None:
                    w.clear()
                    w.update(fresh)
                out["skipped"].append({"name": name, "why": why})
                continue
            fresh["orca"] = fresh.get("orca") or w.get("orca")
            w.clear()
            w.update(fresh)
            if dry_run:
                out["pruned"].append({"name": name, "did": "would remove" + (" through Orca" if w["orca_managed"] else "")})
                continue
            try:
                did, res = remove_one(repo, w, tools)
            except RuntimeError as e:
                w["group"], w["recommendation"], w["reason"] = "Abandoned", None, f"auto-prune failed: {e}"
                out["failed"].append({"name": name, "error": str(e)})
                continue
            w["prune"] = dict(res, did=did)
            out["pruned"].append({"name": name, "did": did, **res})
    if not dry_run:
        d["pruned_done"] = True
        groups = {}
        for r in d["repos"]:
            for w in r["worktrees"]:
                groups[w["group"]] = groups.get(w["group"], 0) + 1
        d["groups"] = groups
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("discover_json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-cwd", default=os.getcwd())
    a = ap.parse_args(argv)
    d = json.loads(Path(a.discover_json).read_text())
    home = Path.home()
    res = prune_auto(d, lambda ok: D.build_ctx(home, ok, a.self_cwd), dry_run=a.dry_run)
    if not a.dry_run:
        Path(a.discover_json).write_text(json.dumps(d, indent=1))
    verb = "would remove" if a.dry_run else "removed"
    print(f"{verb} {len(res['pruned'])}, failed {len(res['failed'])}, no longer safe {len(res['skipped'])}")
    for k in ("pruned", "failed", "skipped"):
        for x in res[k]:
            print(f"  {k}: {x['name']}: {x.get('did') or x.get('error') or x.get('why')}")


if __name__ == "__main__":
    main()
