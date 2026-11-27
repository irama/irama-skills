#!/usr/bin/env python3
"""Rows and brief for /cleanup (spec sections 4 and 5).

  make_brief.py rows  <discover.json> --run-dir DIR   discover JSON -> DIR/rows.json, plus one
                                                      DIR/abandoned/<key>.prompt.md per Abandoned row
  make_brief.py brief <DIR/rows.json> [--read-only] [--render]
                                                      rows (+ any <key>.answer.md a subagent wrote)
                                                      -> DIR/cleanup.md (and .html with --render)

Read-only: git reads, register reads, transcript streaming. Nothing on disk changes outside DIR.
"""
import argparse
import html
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resume as RS  # noqa: E402

DIFF_CAP = 400
EXCERPT_CAP = 2000
MAX_TRANSCRIPTS = 15  # ponytail: newest 15 candidate transcripts per row; widen if a session is missed
MAX_HANDOFF_BYTES = 64 * 1024
ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")

PUSH_NOW, PUSH_LATER, HOLD = "Push now", "Push when the running work lands", "Hold, ask me again next cleanup"
RESUME, MERGE, PARK, DELETE = "Resume from its handoff", "Merge and push", "Park for 30 days", "Delete"
HELD_STATES = {"waiting-on-user", "blocked"}
LABELS = ["For you", "What the change does", "How far it got", "Why it stopped", "Recommended"]


def git(cwd, *args):
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, env=ENV, timeout=30)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def under(p, root):
    p, root = os.path.realpath(p), os.path.realpath(root)
    return p == root or p.startswith(root + os.sep)


def home_rel(p):
    h = str(Path.home())
    return "~" + p[len(h):] if p.startswith(h + os.sep) else p


def sha7(s):
    return (s or "0000000")[:7]


