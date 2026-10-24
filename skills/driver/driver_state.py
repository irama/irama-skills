#!/usr/bin/env python3
"""/driver run-state manager — atomic writes, a journal, a single-run lock,
and git-backed reconciliation. Deliberately small: this is a single-user,
single-machine tool, not a distributed job scheduler (see docs/driver-spec.md
§ Codex review — what changed for why the fancier version was cut).

Run layout, all under <run-dir> (caller picks, convention:
.scratch/driver-runs/<run-id>/):

    state.json      current snapshot: {ticket_id: {status, commit, reviewer, ts}}
    journal.ndjson  append-only line per status transition (source of truth on
                     a torn/missing state.json — reconcile replays it)
    handoffs/        one <ticket_id>.md per completed ticket
    .lock/           mkdir-based lock; contains owner.json {pid, started}

Statuses: pending -> in-progress -> merged | blocked | skipped

    python3 driver_state.py init <run-dir> <ticket-id> [<ticket-id> ...]
    python3 driver_state.py lock <run-dir> [--stale-hours N]
    python3 driver_state.py unlock <run-dir>
    python3 driver_state.py set-status <run-dir> <ticket-id> <status> [--commit SHA] [--reviewer NAME]
    python3 driver_state.py get-status <run-dir> <ticket-id>
    python3 driver_state.py summary <run-dir>
    python3 driver_state.py reconcile <run-dir> --repo <path> --integration-branch <branch>
    python3 driver_state.py --selftest

Exit codes: 0 ok, 1 error (e.g. lock held), 2 bad usage.
"""

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

VALID_STATUSES = {"pending", "in-progress", "merged", "blocked", "skipped"}


def _state_path(run_dir):
    return os.path.join(run_dir, "state.json")


def _journal_path(run_dir):
    return os.path.join(run_dir, "journal.ndjson")


def _lock_dir(run_dir):
    return os.path.join(run_dir, ".lock")


def atomic_write_json(path, obj):
    """Never edit in place — write to a temp file in the same dir, then rename.
    A crash mid-write leaves the old file intact, never a half-written one."""
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _next_seq(run_dir):
    """Wall clock cannot order two writers, and it moves backwards. Count the
    journal instead: it is append-only, so its length is a sequence number."""
    path = _journal_path(run_dir)
    if not os.path.exists(path):
        return 1
    with open(path) as f:
        return sum(1 for line in f if line.strip()) + 1


def append_journal(run_dir, entry):
    entry = dict(entry)
    entry["ts"] = time.time()
    entry.setdefault("seq", _next_seq(run_dir))
    with open(_journal_path(run_dir), "a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def load_state(run_dir):
    """The journal is the recovery source of truth, the snapshot is a cache.

    A crash between the journal append and the snapshot rename leaves a READABLE
    but older state.json, so trusting it only when it is missing or torn loses
    the last transition. Start from the snapshot (it carries tickets that init
    recorded but never journaled), then apply every journal entry at least as
    new as the snapshot's own entry for that ticket."""
    path = _state_path(run_dir)
    state = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            state = {}
    for tid, entry in replay_journal(run_dir).items():
        current = state.get(tid)
        if current is None:
            state[tid] = entry
            continue
        if entry.get("seq") is not None and current.get("seq") is not None:
            newer = entry["seq"] >= current["seq"]
        else:
            newer = (entry.get("ts") or 0) >= (current.get("ts") or 0)
        if newer:
            state[tid] = entry
    return state


def replay_journal(run_dir):
    state = {}
    path = _journal_path(run_dir)
    if not os.path.exists(path):
        return state
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn final line — skip it, journal lines are append-only-whole
            tid = e.get("ticket_id")
            if not tid or not e.get("status"):
                continue  # a landing phase record, not a status transition
            state[tid] = {
                "status": e.get("status"),
                "commit": e.get("commit"),
                "reviewer": e.get("reviewer"),
                "ts": e.get("ts"),
                "seq": e.get("seq"),
            }
    return state


def _owner_pid():
    """The long-lived agent process above this short-lived CLI call.

    This process exits as soon as the command returns, so its own pid is
    useless as a liveness signal. Same walk register.py does."""
    pid = os.getpid()
    for _ in range(12):
        try:
            out = subprocess.run(["ps", "-o", "ppid=,command=", "-p", str(pid)],
                                 capture_output=True, text=True, check=True).stdout.strip()
        except (subprocess.CalledProcessError, OSError):
            return None
        if not out:
            return None
        parent, _, command = out.partition(" ")
        if "claude" in command and "native-binary" in command:
            return pid
        try:
            pid = int(parent)
        except ValueError:
            return None
        if pid <= 1:
            return None
    return None


def _pid_start(pid):
    """Start time of a pid, so a recycled pid is not mistaken for the owner."""
    if not pid:
        return None
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                             capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return None
    return out or None


def _owner_record():
    pid = _owner_pid()
    return {"pid": pid, "pid_start": _pid_start(pid), "started": time.time()}


def _owner_is_live(owner, stale_hours=None):
    """A dead owner reclaims. An owner we cannot identify does NOT — failing
    open there lets a second run start over a live one. The age backstop applies
    only to an unidentifiable owner, so a wedged lock still recovers, and a long
    but healthy run is never evicted for being long."""
    pid = owner.get("pid")
    if pid:
        start = _pid_start(pid)
        if start is None:
            return False
        recorded = owner.get("pid_start")
        # An owner written before pid_start existed can only be checked by liveness.
        return recorded is None or start == recorded
    if stale_hours is not None:
        age_hours = (time.time() - (owner.get("started") or 0)) / 3600
        if age_hours > stale_hours:
            return False
    return True


def _git_common_dir(repo):
    res = subprocess.run(["git", "-C", repo, "rev-parse", "--path-format=absolute",
                          "--git-common-dir"], capture_output=True, text=True)
    if res.returncode != 0:
        return None
    return res.stdout.strip()


def _flock(repo, name, wait_seconds):
    """A kernel lock held by THIS process for the whole critical section.

    ponytail: flock, not a lock directory with an owner token. The kernel drops
    it when the process dies, so there is no stale entry to reclaim and no
    acquire/release pair whose acquiring process has already exited. macOS has
    no flock(1), hence Python. Upgrade path if a lock is ever needed across
    machines: a real lease service, not a longer timeout."""
    common = _git_common_dir(repo)
    if not common:
        print(f"not a git repo: {repo}", file=sys.stderr)
        return None
    d = os.path.join(common, "driver-locks")
    os.makedirs(d, exist_ok=True)
    handle = open(os.path.join(d, f"{name}.lock"), "a+")
    deadline = time.time() + max(0.0, wait_seconds)
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(_owner_record()) + "\n")
            handle.flush()
            return handle
        except OSError:
            if time.time() >= deadline:
                handle.close()
                return None
            time.sleep(1.0)


def cmd_with_lock(args):
    """Run a command holding the repo lock <name>. Exit code is the command's."""
    if not args.command:
        print("nothing to run after --", file=sys.stderr)
        return 2
    command = args.command[1:] if args.command[0] == "--" else args.command
    handle = _flock(args.repo, args.name, args.wait)
    if handle is None:
        print(f"lock {args.name!r} is held by another process", file=sys.stderr)
        return 1
    try:
        return subprocess.run(command).returncode
    finally:
        handle.close()


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)


def _is_clean(worktree, ignore=()):
    """No change in <worktree>, apart from the paths in <ignore> (relative)."""
    res = _git(worktree, "status", "--porcelain", "-z")
    if res.returncode != 0:
        return False
    skip = {p.rstrip("/") for p in ignore}
    return all(entry[3:].rstrip("/") in skip for entry in res.stdout.split("\0") if entry)


def _tracked(repo, rel):
    return bool(_git(repo, "ls-files", "--", rel).stdout.strip())


def _lockfile_dirs(tmp):
    """Every dir in the candidate tree that tracks its own pnpm-lock.yaml ("" is the root)."""
    listed = _git(tmp, "ls-files", "-z", "--", "pnpm-lock.yaml", "*/pnpm-lock.yaml").stdout
    return [os.path.dirname(f) for f in listed.split("\0") if f]


def _pnpm_fresh(work, tmp):
    """Package dirs whose candidate pnpm-lock.yaml is not what --work's node_modules holds.

    pnpm 11 records the absolute project path (and absolute patch paths) of the last install
    in node_modules/.pnpm-workspace-state-v1.json, so a linked node_modules ALWAYS fails
    verifyDepsBeforeRun in another directory ("workspace structure has changed", "the value
    of the patchedDependencies setting has changed"), whatever the lockfile says. Where the
    lockfile matches, the linked deps are the right deps and the gate only needs the check
    off. Where it differs, the dir gets its own install instead of a link.

    The reference is node_modules/.pnpm/lock.yaml, the lockfile pnpm wrote at install, never
    --work's HEAD: land fast-forwards --work without reinstalling, so HEAD can be ahead of
    what is installed. pnpm writes that record as a copy of the lockfile it installed (byte
    for byte on pnpm 11), so bytes are compared. A missing or unreadable record, or one
    that differs only in layout, counts as differs: a needless install costs time, a wrong
    link gates the wrong deps."""
    # Turbopack refuses a node_modules symlink that points outside the project root, so a gate
    # that starts a Next dev server (Playwright webServer) needs a real install. Opt in per run.
    if os.environ.get("DRIVER_LAND_INSTALL"):
        return _lockfile_dirs(tmp)
    fresh = []
    for d in _lockfile_dirs(tmp):
        f = os.path.join(d, "pnpm-lock.yaml") if d else "pnpm-lock.yaml"
        try:
            with open(os.path.join(tmp, f), "rb") as fh:
                theirs = fh.read()
            with open(os.path.join(work, d, "node_modules", ".pnpm", "lock.yaml"), "rb") as fh:
                ours = fh.read()
        except OSError:
            ours, theirs = None, b""
        if theirs != ours:
            fresh.append(d)
    return fresh


