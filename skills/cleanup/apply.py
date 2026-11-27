#!/usr/bin/env python3
"""Apply the returned cleanup brief: park, delete and hold. Spec: docs/specs/cleanup.md, sections 6 and 7.

    apply.py <run-dir> <responses.json> [--self-cwd DIR] [--only KEY [--choose OPTION] [--reapply]]

Reads rows.json and discover.json from the run folder, resolves each row from the responses
(absent = its recommendation, `none` = do nothing, two ticks = ask), re-checks the row, runs
Park, Delete and Hold, writes results.json and asks.json, then rebuilds the brief as round two.
Push and merge rows go to ship.py (range checks, one push per repo, prune after push); resume rows go to resume.py (Orca launch, done bubbles).
Every outside effect is injected (ctx_fn, orca_fn, claims_fn, tools, ask_fn, home), so tests use synthetic repos.
"""
import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import discover as D  # noqa: E402
import make_brief as MB  # noqa: E402
import prune_auto as PA  # noqa: E402
import resume as RS  # noqa: E402
import ship as SH  # noqa: E402

SECRETS = (".env*", "*.pem", "*.key", "credentials*", ".npmrc")
PARK_DAYS = 30
LEAVE, AGAIN = "Leave it for next cleanup", "Re-check and apply now"
UNSUPPORTED = set()
# parks, deletes, merges, resumes, pushes now, deferred pushes
ORDER = {MB.PARK: 0, MB.DELETE: 1, MB.MERGE: 2, MB.RESUME: 3, MB.PUSH_NOW: 4, MB.PUSH_LATER: 5}


# ── reading the responses ────────────────────────────────────────────────────

def read_notes(payload):
    """id -> note, from the payload's `notes: [{id, label, note}]` (a plain dict also works)."""
    n = payload.get("notes") or []
    return n if isinstance(n, dict) else {x["id"]: x.get("note", "") for x in n if isinstance(x, dict) and "id" in x}


def ticked_options(note, options):
    """Options named in a note. Labels hold commas, so match whole labels rather than split. Returns (options, junk left)."""
    rest, hit = note, set()
    for o in sorted(options, key=len, reverse=True):
        if o in rest:
            hit.add(o)
            rest = rest.replace(o, "")
    return [o for o in options if o in hit], bool(rest.replace(",", "").strip())


def resolve(row, notes):
    """(kind, option or ticked list): run, none or ask. Absent means the recommendation the row showed."""
    note = (notes.get(row["key"]) or "").strip()
    if not note:
        return "run", row.get("recommendation") or MB.default_recommendation(row)
    if note.lower() == "none":
        return "none", None
    ticked, junk = ticked_options(note, row["options"])
    if len(ticked) == 1 and not junk:
        return "run", ticked[0]
    return "ask", ticked


# ── asks ─────────────────────────────────────────────────────────────────────

COUNTED = ("launched", "launch uncertain")  # statuses that used a launch slot


def make_ask(question, choices):
    """Agent X limits: question 500 characters, two to six choices of 60."""
    return {"question": question[:500], "choices": [c[:60] for c in choices][:6]}


# ── re-check ─────────────────────────────────────────────────────────────────

def problem_with(row, fresh, ctx):
    """Why the row must not run now, or None: the tip, the cleanliness and the liveness the brief showed."""
    if fresh is None:
        return "the folder is gone"
    if fresh["tip"] != row["tip"]:
        return f"its tip moved from {MB.sha7(row['tip'])} to {MB.sha7(fresh['tip'])} since the brief"
    if fresh.get("group") not in ("Abandoned", "Push"):
        return f"it now reads {fresh.get('group')}, not Abandoned or Push ({fresh.get('reason')})"
    if fresh.get("status_failed") or fresh.get("dirty_count") is None or fresh.get("untracked_count") is None:
        return "git status failed, so cleanliness is unknown"
    if not ctx.get("orca_ok"):
        return "Orca is unavailable, so liveness cannot be checked"
    if ctx.get("proc_cwds") is None or ctx.get("sessions") is None:
        return "the process or session check is unavailable, so liveness cannot be checked"
    for k, what in (("dirty_count", "uncommitted"), ("untracked_count", "untracked")):
        if (fresh.get(k) or 0) != (row.get(k) or 0):
            return f"its {what} file count changed from {row.get(k) or 0} to {fresh.get(k) or 0} since the brief"
    live = D.live_reason(fresh, ctx)
    return f"it is live now: {live}" if live else None


# ── Park ─────────────────────────────────────────────────────────────────────