def slug(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")


# ── push rows ────────────────────────────────────────────────────────────────

def push_recommendation(held, running):
    """Spec section 5 table: Hold beats everything, then running work defers, else push now."""
    if held:
        return HOLD
    return PUSH_LATER if running else PUSH_NOW


MERGE_RE = re.compile(r"^merge (\S+) into ")


def push_row(repo, self_cwd):
    name = Path(repo["path"]).name
    wts = repo["worktrees"]
    # The run's own worktree is this cleanup thread, not work that will land on the default branch.
    running = [Path(w["path"]).name for w in wts if w["group"] == "Running" and not under(self_cwd, w["path"])]
    held = [{"thread": c.get("thread"), "key": c.get("key"), "state": c.get("state"), "note": c.get("note") or ""}
            for c in repo["push"]["held_claims"]]
    commits = [{"sha": c["sha"], "subject": c["subject"], "date": c["author_date"][:10],
                "from": (MERGE_RE.match(c["subject"]) or [None, ""])[1]} for c in repo["push"]["commits"]]
    return {"key": f"push-{slug(name)}-{sha7(commits[-1]['sha'])}", "repo": name, "path": repo["path"],
            "default_branch": repo["default_branch"], "commits": commits, "running": running, "held": held,
            "ready": [Path(w["path"]).name for w in wts if w["group"] == "Ready"],
            "options": [PUSH_NOW, PUSH_LATER, HOLD], "recommendation": push_recommendation(held, running)}


# ── abandoned rows: the inputs one subagent gets ─────────────────────────────

def diff_of(path, base):
    """Working tree against the merge base, capped; a longer diff keeps a by-file summary."""
    if not base:
        return {"text": "", "lines": 0, "truncated": False, "stat": ""}
    full = git(path, "diff", "--no-color", "--no-ext-diff", base) or ""
    lines = full.splitlines()
    out = {"lines": len(lines), "truncated": len(lines) > DIFF_CAP, "text": "\n".join(lines[:DIFF_CAP]), "stat": ""}
    if out["truncated"]:
        out["stat"] = (git(path, "diff", "--stat=120", base) or "").rstrip()
    return out


def merge_base(path, repo, tip):
    ref = f"origin/{repo['default_branch']}" if repo["has_origin"] else repo["default_branch"]
    mb = git(path, "merge-base", ref, tip) or git(path, "merge-base", repo["default_branch"], tip)
    return mb.strip() if mb else None


def needles(w):
    n = [w["path"], home_rel(w["path"]), "/" + Path(w["path"]).name]
    return n + ([w["branch"]] if w.get("branch") else [])


def mentions(fp, keys):
    try:
        with open(fp, "rb") as fh:
            text = fh.read(MAX_HANDOFF_BYTES).decode("utf-8", "ignore")
    except OSError:
        return False
    return any(k in text for k in keys)


def find_handoffs(w, main):
    keys = needles(w)
    found = []
    for root in dict.fromkeys([w["path"], main]):
        ls = git(root, "ls-files", "-co", "--exclude-standard") or ""
        cands = [Path(root) / f for f in ls.splitlines() if "handoff" in f.lower()]
        cands += list((Path(root) / ".scratch").glob("driver-runs/*/handoffs/*.md"))
        found += [str(p) for p in cands[:500] if p.is_file() and mentions(p, keys)]
    return sorted(set(found))


def find_closings(w, home):
    keys = [k for k in needles(w) if not k.startswith("/") or os.sep in k[1:]]  # a bare folder name is too loose here
    d = home / ".claude" / "closings"
    return sorted(str(p) for p in d.glob("*.md") if mentions(p, keys)) if d.is_dir() else []


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def excerpt(transcript):
    """First user message and last assistant message, streamed, each capped."""
    first, last = None, None
    try:
        with open(transcript, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if '"type":"user"' not in line and '"type":"assistant"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                msg = rec.get("message") or {}
                t = text_of(msg.get("content")).strip()
                if not t:
                    continue
                if rec.get("type") == "user" and first is None and not rec.get("isMeta"):
                    first = t
                elif rec.get("type") == "assistant":
                    last = t
    except OSError:
        return None
    return {"transcript": transcript, "first_user": (first or "")[:EXCERPT_CAP], "last_assistant": (last or "")[:EXCERPT_CAP]}


def encode(p):
    return re.sub(r"[^A-Za-z0-9]", "-", p)


def find_session(w, main, home, register_sessions):
    """The session that entered the worktree: the conductor's cwd index first, then a bounded scan."""
    for s in register_sessions:
        if s.get("cwd") and under(s["cwd"], w["path"]) and s.get("transcript"):
            return s["transcript"]
    born = w.get("folder_birthtime") or w.get("folder_ctime") or 0
    proj = home / ".claude" / "projects"
    cands = []
    for d in dict.fromkeys([encode(w["path"]), encode(main)]):
        cands += [p for p in (proj / d).glob("*.jsonl") if p.stat().st_mtime >= born]
    needle = f'"cwd":"{w["path"]}'
    for p in sorted(cands, key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_TRANSCRIPTS]:
        try:
            with open(p, encoding="utf-8", errors="ignore") as fh:
                if any(needle in line for line in fh):
                    return str(p)
        except OSError:
            continue
    return None


def load_register_sessions(home):
    path = home / ".claude" / "skills" / "threads" / "assets" / "register.py"
    try:
        spec = importlib.util.spec_from_file_location("cleanup_register_rows", path)
        reg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reg)
        return [{"cwd": s.get("cwd"), "transcript": reg.transcript_of(s)} for s in reg.sessions(reg.read()).values()]
    except Exception:  # no register: fall back to the transcript scan
        return []


def abandoned_options(w, handoffs, commits):
    opts = [RESUME] if handoffs else []
    if w.get("branch") and not w.get("detached") and commits:
        opts.append(MERGE)
    opts.append(PARK)
    if not (w.get("detached") or w.get("has_nested") or w.get("status_failed")):
        opts.append(DELETE)
    return opts


def delete_safe(w):
    """True only when Delete loses no commit: classify said so, or a branch that moved has every commit
    on the remote default. A never-moved branch the classifier did not mark Delete stays unsafe (a new thread)."""
    if w.get("recommendation") == DELETE:
        return True
    clean = w.get("dirty_count") == 0 and w.get("untracked_count") == 0
    return bool(clean and w.get("branch") and w.get("commits_since_creation")
                and w.get("ahead_of_remote_default") == 0)


def default_recommendation(row):
    if row["delete_safe"] and DELETE in row["options"]:
        return DELETE
    return RESUME if RESUME in row["options"] else PARK


def abandoned_row(repo, w, home, register_sessions):
    main = next((x["path"] for x in repo["worktrees"] if x.get("is_main")), repo["path"])
    name = Path(w["path"]).name
    base = merge_base(w["path"], repo, w["tip"]) if w.get("tip") else None
    log = git(w["path"], "log", "--format=%h %ad %s", "--date=short", "-50", f"{base}..{w['tip']}") if base else ""
    handoffs = find_handoffs(w, main)
    tr = find_session(w, main, home, register_sessions)
    row = {"key": f"wt-{slug(Path(repo['path']).name)}-{slug(name)}-{sha7(w.get('tip'))}",
           "repo": Path(repo["path"]).name, "name": name, "path": w["path"], "branch": w.get("branch"),
           "tip": w.get("tip"), "reason": ("park expired. " if w.get("park_expired") else "") + w["reason"], "detached": w.get("detached"),
           "dirty_files": w.get("dirty_files") or [], "dirty_count": w.get("dirty_count"),
           "untracked_count": w.get("untracked_count"), "commits": len((log or "").splitlines()),
           "ahead_of_remote_default": w.get("ahead_of_remote_default"),
           "last_commit_ts": w.get("last_commit_ts"), "log": (log or "").rstrip(),
           "handoffs": handoffs, "closings": find_closings(w, home),
           "session": excerpt(tr) if tr else None, "diff": diff_of(w["path"], base),
           "delete_safe": delete_safe(w)}
    row["options"] = abandoned_options(w, handoffs, row["commits"])
    row["recommendation"] = default_recommendation(row)
    return row


PROMPT = """You write one row of a cleanup brief: a git worktree that looks abandoned.
The owner reads it cold, on a phone, with no memory of the work. Plain words, Australian spelling,
no em dash, one idea per sentence.

Write at most 12 lines to {answer} with exactly these five labels, each starting a line:
For you: what the work was trying to achieve for the owner.
What the change does: what the diff below changes, readable by someone who never saw it.
How far it got: commits, finished or not, tests if the evidence shows them.
Why it stopped: waiting on the owner's decision, the thread died or closed, or other; name the evidence.
Recommended: exactly one of: {options}.
  Rules: {resume_rule} "{merge}" only when the work is complete and the evidence shows its tests pass.
  {delete_rule} Otherwise "{park}".

Read only the inputs below and the files they name. Change nothing on disk except {answer}.

## Facts
Repo: {repo}. Worktree: {path}. Branch: {branch}. Tip: {tip}.
Classifier reason: {reason}.
Changed files not committed: {dirty_count}; untracked: {untracked}. {dirty}

## Commit log against its merge base
{log}

## Handoff files that name it
{handoffs}

## Closing notes that name it
{closings}

## The session that entered it
{session}

## Diff against its merge base ({lines} lines{trunc})
{diff}

Return the same lines you wrote, nothing else: 12 lines at most.
If anything contradicts the assumptions above, stop and return what you saw verbatim rather than working around it.
"""


def write_prompt(row, run_dir):
    d = run_dir / "abandoned"
    d.mkdir(parents=True, exist_ok=True)
    answer = d / f"{row['key']}.answer.md"
    s = row["session"]
    sess = ("none found" if not s else f"Transcript: {s['transcript']}\nFirst user message:\n{s['first_user']}\n\n"
            f"Last assistant message:\n{s['last_assistant']}")
    df = row["diff"]
    # The diff goes in its own file: a reader with a per-read size cap would otherwise see only the prompt's head.
    diff_ref = "(empty)"
    if df["lines"]:
        dp = d / f"{row['key']}.diff"
        dp.write_text((df["stat"] + "\n\n" if df["stat"] else "") + df["text"] + "\n")
        diff_ref = f"In {dp}. Read all of it, in ranges of 150 lines if one read is refused for size."
    text = PROMPT.format(
        answer=answer, options=", ".join(f'"{o}"' for o in row["options"]), merge=MERGE, park=PARK,
        resume_rule=f'"{RESUME}" when a handoff exists.' if RESUME in row["options"] else "",
        delete_rule=(f'"{DELETE}" is allowed: no commit would be lost.' if row["delete_safe"] and DELETE in row["options"]
                     else f'Never "{DELETE}": it would lose work nobody has read.'),
        repo=row["repo"], path=row["path"], branch=row["branch"] or "none (detached)", tip=row["tip"],
        reason=row["reason"], dirty_count=row["dirty_count"], untracked=row["untracked_count"],
        dirty=("Files: " + ", ".join(row["dirty_files"][:40])) if row["dirty_files"] else "",
        log=row["log"] or "no commits of its own", handoffs="\n".join(row["handoffs"]) or "none",
        closings="\n".join(row["closings"]) or "none", session=sess, lines=df["lines"],
        trunc=f", first {DIFF_CAP} shown" if df["truncated"] else "",
        diff=diff_ref)
    p = d / f"{row['key']}.prompt.md"
    p.write_text(text)
    row["prompt"], row["answer_path"] = str(p), str(answer)


def running_row(repo, w):
    claims = [c for c in repo["claims"] if c.get("cwd") and under(c["cwd"], w["path"])
              and c.get("state") not in ("incomplete", "abandoned", "done", "released")]
    c = max(claims, key=lambda c: c.get("ts") or "", default=None)
    return {"name": Path(w["path"]).name, "repo": Path(repo["path"]).name,
            "doing": f"{c.get('note') or c.get('key')} ({c['state']})" if c else w["reason"]}


def build_rows(d, run_dir, run_id, self_cwd, home=None):
    home = home or Path.home()
    regs = load_register_sessions(home)
    rows = {"run_id": run_id, "brief_id": f"cleanup-{run_id}", "generated": time.strftime("%Y-%m-%d %H:%M"),
            "counts": d["counts"], "groups": d["groups"], "running": [], "pruned": [], "push": [], "abandoned": [],
            "skipped": [], "pruned_done": bool(d.get("pruned_done")), "parked": 0, "landing_left": 0, "fetch_failed": []}
    for r in d["repos"]:
        if r["fetch_failed"]:
            rows["fetch_failed"].append(Path(r["path"]).name)
        for w in r["worktrees"]:
            g = w["group"]
            if g == "Running":
                rows["running"].append(running_row(r, w))
            elif g == "Pruned" or (g == "Landing" and w.get("landing_action") == "remove"):
                pr = w.get("prune") or {}
                rows["pruned"].append({"name": Path(w["path"]).name, "repo": Path(r["path"]).name,
                                       "landing": g == "Landing", "why": w["reason"] + (". Removed: " + pr["did"] if pr else "")})
            elif g == "Landing":
                rows["landing_left"] += 1
            elif g == "Parked":
                rows["parked"] += 1
            elif g == "Skipped":
                rows["skipped"].append({"name": Path(w["path"]).name, "repo": Path(r["path"]).name, "why": w["reason"]})
            elif g == "Abandoned":
                row = abandoned_row(r, w, home, regs)
                write_prompt(row, run_dir)
                rows["abandoned"].append(row)
        if r.get("push"):
            rows["push"].append(push_row(r, self_cwd))
    return rows


# ── the brief ────────────────────────────────────────────────────────────────

def read_answer(row):
    """Labelled lines from the subagent; the recommendation must survive the row's own facts."""
    p = row.get("answer_path")
    try:
        text = Path(p).read_text() if p else ""
    except OSError:
        text = ""
    got, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"\s*\**(%s)\**\s*:\s*\**\s*(.*)" % "|".join(map(re.escape, LABELS)), line)
        if m:
            cur = m.group(1)
            got[cur] = m.group(2).strip()
        elif cur and line.strip():
            got[cur] += " " + line.strip()
    rec = got.pop("Recommended", "").strip().strip('".*')
    rec = next((o for o in row["options"] if rec.lower().startswith(o.lower())), None)
    if rec == DELETE and not row["delete_safe"]:
        rec = None
    if rec == RESUME and not row["handoffs"]:
        rec = None
    return got, rec or default_recommendation(row)


