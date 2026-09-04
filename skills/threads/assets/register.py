#!/usr/bin/env python3
"""The cross-thread work register: who is doing what, and who has stopped.

Twenty agent sessions run at once and none of them can see the others. This is
the shared store they claim work in and sign off from, so two threads stop
offering — and doing — the same job.

    register.py claim <key> [--note ...]       take a work item
    register.py claim --verb push              same, keyed to this repo
    register.py sign-off <key> --status <s>    close it, with a status
    register.py list [--json]                  every live thread and what it holds
    register.py show <thread>                  one thread in detail
    register.py check <key>                    exit 1 if another live thread holds it
    register.py clear <thread>                 release its claims as incomplete
    register.py kill <thread> --yes            end its process (never automatic)
    register.py self                           this session's identity and claims
    register.py --selftest

One append-only file, one JSON object per line. Append-only because twenty
processes writing to one file need no locking if nobody rewrites a line, and
because the history is what shows two threads collided rather than only that
they did.

ponytail: a file and a linear scan, not a database. The register holds hundreds
of lines, not millions; if a scan ever gets slow, compact it, do not add a server.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

STATE = Path.home() / ".claude" / "state"
REGISTER = STATE / "work-register.jsonl"

# Work statuses. A thread writes one of these at sign-off.
#   held      -> nobody else may take it
#   takeable  -> another thread may pick it up
#   closed    -> finished with
OPEN = {"claimed", "in-progress"}                 # claimed, not yet signed off
HELD = {"blocked", "waiting-on-user"}             # signed off, still owned
TAKEABLE = {"incomplete", "abandoned"}
CLOSED = {"done", "handed-off"}
STATUSES = OPEN | HELD | TAKEABLE | CLOSED

# Thread statuses. Derived, never written by hand — a frozen thread cannot
# report that it has frozen.
IDLE_MINUTES = 15
STALE_MINUTES = 90


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def repo_of(cwd=None):
    """The repo name a key is scoped to, or the directory name outside a repo.

    From the *common* git dir, not the working tree, so every linked worktree of
    one repo answers with the same name. Worktrees are the normal way work is
    isolated here, and a key that changed per worktree would exempt exactly the
    threads most likely to collide."""
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=cwd,
                                capture_output=True, text=True, check=True).stdout.strip()
        if common:
            d = Path(cwd or Path.cwd()) / common if not Path(common).is_absolute() else Path(common)
            d = d.resolve()
            return (d.parent if d.name == ".git" else d).name
    except (subprocess.CalledProcessError, OSError):
        pass
    return Path(cwd or Path.cwd()).name


def claude_pid():
    """Walk up the process tree to the agent process this hook is running under.

    The hook's own pid is a shell that exits in a second, so it is useless as a
    liveness signal. The agent process above it is the thread."""
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


def alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def append(record):
    STATE.mkdir(parents=True, exist_ok=True)
    record.setdefault("ts", now())
    with open(REGISTER, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, separators=(",", ":")) + "\n")


def read():
    if not REGISTER.is_file():
        return []
    out = []
    for line in REGISTER.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue          # a torn line from a concurrent write; skip it
    return out


# ── the current picture ──────────────────────────────────────────────────────

def sessions(records):
    """session id -> its identity record, latest wins."""
    out = {}
    for r in records:
        if r.get("kind") == "session" and r.get("session"):
            out[r["session"]] = r
    return out


def claims(records):
    """key -> the last claim record for it. That record IS its current state."""
    out = {}
    for r in records:
        if r.get("kind") == "claim" and r.get("key"):
            out[r["key"]] = r
    return out


def quiet_minutes(sess):
    """How long since this thread last wrote anything, from its transcript."""
    path = sess.get("transcript")
    if not path:
        return None
    try:
        return (time.time() - os.path.getmtime(path)) / 60
    except OSError:
        return None


def thread_status(sess, held_count):
    """live / idle / stalled / dead — the second axis, and the derived one."""
    if not alive(sess.get("pid")):
        return "dead"
    quiet = quiet_minutes(sess)
    if quiet is None or quiet < IDLE_MINUTES:
        return "live"
    if quiet < STALE_MINUTES:
        return "idle"
    return "stalled" if held_count else "idle"


def picture():
    """Everything the commands below need, computed once.

    Releasing a dead thread's claims happens here, at read time, rather than on
    a timer. A timer is a thing that can be off; a read is what always happens."""
    records = read()
    sess = sessions(records)
    open_claims = {k: c for k, c in claims(records).items()
                   if c.get("state") in OPEN | HELD}

    by_thread = {}
    for key, c in open_claims.items():
        by_thread.setdefault(c.get("session"), []).append(c)

    status = {}
    for sid, s in sess.items():
        status[sid] = thread_status(s, len(by_thread.get(sid, [])))

    # A dead thread's claims are released. A stalled one's are not: it is still
    # running and may come back, so it is reported and you decide.
    freed = []
    for sid, st in status.items():
        if st != "dead":
            continue
        for c in by_thread.get(sid, []):
            append({"kind": "claim", "session": sid, "thread": c.get("thread"),
                    "repo": c.get("repo"), "key": c["key"], "state": "incomplete",
                    "note": "auto-released: the thread that held this is gone"})
            freed.append(c["key"])
    if freed:
        return picture()          # re-read once, with the releases applied
    return sess, status, open_claims, by_thread


# ── identity ─────────────────────────────────────────────────────────────────

def register_session(session_id, thread_name, transcript, cwd):
    append({"kind": "session", "session": session_id, "thread": thread_name,
            "pid": claude_pid(), "cwd": str(cwd), "transcript": str(transcript or "")})


def this_session():
    """The session id of the thread running this command.

    A hook is handed it; a command run from a thread is not, so it comes from
    the environment the hook wrote, and falls back to the newest session that
    matches this working directory."""
    sid = os.environ.get("CLAUDE_SESSION_ID")
    if sid:
        return sid
    sess, _, _, _ = picture()
    here = str(Path.cwd())
    best = None
    for s in sess.values():
        if s.get("cwd") == here and alive(s.get("pid")):
            if best is None or s["ts"] > best["ts"]:
                best = s
    return best["session"] if best else None


def resolve(sess, name):
    """A thread by name, by short ref, or by session id."""
    for s in sess.values():
        if name in (s.get("thread"), s.get("session")) or \
           (s.get("session") or "").startswith(name):
            return s
    return None


# ── commands ─────────────────────────────────────────────────────────────────

def cmd_claim(key, note):
    sess, status, open_claims, _ = picture()
    sid = this_session()
    if not sid:
        # No identity means no process to watch, so this claim could never
        # auto-release when the thread ends -- it would hold the key forever.
        # No claim is strictly better than an unreleasable one.
        print("not claiming: this thread is not registered, so the claim could "
              "never be released. The SessionStart hook did not run — start a "
              "fresh session, or see skills/threads/SKILL.md.")
        return 0
    holder = open_claims.get(key)
    if holder and holder.get("session") != sid and status.get(holder.get("session")) != "dead":
        print(f"HELD by {holder.get('thread')} since {holder['ts']} "
              f"({holder.get('state')}): {holder.get('note') or 'no note'}")
        return 1
    me = sess.get(sid, {})
    append({"kind": "claim", "session": sid, "thread": me.get("thread"),
            "repo": repo_of(), "key": key, "state": "in-progress", "note": note})
    print(f"claimed {key}")
    return 0


def cmd_signoff(key, status_name, note):
    if status_name not in STATUSES - OPEN:
        print(f"status must be one of: {' '.join(sorted(STATUSES - OPEN))}")
        return 2
    sess, _, open_claims, _ = picture()
    sid = this_session()
    c = open_claims.get(key)
    if not c:
        print(f"no open claim on {key}")
        return 1
    append({"kind": "claim", "session": sid, "thread": sess.get(sid, {}).get("thread"),
            "repo": c.get("repo"), "key": key, "state": status_name, "note": note})
    print(f"{key}: {status_name}")
    return 0


def cmd_check(key):
    """Exit 1 if a live thread that is not this one holds this key."""
    _, status, open_claims, _ = picture()
    sid = this_session()
    c = open_claims.get(key)
    if not c or c.get("session") == sid:
        return 0
    if status.get(c.get("session")) == "dead":
        return 0
    print(f"{key} is held by {c.get('thread')} ({c.get('state')}, "
          f"thread is {status.get(c.get('session'))}) since {c['ts']}")
    return 1


def cmd_list(as_json):
    sess, status, open_claims, by_thread = picture()
    live = {sid: s for sid, s in sess.items() if status.get(sid) != "dead"}
    if as_json:
        print(json.dumps({"threads": [
            {"thread": s.get("thread"), "session": sid, "status": status[sid],
             "cwd": s.get("cwd"),
             "quiet_minutes": round(quiet_minutes(s) or 0),
             "claims": [{"key": c["key"], "state": c["state"], "note": c.get("note")}
                        for c in by_thread.get(sid, [])]}
            for sid, s in live.items()]}, indent=1))
        return 0
    if not live:
        print("no threads registered")
        return 0
    for sid, s in sorted(live.items(), key=lambda kv: status[kv[1]["session"]]):
        q = quiet_minutes(s)
        print(f"{status[sid]:8} {s.get('thread','?'):28} "
              f"quiet {round(q) if q is not None else '?':>4}m  {Path(s.get('cwd','')).name}")
        for c in by_thread.get(sid, []):
            print(f"         └ {c['state']:16} {c['key']}"
                  + (f"  — {c['note']}" if c.get("note") else ""))
    stalled = [s.get("thread") for sid, s in live.items() if status[sid] == "stalled"]
    if stalled:
        print(f"\nstalled, still holding work: {', '.join(stalled)}")
        print("clear one with:  register.py clear <thread>")
    return 0


def cmd_show(name):
    sess, status, _, by_thread = picture()
    s = resolve(sess, name)
    if not s:
        print(f"no thread matching {name!r}")
        return 1
    sid = s["session"]
    print(f"{s.get('thread')}  [{sid[:6]}]  {status[sid]}")
    print(f"  started   {s['ts']}")
    print(f"  directory {s.get('cwd')}")
    print(f"  pid       {s.get('pid')} ({'alive' if alive(s.get('pid')) else 'gone'})")
    q = quiet_minutes(s)
    print(f"  quiet     {round(q) if q is not None else '?'} minutes")
    for c in by_thread.get(sid, []):
        print(f"  holds     {c['state']:16} {c['key']}"
              + (f"  — {c['note']}" if c.get("note") else ""))
    return 0


def cmd_clear(name):
    """Release a thread's claims. Deliberately does not touch its process."""
    sess, status, _, by_thread = picture()
    s = resolve(sess, name)
    if not s:
        print(f"no thread matching {name!r}")
        return 1
    held = by_thread.get(s["session"], [])
    if not held:
        print(f"{s.get('thread')} holds nothing")
        return 0
    for c in held:
        append({"kind": "claim", "session": s["session"], "thread": s.get("thread"),
                "repo": c.get("repo"), "key": c["key"], "state": "incomplete",
                "note": f"released by hand from a {status[s['session']]} thread"})
        print(f"released {c['key']}")
    print(f"\n{s.get('thread')} is still running. Its window is untouched.")
    return 0


