#!/usr/bin/env python3
"""/cleanup schedule | unschedule | gate. Weekly Orca automation for /cleanup --scheduled.

  schedule.py schedule      create the automation (idempotent) and print its id
  schedule.py unschedule    remove it
  schedule.py gate          for a scheduled run: exit 0 only if cleanup:run was claimed

Never --repo (it makes a fresh worktree per run, which cleanup would then classify): the run
goes in one permanent folder workspace, which classification skips (discover.schedule_dir).
"""
import calendar
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import discover as D  # noqa: E402

NAME = "Weekly cleanup"
PROMPT = "/cleanup --scheduled"
TZ = "Australia/Brisbane"
STALE_DAYS = 7


def sh(argv):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def orca_json(run, *args):
    rc, out = run(["orca", *args, "--json"])
    try:
        return rc, json.loads(out)
    except ValueError:
        return rc or 1, {"raw": out}


def find_id(o):
    """The id in a create reply: result.automation.id, else result.id."""
    r = o.get("result") or {}
    a = r.get("automation") if isinstance(r.get("automation"), dict) else r
    return a.get("id")


def state_file():
    return Path.home() / ".claude" / "cleanup" / "schedule.json"


def saved_id():
    try:
        return json.loads(state_file().read_text()).get("id")
    except (OSError, ValueError, AttributeError):
        return None


def owned(a):
    """Ours only if its id was saved on create, or its prompt and workspace are the scheduled ones."""
    if saved_id() and a.get("id") == saved_id():
        return True
    return a.get("prompt") == PROMPT and str(D.schedule_dir()) in json.dumps(a)


def existing(run):
    """(id, err). A same-named automation that is not ours is an error: never reused, never removed."""
    rc, o = orca_json(run, "automations", "list")
    res = o.get("result")
    if rc or not isinstance(res, dict):
        return None, f"automations list failed: {o}"
    for a in (res.get("automations") or []) + (res.get("items") or []):
        if isinstance(a, dict) and a.get("name") == NAME:
            if owned(a):
                return a.get("id"), None
            return None, f"refusing: an automation named {NAME!r} exists that /cleanup did not create; rename or remove it yourself"
    return None, None


def ensure_folder(run, folder):
    """Make the folder and register it with Orca as a folder project when it is not yet."""
    folder.mkdir(parents=True, exist_ok=True)
    rc, o = orca_json(run, "repo", "list")
    if rc:
        return f"repo list failed: {o}"
    if any(r.get("path") == str(folder) for r in (o.get("result") or {}).get("repos") or []):
        return None
    rc, o = orca_json(run, "repo", "add", "--path", str(folder), "--kind", "folder")
    return None if not rc and o.get("ok") else f"repo add failed: {o}"


def schedule(run=sh):
    aid, err = existing(run)
    if err:
        return 1, err
    if aid:
        return 0, f"already scheduled: {aid}"
    folder = D.schedule_dir()
    err = ensure_folder(run, folder)
    if err:
        return 1, err
    rc, o = orca_json(run, "automations", "create", "--name", NAME, "--trigger", "weekly", "--day", "1",
                      "--time", "08:00", "--timezone", TZ, "--prompt", PROMPT, "--provider", "claude",
                      "--workspace", f"path:{folder}", "--fresh-session")
    aid = find_id(o)
    if rc or not o.get("ok") or not aid:
        return 1, f"create failed: {o}"
    state_file().parent.mkdir(parents=True, exist_ok=True)
    state_file().write_text(json.dumps({"id": aid}))
    return 0, f"scheduled: {aid} (Mondays 08:00 {TZ})"


def unschedule(run=sh):
    aid, err = existing(run)
    if err:
        return 1, err
    if not aid:
        return 0, "not scheduled"
    rc, o = orca_json(run, "automations", "remove", aid)
    return (0, f"unscheduled: {aid}") if not rc and o.get("ok") else (1, f"remove failed: {o}")


def notify(text):
    """Post an Agent X bubble without waiting for an answer."""
    try:
        subprocess.Popen([str(Path.home() / ".claude" / "bin" / "xagent-ask"), "--question", text,
                          "--choice", "Noted"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def held_days(line, now=None):
    """Days since the 'since <ISO ts>' in a HELD line, or None."""
    m = re.search(r"since (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)", line)
    if not m:
        return None
    t = calendar.timegm(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ"))
    return ((now if now is not None else time.time()) - t) / 86400


def gate(run=sh, reg=None, notify=notify, now=None):
    """A scheduled run goes on only if it takes cleanup:run; otherwise one line and exit 3.

    register.py has no takeover of a live holder (`clear` releases a whole thread by hand), so a
    claim held over STALE_DAYS is reported with its age and posted to Agent X, never taken."""
    reg = reg or HERE.parent / "threads" / "assets" / "register.py"
    rc, out = run([sys.executable, str(reg), "claim", "cleanup:run", "--note", "scheduled cleanup run"])
    if out.startswith("claimed"):
        return 0, out.splitlines()[0]
    first = out.splitlines()[0] if out else "no claim"
    line = f"cleanup: not running ({first})"
    days = held_days(first, now) if first.startswith("HELD") else None
    if days is not None and days > STALE_DAYS:
        line += f" [held {int(days)} days, likely stalled: release it with register.py clear <thread>]"
        notify(line)
    return 3, line


def main(argv=None):
    cmd = (argv or sys.argv[1:] or [""])[0]
    fn = {"schedule": schedule, "unschedule": unschedule, "gate": gate}.get(cmd)
    if not fn:
        print("usage: schedule.py schedule|unschedule|gate")
        return 2
    rc, line = fn()
    print(line)
    return rc


if __name__ == "__main__":
    sys.exit(main())