def _link_shared(work, tmp, node_modules=True):
    """Symlink --work's gitignored dependencies and env files into the gate worktree.

    A fresh checkout has no node_modules or .env.local, so a Node gate would fail
    or reinstall on every landing. Links: node_modules beside the root and every
    tracked package.json, and untracked top-level .env / .env.* files. Call it after
    the merge: a path that already exists in the merged tree (so is tracked there)
    is never shadowed. node_modules=False links no node_modules at any depth: a fresh
    root install would otherwise write through a nested link into --work. Returns the
    relative paths linked, so the clean check and cleanup know them."""
    work = os.path.abspath(work)
    listed = _git(tmp, "ls-files", "-z", "--", "package.json", "*/package.json").stdout
    dirs = {""}
    for f in listed.split("\0"):
        parts = f.split("/")
        # ponytail: depth cap of 4 dirs covers apps/*/packages/*; raise if a monorepo nests deeper.
        if parts[-1] == "package.json" and "node_modules" not in parts and len(parts) <= 5:
            dirs.add("/".join(parts[:-1]))
    wanted = [os.path.join(d, "node_modules") if d else "node_modules"
              for d in sorted(dirs)] if node_modules else []
    wanted += sorted(n for n in os.listdir(work)
                     if (n == ".env" or n.startswith(".env."))
                     and os.path.isfile(os.path.join(work, n)) and not _tracked(work, n))
    linked = []
    for rel in wanted:
        src, dst = os.path.join(work, rel), os.path.join(tmp, rel)
        if (not os.path.exists(src) or os.path.lexists(dst)
                or not os.path.isdir(os.path.dirname(dst))):
            continue
        os.symlink(src, dst)
        linked.append(rel)
    return linked


def _rev(repo, ref):
    res = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    return res.stdout.strip() if res.returncode == 0 else None


def _checked_out(repo, branch):
    """Every worktree holding <branch>, the one we are landing from included."""
    res = _git(repo, "worktree", "list", "--porcelain")
    out, path = [], None
    for line in res.stdout.splitlines():
        if line.startswith("worktree "):
            path = line.split(" ", 1)[1]
        elif line.startswith("branch ") and path:
            if line.split(" ", 1)[1] == f"refs/heads/{branch}":
                out.append(path)
    return out


def _overwritten_files(stderr):
    """The file list git prints when a merge refuses to overwrite local changes."""
    return [line.strip() for line in stderr.splitlines() if line.startswith(("\t", "    "))]


LAND_OK, LAND_CONFLICT, LAND_GATE_RED, LAND_MOVED, LAND_BLOCKED = 0, 3, 4, 5, 6


def cmd_land(args):
    """Gate a candidate, then advance the target only if it has not moved.

    The target branch is NEVER the thing being tested. A merge commit cannot be
    aborted once it exists, so merging into the target first and testing second
    leaves rejected code on the branch, where a later green run carries it in.
    Here the merge happens in a temporary detached worktree, the gate runs
    there, and the target moves from the exact commit that was gated. --work is
    only touched by the final fast-forward, so another thread's unrelated
    uncommitted file in it never blocks a landing."""
    work, target, source = args.work, args.target, args.source
    if not (args.gate or "").strip():
        print("--gate is required: nothing lands untested. Pass --gate true to say "
              "so deliberately.", file=sys.stderr)
        return 2
    handle = None
    if not getattr(args, "no_lock", False):
        handle = _flock(work, "land", getattr(args, "wait", 0.0) or 0.0)
        if handle is None:
            print("another landing holds this repo — retry, or use --wait", file=sys.stderr)
            return LAND_BLOCKED
    try:
        return _land_locked(args, work, target, source)
    finally:
        if handle is not None:
            handle.close()


def _land_locked(args, work, target, source):
    if len(_checked_out(work, target)) > 1:
        print(f"{target} is checked out in more than one worktree — free one", file=sys.stderr)
        return LAND_BLOCKED
    g = _rev(work, target)
    if not g:
        print(f"no such ref: {target}", file=sys.stderr)
        return LAND_BLOCKED
    if not _rev(work, source):
        print(f"no such ref: {source}", file=sys.stderr)
        return LAND_BLOCKED
    tmp = tempfile.mkdtemp(prefix="driver-land-")
    linked = []
    try:
        added = _git(work, "worktree", "add", "--quiet", "--detach", tmp, g)
        if added.returncode != 0:
            print(f"could not make a temporary worktree at {g[:8]}:\n{added.stderr.strip()}",
                  file=sys.stderr)
            return LAND_BLOCKED
        return _land_in(args, work, tmp, target, source, g, linked)
    finally:
        for rel in linked:  # unlink first, so nothing below can follow a link into --work
            try:
                os.unlink(os.path.join(tmp, rel))
            except OSError:
                pass
        # ponytail: runs on gate failure and Ctrl-C; a SIGKILL leaves the dir,
        # which the next `git worktree prune` sweeps once the OS clears the temp dir.
        _git(work, "worktree", "remove", "--force", tmp)
        _git(work, "worktree", "prune")
        shutil.rmtree(tmp, ignore_errors=True)


def _land_in(args, work, tmp, target, source, g, linked):
    merged = _git(tmp, "merge", "--no-ff", "-m", args.message or
                  f"merge {source} into {target}", source)
    if merged.returncode != 0:
        print(merged.stdout + merged.stderr, file=sys.stderr)
        return LAND_CONFLICT
    # Link after merging, so a link never sits on a path the source starts tracking.
    # <linked> is the caller's list: it unlinks these on the way out.
    fresh = _pnpm_fresh(work, tmp)
    # Any dir fresh means node_modules is linked nowhere (node_modules=not fresh below), so
    # every dir with a lockfile needs its own install, not just the one(s) that triggered it:
    # a root install can write through a nested link into --work, and an uninstalled root
    # with no link is a false gate failure on a monorepo where only a sub-package changed.
    install_dirs = _lockfile_dirs(tmp) if fresh else []
    fresh_nm = [os.path.join(d, "node_modules") if d else "node_modules" for d in install_dirs]
    linked.extend(_link_shared(work, tmp, node_modules=not fresh))
    for d in install_dirs:
        print(f"pnpm-lock.yaml changed somewhere in the tree: installing into ./{d} in the "
              "gate worktree, no node_modules linked", file=sys.stderr)
        inst = subprocess.run(["pnpm", "install", "--frozen-lockfile", "--prefer-offline"],
                              cwd=os.path.join(tmp, d))
        if inst.returncode != 0:
            print(f"pnpm install failed in the gate worktree ({inst.returncode}) — nothing landed",
                  file=sys.stderr)
            return LAND_GATE_RED
    # Whenever the candidate has submodules: a fresh clone or a linked --work keeps no
    # module store in the common dir, and skipping would hand the gate empty folders.
    if os.path.isfile(os.path.join(tmp, ".gitmodules")):
        sub = _git(tmp, "submodule", "update", "--init", "--recursive")
        if sub.returncode != 0:
            print(f"could not populate submodules in the gate worktree:\n{sub.stderr.strip()}",
                  file=sys.stderr)
            return LAND_BLOCKED
    t = _rev(tmp, "HEAD")
    _journal(args, {"phase": "candidate", "target": target, "source": source,
                    "base": g, "candidate": t})

    env = dict(os.environ, CI_GATE_IGNORE_UNTRACKED="\n".join(linked + fresh_nm))
    if any(rel.endswith("node_modules") for rel in linked):
        # pnpm 11 reads pnpm_config_* from the environment, never npm_config_* (checked on
        # 11.18: npm_config_verify_deps_before_run=false still fails, this one passes).
        env["pnpm_config_verify_deps_before_run"] = "false"
    gate, skipped = _run_gate(args.gate, tmp, env)
    if skipped:
        _journal(args, {"phase": "gate-skip", "target": target, "candidate": t,
                        "line": skipped})
    if gate.returncode != 0:
        moved = _rev(work, target)
        if moved != g:
            print(f"gate failed ({gate.returncode}) AND {target} moved to "
                  f"{(moved or '?')[:8]} during it — the gate wrote to the repo. "
                  f"Check {target} by hand.", file=sys.stderr)
        else:
            print(f"gate failed ({gate.returncode}) — {target} unchanged at {g[:8]}",
                  file=sys.stderr)
        return LAND_GATE_RED
    if _rev(tmp, "HEAD") != t or not _is_clean(tmp, linked + fresh_nm):
        print("the gate changed the tree it tested — nothing landed", file=sys.stderr)
        return LAND_GATE_RED
    _journal(args, {"phase": "gated", "target": target, "base": g, "candidate": t})

    if _rev(work, target) != g:
        print(f"{target} moved since the gate — nothing landed. Re-run to gate again.",
              file=sys.stderr)
        return LAND_MOVED
    busy = _checked_out(work, target)
    if len(busy) > 1:
        print(f"{target} was checked out in a second worktree during the gate — "
              "nothing landed", file=sys.stderr)
        return LAND_BLOCKED
    if busy:
        # Fast-forward the worktree holding the branch, so its ref and files move
        # together. Git allows this over unrelated dirty files and refuses only
        # when one of them would be overwritten. --no-overwrite-ignore makes an
        # ignored file (local config, a secret) count as one; the command-scoped
        # merge.autoStash=false stops autostash hiding a dirty edit, on every git
        # version (the --no-autostash flag only exists from 2.27).
        ff = _git(busy[0], "-c", "merge.autoStash=false", "merge", "--ff-only", "--quiet",
                  "--no-overwrite-ignore", t)
        if ff.returncode != 0:
            if _rev(work, target) != g:
                print(f"{target} moved since the gate — nothing landed. Re-run to gate "
                      "again.", file=sys.stderr)
                return LAND_MOVED
            files = _overwritten_files(ff.stderr)
            print(f"{target} is checked out in {busy[0]} with uncommitted or ignored files the "
                  f"landing would overwrite — nothing landed: {', '.join(files) or '?'}\n"
                  f"{ff.stderr.strip()}", file=sys.stderr)
            return LAND_BLOCKED
    else:
        cas = _git(work, "update-ref", f"refs/heads/{target}", t, g)
        if cas.returncode != 0:
            print(f"{target} moved since the gate — nothing landed. Re-run to gate again.",
                  file=sys.stderr)
            return LAND_MOVED
    _journal(args, {"phase": "landed", "target": target, "base": g, "candidate": t})
    _log_overlap(args, work, target, t)
    print(t)
    return LAND_OK