def choices(key, opts, rec, why=None):
    """A tick-box group pre-ticked through its hidden note (a hand-written `checked` is ignored).
    `why` maps an option to its cost, benefit and likelihood, shown in its label; the value stays the bare option."""
    sug, tag, why = ' class="suggested"', " (Recommended)", why or {}
    rows = [f'  <label{sug if o == rec else ""}><input type="checkbox" value="{html.escape(o)}"> '
            f'{html.escape(o)}{tag if o == rec else ""}' + (f": {html.escape(plain(why[o]))}" if o in why else "") +
            '</label>' for o in opts]
    return (":::html\n<fieldset data-note-group class=\"cleanup-choice\">\n" + "\n".join(rows) +
            f'\n  <textarea data-note="{key}" data-note-label="{key}" hidden>{html.escape(rec)}</textarea>\n</fieldset>\n:::\n')


def plain(s):
    """Text from outside (claim notes, subagent lines, commit subjects, names) made safe to place in the brief.
    No em dash (the brief bans it). No line break, so it never starts a line and cannot open a raw HTML block.
    No run of colons, so it cannot open or close a `:::` container or split a `::` heading. Inline HTML the
    builder does not allowlist is escaped by build-brief itself."""
    s = re.sub(r"\s*\u2014\s*", ", ", str(s))
    s = re.sub(r"\s*[\r\n\u2028\u2029]+\s*", " ", s)
    return re.sub(r":(?=:)", ": ", s)