def park(row, home, now):
    f = home / ".claude" / "cleanup" / "parked.json"
    try:
        data = json.loads(f.read_text())
    except (OSError, ValueError):
        data = []
    data = [p for p in (data if isinstance(data, list) else []) if os.path.realpath(p.get("path") or "") != os.path.realpath(row["path"])]
    until = (datetime.date.fromtimestamp(now) + datetime.timedelta(days=PARK_DAYS)).isoformat()
    data.append({"repo": row["repo"], "path": row["path"], "branch": row["branch"], "tip": row["tip"], "until": until})
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".new")
    tmp.write_text(json.dumps(data, indent=1))
    os.replace(tmp, f)
    return {"status": "parked", "text": f"Parked until {until}. Nothing on disk changed. It stays hidden while the tip is still {MB.sha7(row['tip'])}, "
                                         "and comes back marked 'park expired' on that date or sooner if the tip moves."}


# ── Delete ───────────────────────────────────────────────────────────────────

def secret_files(path):
    """Untracked or ignored secret files in a worktree. Build folders are skipped, collapsed ignored folders are walked."""
    found = set()
    for extra in (["--exclude-standard"], ["--ignored", "--exclude-standard", "--directory"]):
        rc, o = D.git(path, "ls-files", "-z", "--others", *extra)
        for rel in filter(None, o.split("\0") if rc == 0 else []):
            files = [Path(path, rel)]
            if rel.endswith("/"):  # a collapsed ignored folder: walk it, skipping build folders
                files = []
                for r, ds, fs in os.walk(Path(path, rel)):
                    ds[:] = [x for x in ds if x not in PA.ARTEFACT_DIRS]
                    files += [Path(r, f) for f in fs]
            for f in files:
                if any(fnmatch.fnmatch(f.name, g) for g in SECRETS) and not (set(f.relative_to(path).parts[:-1]) & PA.ARTEFACT_DIRS):
                    found.add(f.relative_to(path))
    return sorted(found)