HEAVY_JOB = os.path.expanduser("~/.claude/scripts/heavy-job")
# The whole gate is one ci-gate --gate-only call, optionally after env assignments.
# Anything combined with it (&&, ;, a comment, more flags) holds a slot like any gate.
_CI_GATE_ONLY = re.compile(r"(?:[A-Za-z_]\w*=[\w./:@%+,-]*\s+)*"
                           r"(?:(?:ba)?sh\s+)?[\w./~-]*ci-gate\.sh\s+--gate-only")


def _gate_argv(gate):
    """`ci-gate.sh --gate-only` slots itself after its ledger check, so wrapping it would
    queue behind two suites only to learn it can skip. `true` is no job. Anything else
    holds a heavy-job slot while it runs."""
    sh = ["/bin/sh", "-c", gate]
    if _CI_GATE_ONLY.fullmatch(gate.strip()) or gate.strip() == "true":
        return sh
    if not os.access(HEAVY_JOB, os.X_OK):
        print(f"driver_state: heavy-job not found at {HEAVY_JOB} — gate runs unslotted",
              file=sys.stderr)
        return sh
    return [HEAVY_JOB, "run", "--", *sh]


def _run_gate(gate, cwd, env):
    """Run the gate, echoing its output, and return (result, ci-gate's skip line or None)."""
    proc = subprocess.Popen(_gate_argv(gate), cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors="replace")
    skipped = None
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        if skipped is None and line.startswith("ci-gate: skip,"):
            skipped = line.strip()
    proc.wait()
    return proc, skipped


def _changed_paths(work, base, tip):
    """NUL-delimited: a filename can contain a newline."""
    res = _git(work, "diff", "--name-only", "-z", f"{base}...{tip}")
    return {p for p in res.stdout.split("\0") if p}


def _log_overlap(args, work, target, t):
    """How much does this landing touch what another live run has already landed?

    ponytail: recorded, never enforced. Path overlap arrives after the build it
    would have saved, it false-positives on lockfiles, and holding a ticket on it
    deadlocks two runs that each wait on the other's file. The gate on the
    combined tree is the real check. This line exists to answer 'how often does
    it actually happen' with data rather than a guess."""
    if not target.startswith("driver/"):
        return
    # Live means "still has a worktree": a finished run removes its own, and a
    # retained branch from a pruned run is history, not a contender.
    live = set()
    res = _git(work, "worktree", "list", "--porcelain")
    for line in res.stdout.splitlines():
        if line.startswith("branch refs/heads/"):
            live.add(line.split("refs/heads/", 1)[1])
    others = [b for b in live if b.startswith("driver/") and b != target]
    if not others:
        return
    for other in others:
        base = _git(work, "merge-base", target, other).stdout.strip()
        if not base:
            continue
        ours = _changed_paths(work, base, t)
        theirs = _changed_paths(work, base, other)
        shared = sorted(ours & theirs)
        if shared:
            _journal(args, {"phase": "overlap", "target": target, "other": other,
                            "paths": shared[:50], "count": len(shared)})


def _journal(args, entry):
    run_dir = getattr(args, "run_dir", None)
    if not run_dir or not os.path.isdir(run_dir):
        return
    entry = dict(entry)
    entry.setdefault("ticket_id", getattr(args, "ticket_id", None))
    append_journal(run_dir, entry)


RUN_KEY = "_run"  # reserved: run metadata, never a ticket id


def cmd_note(args):
    _journal(args, {"phase": args.phase, "note": args.text})
    return 0


def cmd_init(args):
    os.makedirs(args.run_dir, exist_ok=True)
    os.makedirs(os.path.join(args.run_dir, "handoffs"), exist_ok=True)
    if os.path.exists(_state_path(args.run_dir)):
        state = load_state(args.run_dir)
        if (args.integration_branch or args.work) and RUN_KEY not in state:
            state[RUN_KEY] = {"run_id": os.path.basename(os.path.abspath(args.run_dir)),
                              "run_dir": os.path.abspath(args.run_dir),
                              "work": os.path.abspath(args.work) if args.work else None,
                              "integration_branch": args.integration_branch,
                              "default_ref": args.default_ref,
                              "base": args.base, "ts": time.time()}
            atomic_write_json(_state_path(args.run_dir), state)
            print(f"run-dir already initialised: {args.run_dir} — recorded its identity")
            return 0
        print(f"run-dir already initialised: {args.run_dir}", file=sys.stderr)
        return 0
    state = {tid: {"status": "pending", "commit": None, "reviewer": None, "ts": time.time()}
             for tid in args.ticket_ids}
    if args.integration_branch or args.work:
        state[RUN_KEY] = {"run_id": os.path.basename(os.path.abspath(args.run_dir)),
                          "run_dir": os.path.abspath(args.run_dir),
                          "work": os.path.abspath(args.work) if args.work else None,
                          "integration_branch": args.integration_branch,
                          "default_ref": args.default_ref,
                          "base": args.base, "ts": time.time()}
    open(_journal_path(args.run_dir), "a").close()
    for tid in args.ticket_ids:
        append_journal(args.run_dir, {"ticket_id": tid, "status": "pending",
                                      "commit": None, "reviewer": None})
    atomic_write_json(_state_path(args.run_dir), state)
    print(f"initialised {len(args.ticket_ids)} ticket(s) in {args.run_dir}")
    return 0


def cmd_lock(args):
    lock_dir = _lock_dir(args.run_dir)
    owner_path = os.path.join(lock_dir, "owner.json")
    try:
        os.mkdir(lock_dir)
    except FileExistsError:
        owner = {}
        try:
            with open(owner_path) as f:
                owner = json.load(f)
        except (json.JSONDecodeError, OSError):
            owner = {}
        if not owner:
            # mkdir landed but owner.json did not: either a crash, or an owner
            # still writing it. Give the writer a moment, then fall through to
            # reclaim — an unreadable owner file must never wedge the run.
            time.sleep(1.5)
            try:
                with open(owner_path) as f:
                    owner = json.load(f)
            except (json.JSONDecodeError, OSError):
                owner = {}
        if owner and _owner_is_live(owner, args.stale_hours):
            print(f"lock held by pid {owner.get('pid')}: {owner_path} — "
                  "another /driver run is active", file=sys.stderr)
            return 1
        # The owner is gone. Claim the reclaim by renaming the stale directory:
        # two contenders both see it dead, only one rename succeeds.
        stale = f"{lock_dir}.stale-{os.getpid()}-{int(time.time())}"
        try:
            os.rename(lock_dir, stale)
        except OSError:
            print("lost the race to reclaim a dead lock — another run has it",
                  file=sys.stderr)
            return 1
        shutil.rmtree(stale, ignore_errors=True)
        try:
            os.mkdir(lock_dir)
        except FileExistsError:
            print("lost the race to reclaim a dead lock — another run has it",
                  file=sys.stderr)
            return 1
    with open(owner_path, "w") as f:
        json.dump(_owner_record(), f)
    print(f"lock acquired: {lock_dir}")
    return 0