def cmd_kill(name, yes):
    """End a thread's process. Never runs without --yes, ever."""
    sess, status, _, by_thread = picture()
    s = resolve(sess, name)
    if not s:
        print(f"no thread matching {name!r}")
        return 1
    pid = s.get("pid")
    if not alive(pid):
        print(f"{s.get('thread')} is already gone")
        return 0
    if not yes:
        print(f"Would end {s.get('thread')} (pid {pid}, {status[s['session']]}, "
              f"{Path(s.get('cwd','')).name}), holding {len(by_thread.get(s['session'], []))} item(s).")
        print("An interactive session may hold uncommitted work, and this cannot be undone.")
        print("Release the work instead:  register.py clear " + name)
        print("Really end it:             register.py kill " + name + " --yes")
        return 2
    cmd_clear(name)
    os.kill(int(pid), 15)
    print(f"ended {s.get('thread')} (pid {pid})")
    return 0


def cmd_self():
    sess, status, _, by_thread = picture()
    sid = this_session()
    if not sid or sid not in sess:
        print("this thread is not registered — the SessionStart hook did not run")
        return 1
    return cmd_show(sid)


def selftest():
    """Six known answers over a register in a temporary home."""
    import tempfile
    global STATE, REGISTER
    ok = True
    with tempfile.TemporaryDirectory() as d:
        STATE = Path(d)
        REGISTER = STATE / "work-register.jsonl"
        transcript = STATE / "t.jsonl"
        transcript.write_text("{}\n")

        append({"kind": "session", "session": "aaa", "thread": "one",
                "pid": os.getpid(), "cwd": "/tmp", "transcript": str(transcript)})
        append({"kind": "session", "session": "bbb", "thread": "two",
                "pid": 999999, "cwd": "/tmp", "transcript": str(transcript)})
        append({"kind": "claim", "session": "aaa", "thread": "one",
                "repo": "r", "key": "r:push", "state": "in-progress"})
        append({"kind": "claim", "session": "bbb", "thread": "two",
                "repo": "r", "key": "r:merge", "state": "in-progress"})

        sess, status, open_claims, by_thread = picture()

        def check(label, got, want):
            nonlocal ok
            if got != want:
                print(f"selftest FAIL: {label} — got {got!r}, want {want!r}")
                ok = False

        # 1. a running process with a fresh transcript is live
        check("live thread", status["aaa"], "live")
        # 2. a process that does not exist is dead
        check("dead thread", status["bbb"], "dead")
        # 3. a dead thread's claim is released, not left holding
        check("dead claim released", "r:merge" in open_claims, False)
        # 4. a live thread's claim survives
        check("live claim held", open_claims["r:push"]["state"], "in-progress")
        # 5. the released claim is takeable, and says why
        released = claims(read())["r:merge"]
        check("released state", released["state"], "incomplete")
        check("released is takeable", released["state"] in TAKEABLE, True)
        # 6. releasing twice does not append twice — the claim is no longer open
        before = len(read())
        picture()
        check("no double release", len(read()), before)

    print("selftest passed" if ok else "selftest FAILED")
    return 0 if ok else 1


