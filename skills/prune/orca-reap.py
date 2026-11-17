#!/usr/bin/env python3
"""Stop idle Orca chat sessions whose git worktree no longer exists.

A thread that prunes its own worktree leaves its Orca chat process alive and
idle. If Orca still counts a background task for it, the sidebar card stays
under "Monitoring background tasks" with no close button. Stopping the
session's Orca supervisor with SIGTERM makes Orca record the exit, and the
card moves to DONE. The transcript stays on disk.

Usage: orca-reap.py [--dry-run]    (orca-reap.py --self-test runs the checks)
"""
import json
import os
import sqlite3
import subprocess
import sys

DB = os.path.expanduser("~/Library/Application Support/orca/agent-session-domain.db")


def orphan_pid(rec, path_exists, pid_alive):
    """Return the supervisor pid to stop, or None. Pure, so --self-test can run it."""
    loc = rec.get("location", {})
    lease = rec.get("lease") or {}
    owner = lease.get("ownerProcess") or {}
    if loc.get("workspaceKind") != "git-worktree" or loc.get("executionHostId") != "local":
        return None
    if lease.get("claimStatus") != "live" or (rec.get("lastTurn") or {}).get("state") != "settled":
        return None
    path = loc.get("workspaceId", "").rsplit("::", 1)[-1]
    pid = owner.get("pid")
    if not path or path_exists(path) or not isinstance(pid, int) or not pid_alive(pid):
        return None
    return pid


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def ancestors():
    pids, pid = set(), os.getpid()
    while pid > 1:
        pids.add(pid)
        out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        pid = int(out) if out.isdigit() else 1
    return pids


def main(dry_run):
    if not os.path.exists(DB):
        return  # Orca is not installed on this machine.
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute("select session_id, adopted_native_id, record_json from agent_session_records").fetchall()
    mine = ancestors()
    for sid, native, raw in rows:
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        pid = orphan_pid(rec, os.path.exists, alive)
        if pid is None:
            continue
        name = rec.get("conversationName") or sid
        cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
        # A recycled pid would not carry this session's id on its command line.
        if not native or f"--session-id={native}" not in cmd:
            print(f"skipped (pid {pid} is not this session's supervisor): {name}")
        elif pid in mine:
            print(f"skipped (this thread; the next /prune stops it): {name}")
        elif dry_run:
            print(f"would stop pid {pid}: {name}")
        else:
            os.kill(pid, 15)
            print(f"stopped pid {pid}: {name}")


def self_test():
    rec = {
        "location": {"workspaceKind": "git-worktree", "executionHostId": "local", "workspaceId": "r::/gone/wt"},
        "lease": {"claimStatus": "live", "ownerProcess": {"pid": 42}},
        "lastTurn": {"state": "settled"},
    }
    yes, no = (lambda _: True), (lambda _: False)
    assert orphan_pid(rec, no, yes) == 42
    assert orphan_pid(rec, yes, yes) is None  # worktree still exists
    assert orphan_pid(rec, no, no) is None  # process already gone
    assert orphan_pid({**rec, "lastTurn": {"state": "running"}}, no, yes) is None  # mid-turn
    assert orphan_pid({**rec, "lease": {"claimStatus": "released"}}, no, yes) is None
    print("self-test ok")


if __name__ == "__main__":
    self_test() if "--self-test" in sys.argv else main("--dry-run" in sys.argv)