def delete(row, repo, w, run_dir, home, tools, today):
    main = next((x["path"] for x in repo["worktrees"] if x.get("is_main")), repo["path"])
    branch, tip, path = w.get("branch"), w["tip"], w["path"]
    if w.get("is_main") or not branch or w.get("detached"):
        return {"status": "refused", "text": "Refused: Delete needs a branch in its own worktree, and this one has none."}
    if w.get("has_nested"):
        return {"status": "refused", "text": "Refused: other worktrees sit inside this one. Delete them first, or park this one."}
    tag = f"cleanup/deleted/{branch}-{today:%Y%m%d}"
    if D.git(main, "show-ref", "--verify", "--quiet", f"refs/tags/{tag}")[0] == 0:
        return {"status": "refused", "text": f"Stopped: the tag {tag} already exists, so nothing was removed. Check it, then run cleanup again."}
    tagh = hashlib.sha1(os.path.realpath(path).encode()).hexdigest()[:8]  # same folder name in two repos must not share a kept dir
    kept_dir = home / ".claude" / "cleanup" / run_dir.name / "kept" / Path(repo["path"]).name / f"{Path(path).name}-{tagh}"
    rc, o = D.git(main, "tag", tag, tip)
    if rc != 0:
        return {"status": "failed", "text": f"Stopped before removing anything: git tag failed ({o[:200]})."}
    kept = []
    try:
        for rel in secret_files(path):
            dst = kept_dir / rel
            if os.path.lexists(dst):
                raise RuntimeError(f"kept file {dst} already exists")
            dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.move(str(Path(path, rel)), str(dst))
            kept.append(str(rel))  # recorded before chmod, so a failure below still rolls it back
            if not os.path.islink(dst):
                os.chmod(dst, 0o600)
            elif hasattr(os, "lchmod"):
                os.lchmod(dst, 0o600)  # never chmod through a link to the real target
        tools["kill_repo"](path)
        if w.get("orca_managed"):
            rc, o = tools["orca_rm"](path)
            if rc != 0:
                raise RuntimeError(f"orca worktree rm failed: {o[:300]}")
        else:
            rc, o = D.git(main, "worktree", "remove", "--force", path)
            if rc != 0:
                raise RuntimeError(f"git worktree remove failed: {o[:300]}")
        if os.path.exists(path) or any(os.path.realpath(x["path"]) == os.path.realpath(path) for x in D.parse_worktrees(main)):
            raise RuntimeError("removal reported success but the worktree is still there")
    except (RuntimeError, OSError) as e:
        if os.path.isdir(path):  # still there: put the files back and drop the tag we made
            for rel in kept:
                if os.path.lexists(kept_dir / rel):
                    shutil.move(str(kept_dir / rel), str(Path(path, rel)))
            D.git(main, "tag", "-d", tag)
            return {"status": "failed", "text": f"Not deleted: {e}. The worktree and its files are as they were."}
        return {"status": "failed", "kept": kept, "text": f"The folder is gone but cleanup stopped: {e}. Tag {tag} holds the tip; kept files are in {kept_dir}."}
    if D.git(main, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")[0] == 0:
        D.git(main, "branch", "-D", branch)
    gone = D.git(main, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")[0] != 0
    undo = f"git -C {main} branch {branch} {tag} && git -C {main} worktree add {path} {branch}"
    if kept:
        undo += f" && cp -pR {kept_dir}/. {path}/"
    return {"status": "deleted", "kept": kept, "tag": tag, "kept_dir": str(kept_dir), "undo": undo,
            "text": (f"Deleted the worktree and {'branch ' + branch if gone else 'its folder (branch ' + branch + ' could not be deleted)'}. "
                     f"Tagged the tip {MB.sha7(tip)} as {tag} (local, never pushed). "
                     + (f"Moved {MB.plural(len(kept), 'secret file')} (mode 600) to {kept_dir}." if kept else "No secret files were in it."))}


def real_tools(home):
    sh = PA.sh
    return {"orca_rm": lambda path: sh(["orca", "worktree", "rm", "--worktree", f"path:{path}", "--force", "--delete-branch", "--json"]),
            "kill_repo": PA.real_tools(home)["kill_repo"], **SH.real_tools(), **RS.real_tools()}


def prune_ready(repo, ctx_fn, orca_fn, claims_fn, tools):
    """After a repo's push succeeded: remove its Ready worktrees through the auto-prune path. Returns a one-line text."""
    out = PA.prune_auto({"repos": [repo]}, ctx_fn, orca_fn, claims_fn, tools, ready_too=True)
    return f"Pruned {len(out['pruned'])} Ready worktree(s) after the push" + (f", {len(out['failed'])} failed" if out["failed"] else "") + "."


# ── the run ──────────────────────────────────────────────────────────────────

def find(d, path):
    rp = os.path.realpath(path)
    for r in d["repos"]:
        for w in r["worktrees"]:
            if os.path.realpath(w["path"]) == rp:
                return r, w
    return None, None


def apply_all(rows, d, payload, run_dir, home, ctx_fn, orca_fn, claims_fn, tools, ask_fn, now=None, only=None, choose=None, reapply=False, done_fn=None, retry_launch=False):
    """Returns {key: result}. Each result has q, label, status and text; results.json merges with an earlier pass."""
    now = now or time.time()
    notes = read_notes(payload)
    allrows = rows["push"] + rows["abandoned"]
    results, todo = {}, []
    try:
        prior = json.loads((run_dir / "results.json").read_text())
    except (OSError, ValueError):
        prior = {}
    _, orca_ok = orca_fn()
    done_fn = done_fn or (lambda **k: None)
    launched = sum(r.get("status") in COUNTED for r in prior.values())  # the cap counts the whole run, not one pass; an uncertain launch counts
    for q, row in enumerate(allrows, 1):
        if only and row["key"] != only:
            continue
        st0 = prior.get(row["key"], {}).get("status")
        if only and st0 in COUNTED and not (retry_launch and st0 == "launch uncertain"):  # --only never re-launches a started or uncertain row
            continue
        if only and retry_launch and st0 == "launch uncertain":
            launched -= 1
        if not only and row["key"] in prior:  # a row that already has a result is never run again (it would overwrite a deleted row's undo)
            continue
        kind, opt = resolve(row, notes)
        if choose and only:
            kind, opt = "run", choose
        res = {"q": q, "label": opt if kind == "run" else "Left alone" if kind == "none" else "Asked you"}
        if kind == "none":
            res.update(status="none", text="Left alone. You unticked every box, so nothing ran. It comes back at the next cleanup.")
        elif kind == "ask":
            what = f"{row['repo']}/{row.get('name') or 'push'}"
            if len(opt) > 1:
                ask = make_ask(f"You ticked {' and '.join(opt)} for {what}. Cleanup acts on one box per row. Which one?", opt)
            else:
                ask = make_ask(f"The answer for {what} was not one of its options, so nothing ran. What now?", [LEAVE, AGAIN])
            ask_fn(**ask)
            res.update(status="asked", text="Nothing ran. " + ask["question"] + " An Agent X ask went out.")
        elif opt == MB.HOLD:
            res.update(status="held", text="Held. Nothing was pushed. It appears again at the next cleanup.")
        elif opt in UNSUPPORTED:
            res.update(status="unsupported", text=f"Not yet supported: cleanup cannot run '{opt}' in this build, so nothing was done. The row comes back at the next cleanup.")
        else:
            res["opt"] = opt
            todo.append((row, res))
        results[row["key"]] = res
    pushes = {}  # repo path -> {"now": (row, res), "later": (row, res), "merged": [(row, res, landed)], "shown": bool}
    for row, res in todo:  # only Push now approves the shown range for an immediate push; Push when the running work lands always waits for its watcher
        if row["key"].startswith("push-"):
            pushes.setdefault(row["path"], {"merged": []}).update(shown=res["opt"] == MB.PUSH_NOW, row=row)
    for row, res in sorted(todo, key=lambda t: ORDER.get(t[1]["opt"], 9)):
        if row["key"].startswith("push-"):  # a push row is the main checkout, not an Abandoned worktree: its re-check is the range check
            repo, _ = find(d, row["path"])
            if repo is None:
                res.update(status="failed", text="Not found in this run's discovery, so nothing ran.")
            else:
                pushes[row["path"]]["now" if res["opt"] == MB.PUSH_NOW else "later"] = (row, res)
            continue
        repo, w = find(d, row["path"])
        if repo is None:
            res.update(status="failed", text="Not found in this run's discovery, so nothing ran.")
            continue
        fresh = PA.fresh_facts(repo, w, ctx_fn, orca_fn, claims_fn)
        if reapply and fresh:
            row.update(tip=fresh["tip"], dirty_count=fresh.get("dirty_count"), untracked_count=fresh.get("untracked_count"))
        why = problem_with(row, fresh, ctx_fn(orca_ok))
        if why:
            ask = make_ask(f"{row['repo']}/{row['name']}: {why}, so cleanup did not run '{res['opt']}'. What now?", [LEAVE, AGAIN])
            ask_fn(**ask)
            res.update(status="asked", text=f"Nothing ran: {why}. An Agent X ask went out.")
            continue
        fresh["orca"] = fresh.get("orca") or w.get("orca")
        try:
            if res["opt"] == MB.RESUME:
                out = RS.resume(row, fresh, tools, now, launched)
                launched += out["status"] in COUNTED
                if out.get("ask"):
                    ask_fn(**make_ask(**out.pop("ask")))
                res.update(out)
                write_result(run_dir, row["key"], res)  # at once, so an interrupted apply never re-launches this row
                if out.get("bubble"):
                    done_fn(**out["bubble"])
            elif res["opt"] == MB.MERGE:
                out = SH.merge_branch(repo, fresh, tools)
                if out["status"] == "merged":
                    pushes.setdefault(repo["path"], {"merged": [], "shown": False})["merged"].append((row, res, out["landed"]))
            else:
                out = park(row, home, now) if res["opt"] == MB.PARK else delete(row, repo, fresh, run_dir, home, tools, datetime.date.fromtimestamp(now))
        except OSError as e:
            out = {"status": "failed", "text": f"Failed: {e}"}
        res.update(out)
    ship_pushes(pushes, d, run_dir, ctx_fn, orca_ok, orca_fn, claims_fn, tools, ask_fn, now)
    return results


def ship_pushes(pushes, d, run_dir, ctx_fn, orca_ok, orca_fn, claims_fn, tools, ask_fn, now):
    """One push per repo: a Push now row and the merges that just landed share it. Approved range = shown range + landed spans."""
    for path, p in pushes.items():
        repo, _ = find(d, path)
        if not p.get("now") and not p["merged"]:
            continue
        approved = set(c["sha"] for c in p["row"]["commits"]) if p.get("shown") else set()
        for _, _, landed in p["merged"]:
            approved |= set(landed)
        out = SH.push_range(repo, approved, tools, ask_fn)
        ok = out["status"] == "pushed"
        tail = " " + prune_ready(repo, ctx_fn, orca_fn, claims_fn, tools) if ok and out["pushed"] else ""
        if p.get("now"):
            p["now"][1].update(status=out["status"], text=out["text"] + tail)
        for _, res, landed in p["merged"]:
            res.update(status="merged and pushed" if ok else "merged",
                       text=f"Merged through /merge's steps ({len(landed)} new commit(s)). " + out["text"] + tail)
        p["pushed_ok"] = ok
    for path, p in pushes.items():
        if p.get("later"):
            row, res = p["later"]
            repo, _ = find(d, path)
            if p.get("pushed_ok"):
                res.update(status="pushed", text="Already pushed in this run (with a merge), so nothing waits.")
                continue
            st = SH.start_deferred(run_dir, row, repo, ctx_fn(orca_ok), now)
            res.update(status="waiting", text=(f"Waiting for the running work ({', '.join(st['running']) or 'none named'}) to land, up to 24 hours. "
                       "Then it pushes only if every extra commit comes from that work; otherwise an Agent X ask goes out. "
                       f"Monitor command: python3 {os.path.join(HERE, 'ship.py')} deferred {run_dir} {row['key']}"))


def record_late(run_dir, d, key, out, asks, home, ctx_fn, orca_fn, claims_fn, tools=None):
    """The deferred push finished: update its result, prune Ready worktrees on success, write asks.json, rebuild round two."""
    f = run_dir / "results.json"
    allres = json.loads(f.read_text())
    res = allres[key]
    text = out["text"]
    if out["status"] == "pushed" and out.get("pushed"):
        repo, _ = find(d, json.loads((run_dir / "deferred.json").read_text())[key]["repo"])
        text += " " + prune_ready(repo, ctx_fn, orca_fn, claims_fn, tools or real_tools(home))
    res.update(status=out["status"], text=text)
    f.write_text(json.dumps(allres, indent=1))
    (run_dir / "asks.json").write_text(json.dumps(asks, indent=1))
    return MB.main(["brief", str(run_dir / "rows.json"), "--results", str(f), "--render"])


def write_result(run_dir, key, res):
    """Merge one result into results.json atomically (temp file, then replace)."""
    f = run_dir / "results.json"
    try:
        old = json.loads(f.read_text())
    except (OSError, ValueError):
        old = {}
    old[key] = res
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(old, indent=1))
    os.replace(tmp, f)


def merge_results(run_dir, new):
    f = run_dir / "results.json"
    try:
        old = json.loads(f.read_text())
    except (OSError, ValueError):
        old = {}
    old.update(new)
    f.write_text(json.dumps(old, indent=1))
    return old


def round_one_refusal(run_dir, payload):
    """Only round one's responses may run: a round-two payload has no ticks, so every row would read absent and re-run."""
    try:
        rounds = json.loads((run_dir / "cleanup.html.rounds.json").read_text()).get("rounds", [])
    except (OSError, ValueError, AttributeError):
        return None  # no round history: nothing to compare against
    build = payload.get("build")
    if len(rounds) > 1 and (not build or build not in rounds[0].get("builds", [])):
        return "these responses are not from round one of this brief (build token missing or from a later round), so nothing ran"
    if len(rounds) == 1 and build and build not in rounds[0].get("builds", []):
        return "these responses name a build this run never made, so nothing ran"
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("responses")
    ap.add_argument("--self-cwd", default=os.getcwd())
    ap.add_argument("--only")
    ap.add_argument("--choose")
    ap.add_argument("--reapply", action="store_true")
    ap.add_argument("--retry-launch", action="store_true")
    a = ap.parse_args(argv)
    run_dir, home = Path(a.run_dir), Path.home()
    rows = json.loads((run_dir / "rows.json").read_text())
    d = json.loads((run_dir / "discover.json").read_text())
    payload = json.loads(Path(a.responses).read_text())
    if payload.get("brief") and payload["brief"] != rows["brief_id"]:
        print(f"responses are for brief {payload['brief']}, this run is {rows['brief_id']}")
        return 2
    why = round_one_refusal(run_dir, payload)
    if why:
        print(why)
        return 2
    asks, dones = [], []
    new = apply_all(rows, d, payload, run_dir, home, lambda ok: D.build_ctx(home, ok, a.self_cwd),
                    lambda: D.load_orca(argparse.Namespace(no_orca=False, orca_json=None)), D.load_claims(home),
                    real_tools(home), lambda **k: asks.append(k), only=a.only, choose=a.choose, reapply=a.reapply, retry_launch=a.retry_launch, done_fn=lambda **k: dones.append(k))
    results = merge_results(run_dir, new)
    (run_dir / "asks.json").write_text(json.dumps(asks, indent=1))
    (run_dir / "dones.json").write_text(json.dumps(dones, indent=1))
    for k, r in sorted(results.items(), key=lambda kv: kv[1]["q"]):
        print(f"Q{r['q']} {r['label']}: {r['status']}: {r['text'][:160]}")
    rc = MB.main(["brief", str(run_dir / "rows.json"), "--results", str(run_dir / "results.json"), "--render"])
    if rc:
        return rc
    assets = home / ".claude" / "skills" / "peakstate-brief" / "assets"
    rc = subprocess.run([sys.executable, str(assets / "check-coverage.py"), str(run_dir / "cleanup.md"), a.responses]).returncode
    print(f"asks to post: {len(asks)} (in asks.json); done bubbles to post: {len(dones)} (in dones.json)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