def cmd_unlock(args):
    """Release only a lock this thread owns — never whoever replaced it."""
    lock_dir = _lock_dir(args.run_dir)
    owner_path = os.path.join(lock_dir, "owner.json")
    if not os.path.exists(lock_dir):
        print("lock already released")
        return 0
    owner = {}
    try:
        with open(owner_path) as f:
            owner = json.load(f)
    except (json.JSONDecodeError, OSError):
        owner = {}
    mine = _owner_pid()
    if owner.get("pid") and owner.get("pid") != mine and _owner_is_live(owner):
        print(f"not releasing: the lock belongs to pid {owner['pid']}, not {mine}",
              file=sys.stderr)
        return 1
    shutil.rmtree(lock_dir, ignore_errors=True)
    print("lock released")
    return 0


def cmd_set_status(args):
    if args.status not in VALID_STATUSES:
        print(f"invalid status {args.status!r}, must be one of {sorted(VALID_STATUSES)}",
              file=sys.stderr)
        return 2
    entry = {"ticket_id": args.ticket_id, "status": args.status,
              "commit": args.commit, "reviewer": args.reviewer}
    append_journal(args.run_dir, entry)  # journal first — it's the recovery source of truth
    state = load_state(args.run_dir)
    state[args.ticket_id] = {"status": args.status, "commit": args.commit,
                              "reviewer": args.reviewer, "ts": time.time(),
                              "seq": _next_seq(args.run_dir) - 1}
    atomic_write_json(_state_path(args.run_dir), state)
    print(f"{args.ticket_id}: {args.status}")
    return 0


def cmd_env(args):
    """Print the run's identity as shell assignments, for a resume to eval."""
    meta = load_state(args.run_dir).get(RUN_KEY)
    if not meta:
        print(f"no run metadata in {args.run_dir} — this run predates it, or init "
              "never recorded it", file=sys.stderr)
        return 1
    for name, key in (("RUN_ID", "run_id"), ("RUN_DIR", "run_dir"), ("WORK", "work"),
                      ("INTEGRATION_BRANCH", "integration_branch"),
                      ("DEFAULT_REF", "default_ref"), ("RUN_BASE", "base")):
        value = meta.get(key)
        if value:
            print(f"{name}={value!r}".replace("'", '"'))
    return 0


def cmd_get_status(args):
    state = load_state(args.run_dir)
    entry = state.get(args.ticket_id)
    if entry is None:
        print("unknown", file=sys.stderr)
        return 1
    print(json.dumps(entry))
    return 0


def cmd_summary(args):
    state = load_state(args.run_dir)
    for tid, entry in sorted(state.items()):
        if tid == RUN_KEY:
            print(f"{tid}\t{json.dumps(entry)}")
            continue
        print(f"{tid}\t{entry.get('status')}\t{entry.get('commit') or '-'}\t{entry.get('reviewer') or '-'}")
    return 0