def cell(s):
    return plain(s).replace("|", "\\|").replace("\n", " ")


def plural(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


def diff_block(row):
    df = row["diff"]
    if not df["lines"]:
        return ""
    head = f"The diff: {plural(df['lines'], 'line')}" + (f", first {DIFF_CAP} shown" if df["truncated"] else "")
    body = (df["stat"] + "\n\n" if df["stat"] else "") + df["text"]
    return (f":::html\n<details class=\"example\"><summary>{head}</summary>\n"
            # A diff is quoted material and keeps its own em dashes, as an entity so the prose lint stays on authored text.
            # A diff line that starts with a colon (" :::html") would open or close the container: entity it.
            f"<pre><code>{re.sub(r'(?m)^(\s*):', r'\1&#58;', html.escape(body).replace(chr(0x2014), '&#8212;'))}"
            "</code></pre>\n</details>\n:::\n")


def ahead(row):
    """Commits a merge would ship: the remote-default count when known (0 is a real answer), else the branch's own."""
    n = row["ahead_of_remote_default"]
    return row["commits"] if n is None else n


def road_costs(row):
    """Each road's cost, benefit and likelihood, in numbers, for its own tick-box label."""
    n, tip = ahead(row), sha7(row.get("tip"))
    dirty = (row["dirty_count"] or 0) + (row["untracked_count"] or 0)
    files = plural(dirty, "uncommitted or untracked file")
    why = {}
    if RESUME in row["options"]:
        hp, _ = RS.pick_handoff(row)
        cmd = f"it will ask you which of {len(row['handoffs'])} handoffs to use" if hp is None and len(row["handoffs"]) > 1 else \
            "the exact command that will run is " + (RS.handoff_command(hp) if hp else "none (no handoff file found)")
        why[RESUME] = (f"costs 1 new thread, started from {plural(len(row['handoffs']), 'handoff')} at tip {tip}; {cmd}. "
                       "Buys the work going on where it stopped. Likely to help only if the handoff still matches the tip")
    if MERGE in row["options"]:
        why[MERGE] = (f"ships {plural(n, 'commit')} to the remote after the merge gates and review. "
                      + ("Buys nothing: there is no commit to ship" if not n else "Buys the work landing on main")
                      + ". The gates refuse it if its tests fail, so a broken branch does not ship")
    why[PARK] = ("costs nothing: no file changes for 30 days. Buys time to decide with nothing lost. "
                 "Certain: the row comes back when the park ends or the tip moves")
    if DELETE in row["options"]:
        if row["delete_safe"] or not n:
            lose = "loses no commit" + (f", but does lose {files}" if dirty else "")
        else:
            lose = (f"will tag the tip first, so its {plural(n, 'commit')} nobody has merged stay restorable from a local tag"
                    + (f"; the tag holds commits only, so {files} are lost" if dirty else ""))
        why[DELETE] = (f"{lose}. Only ignored secret files (.env and key files) are moved aside. "
                       "Buys a free folder and branch. Certain: the folder and branch are removed")
    return why


def push_costs(p):
    """Push now, Push later and Hold: cost, benefit and likelihood, in numbers."""
    n, run, ready = len(p["commits"]), p["running"], p["ready"]
    names = ", ".join(map(plain, run))
    prune = f", and cleanup prunes {plural(len(ready), 'worktree')} it ships" if ready else ""
    held = f"{plural(len(p['held']), 'thread')} held this push back, so main may not be ready to deploy" if p["held"] else ""
    now = f"ships all {n} commits on local {plain(p['default_branch'])} to the remote now. Buys them going live today{prune}. "
    now += (held if held else
            f"{plural(len(run), 'worktree')} still running ({names}), so a second push is likely when it lands" if run else
            "Nothing else runs in this repo, so one push carries everything and nothing waits behind it")
    later = (f"ships nothing until {names} lands, up to 24 hours; then one push carries the {n} commits plus what landed. "
             "Buys one deploy instead of two. If it has not landed in 24 hours, nothing ships and you get an ask"
             if run else f"nothing runs in this repo, so this ships the {n} commits now, the same as Push now")
    hold = (f"the {n} commits stay unpushed until the next cleanup asks again. Buys no deploy"
            + (f", which respects the {plural(len(p['held']), 'thread')} holding it" if p["held"] else "")
            + ". Certain: nothing changes on the remote")
    return {PUSH_NOW: now, PUSH_LATER: later, HOLD: hold}


DEFS = [("Worktree", "a second working folder of a repo, on its own branch, where one thread builds without touching another's files"),
        ("The conductor", "the shared work register every thread claims work in; the source for what is live and its status"),
        ("Local main", "the default branch on this machine; a merge lands work here and a push sends all of it to the remote"),
        ("Prune", "remove a worktree folder and its branch, refused while it holds uncommitted or unmerged work"),
        ("Driver run", "an unattended build that works through tickets, each in its own worktree, and lands them one at a time")]


def answered(results, key, q, question, tag):
    """Round one asks `Qn question`; round two keeps the section as `Your Qn answer: <what was picked>`."""
    if results:
        return f"## Your Q{q} answer: {plain(results[key]['label'])} :: {tag}\n"
    return f"## Q{q} {question} :: {tag}\n"


def outcome_md(r):
    """What ran for one answered row: the outcome, then how to undo it."""
    out = f"**What ran:** {plain(r['text'])}\n"
    if r.get("undo"):
        out += f"\n**To undo:** {plain(r['undo'])}\n"
    return out


def results_call(results):
    """The call and its price, in one sentence: what cleanup did with the returned brief."""
    n = lambda st: sum(r["status"] == st for r in results.values())
    files = sum(len(r.get("kept") or []) for r in results.values())
    dele = [r for r in results.values() if r["status"] == "deleted"]
    parts = [(n("parked"), f"parked {n('parked')} (nothing on disk changed)"),
             (len(dele), f"deleted {len(dele)} (each tagged first, so its commits stay restorable, with {plural(files, 'secret file')} moved aside)"),
             (n("held"), f"held {n('held')}"), (n("none"), f"left {n('none')} alone"),
             (n("asked"), f"asked you about {n('asked')}"),
             (n("pushed"), f"pushed {n('pushed')} repo(s) after a range check"),
             (n("merged and pushed"), f"merged and pushed {n('merged and pushed')}"), (n("merged"), f"merged {n('merged')} without pushing"),
             (n("waiting"), f"left {n('waiting')} push(es) waiting for running work"),
             (n("launched"), f"started {n('launched')} thread(s) in Orca from handoffs"),
             (n("bubble"), f"started no thread for {n('bubble')} resume row(s) and sent each as a done bubble with its command"),
             (n("unsupported"), f"did nothing for {n('unsupported')} that cleanup cannot run")]
    parts = [t for c, t in parts if c] or ["did nothing"]
    bad = n("failed") + n("refused")
    return "Cleanup " + ", ".join(parts) + (f", and could not finish {bad}" if bad else "") + ("" if any(n(x) for x in ("pushed", "merged", "merged and pushed")) else "; nothing was pushed or merged") + "."


def render(rows, read_only=False, results=None, consumed=None):
    """results (key -> outcome) makes this round two: answered rows become `Your Qn answer`."""
    run, pr, ab, pu = rows["running"], rows["pruned"], rows["abandoned"], rows["push"]
    answers = [read_answer(a) for a in ab]
    for a, (_, rec) in zip(ab, answers):
        a["recommendation"] = rec
    n_commits = sum(len(p["commits"]) for p in pu)
    tally = {o: sum(p["recommendation"] == o for p in pu) for o in (PUSH_NOW, PUSH_LATER, HOLD)}
    roads = {o: sum(a["recommendation"] == o for a in ab) for o in (RESUME, MERGE, PARK, DELETE)}
    road_txt = ", ".join(f"{n} {o.split(' ')[0].lower()}" for o, n in roads.items() if n) or "none"
    decisions = len(pu) + len(ab)
    would = read_only and not rows.get("pruned_done")  # an auto-prune ran: the Pruned group reports real removals
    verb = "would prune" if would else "pruned"
    finished = sum(not p["landing"] for p in pr)
    c = rows["counts"]
    pushed = {o: sum(len(p["commits"]) for p in pu if p["recommendation"] == o) for o in (PUSH_NOW, PUSH_LATER)}
    merged = sum(ahead(a) for a in ab if a["recommendation"] == MERGE)
    # The call and its price, in numbers: the sub line's first sentence and the verdict both carry it.
    call = (f"Sending this back untouched approves {plural(decisions, 'decision')}: push {plural(tally[PUSH_NOW], 'repo')} now "
            f"({plural(pushed[PUSH_NOW], 'commit')} to the remote), push {tally[PUSH_LATER]} after their running work lands "
            f"({plural(pushed[PUSH_LATER], 'commit')}), hold {tally[HOLD]}, and {road_txt} for the "
            f"{plural(len(ab), 'abandoned worktree')}" + (f" (the merges ship {plural(merged, 'commit')})" if roads[MERGE] else "") + ".")
    if results:
        call = results_call(results)
    md = [f"""---
title: Cleanup, {rows['generated'][:10]}
head-title: Cleanup | {c['worktrees']} worktrees across {c['repos']} repos
brief-id: {rows['brief_id']}
{('consumed: ' + consumed) if consumed else ''}
eyebrow: /cleanup · run {rows['run_id']}{' · round two, what ran' if results else ''}{' · read-only run, nothing is acted on' if read_only else ''}
sub: {call}{' This run is read-only, so nothing is acted on.' if read_only else ''} Below, every worktree on this machine, sorted into what is running, what cleanup {verb} on its own, what is ready to push, and what looks abandoned.
---

## Answers

{'What did cleanup do with your answers?' + chr(10) + ': ' + call + chr(10) if results else ''}
What is still running?
: {plural(len(run), 'worktree')}. Nothing to decide.

What {'would cleanup prune' if would else 'did cleanup prune'} on its own?
: {plural(len(pr), 'folder')}: {finished} finished worktrees whose work is on the remote, and {len(pr) - finished} landing scratch folders.

What is ready to push?
: {plural(len(pu), 'repo')} hold {plural(n_commits, 'unpushed commit')} on local main, one question per repo, because a push ships the whole of main.

What looks abandoned?
: {plural(len(ab), 'worktree')}, one question each: recommended {road_txt}.

{call}{' This run is read-only, so nothing is acted on.' if read_only else ''}{'' if results else ' One box per row.'}

## Contents

# Running

Nothing here needs you. Each row comes from the conductor's claim, or the reason cleanup saw it as live.

## Still working :: {plural(len(run), 'worktree')}, no action

"""]
    md.append("| Worktree | Repo | Doing, and its status |\n| --- | --- | --- |\n" +
              "".join(f"| {cell(r['name'])} | {cell(r['repo'])} | {cell(r['doing'])} |\n" for r in run)
              if run else "No worktree is running.\n")
    md.append(f"""
# Pruned

Cleanup {verb} these without asking, because each one passed the prune guards and no session was using it.{' This run is read-only: nothing was removed.' if would else ''}

## {'Would prune' if would else 'Pruned automatically'} :: {plural(len(pr), 'folder')}

""")
    md.append("| Folder | Repo | Why it was safe |\n| --- | --- | --- |\n" +
              "".join(f"| {cell(p['name'])} | {cell(p['repo'])} | {cell(p['why'])} |\n" for p in pr) if pr else "Nothing to prune.\n")
    extra = []
    if rows["landing_left"]:
        extra.append(f"{plural(rows['landing_left'], 'landing scratch folder')} left alone (newer than 24 hours or in use)")
    if rows["parked"]:
        extra.append(f"{plural(rows['parked'], 'parked worktree')} hidden until its park ends")
    if rows["skipped"]:
        extra.append(f"{plural(len(rows['skipped']), 'worktree')} skipped: " + "; ".join(plain(f"{s['repo']}/{s['name']} ({s['why']})") for s in rows["skipped"]))
    if rows["fetch_failed"]:
        extra.append("fetch failed, so nothing was pruned or pushed in: " + ", ".join(map(plain, rows["fetch_failed"])))
    if extra:
        md.append("\n" + ". ".join(e[0].upper() + e[1:] for e in extra) + ".\n")

    md.append("""
# Ready to push

**A push ships everything on local main, not one thread's work.** So this part has one question per repo, listing every commit the push carries.
""")
    q = 1
    for p in pu:
        n = len(p["commits"])
        md.append(answered(results, p["key"], q, f"Push {plain(p['repo'])} now?", plural(n, 'commit')))
        md.append(f"**What ships:** {plural(n, 'commit')} on local {plain(p['default_branch'])}, oldest first. "
                  "Each box below says what it costs, what it buys and how likely that is.\n")
        md.append("| Commit | Date | Subject | From |\n| --- | --- | --- | --- |\n" +
                  "".join(f"| {c['sha'][:7]} | {c['date']} | {cell(c['subject'])} | {cell(c['from'])} |\n" for c in p["commits"]))
        if p["held"]:
            md.append("**Already waiting:** " + "; ".join(
                f"thread {plain(h['thread'])} holds {plain(h['key'])} at {plain(h['state'])}" + (f": {plain(h['note'])}" if h["note"] else "") for h in p["held"]) +
                ". That thread may know main is not ready to deploy, so Hold is recommended.\n")
        md.append(outcome_md(results[p["key"]]) if results else choices(p["key"], p["options"], p["recommendation"], push_costs(p)))
        q += 1
    if not pu:
        md.append("\nNo repo has unpushed commits on local main.\n")

    md.append(f"""
# Looks abandoned

Each row says what the work was for, what the change does, how far it got and why it stopped, with the diff below it. Pick one road per row. Delete is never recommended where it loses a commit nobody has read.
""")
    for a, (got, rec) in zip(ab, answers):
        md.append(answered(results, a["key"], q, f"{plain(a['repo'])} / {plain(a['name'])}: what happens to it?", plain(a['branch'] or 'detached')))
        fallback = {"For you": "Not summarised in this run; read the diff and log below.",
                    "What the change does": (f"See the diff below ({plural(a['diff']['lines'], 'line')})." if a["diff"]["lines"]
                                             else "Nothing: the worktree has no commits or edits against its base."),
                    "How far it got": f"{plural(a['commits'], 'commit')} of its own, {plural((a['dirty_count'] or 0) + (a['untracked_count'] or 0), 'uncommitted file')}.",
                    "Why it stopped": f"Unknown. Cleanup saw: {plain(a['reason'])}."}
        for lab in LABELS[:4]:
            md.append(f"**{lab}:** {plain(got.get(lab) or fallback[lab])}\n")
        md.append(diff_block(a))
        md.append(outcome_md(results[a["key"]]) if results else choices(a["key"], a["options"], rec, road_costs(a)))
        q += 1
    if not ab:
        md.append("\nNothing looks abandoned.\n")

    md.append("""
# Words used here

The terms this brief leans on, so a row reads the same to anyone.

## Definitions :: the five terms this brief uses

:::html
<p class="defs-h">Used here</p>
<div class="defs-in">
""" + "".join(f'  <div class="term"><h4>{t}</h4><ul><li><span class="k">In this brief</span> {d}</li></ul></div>\n' for t, d in DEFS) +
"""</div>
:::
""")
    return "\n".join(md)


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rows")
    r.add_argument("discover_json")
    r.add_argument("--run-dir", required=True)
    r.add_argument("--self-cwd", default=os.getcwd())
    b = sub.add_parser("brief")
    b.add_argument("rows_json")
    b.add_argument("--read-only", action="store_true")
    b.add_argument("--render", action="store_true", help="also build the HTML and lint it")
    b.add_argument("--results", help="results.json from apply.py: build round two")
    a = ap.parse_args(argv)
    if a.cmd == "rows":
        run_dir = Path(a.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        rows = build_rows(json.loads(Path(a.discover_json).read_text()), run_dir, run_dir.name, a.self_cwd)
        (run_dir / "rows.json").write_text(json.dumps(rows, indent=1))
        print(f"{run_dir / 'rows.json'}: {len(rows['abandoned'])} abandoned prompts in {run_dir / 'abandoned'}")
        return 0
    rp = Path(a.rows_json)
    rows = json.loads(rp.read_text())
    md = rp.parent / "cleanup.md"
    results = json.loads(Path(a.results).read_text()) if a.results else None
    md.write_text(render(rows, a.read_only and not results, results, f"r2-{int(time.time())}" if results else None))
    if not results:  # apply.py needs the recommendation each row showed
        rp.write_text(json.dumps(rows, indent=1))
    print(md)
    if a.render:
        assets = Path.home() / ".claude" / "skills" / "peakstate-brief" / "assets"
        out = md.with_suffix(".html")
        subprocess.run(["node", str(assets / "build-brief.mjs"), str(md), str(out)], check=True)
        return subprocess.run([sys.executable, str(assets / "brief-lint.py"), str(out)]).returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
