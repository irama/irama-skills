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
import json
import os
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


def append_journal(run_dir, entry):
    entry = dict(entry)
    entry["ts"] = time.time()
    with open(_journal_path(run_dir), "a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def load_state(run_dir):
    path = _state_path(run_dir)
    if not os.path.exists(path):
        # never written (or the rename never happened) -- the journal is the
        # only source of truth left.
        return replay_journal(run_dir)
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # state.json is torn/missing — replay the journal, which is append-only
        # and can't be torn the same way (each line is written+flushed whole).
        return replay_journal(run_dir)


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
            if not tid:
                continue
            state[tid] = {
                "status": e.get("status"),
                "commit": e.get("commit"),
                "reviewer": e.get("reviewer"),
                "ts": e.get("ts"),
            }
    return state


def cmd_init(args):
    os.makedirs(args.run_dir, exist_ok=True)
    os.makedirs(os.path.join(args.run_dir, "handoffs"), exist_ok=True)
    if os.path.exists(_state_path(args.run_dir)):
        print(f"run-dir already initialised: {args.run_dir}", file=sys.stderr)
        return 0
    state = {tid: {"status": "pending", "commit": None, "reviewer": None, "ts": time.time()}
             for tid in args.ticket_ids}
    atomic_write_json(_state_path(args.run_dir), state)
    open(_journal_path(args.run_dir), "a").close()
    print(f"initialised {len(args.ticket_ids)} ticket(s) in {args.run_dir}")
    return 0


def cmd_lock(args):
    lock_dir = _lock_dir(args.run_dir)
    owner_path = os.path.join(lock_dir, "owner.json")
    try:
        os.mkdir(lock_dir)
    except FileExistsError:
        # held — check staleness before refusing
        stale = False
        if os.path.exists(owner_path):
            try:
                with open(owner_path) as f:
                    owner = json.load(f)
                age_hours = (time.time() - owner.get("started", 0)) / 3600
                stale = age_hours > args.stale_hours
            except (json.JSONDecodeError, OSError):
                stale = True  # unreadable owner file — treat as stale, don't wedge forever
        else:
            stale = True
        if not stale:
            print(f"lock held: {owner_path} — another /driver run is active", file=sys.stderr)
            return 1
        # reclaim a stale lock
        shutil.rmtree(lock_dir, ignore_errors=True)
        os.mkdir(lock_dir)
    with open(owner_path, "w") as f:
        json.dump({"pid": os.getpid(), "started": time.time()}, f)
    print(f"lock acquired: {lock_dir}")
    return 0


def cmd_unlock(args):
    shutil.rmtree(_lock_dir(args.run_dir), ignore_errors=True)
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
                              "reviewer": args.reviewer, "ts": time.time()}
    atomic_write_json(_state_path(args.run_dir), state)
    print(f"{args.ticket_id}: {args.status}")
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
        print(f"{tid}\t{entry.get('status')}\t{entry.get('commit') or '-'}\t{entry.get('reviewer') or '-'}")
    return 0


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)


def cmd_reconcile(args):
    """A ticket marked in-progress/merged with a commit that isn't actually an
    ancestor of the integration branch tip did NOT really land — a crash could
    have died between 'merge succeeded' and 'state says done'. Re-derive truth
    from git, don't trust the state file blindly."""
    state = load_state(args.run_dir)
    changed = False
    for tid, entry in state.items():
        status, commit = entry.get("status"), entry.get("commit")
        if status not in ("in-progress", "merged"):
            continue
        if status == "in-progress":
            # never actually confirmed merged — always demote back to pending
            entry["status"] = "pending"
            changed = True
            print(f"{tid}: in-progress with no confirmed merge -> pending (re-run)")
            continue
        if not commit:
            entry["status"] = "pending"
            changed = True
            print(f"{tid}: merged but no recorded commit -> pending (re-run)")
            continue
        res = _git(args.repo, "merge-base", "--is-ancestor", commit, args.integration_branch)
        if res.returncode != 0:
            entry["status"] = "pending"
            changed = True
            print(f"{tid}: commit {commit[:8]} not on {args.integration_branch} -> pending (re-run)")
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

    s = sub.add_parser("get-status")
    s.add_argument("run_dir")
    s.add_argument("ticket_id")
    s.set_defaults(func=cmd_get_status)

    s = sub.add_parser("summary")
    s.add_argument("run_dir")
    s.set_defaults(func=cmd_summary)

    s = sub.add_parser("reconcile")
    s.add_argument("run_dir")
    s.add_argument("--repo", required=True)
    s.add_argument("--integration-branch", required=True)
    s.set_defaults(func=cmd_reconcile)

    return p


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

    print("ALL SELFTESTS PASSED")


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    if not args.cmd:
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