def progress_line(state, label, now=None):
    """One phone-sized progress line with an ETA. Pure, so the selftest can pin it."""
    now = now or time.time()
    tickets = {k: v for k, v in state.items() if k != RUN_KEY}
    count = {s: 0 for s in VALID_STATUSES}
    for entry in tickets.values():
        count[entry.get("status", "pending")] = count.get(entry.get("status", "pending"), 0) + 1
    started = (state.get(RUN_KEY) or {}).get("ts") or min(
        (e.get("ts") or now for e in tickets.values()), default=now)
    elapsed = max(0.0, now - started)
    # Skipped tickets cascade instantly, so only worked tickets set the pace.
    # ponytail: mean pace since run start, so a resumed run counts the gap; per-ticket timings if the ETA misleads
    worked = count["merged"] + count["blocked"]
    left = count["pending"] + count["in-progress"]
    done = worked + count["skipped"]

    def dur(s):
        h, m = divmod(int(s // 60), 60)
        return f"{h}h{m:02d}m" if h else f"{m}m"

    if left == 0:
        eta = "ETA: finishing now"
    elif worked == 0:
        eta = "ETA after the first ticket lands"
    else:
        rest = elapsed / worked * left
        eta = f"ETA {time.strftime('%H:%M', time.localtime(now + rest))} (about {dur(rest)})"
    parts = [f"{count['merged']} merged"]
    parts += [f"{count[s]} {s}" for s in ("blocked", "skipped") if count[s]]
    return (f"{label}: {done}/{len(tickets)} done ({', '.join(parts)}), "
            f"{count['in-progress']} in progress. Running {dur(elapsed)}. {eta}")


def cmd_progress(args):
    """Print the progress line. Exit 3 when no live run holds the lock, so an
    hourly watcher loop stops by itself when the run ends or its thread dies."""
    try:
        with open(os.path.join(_lock_dir(args.run_dir), "owner.json")) as f:
            owner = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 3
    if not _owner_is_live(owner):
        return 3
    # 'started' is the lock-acquisition timestamp, written fresh by _owner_record()
    # every time the lock is taken — unique per acquisition even when the pid is
    # unidentifiable (pid None). A resumed run relocks with a new 'started', so
    # comparing it (not the pid) is what makes the old thread's watcher stop
    # instead of double-reporting against the new owner. Only a missing owner.json
    # (handled above) fails open; a present-but-unmatched token fails closed.
    token = owner.get("started")
    if args.owner is not None and str(token) != str(args.owner):
        return 3
    if args.owner_only:
        print(token if token is not None else "none")
        return 0
    print(progress_line(load_state(args.run_dir), args.label))
    return 0


def cmd_reconcile(args):
    """A ticket marked in-progress/merged with a commit that isn't actually an
    ancestor of the integration branch tip did NOT really land — a crash could
    have died between 'merge succeeded' and 'state says done'. Re-derive truth
    from git, don't trust the state file blindly."""
    state = load_state(args.run_dir)
    changed = False
    for tid, entry in state.items():
        if tid == RUN_KEY:
            continue
        status, commit = entry.get("status"), entry.get("commit")
        if status not in ("in-progress", "merged"):
            continue
        if status == "in-progress":
            # never actually confirmed merged — always demote back to pending
            entry["status"] = "pending"
            changed = True
            print(f"{tid}: in-progress with no confirmed merge -> pending (re-run)")
            append_journal(args.run_dir, {"ticket_id": tid, "status": "pending",
                                          "commit": None, "reviewer": None,
                                          "note": "reconcile: no confirmed merge"})
            continue
        if not commit:
            entry["status"] = "pending"
            changed = True
            print(f"{tid}: merged but no recorded commit -> pending (re-run)")
            append_journal(args.run_dir, {"ticket_id": tid, "status": "pending",
                                          "commit": None, "reviewer": None,
                                          "note": "reconcile: merged without a commit"})
            continue
        res = _git(args.repo, "merge-base", "--is-ancestor", commit, args.integration_branch)
        if res.returncode != 0:
            entry["status"] = "pending"
            changed = True
            print(f"{tid}: commit {commit[:8]} not on {args.integration_branch} -> pending (re-run)")
            append_journal(args.run_dir, {"ticket_id": tid, "status": "pending",
                                          "commit": None, "reviewer": None,
                                          "note": f"reconcile: {commit[:8]} not on {args.integration_branch}"})
    if changed:
        atomic_write_json(_state_path(args.run_dir), state)
    else:
        print("state matches git ancestry, nothing to reconcile")
    return 0


def build_parser():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--selftest", action="store_true")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("init")
    s.add_argument("run_dir")
    s.add_argument("ticket_ids", nargs="+")
    s.add_argument("--work", help="worktree holding the integration branch")
    s.add_argument("--integration-branch")
    s.add_argument("--default-ref")
    s.add_argument("--base", help="default branch OID when the run started")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("lock")
    s.add_argument("run_dir")
    s.add_argument("--stale-hours", type=float, default=6.0)
    s.set_defaults(func=cmd_lock)

    s = sub.add_parser("unlock")
    s.add_argument("run_dir")
    s.set_defaults(func=cmd_unlock)

    s = sub.add_parser("set-status")
    s.add_argument("run_dir")
    s.add_argument("ticket_id")
    s.add_argument("status")
    s.add_argument("--commit")
    s.add_argument("--reviewer")
    s.set_defaults(func=cmd_set_status)

    s = sub.add_parser("note", help="journal a phase record that is not a status change")
    s.add_argument("run_dir")
    s.add_argument("ticket_id")
    s.add_argument("phase")
    s.add_argument("text")
    s.set_defaults(func=cmd_note)

    s = sub.add_parser("env", help="print the run's identity as shell assignments")
    s.add_argument("run_dir")
    s.set_defaults(func=cmd_env)

    s = sub.add_parser("get-status")
    s.add_argument("run_dir")
    s.add_argument("ticket_id")
    s.set_defaults(func=cmd_get_status)

    s = sub.add_parser("summary")
    s.add_argument("run_dir")
    s.set_defaults(func=cmd_summary)

    s = sub.add_parser("progress", help="one-line progress + ETA; exit 3 when the run is not live")
    s.add_argument("run_dir")
    s.add_argument("--label", default="", help="e.g. '<repo> driver, <run label>'")
    s.add_argument("--owner", help="exit 3 unless this acquisition token still owns the lock "
                   "(value from --owner-only; a stale resumed lock's token never matches)")
    s.add_argument("--owner-only", action="store_true", help="print the lock's acquisition "
                   "token ('started' timestamp), or 'none' if owner.json predates it")
    s.set_defaults(func=cmd_progress)

    s = sub.add_parser("with-lock", help="run a command holding a repo-wide lock")
    s.add_argument("name")
    s.add_argument("--repo", default=".")
    s.add_argument("--wait", type=float, default=0.0,
                   help="seconds to wait for the lock (default: fail immediately)")
    s.set_defaults(func=cmd_with_lock, command=[])

    s = sub.add_parser("land", help="gate a candidate merge, then advance the target by CAS")
    s.add_argument("--work", required=True, help="worktree to build the candidate in")
    s.add_argument("--target", required=True, help="branch to advance (never tested directly)")
    s.add_argument("--source", required=True, help="branch to merge in")
    s.add_argument("--gate", help="shell command to run on the candidate")
    s.add_argument("--message")
    s.add_argument("--run-dir")
    s.add_argument("--ticket-id")
    s.add_argument("--wait", type=float, default=0.0,
                   help="seconds to wait for the landing lock")
    s.add_argument("--no-lock", action="store_true",
                   help="skip the landing lock (tests only)")
    s.set_defaults(func=cmd_land)

    s = sub.add_parser("reconcile")
    s.add_argument("run_dir")
    s.add_argument("--repo", required=True)
    s.add_argument("--integration-branch", required=True)
    s.set_defaults(func=cmd_reconcile)

    return p


def _fixture_repo(path):
    """A tiny git repo: main with one file, plus a `feature` branch on top."""
    subprocess.run(["git", "init", "-q", "-b", "main", path], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", path, "config", k, v], check=True)
    with open(os.path.join(path, "a.txt"), "w") as f:
        f.write("base\n")
    subprocess.run(["git", "-C", path, "add", "."], check=True)
    subprocess.run(["git", "-C", path, "commit", "-q", "-m", "init"], check=True)
    subprocess.run(["git", "-C", path, "switch", "-q", "-c", "feature"], check=True)
    with open(os.path.join(path, "b.txt"), "w") as f:
        f.write("feature\n")
    subprocess.run(["git", "-C", path, "add", "."], check=True)
    subprocess.run(["git", "-C", path, "commit", "-q", "-m", "feature"], check=True)
    subprocess.run(["git", "-C", path, "switch", "-q", "main"], check=True)


def _worktrees(repo):
    res = _git(repo, "worktree", "list", "--porcelain")
    return [line for line in res.stdout.splitlines() if line.startswith("worktree ")]


def _land(repo, gate="true", source="feature", target="main", run_dir=None):
    return cmd_land(argparse.Namespace(work=repo, target=target, source=source,
                                       gate=gate, message=None, run_dir=run_dir,
                                       ticket_id="t1"))


def selftest_land():
    import tempfile as tf

    # Every non-ci-gate gate below runs under a stub heavy-job that logs and runs it,
    # so the selftest never queues for a real slot.
    global HEAVY_JOB
    stub_dir = tf.TemporaryDirectory()
    HEAVY_JOB = os.path.join(stub_dir.name, "heavy-job")
    stub_log = os.path.join(stub_dir.name, "calls")
    with open(HEAVY_JOB, "w") as f:
        f.write(f'#!/bin/sh\necho "$*" >> "{stub_log}"\nshift 2\nexec "$@"\n')
    os.chmod(HEAVY_JOB, 0o755)

    # (w) the wrap rule: ci-gate --gate-only and `true` run bare, anything else is slotted.
    assert _gate_argv("bash scripts/ci-gate.sh --gate-only")[0] == "/bin/sh"
    assert _gate_argv("true")[0] == "/bin/sh"
    assert _gate_argv("pnpm test")[:3] == [HEAVY_JOB, "run", "--"]
    assert _gate_argv("FOO=1 BAR=x scripts/ci-gate.sh --gate-only")[0] == "/bin/sh"
    for combined in ("scripts/ci-gate.sh --gate-only && pnpm build",
                     "pnpm build; scripts/ci-gate.sh --gate-only",
                     "echo x # ci-gate.sh --gate-only",
                     "scripts/ci-gate.sh --gate-only --extra"):
        assert _gate_argv(combined)[0] == HEAVY_JOB, combined
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        assert _land(repo, gate="test -f b.txt") == LAND_OK
        assert open(stub_log).read() == "run -- /bin/sh -c test -f b.txt\n"
    print("ok: (w) a plain gate holds a heavy-job slot; ci-gate --gate-only slots itself")

    # (s) ci-gate's skip line is journalled.
    with tf.TemporaryDirectory() as repo, tf.TemporaryDirectory() as run_dir:
        _fixture_repo(repo)
        open(_journal_path(run_dir), "a").close()
        gate = "echo 'ci-gate: skip, matched abc differs only in README.md' # ci-gate.sh --gate-only"
        assert _land(repo, gate=gate, run_dir=run_dir) == LAND_OK
        rows = [json.loads(line) for line in open(_journal_path(run_dir))]
        assert [r["phase"] for r in rows] == ["candidate", "gate-skip", "gated", "landed"], rows
        assert rows[1]["line"].endswith("differs only in README.md"), rows[1]
    print("ok: (s) a gate that ci-gate skipped is journalled as gate-skip")

    # (u) the candidate's pnpm lockfile is compared with the lockfile pnpm recorded at
    # install (node_modules/.pnpm/lock.yaml), never with --work's HEAD: land fast-forwards
    # --work without reinstalling, so HEAD can be ahead of what is installed.
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        with open(os.path.join(repo, ".gitignore"), "w") as f:
            f.write("node_modules/\n")
        for branch, text in (("main", "lock: 2\n"), ("feature", "lock: 2\n")):
            subprocess.run(["git", "-C", repo, "switch", "-q", branch], check=True)
            with open(os.path.join(repo, "pnpm-lock.yaml"), "w") as f:
                f.write(text)
            subprocess.run(["git", "-C", repo, "add", "."], check=True)
            subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "lock"], check=True)
        subprocess.run(["git", "-C", repo, "switch", "-q", "main"], check=True)
        cand = os.path.join(repo, ".git", "cand")
        subprocess.run(["git", "-C", repo, "worktree", "add", "-q", "--detach", cand, "feature"],
                       check=True)
        assert _pnpm_fresh(repo, cand) == [""], "no install record: fresh, never equal"
        record = os.path.join(repo, "node_modules", ".pnpm", "lock.yaml")
        os.makedirs(os.path.dirname(record))
        with open(record, "w") as f:
            f.write("lock: 1\n")  # installed from an older lockfile than HEAD's
        assert _pnpm_fresh(repo, cand) == [""], "HEAD matches but the install does not"
        with open(record, "w") as f:
            f.write("lock: 2\n")
        assert _pnpm_fresh(repo, cand) == [], "install record matches: link"
        assert _link_shared(repo, cand, node_modules=False) == []
        assert not os.path.lexists(os.path.join(cand, "node_modules"))
    print("ok: (u) the lockfile is compared with what node_modules was installed from")

    # (u2) a fresh install links no node_modules at any depth, so the root install
    # cannot write through a nested link into --work.
    stub_pnpm = os.path.join(stub_dir.name, "pnpm")
    with open(stub_pnpm, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(stub_pnpm, 0o755)
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        os.makedirs(os.path.join(repo, "packages", "a"))
        for rel, text in ((".gitignore", "node_modules/\n"), ("package.json", "{}\n"),
                          ("packages/a/package.json", "{}\n"), ("pnpm-lock.yaml", "lock: 1\n")):
            with open(os.path.join(repo, rel), "w") as f:
                f.write(text)
        subprocess.run(["git", "-C", repo, "add", "."], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "pnpm"], check=True)
        os.makedirs(os.path.join(repo, "node_modules", "x"))
        os.makedirs(os.path.join(repo, "packages", "a", "node_modules", "y"))
        old_path = os.environ["PATH"]
        os.environ["PATH"] = stub_dir.name + os.pathsep + old_path
        try:
            gate = "! test -L node_modules && ! test -L packages/a/node_modules"
            assert _land(repo, gate=gate) == LAND_OK, "a nested node_modules was linked"
        finally:
            os.environ["PATH"] = old_path
    print("ok: (u2) a fresh pnpm install links no node_modules at any depth")

    # (u3) only a nested lockfile changed, but the root lockfile is untouched: any dir
    # being fresh must still install the root too, not just the dir that triggered it,
    # or the gate worktree ends up with no root node_modules at all (a false red).
    install_log = os.path.join(stub_dir.name, "u3-installs.log")
    stub_pnpm_log = os.path.join(stub_dir.name, "pnpm")
    with open(stub_pnpm_log, "w") as f:
        f.write(f'#!/bin/sh\necho "$PWD" >> {install_log}\nexit 0\n')
    os.chmod(stub_pnpm_log, 0o755)
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        os.makedirs(os.path.join(repo, "packages", "a"))
        with open(os.path.join(repo, ".gitignore"), "w") as f:
            f.write("node_modules/\n")
        for rel, text in (("package.json", "{}\n"), ("packages/a/package.json", "{}\n"),
                          ("pnpm-lock.yaml", "lock: 1\n"), ("packages/a/pnpm-lock.yaml", "lock: 1\n")):
            with open(os.path.join(repo, rel), "w") as f:
                f.write(text)
        subprocess.run(["git", "-C", repo, "add", "."], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "lockfiles on main"], check=True)
        # Bring the (identical) lockfiles onto feature too, then move only the sub-package's.
        subprocess.run(["git", "-C", repo, "switch", "-q", "feature"], check=True)
        subprocess.run(["git", "-C", repo, "merge", "-q", "--no-edit", "main"], check=True)
        with open(os.path.join(repo, "packages", "a", "pnpm-lock.yaml"), "w") as f:
            f.write("lock: 2\n")
        subprocess.run(["git", "-C", repo, "add", "."], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "bump sub lock"], check=True)
        subprocess.run(["git", "-C", repo, "switch", "-q", "main"], check=True)
        # Record the root install as matching HEAD, so the root alone is never "fresh" —
        # only packages/a is, because its lockfile moves between main and feature.
        record = os.path.join(repo, "node_modules", ".pnpm", "lock.yaml")
        os.makedirs(os.path.dirname(record))
        with open(record, "w") as f:
            f.write("lock: 1\n")
        old_path = os.environ["PATH"]
        os.environ["PATH"] = stub_dir.name + os.pathsep + old_path
        try:
            assert _land(repo) == LAND_OK
        finally:
            os.environ["PATH"] = old_path
        # The gate worktree's absolute path varies per run; only the tail after it matters.
        tails = {("packages/a" if line.endswith(os.path.join("packages", "a")) else "root")
                 for line in open(install_log).read().splitlines()}
        assert tails == {"root", "packages/a"}, (
            f"expected pnpm install in both the root and packages/a, got {tails}")
    print("ok: (u3) any fresh lockfile dir installs every dir with a lockfile, root included")

    # (d) a red gate leaves the target exactly where it was.
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        before = _rev(repo, "main")
        with open(os.path.join(repo, "note.md"), "w") as f:
            f.write("another thread's note\n")
        assert _land(repo, gate="exit 1") == LAND_GATE_RED
        assert _rev(repo, "main") == before
        assert _rev(repo, "HEAD") == before, "--work is untouched"
        assert _rev(repo, "feature") is not None, "the ticket branch survives for inspection"
        assert open(os.path.join(repo, "note.md")).read() == "another thread's note\n"
        assert _checked_out(repo, "main") and len(_worktrees(repo)) == 1, "temp worktree left"
    print("ok: (d) a ticket that fails its gate never reaches the target branch")

    # (e) a conflicting merge aborts and leaves no half-merged worktree.
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        for branch, text in (("main", "mine\n"), ("feature", "theirs\n")):
            subprocess.run(["git", "-C", repo, "switch", "-q", branch], check=True)
            with open(os.path.join(repo, "c.txt"), "w") as f:
                f.write(text)
            subprocess.run(["git", "-C", repo, "add", "."], check=True)
            subprocess.run(["git", "-C", repo, "commit", "-q", "-m", f"c on {branch}"], check=True)
        subprocess.run(["git", "-C", repo, "switch", "-q", "main"], check=True)
        before = _rev(repo, "main")
        assert _land(repo) == LAND_CONFLICT
        assert _rev(repo, "main") == before
        assert _is_clean(repo), "no unresolved merge left behind"
    print("ok: (e) a conflicting ticket aborts cleanly and the target is untouched")

    # (f) the target moving during the gate is caught by compare-and-swap.
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        subprocess.run(["git", "-C", repo, "switch", "-q", "-c", "sneak"], check=True)
        with open(os.path.join(repo, "d.txt"), "w") as f:
            f.write("sneak\n")
        subprocess.run(["git", "-C", repo, "add", "."], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "sneak"], check=True)
        sneak = _rev(repo, "sneak")
        subprocess.run(["git", "-C", repo, "switch", "-q", "main"], check=True)
        rc = _land(repo, gate=f"git update-ref refs/heads/main {sneak}")
        assert rc == LAND_MOVED, rc
        assert _rev(repo, "main") == sneak, "the other writer's commit stands, ours does not"
    print("ok: (f) a target that moved during the gate refuses the landing")

    # (g) a gate that writes to the tree it tested lands nothing.
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        before = _rev(repo, "main")
        assert _land(repo, gate="echo dirty >> a.txt") == LAND_GATE_RED
        assert _rev(repo, "main") == before
    print("ok: (g) a gate that modifies the tree it tested lands nothing")

    # (h) the happy path: the target ends at the exact commit that was gated.
    with tf.TemporaryDirectory() as repo, tf.TemporaryDirectory() as run_dir:
        _fixture_repo(repo)
        os.makedirs(os.path.join(run_dir, "handoffs"))
        open(_journal_path(run_dir), "a").close()
        assert _land(repo, gate="test -f b.txt", run_dir=run_dir) == LAND_OK
        head = _rev(repo, "main")
        assert _rev(repo, "HEAD") == head
        assert subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor",
                               "feature", "main"]).returncode == 0
        phases = [json.loads(line)["phase"] for line in open(_journal_path(run_dir))]
        assert phases == ["candidate", "gated", "landed"], phases
    print("ok: (h) a green ticket lands the exact commit the gate ran on")

    # (l) an unrelated uncommitted file in --work does not block, and survives.
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        before = _rev(repo, "main")
        with open(os.path.join(repo, "a.txt"), "a") as f:
            f.write("uncommitted\n")
        with open(os.path.join(repo, "note.md"), "w") as f:
            f.write("untracked\n")
        assert _land(repo, gate="test -f b.txt") == LAND_OK
        assert _rev(repo, "main") != before and _rev(repo, "HEAD") == _rev(repo, "main")
        assert open(os.path.join(repo, "a.txt")).read() == "base\nuncommitted\n"
        assert open(os.path.join(repo, "note.md")).read() == "untracked\n"
        assert os.path.exists(os.path.join(repo, "b.txt")), "--work got the landed files"
        assert len(_worktrees(repo)) == 1, "temp worktree left"
    print("ok: (l) an unrelated uncommitted file in --work neither blocks nor gets touched")

    # (l4) the gate sees --work's gitignored node_modules and .env.local, via links
    # that leave with the temp worktree.
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        with open(os.path.join(repo, ".gitignore"), "w") as f:
            f.write("node_modules/\n.env.local\n")
        with open(os.path.join(repo, "package.json"), "w") as f:
            f.write("{}\n")
        subprocess.run(["git", "-C", repo, "add", "."], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "node"], check=True)
        os.makedirs(os.path.join(repo, "node_modules", "x"))
        with open(os.path.join(repo, ".env.local"), "w") as f:
            f.write("SECRET=1\n")
        gate = ("test -d node_modules/x && test -f .env.local && pwd > \"$TMPDIR_PROBE\" && "
                "test \"$CI_GATE_IGNORE_UNTRACKED\" = \"$(printf 'node_modules\\n.env.local')\" && "
                "test \"$pnpm_config_verify_deps_before_run\" = false")
        probe = os.path.join(repo, ".git", "probe")
        os.environ["TMPDIR_PROBE"] = probe
        try:
            assert _land(repo, gate=gate) == LAND_OK
        finally:
            del os.environ["TMPDIR_PROBE"]
        gated = open(probe).read().strip()
        assert gated != os.path.realpath(repo) and not os.path.lexists(gated), "temp worktree left"
        assert len(_worktrees(repo)) == 1, "temp worktree left"
        assert os.path.isdir(os.path.join(repo, "node_modules", "x")), "shared deps untouched"
        assert open(os.path.join(repo, ".env.local")).read() == "SECRET=1\n"
    print("ok: (l4) the gate worktree borrows node_modules and .env.local, then drops them,"
          " and is told both links are not dirt")

    # (l2) a dirty file in --work that the merge changes stops the landing.
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        before = _rev(repo, "main")
        with open(os.path.join(repo, "b.txt"), "w") as f:
            f.write("mine\n")
        assert _land(repo) == LAND_BLOCKED
        assert _rev(repo, "main") == before
        assert open(os.path.join(repo, "b.txt")).read() == "mine\n"
        assert len(_worktrees(repo)) == 1, "temp worktree left"
    assert _overwritten_files("error: ...overwritten by merge:\n\tb.txt\nPlease move") \
        == ["b.txt"]
    print("ok: (l2) a dirty file the landing would overwrite stops it (exit 6)")

    # (l5) an ignored file in --work at a path the source starts tracking stops it.
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        with open(os.path.join(repo, ".gitignore"), "w") as f:
            f.write("config.local\n")
        subprocess.run(["git", "-C", repo, "add", "."], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "ignore"], check=True)
        subprocess.run(["git", "-C", repo, "switch", "-q", "feature"], check=True)
        with open(os.path.join(repo, "config.local"), "w") as f:
            f.write("tracked\n")
        subprocess.run(["git", "-C", repo, "add", "-f", "config.local"], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "track"], check=True)
        subprocess.run(["git", "-C", repo, "switch", "-q", "main"], check=True)
        with open(os.path.join(repo, "config.local"), "w") as f:
            f.write("SECRET=mine\n")
        before = _rev(repo, "main")
        assert _land(repo) == LAND_BLOCKED
        assert _rev(repo, "main") == before
        assert open(os.path.join(repo, "config.local")).read() == "SECRET=mine\n"
    print("ok: (l5) an ignored local file the landing would overwrite stops it (exit 6)")

    # (l6) merge.autoStash=true does not stash a dirty overlapping file past the refusal.
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        subprocess.run(["git", "-C", repo, "config", "merge.autoStash", "true"], check=True)
        before = _rev(repo, "main")
        with open(os.path.join(repo, "b.txt"), "w") as f:
            f.write("mine\n")
        assert _land(repo) == LAND_BLOCKED
        assert _rev(repo, "main") == before
        assert open(os.path.join(repo, "b.txt")).read() == "mine\n"
        assert not _git(repo, "stash", "list").stdout.strip(), "a stash entry was left"
    print("ok: (l6) merge.autoStash=true still refuses (exit 6) and leaves no stash")

    # (l7) an untracked .env.local the source starts tracking is not linked over:
    # the gate sees the tracked version.
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        subprocess.run(["git", "-C", repo, "switch", "-q", "feature"], check=True)
        with open(os.path.join(repo, ".env.local"), "w") as f:
            f.write("TRACKED=1\n")
        subprocess.run(["git", "-C", repo, "add", ".env.local"], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "track env"], check=True)
        subprocess.run(["git", "-C", repo, "switch", "-q", "-c", "side", "main"], check=True)
        with open(os.path.join(repo, ".env.local"), "w") as f:
            f.write("LOCAL=1\n")
        gate = "test ! -L .env.local && grep -q TRACKED=1 .env.local"
        assert _land(repo, gate=gate) == LAND_OK
        assert subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor",
                               "feature", "main"]).returncode == 0
        assert open(os.path.join(repo, ".env.local")).read() == "LOCAL=1\n"
    print("ok: (l7) a path the source starts tracking is never shadowed by a link")

    # (l3) a target checked out nowhere lands by compare-and-swap.
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        subprocess.run(["git", "-C", repo, "switch", "-q", "-c", "side"], check=True)
        before = _rev(repo, "main")
        assert not _checked_out(repo, "main")
        assert _land(repo) == LAND_OK
        assert _rev(repo, "main") != before
        assert subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor",
                               "feature", "main"]).returncode == 0
        assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "side"
    print("ok: (l3) a target checked out nowhere lands via update-ref")

    # (m) no gate, no landing.
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        before = _rev(repo, "main")
        assert _land(repo, gate=None) == 2
        assert _land(repo, gate="  ") == 2
        assert _rev(repo, "main") == before
    print("ok: (m) a landing with no gate is refused, not waved through")

    # (n) a landing phase record must not overwrite a ticket's status on replay.
    with tf.TemporaryDirectory() as run_dir:
        os.makedirs(os.path.join(run_dir, "handoffs"))
        open(_journal_path(run_dir), "a").close()
        append_journal(run_dir, {"ticket_id": "t1", "status": "in-progress",
                                 "commit": None, "reviewer": None})
        append_journal(run_dir, {"ticket_id": "t1", "phase": "candidate",
                                 "target": "driver/x", "base": "aaa", "candidate": "bbb"})
        state = load_state(run_dir)
        assert state["t1"]["status"] == "in-progress", state
    print("ok: (n) a landing phase record leaves the ticket's status alone")

    # (o) a gate that writes to the target AND fails is called out, not hidden.
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        subprocess.run(["git", "-C", repo, "switch", "-q", "-c", "sneak"], check=True)
        with open(os.path.join(repo, "e.txt"), "w") as f:
            f.write("sneak\n")
        subprocess.run(["git", "-C", repo, "add", "."], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "sneak"], check=True)
        sneak = _rev(repo, "sneak")
        subprocess.run(["git", "-C", repo, "switch", "-q", "main"], check=True)
        rc = _land(repo, gate=f"git update-ref refs/heads/main {sneak}; false")
        assert rc == LAND_GATE_RED, rc
        assert _rev(repo, "main") == sneak, "our candidate did not land"
    print("ok: (o) a red gate that moved the target lands nothing and says so")

    # (p) run metadata is not a ticket, and reconcile leaves it alone.
    with tf.TemporaryDirectory() as repo, tf.TemporaryDirectory() as run_dir:
        _fixture_repo(repo)
        cmd_init(argparse.Namespace(run_dir=run_dir, ticket_ids=["t1"], work=repo,
                                    integration_branch="driver/x", default_ref="main",
                                    base=_rev(repo, "main")))
        cmd_reconcile(argparse.Namespace(run_dir=run_dir, repo=repo,
                                         integration_branch="main"))
        state = load_state(run_dir)
        assert state[RUN_KEY]["integration_branch"] == "driver/x", state
        assert state["t1"]["status"] == "pending", state
    print("ok: (p) run metadata survives init and reconcile without posing as a ticket")

    # (q) a landing records what it shares with another run, and lands anyway.
    with tf.TemporaryDirectory() as repo, tf.TemporaryDirectory() as run_dir, \
            tf.TemporaryDirectory() as wt_parent:
        _fixture_repo(repo)
        os.makedirs(os.path.join(run_dir, "handoffs"))
        open(_journal_path(run_dir), "a").close()
        for branch in ("driver/other", "driver/mine"):
            subprocess.run(["git", "-C", repo, "switch", "-q", "-c", branch, "main"], check=True)
            with open(os.path.join(repo, "shared.txt"), "w") as f:
                f.write(branch + "\n")
            subprocess.run(["git", "-C", repo, "add", "."], check=True)
            subprocess.run(["git", "-C", repo, "commit", "-q", "-m", f"touch shared on {branch}"],
                           check=True)
        # the other run is live only while it still has a worktree
        subprocess.run(["git", "-C", repo, "worktree", "add", "-q",
                        os.path.join(wt_parent, "other"), "driver/other"], check=True)
        subprocess.run(["git", "-C", repo, "switch", "-q", "-c", "ticket", "driver/mine"],
                       check=True)
        with open(os.path.join(repo, "shared.txt"), "a") as f:
            f.write("ticket\n")
        subprocess.run(["git", "-C", repo, "add", "."], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "ticket work"], check=True)
        subprocess.run(["git", "-C", repo, "switch", "-q", "driver/mine"], check=True)
        assert _land(repo, source="ticket", target="driver/mine", run_dir=run_dir) == LAND_OK
        phases = [json.loads(line) for line in open(_journal_path(run_dir))]
        overlaps = [e for e in phases if e.get("phase") == "overlap"]
        assert overlaps and "shared.txt" in overlaps[0]["paths"], phases
        assert overlaps[0]["other"] == "driver/other"
        # a run whose worktree is gone is history, not a contender
        subprocess.run(["git", "-C", repo, "worktree", "remove",
                        os.path.join(wt_parent, "other")], check=True)
        open(_journal_path(run_dir), "w").close()
        subprocess.run(["git", "-C", repo, "switch", "-q", "-c", "ticket2", "driver/mine"],
                       check=True)
        with open(os.path.join(repo, "shared.txt"), "a") as f:
            f.write("more\n")
        subprocess.run(["git", "-C", repo, "add", "."], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "more ticket work"], check=True)
        subprocess.run(["git", "-C", repo, "switch", "-q", "driver/mine"], check=True)
        assert _land(repo, source="ticket2", target="driver/mine", run_dir=run_dir) == LAND_OK
        again = [json.loads(line) for line in open(_journal_path(run_dir))]
        assert not [e for e in again if e.get("phase") == "overlap"], again
    print("ok: (q) an overlapping live run is recorded; a finished one is not")

    # (r) the target checked out in ANOTHER worktree: clean lands there, dirty stops.
    with tf.TemporaryDirectory() as repo, tf.TemporaryDirectory() as wt_parent:
        _fixture_repo(repo)
        other = os.path.join(wt_parent, "main-wt")
        subprocess.run(["git", "-C", repo, "switch", "-q", "-c", "side"], check=True)
        subprocess.run(["git", "-C", repo, "worktree", "add", "-q", other, "main"], check=True)
        before = _rev(repo, "main")
        # a dirty file the landing would overwrite: nothing lands, the file survives
        with open(os.path.join(other, "b.txt"), "w") as f:
            f.write("theirs\n")
        assert _land(repo, source="feature", target="main") == LAND_BLOCKED
        assert _rev(repo, "main") == before
        assert open(os.path.join(other, "b.txt")).read() == "theirs\n"
        # unrelated dirt only: the ref AND that worktree's files move together
        os.remove(os.path.join(other, "b.txt"))
        with open(os.path.join(other, "a.txt"), "a") as f:
            f.write("theirs\n")
        assert _land(repo, source="feature", target="main") == LAND_OK
        assert _rev(repo, "main") != before
        assert os.path.exists(os.path.join(other, "b.txt")), "the other worktree got the files"
        assert open(os.path.join(other, "a.txt")).read() == "base\ntheirs\n"
    print("ok: (r) the target's checkout fast-forwards in place; an overwrite stops it")

    # (i) the repo lock is a mutex: no two holders overlap.
    with tf.TemporaryDirectory() as repo:
        _fixture_repo(repo)
        trace = os.path.join(repo, "trace.log")
        here = os.path.abspath(__file__)
        body = (f"import time;f=open({trace!r},'a');f.write('in\\n');f.flush();"
                "time.sleep(0.05);f.write('out\\n');f.close()")
        procs = [subprocess.Popen([sys.executable, here, "with-lock", "barrier",
                                   "--repo", repo, "--wait", "30", "--",
                                   sys.executable, "-c", body],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                 for _ in range(20)]
        for proc in procs:
            assert proc.wait() == 0
        lines = [line.strip() for line in open(trace)]
        assert len(lines) == 40, len(lines)
        assert lines == ["in", "out"] * 20, "two processes were inside the lock at once"
    print("ok: (i) twenty contenders enter the repo lock strictly one at a time")

    # (j) a lock whose owner is alive is never reclaimed by age.
    with tf.TemporaryDirectory() as run_dir:
        lock_dir = _lock_dir(run_dir)
        os.mkdir(lock_dir)
        with open(os.path.join(lock_dir, "owner.json"), "w") as f:
            json.dump({"pid": os.getpid(), "pid_start": _pid_start(os.getpid()),
                       "started": time.time() - 86400}, f)
        assert cmd_lock(argparse.Namespace(run_dir=run_dir, stale_hours=6.0)) == 1
        # a dead owner IS reclaimed
        with open(os.path.join(lock_dir, "owner.json"), "w") as f:
            json.dump({"pid": 999999, "pid_start": "never", "started": time.time()}, f)
        assert cmd_lock(argparse.Namespace(run_dir=run_dir, stale_hours=6.0)) == 0
    print("ok: (j) a day-old lock with a live owner holds; a dead owner's lock is reclaimed")

    # (k) a readable but stale snapshot does not beat a newer journal entry.
    with tf.TemporaryDirectory() as run_dir:
        os.makedirs(os.path.join(run_dir, "handoffs"))
        open(_journal_path(run_dir), "a").close()
        atomic_write_json(_state_path(run_dir), {
            "t1": {"status": "in-progress", "commit": None, "reviewer": None,
                   "ts": time.time() - 10}})
        append_journal(run_dir, {"ticket_id": "t1", "status": "merged",
                                 "commit": "abc123", "reviewer": "codex"})
        state = load_state(run_dir)
        assert state["t1"]["status"] == "merged", state
        assert state["t1"]["reviewer"] == "codex"
    print("ok: (k) a newer journal entry wins over a readable, older snapshot")


def selftest():
    """assert-based self-check for the three scenarios called out in
    docs/driver-spec.md § Testing Decisions, seam 2. Run: python3 driver_state.py --selftest"""
    import tempfile as tf

    # (a) crash after journal-write but before state-file rename -> resume
    #     reconciles from the journal.
    with tf.TemporaryDirectory() as run_dir:
        os.makedirs(os.path.join(run_dir, "handoffs"))
        open(_journal_path(run_dir), "a").close()
        append_journal(run_dir, {"ticket_id": "t1", "status": "merged", "commit": "abc123"})
        # simulate the rename never happening: state.json still absent
        assert not os.path.exists(_state_path(run_dir))
        recovered = load_state(run_dir)
        assert recovered["t1"]["status"] == "merged"
        assert recovered["t1"]["commit"] == "abc123"
    print("ok: (a) journal replay recovers a torn/missing state.json")

    # (b) an in-progress ticket whose commit is NOT on the integration branch
    #     -> reconcile demotes it to pending, not trusted as done.
    with tf.TemporaryDirectory() as repo, tf.TemporaryDirectory() as run_dir:
        subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
        subprocess.run(["git", "-C", repo, "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", repo, "config", "user.name", "t"], check=True)
        open(os.path.join(repo, "f.txt"), "w").close()
        subprocess.run(["git", "-C", repo, "add", "."], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "init"], check=True)
        os.makedirs(os.path.join(run_dir, "handoffs"))
        atomic_write_json(_state_path(run_dir), {
            "t1": {"status": "in-progress", "commit": None, "reviewer": None, "ts": time.time()},
            "t2": {"status": "merged", "commit": "deadbeef" * 5, "reviewer": None, "ts": time.time()},
        })
        open(_journal_path(run_dir), "a").close()
        args = argparse.Namespace(run_dir=run_dir, repo=repo, integration_branch="main")
        cmd_reconcile(args)
        state = load_state(run_dir)
        assert state["t1"]["status"] == "pending", state
        assert state["t2"]["status"] == "pending", state
    print("ok: (b) unconfirmed in-progress/merged tickets demote to pending on reconcile")

    # (c) a second /driver invocation while the lock is held -> refuses to start.
    with tf.TemporaryDirectory() as run_dir:
        os.makedirs(run_dir, exist_ok=True)
        a1 = argparse.Namespace(run_dir=run_dir, stale_hours=6.0)
        rc1 = cmd_lock(a1)
        assert rc1 == 0
        a2 = argparse.Namespace(run_dir=run_dir, stale_hours=6.0)
        rc2 = cmd_lock(a2)
        assert rc2 == 1, "second lock attempt should be refused while first is held"
    print("ok: (c) concurrent /driver runs against the same run-dir are refused")

    # (d) the progress line paces the ETA on worked tickets only, never skipped ones.
    t0 = 1_000_000.0
    st = {RUN_KEY: {"ts": t0},
          "a": {"status": "merged"}, "b": {"status": "blocked"}, "c": {"status": "skipped"},
          "d": {"status": "in-progress"}, "e": {"status": "pending"}}
    line = progress_line(st, "x driver", now=t0 + 2 * 3600)
    assert "3/5 done (1 merged, 1 blocked, 1 skipped), 1 in progress" in line, line
    assert "Running 2h00m" in line and "(about 2h00m)" in line, line
    assert "after the first ticket" in progress_line({RUN_KEY: {"ts": t0}, "a": {"status": "pending"}}, "x", now=t0)
    with tf.TemporaryDirectory() as run_dir:
        ns = dict(run_dir=run_dir, label="x", owner=None, owner_only=False)
        assert cmd_progress(argparse.Namespace(**ns)) == 3
        assert cmd_lock(argparse.Namespace(run_dir=run_dir, stale_hours=6.0)) == 0
        assert cmd_progress(argparse.Namespace(**ns)) == 0
        assert cmd_progress(argparse.Namespace(**{**ns, "owner": _owner_pid() + 1})) == 3
    print("ok: (d) progress ETA ignores skipped tickets; no live lock stops the watcher")

    # (e) --owner-only prints the lock's acquisition token ('started'), not the pid — and a
    # resumed run's fresh acquisition never matches a stale watcher's captured token, even when
    # neither acquisition can identify a pid. (Before the fix, an unidentifiable pid round-tripped
    # as the sentinel 'none', which disabled the comparison and let a stale watcher keep sending
    # for whichever run held the lock.)
    with tf.TemporaryDirectory() as run_dir:
        os.makedirs(os.path.join(run_dir, ".lock"))
        owner_path = os.path.join(run_dir, ".lock", "owner.json")
        with open(owner_path, "w") as f:
            json.dump({"pid": None, "started": 111.0}, f)
        no_pid_ns = dict(run_dir=run_dir, label="x", owner=None, owner_only=True)
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_progress(argparse.Namespace(**no_pid_ns))
        assert rc == 0 and buf.getvalue().strip() == "111.0", buf.getvalue()
        stale_token = buf.getvalue().strip()
        # resume: a new acquisition overwrites owner.json with a fresh token, pid still None
        with open(owner_path, "w") as f:
            json.dump({"pid": None, "started": 222.0}, f)
        stale_ns = dict(run_dir=run_dir, label="x", owner=stale_token, owner_only=False)
        assert cmd_progress(argparse.Namespace(**stale_ns)) == 3, \
            "a stale watcher's captured token must not match the resumed acquisition"
        current_ns = dict(run_dir=run_dir, label="x", owner="222.0", owner_only=False)
        assert cmd_progress(argparse.Namespace(**current_ns)) == 0
    print("ok: (e) a resumed lock's fresh acquisition token never matches a stale watcher's "
          "captured token, even with an unidentifiable pid")

    # (f) atomic slot claim: of several contenders racing to claim the same hourly slot
    # directory, exactly one succeeds. This is the mkdir-wins primitive the progress-watch.sh
    # script (SKILL.md) relies on so several boundary-launched / resumed watcher chains waking
    # for the same slot produce exactly one send and one relaunch, not several.
    with tf.TemporaryDirectory() as run_dir:
        slots = os.path.join(run_dir, "progress-slots")
        os.makedirs(slots)
        slot_dir = os.path.join(slots, "12345")
        winners = 0
        for _ in range(5):
            try:
                os.mkdir(slot_dir)
                winners += 1
            except FileExistsError:
                pass
        assert winners == 1, f"exactly one contender should claim the slot, got {winners}"
    print("ok: (f) mkdir-based slot claim lets exactly one contender through per slot")

    selftest_land()
    print("ALL SELFTESTS PASSED")


def main():
    # argparse's REMAINDER swallows this command's OWN options, so split the
    # wrapped command off by hand at the first `--`.
    argv = sys.argv[1:]
    wrapped = []
    if argv[:1] == ["with-lock"] and "--" in argv:
        cut = argv.index("--")
        wrapped, argv = argv[cut + 1:], argv[:cut]
    parser = build_parser()
    args = parser.parse_args(argv)
    if wrapped:
        args.command = wrapped
    if args.selftest:
        selftest()
        return 0
    if not args.cmd:
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
