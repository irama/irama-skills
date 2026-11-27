#!/usr/bin/env python3
"""Resume rows: start a Claude thread in the worktree with the handoff's own next command. Spec: docs/specs/cleanup.md, section 6.

At most MAX_LAUNCH launches per run, one at a time. Anything else gets a done bubble with the same command:
rows past the cap, a worktree Orca cannot target, and a worktree whose Orca card was active in the last 24 hours
(never a second session beside a live card). The bubble is returned in the result; the thread posts it (never a subagent).
The `orca` call is injected as tools["orca_launch"](selector, prompt) -> (rc, text), so tests never start anything.
"""
import json
import os
import re

MAX_LAUNCH = 3
ACTIVE_HOURS = 24
VERB = re.compile(r"^[\s>*\-`]*(/[a-z][a-z0-9:_-]*)(?=[\s`]|$)([^`\n]*)", re.M)
FALLBACK_VERB = "/to-driver"  # the spec's example; used only when the handoff names no next command
ALLOWED_VERBS = ("/to-driver", "/driver")
OK_OUTCOMES = ("journaled", "handed-to-terminal")


def pick_handoff(row):
    """(path, candidates). A handoff inside the worktree wins (the newest of those). Otherwise one candidate is taken,
    and more than one is ambiguous: path is None and the caller asks the owner."""
    files = [p for p in row.get("handoffs") or [] if os.path.isfile(p)]
    root = os.path.realpath(row.get("path") or "") + os.sep
    inside = [p for p in files if os.path.realpath(p).startswith(root)]
    if inside:
        return max(inside, key=os.path.getmtime), files
    return (files[0] if len(files) == 1 else None), files


def handoff_command(path):
    """The handoff's own next command: its last slash-line, if that is /to-driver or /driver with a real target.
    Anything else (a /flush line, a missing file) gets the fallback verb with the handoff path."""
    fallback = f"{FALLBACK_VERB} {path}"
    try:
        with open(path, "rb") as fh:
            text = fh.read(64 * 1024).decode("utf-8", "ignore")
    except OSError:
        return fallback
    found = [(v, a.strip()) for v, a in VERB.findall(text)]
    if not found:
        return fallback
    verb, arg = found[-1]
    if verb not in ALLOWED_VERBS:
        return fallback
    if not arg:
        return f"{verb} {path}"
    if not os.path.isabs(arg):
        return fallback
    ok = os.path.isfile(arg) or (verb == "/driver" and os.path.isdir(arg) and f"{os.sep}.scratch{os.sep}driver-runs{os.sep}" in arg + os.sep)
    return f"{verb} {arg}" if ok else fallback


def selector(orca):
    """id:<repoId>::<path>, from the Orca row (its own id already has that shape). None when Orca cannot target it."""
    if not orca:
        return None
    i = orca.get("id") or ""
    if "::" in i:
        return "id:" + i
    return None


def active_recently(orca, now):
    la = (orca or {}).get("lastActivityAt")
    if not la:
        return False
    la = la / 1000 if la > 1e11 else la
    return now - la < ACTIVE_HOURS * 3600


def parse_receipt(text):
    """(ok, receipt dict) from `orca agent launch --json` output."""
    i = text.find("{")
    try:
        data = json.loads(text[i:]) if i >= 0 else {}
    except ValueError:
        return False, {}
    launch = (data.get("result") or {}).get("launch") or data.get("launch") or {}
    outcome = (launch.get("prompt") or {}).get("outcome")
    return bool(data.get("ok")) and outcome in OK_OUTCOMES, {
        "kind": (launch.get("outcome") or {}).get("kind"), "handle": (launch.get("outcome") or {}).get("handle"),
        "prompt": outcome, "operationId": launch.get("operationId") or data.get("operationId")}


def bubble(row, cmd, why):
    note = f"Resume {row['repo']}/{row['name']}: open a new thread in that worktree and paste. {why}"
    return {"note": note[:200], "copy": cmd[:4000]}


def resume(row, fresh, tools, now, launched):
    """One Resume row. `launched` = threads already started this run. Returns a result dict; "bubble" holds a done bubble to post."""
    path, files = pick_handoff(row)
    if not files:
        return {"status": "failed", "text": "Failed: the handoff file is gone, so nothing was started."}
    if not path:
        q = f"{row['repo']}/{row['name']}: {len(files)} handoffs mention this worktree and none is inside it. Which one should resume start from?"
        return {"status": "asked", "text": "Nothing started: more than one handoff matches. An Agent X ask went out.",
                "ask": {"question": q, "choices": [os.path.basename(p) for p in files]}}
    cmd = handoff_command(path)
    orca = (fresh or {}).get("orca")
    sel = selector(orca)
    why = None
    if not sel:
        why = "Orca cannot target this worktree."
    elif active_recently(orca, now):
        why = f"Its Orca card was active in the last {ACTIVE_HOURS} hours, so no second session started beside it."
    elif launched >= MAX_LAUNCH:
        why = f"This run already started {MAX_LAUNCH} threads, the most it starts."
    if why:
        return {"status": "bubble", "text": f"No thread started. {why} A done bubble with the command went to Agent X: {cmd}", "bubble": bubble(row, cmd, why)}
    rc, out = tools["orca_launch"](sel, cmd)
    ok, rec = parse_receipt(out)
    if rc != 0 or not ok:
        # The launch may have started a thread: no paste bubble (it could make a second one). The owner checks Orca.
        op = rec.get("operationId") or "unknown"
        return {"status": "launch uncertain", "receipt": rec,
                "text": (f"Launch uncertain: Orca did not confirm the prompt (operation {op}), so a thread may or may not have started. Check Orca for a new card in this worktree. "
                         f"It counts against the {MAX_LAUNCH}-thread cap. To try again, run apply with --only {row['key']} --retry-launch. Command: {cmd}")}
    return {"status": "launched", "text": f"Started a Claude thread in Orca ({rec['kind'] or 'agent'} {rec['handle'] or ''}, prompt {rec['prompt']}) with: {cmd}".replace("  ", " "),
            "receipt": rec}


def real_tools():
    import prune_auto as PA
    return {"orca_launch": lambda sel, prompt: PA.sh(["orca", "agent", "launch", "--agent", "claude", "--worktree", sel,
                                                       "--prompt", prompt, "--json"])}
