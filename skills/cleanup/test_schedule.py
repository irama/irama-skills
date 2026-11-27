#!/usr/bin/env python3
"""Hermetic self-check for schedule.py. Run: python3 skills/cleanup/test_schedule.py

orca and the register are stubs: nothing real is created, run or removed.
"""
import calendar
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import discover as D  # noqa: E402
import schedule as S  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{detail}]"))
    if not cond:
        FAILS.append(name)


class Orca:
    def __init__(self, automations=(), repos=()):
        self.calls, self.automations, self.repos = [], list(automations), list(repos)

    def __call__(self, argv):
        self.calls.append(argv)
        k = tuple(argv[1:3])
        if k == ("automations", "list"):
            r = {"automations": self.automations}
        elif k == ("repo", "list"):
            r = {"repos": self.repos}
        elif k == ("automations", "create"):
            r = {"automation": {"id": "auto-1"}}
        else:
            r = {}
        return 0, json.dumps({"ok": True, "result": r})

    def verbs(self):
        return [tuple(c[1:3]) for c in self.calls]


def main():
    home = os.path.realpath(tempfile.mkdtemp())
    os.environ["HOME"] = home
    folder = str(D.schedule_dir())
    check("folder under home, not hard-coded", folder.startswith(home))

    o = Orca()
    rc, msg = S.schedule(o)
    create = [c for c in o.calls if c[1:3] == ["automations", "create"]][0]
    check("schedule ok and reports id", rc == 0 and "auto-1" in msg, msg)
    check("create saves the id", json.loads((Path(home) / ".claude" / "cleanup" / "schedule.json").read_text()) == {"id": "auto-1"})
    check("folder made and added as kind folder",
          Path(folder).is_dir() and ["orca", "repo", "add", "--path", folder, "--kind", "folder", "--json"] in o.calls)
    check("exact create argv", create == ["orca", "automations", "create", "--name", S.NAME, "--trigger", "weekly",
          "--day", "1", "--time", "08:00", "--timezone", "Australia/Brisbane", "--prompt", "/cleanup --scheduled",
          "--provider", "claude", "--workspace", f"path:{folder}", "--fresh-session", "--json"], create)
    check("never --repo", "--repo" not in create)

    o = Orca(repos=[{"path": folder, "kind": "folder"}])
    S.schedule(o)
    check("registered folder is not added again", ("repo", "add") not in o.verbs())

    o = Orca(automations=[{"id": "x9", "name": S.NAME, "prompt": S.PROMPT, "workspace": f"path:{folder}"}])
    rc, msg = S.schedule(o)
    check("already scheduled creates nothing", rc == 0 and "x9" in msg and ("automations", "create") not in o.verbs())

    o = Orca(automations=[{"id": "x9", "name": S.NAME, "prompt": S.PROMPT, "workspace": f"path:{folder}"}])
    rc, msg = S.unschedule(o)
    check("unschedule removes by id", rc == 0 and ["orca", "automations", "remove", "x9", "--json"] in o.calls, o.calls)
    o = Orca()
    rc, msg = S.unschedule(o)
    check("unschedule with nothing scheduled removes nothing", rc == 0 and ("automations", "remove") not in o.verbs())

    rc, line = S.gate(lambda a: (0, "claimed cleanup:run"), reg="r.py")
    check("gate goes on when claimed", rc == 0)
    rc, line = S.gate(lambda a: (0, "HELD by thread abc (pid 1)\nmore"), reg="r.py")
    check("gate exits with one line when held", rc == 3 and "\n" not in line and "HELD" in line, line)
    rc, line = S.gate(lambda a: (0, "not claiming: no identity"), reg="r.py")
    check("gate exits when no identity", rc == 3 and "\n" not in line)

    w = {"path": folder + "/sub", "locked": False, "lock_reason": None, "exists": True, "detached": False, "is_main": False}
    ctx = {"self_cwd": "/nonexistent", "now": 0}
    g = D.classify_one({}, w, ctx, {}, {})
    check("scheduled folder is Skipped, never pruned", g[0] == "Skipped" and "never pruned" in g[1], g)

    # i) ownership: a same-named foreign automation is never reused or removed
    foreign = {"id": "mine", "name": S.NAME, "prompt": "/my own thing", "workspace": "path:/elsewhere"}
    for fn, verb in ((S.schedule, ("automations", "create")), (S.unschedule, ("automations", "remove"))):
        o = Orca(automations=[foreign])
        rc, msg = fn(o)
        check(f"{fn.__name__}: foreign same-name refused, nothing changed", rc == 1 and "refusing" in msg
              and "\n" not in msg and verb not in o.verbs(), (rc, msg))
    ours = {"id": "x9", "name": S.NAME, "prompt": S.PROMPT, "workspace": f"path:{folder}"}
    o = Orca(automations=[ours])
    rc, msg = S.unschedule(o)
    check("prompt+workspace match is removed", rc == 0 and ("automations", "remove") in o.verbs(), msg)
    sf = Path(home) / ".claude" / "cleanup" / "schedule.json"
    sf.write_text(json.dumps({"id": "mine"}))
    o = Orca(automations=[foreign])
    rc, msg = S.unschedule(o)
    check("saved id match is removed", rc == 0 and ["orca", "automations", "remove", "mine", "--json"] in o.calls, msg)
    sf.unlink()

    # iii) list shapes
    o = Orca()
    o.automations = []
    run = lambda argv: (0, json.dumps({"ok": True, "result": {"items": [ours]}})) if argv[1:3] == ["automations", "list"] else o(argv)
    rc, msg = S.unschedule(run)
    check("entries under result.items are seen", rc == 0 and "x9" in msg, msg)
    rc, msg = S.schedule(lambda argv: (0, json.dumps({"ok": True, "result": []})))
    check("non-dict result is a clean error line", rc == 1 and "failed" in msg and "\n" not in msg, msg)

    # ii) stale holder
    posted = []
    old = "HELD by t1 since 2026-01-01T00:00:00Z (in-progress): x"
    fresh = "HELD by t1 since 2026-01-01T00:00:00Z (in-progress): x"
    rc, line = S.gate(lambda a: (1, old), reg="r.py", notify=posted.append, now=calendar.timegm((2026, 1, 9, 0, 0, 0)))
    check("claim older than 7 days: age, release hint, one bubble", rc == 3 and "8 days" in line and "clear" in line
          and "\n" not in line and len(posted) == 1, (line, posted))
    posted.clear()
    rc, line = S.gate(lambda a: (1, fresh), reg="r.py", notify=posted.append, now=calendar.timegm((2026, 1, 3, 0, 0, 0)))
    check("young claim: plain HELD line, no bubble", rc == 3 and "days" not in line and not posted, line)

    print("FAILED: " + ", ".join(FAILS) if FAILS else "all pass")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
