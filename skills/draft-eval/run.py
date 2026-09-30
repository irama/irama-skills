#!/usr/bin/env python3
"""The run's bookkeeping: lock, run folder, per-round record, the round commit.

    run.py start <folder> --target <name> --session <id> [--baseline-gap G]
    run.py record <run dir> <n>
    run.py commit <run dir> <n> <path> [<path> ...]
    run.py check <run dir>
    run.py release <folder> [--reason <text>]

start   refuses unless `git status --porcelain <folder>` is empty and no
        <folder>/.draft-eval.lock exists. It takes the lock (session id and run
        dir), adds `eval-runs/` and `.draft-eval.lock` to the repo's
        .git/info/exclude (so the run record never dirties the tree and no
        tracked file changes), creates <folder>/eval-runs/<UTC timestamp>/ with
        rubric.json (as used), run.json (target, session, Codex CLI and Chrome
        versions, baseline gap) and an empty images.json, and prints the run dir.
record  writes rounds/r<n>/record.json: the source commit being graded, the
        screenshot sha256 values, the grader prompt and schema sha256, the full
        model ids and the tool versions.
commit  stages and commits only the given paths (relative ones are taken from the
        target folder), all inside it,
        as `draft-eval(<target>): round <n>`, and stores the sha in record.json.
check   lists every run-record field from spec section 9 that is missing.
release removes the lock and stamps run.json with the end time and reason.
Exit 0 on success, 1 on a failed check, 2 on a refused start or commit, or a git
failure (which releases the lock).
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK = ".draft-eval.lock"
CHROMES = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
           "google-chrome", "chromium", "chromium-browser"]


def git(folder, *args, check=True):
    return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True,
                          check=check).stdout.strip()


def _version(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _chrome():
    for c in [os.environ.get("CHROME")] + CHROMES:
        if c and (Path(c).exists() or shutil.which(c)):
            return c
    return None


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _json(p, default=None):
    p = Path(p)
    return json.loads(p.read_text()) if p.exists() else default


def _write(p, obj):
    Path(p).write_text(json.dumps(obj, indent=1) + "\n")


def start(folder, target, session, baseline_gap=None, versions=None):
    folder = Path(folder).resolve()
    lock = folder / LOCK
    dirty = git(folder, "status", "--porcelain", "--", ".")
    if dirty:
        raise SystemExit(f"run.py: refused, {folder} is not clean in git:\n{dirty}")
    try:
        # O_EXCL: two sessions starting at once cannot both take the lock
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(f"run.py: refused, {lock} exists: {lock.read_text().strip()}")
    try:
        # anchored to this folder, so the patterns ignore nothing elsewhere in the repo
        rel = Path(os.path.relpath(folder, git(folder, "rev-parse", "--show-toplevel"))).as_posix()
        base = "/" if rel == "." else f"/{rel}/"
        exclude = Path(git(folder, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"))
        exclude.parent.mkdir(parents=True, exist_ok=True)
        have = exclude.read_text().splitlines() if exclude.exists() else []
        add = [p for p in (base + "eval-runs/", base + LOCK) if p not in have]
        if add:
            with exclude.open("a") as f:
                f.write("\n".join(["# draft-eval run records and lock"] + add) + "\n")
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run = folder / "eval-runs" / stamp
        run.mkdir(parents=True)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps({"session": session, "run": str(run), "started": stamp}) + "\n")
    except BaseException:
        lock.unlink(missing_ok=True)
        raise
    shutil.copyfile(HERE / "rubric.json", run / "rubric.json")
    if versions is None:
        chrome = _chrome()
        versions = {"codex_cli": _version(["codex", "--version"]),
                    "chrome": _version([chrome, "--version"]) if chrome else None}
    _write(run / "run.json", {"target": target, "folder": str(folder), "session": session,
                              "started": stamp, "start_commit": git(folder, "rev-parse", "HEAD"),
                              "baseline_gap": baseline_gap, "versions": versions})
    _write(run / "images.json", {"cap": 10, "images": []})
    return run


def record(run, n):
    run = Path(run)
    meta = _json(run / "run.json")
    rd = run / "rounds" / f"r{n}"
    units = _json(rd / "units.json")
    shots = _json(rd / "shots" / "shots.json", {})
    models = {}
    for g in ("codex", "claude"):
        ids = {json.loads(x)["model"] for p in (rd / "grading").glob(f"{g}*.jsonl")
               for x in p.read_text().splitlines() if x.strip()}
        arc = (_json(rd / "arc.json", {}).get("graders") or {}).get(g)
        if arc:
            ids.add(arc["model"])
        if ids:
            models[g] = sorted(ids)
    rec = {"round": n, "kind": units["kind"],
           "source_commit": git(meta["folder"], "rev-parse", "HEAD"),
           "source_dirty": bool(git(meta["folder"], "status", "--porcelain", "--", ".")),
           "shots_sha256": {s["id"]: s["sha256"] for s in shots.get("shots", [])},
           "prompt_sha256": _sha(HERE / "grader-prompt.md"), "schema_sha256": _sha(HERE / "schema.json"),
           "arc_prompt_sha256": _sha(HERE / "arc-prompt.md"), "arc_schema_sha256": _sha(HERE / "arc-schema.json"),
           "rubric_version": _json(run / "rubric.json")["rubric_version"],
           "models": models,
           "versions": {**meta["versions"], "playwright": shots.get("playwright"),
                        "chromium": shots.get("chromium")},
           "rewrite_commit": (_json(rd / "record.json", {}) or {}).get("rewrite_commit")}
    _write(rd / "record.json", rec)
    return rec


def commit(run, n, paths):
    run = Path(run)
    meta = _json(run / "run.json")
    folder = Path(meta["folder"])
    # a relative path is taken from the target folder, not from wherever the caller stands
    paths = [str((folder / p).resolve()) for p in paths]
    outside = [p for p in paths if not Path(p).is_relative_to(folder)]
    if outside or not paths:
        raise SystemExit(f"run.py: refused, paths outside {folder} (or none given): {outside}")
    if any("eval-runs" in Path(p).relative_to(folder).parts for p in paths):
        raise SystemExit("run.py: refused, the run record is never committed")
    git(folder, "add", "--", *paths)
    # `commit -- <paths>` commits only these paths, whatever else another thread has staged
    git(folder, "commit", "-q", "-m", f"draft-eval({meta['target']}): round {n}", "--", *paths)
    sha = git(folder, "rev-parse", "HEAD")
    rec_path = run / "rounds" / f"r{n}" / "record.json"
    rec = _json(rec_path, {})
    rec["rewrite_commit"] = sha
    _write(rec_path, rec)
    return sha


def check(run):
    """Spec section 9: every field of the run record, per round."""
    run = Path(run)
    missing = [f for f in ("rubric.json", "run.json", "images.json") if not (run / f).exists()]
    meta = _json(run / "run.json", {})
    for v in ("codex_cli", "chrome"):
        if not (meta.get("versions") or {}).get(v):
            missing.append(f"run.json versions.{v}")
    rounds = sorted((run / "rounds").glob("r*"), key=lambda p: int(p.name[1:]))
    if not rounds:
        missing.append("rounds/r1")
    for rd in rounds:
        r = rd.name
        units = _json(rd / "units.json")
        if not units:
            missing.append(f"{r}/units.json")
            continue
        deck = units["kind"] == "deck"
        need = ["score.json", "rewrites.json", "record.json"] + (["mechanical.json", "arc.json"] if deck else [])
        missing += [f"{r}/{f}" for f in need if not (rd / f).exists()]
        rec = _json(rd / "record.json", {})
        graders = list(rec.get("models", {}))
        if not graders:
            missing.append(f"{r}/record.json models")
        failed = {f["grader"] for f in _json(rd / "grading" / "failed.json", {}).get("failed", [])}
        for g in graders:
            # a grader whose every batch failed has no parsed file; failed.json records why
            if not (rd / "grading" / f"{g}.jsonl").exists() and g not in failed:
                missing.append(f"{r}/grading/{g}.jsonl (parsed)")
            if not list((rd / "grading").glob(f"*.{g}.json")):
                missing.append(f"{r}/grading/*.{g}.json (raw)")
            # Codex runs the arc pass only in a calibration round (--graders both); Claude always does
            arc_graders = set((_json(rd / "arc.json", {}) or {}).get("graders") or {}) | {"claude"}
            if deck and g in arc_graders and not list((rd / "arc").glob(f"*.{g}.json")):
                missing.append(f"{r}/arc/*.{g}.json (raw arc)")
        for k in ("source_commit", "prompt_sha256", "schema_sha256", "rubric_version"):
            if not rec.get(k):
                missing.append(f"{r}/record.json {k}")
        if deck:
            if not rec.get("shots_sha256"):
                missing.append(f"{r}/record.json shots_sha256")
            for v in ("playwright", "chromium"):
                if not (rec.get("versions") or {}).get(v):
                    missing.append(f"{r}/record.json versions.{v}")
        if _json(rd / "rewrites.json", {}).get("rewrites") and not rec.get("rewrite_commit"):
            missing.append(f"{r}/record.json rewrite_commit")
    return missing


def release(folder, reason="done"):
    lock = Path(folder).resolve() / LOCK
    if not lock.exists():
        return None
    run = Path(json.loads(lock.read_text())["run"])
    meta = _json(run / "run.json")
    if meta is not None:
        meta.update(ended=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"), end_reason=reason)
        _write(run / "run.json", meta)
    lock.unlink()
    return run


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("folder")
    s.add_argument("--target", required=True)
    s.add_argument("--session", required=True)
    s.add_argument("--baseline-gap", type=float)
    r = sub.add_parser("record")
    r.add_argument("run")
    r.add_argument("n", type=int)
    c = sub.add_parser("commit")
    c.add_argument("run")
    c.add_argument("n", type=int)
    c.add_argument("paths", nargs="+")
    k = sub.add_parser("check")
    k.add_argument("run")
    x = sub.add_parser("release")
    x.add_argument("folder")
    x.add_argument("--reason", default="done")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "start":
            print(start(a.folder, a.target, a.session, a.baseline_gap))
        elif a.cmd == "record":
            print(json.dumps(record(a.run, a.n), indent=1))
        elif a.cmd == "commit":
            print(commit(a.run, a.n, a.paths))
        elif a.cmd == "check":
            missing = check(a.run)
            print("\n".join(missing) if missing else "run record complete")
            return 1 if missing else 0
        else:
            print(release(a.folder, a.reason) or "no lock held")
    except SystemExit as e:
        if isinstance(e.code, str):
            print(e.code, file=sys.stderr)
            return 2
        raise
    except subprocess.CalledProcessError as e:
        # a git failure mid-run still releases the lock, as every exit must
        print(f"run.py: git failed: {' '.join(e.cmd[3:])}\n{e.stderr or ''}".rstrip(), file=sys.stderr)
        if a.cmd in ("record", "commit"):
            release((_json(Path(a.run) / "run.json", {}) or {}).get("folder", a.run),
                    f"failed: git {' '.join(e.cmd[3:4])}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