def main():
    argv = sys.argv[1:]
    if not argv or "--selftest" in argv:
        return selftest() if argv else (print(__doc__.strip().split("\n\n")[1]) or 2)

    cmd, rest = argv[0], argv[1:]

    def opt(name, default=None):
        return rest[rest.index(name) + 1] if name in rest and len(rest) > rest.index(name) + 1 else default

    positional = [a for a in rest if not a.startswith("--")
                  and (not rest or rest[rest.index(a) - 1] not in ("--note", "--status", "--verb"))]

    def key():
        """`--verb push` is `<this repo>:push`. A skill must never build that
        key by hand: the repo name comes from the common git dir, so a hand-built
        one is wrong in every worktree."""
        verb = opt("--verb")
        return f"{repo_of()}:{verb}" if verb else positional[0]

    if cmd == "claim":
        return cmd_claim(key(), opt("--note"))
    if cmd == "sign-off":
        return cmd_signoff(key(), opt("--status", ""), opt("--note"))
    if cmd == "check":
        return cmd_check(key())
    if cmd == "list":
        return cmd_list("--json" in rest)
    if cmd == "show":
        return cmd_show(positional[0])
    if cmd == "clear":
        return cmd_clear(positional[0])
    if cmd == "kill":
        return cmd_kill(positional[0], "--yes" in rest)
    if cmd == "self":
        return cmd_self()
    if cmd == "register-session":
        register_session(opt("--session"), opt("--thread"), opt("--transcript"), opt("--cwd", Path.cwd()))
        return 0
    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
