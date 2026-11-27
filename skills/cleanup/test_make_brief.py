#!/usr/bin/env python3
"""Hermetic self-check for make_brief.py. Run: python3 skills/cleanup/test_make_brief.py

A real git repo in a temp folder for the Abandoned-row inputs; hand-built rows for the brief.
Nothing real is read or changed (HOME points at the temp folder).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_brief as M  # noqa: E402

FAILS = []
GENV = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null",
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{detail}]"))
    if not cond:
        FAILS.append(name)


def git(cwd, *a):
    r = subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, env=GENV)
    assert r.returncode == 0, (a, r.stderr)
    return r.stdout.strip()


def wt_facts(path, branch, tip, **kw):
    f = {"path": path, "branch": branch, "tip": tip, "detached": False, "has_nested": False,
         "dirty_count": 0, "untracked_count": 0, "dirty_files": [], "status_failed": False,
         "reason": "1 commit(s) on no default branch (no Delete option)", "recommendation": None,
         "commits_since_creation": 1, "ahead_of_remote_default": 1, "folder_ctime": 0}
    f.update(kw)
    return f


def test_abandoned_inputs(tmp):
    os.environ["GIT_CONFIG_GLOBAL"] = "/dev/null"
    a = os.path.join(tmp, "repo")
    os.makedirs(a)
    git(a, "init", "-q", "-b", "main")
    open(os.path.join(a, "base.txt"), "w").write("base\n")
    git(a, "add", ".")
    git(a, "commit", "-qm", "base")
    w = os.path.join(tmp, "repo-wt", "feature")
    git(a, "worktree", "add", "-q", "-b", "feat/big", w)
    open(os.path.join(w, "big.txt"), "w").write("".join(f"line {i}\n" for i in range(600)))
    git(w, "add", ".")
    git(w, "commit", "-qm", "add a big file")
    tip = git(w, "rev-parse", "HEAD")
    # A handoff in the main repo that names the branch; another that does not.
    os.makedirs(os.path.join(a, "docs"))
    open(os.path.join(a, "docs", "HANDOFF-feature.md"), "w").write("Resume on feat/big.\n")
    open(os.path.join(a, "docs", "handoff-other.md"), "w").write("Nothing to see.\n")
    home = Path(tmp) / "home"
    (home / ".claude" / "closings").mkdir(parents=True)
    (home / ".claude" / "closings" / "x.md").write_text("Closed feat/big after review.\n")
    (home / ".claude" / "closings" / "y.md").write_text("Unrelated.\n")
    # A transcript in the main repo's project folder whose session entered the worktree.
    pd = home / ".claude" / "projects" / M.encode(a)
    pd.mkdir(parents=True)
    lines = [{"type": "user", "cwd": a, "message": {"role": "user", "content": "Make the big file " + "x" * 3000}},
             {"type": "assistant", "cwd": w, "message": {"content": [{"type": "text", "text": "first reply"}]}},
             {"type": "assistant", "cwd": w, "message": {"content": [{"type": "text", "text": "Stopped: waiting on you."}]}}]
    (pd / "s1.jsonl").write_text("\n".join(json.dumps(l, separators=(",", ":")) for l in lines) + "\n")
    repo = {"path": a, "default_branch": "main", "has_origin": False,
            "worktrees": [{"path": a, "is_main": True}, wt_facts(w, "feat/big", tip)]}
    row = M.abandoned_row(repo, repo["worktrees"][1], home, [])
    check("key carries repo, folder and tip sha7", row["key"] == f"wt-repo-feature-{tip[:7]}", row["key"])
    check("diff capped at 400 lines", len(row["diff"]["text"].splitlines()) == M.DIFF_CAP, row["diff"]["lines"])
    check("long diff marked truncated with a by-file summary",
          row["diff"]["truncated"] and "big.txt" in row["diff"]["stat"], row["diff"]["stat"])
    check("handoff naming the branch found, other ignored",
          [Path(p).name for p in row["handoffs"]] == ["HANDOFF-feature.md"], row["handoffs"])
    check("closing note naming the branch found", [Path(p).name for p in row["closings"]] == ["x.md"], row["closings"])
    s = row["session"] or {}
    check("session that entered the worktree found from the parent's folder", s.get("transcript", "").endswith("s1.jsonl"))
    check("first user message capped at 2,000 chars", len(s.get("first_user", "")) == M.EXCERPT_CAP)
    check("last assistant message is the last one", s.get("last_assistant") == "Stopped: waiting on you.")
    check("handoff makes Resume the default", row["recommendation"] == M.RESUME, row["recommendation"])
    check("unmerged commit: Delete offered but not safe", M.DELETE in row["options"] and not row["delete_safe"])
    M.write_prompt(row, Path(tmp) / "run")
    p = Path(row["prompt"]).read_text()
    check("prompt has the 12-line budget and the contradiction clause",
          "12 lines at most" in p and "return what you saw verbatim" in p)
    check("prompt forbids Delete for unread commits", 'Never "Delete"' in p)
    check("prompt names the answer file", row["answer_path"] in p)
    dp = Path(row["prompt"]).with_suffix("").with_suffix(".diff")
    check("diff in its own file, prompt stays under one read (10 KB)",
          dp.is_file() and str(dp) in p and len(p.encode()) < 10_000, len(p.encode()))


def test_rules():
    check("Hold when a claim waits on the owner", M.push_recommendation([{"state": "waiting-on-user"}], []) == M.HOLD)
    check("Hold beats running work", M.push_recommendation([{"state": "blocked"}], ["x"]) == M.HOLD)
    check("running work defers the push", M.push_recommendation([], ["x"]) == M.PUSH_LATER)
    check("nothing running: push now", M.push_recommendation([], []) == M.PUSH_NOW)
    new = wt_facts("/x", "b", "t", commits_since_creation=0, ahead_of_remote_default=0)
    check("never-moved branch the classifier did not mark Delete is unsafe", not M.delete_safe(new))
    check("classifier Delete is safe", M.delete_safe(dict(new, recommendation="Delete")))
    check("reflog expired: never safe", not M.delete_safe(wt_facts("/x", "b", "t", commits_since_creation=None,
                                                                  ahead_of_remote_default=0)))
    det = wt_facts("/x", None, "t", detached=True)
    check("detached: no Delete, no Merge", M.abandoned_options(det, [], 2) == [M.PARK])
    check("nested: no Delete", M.DELETE not in M.abandoned_options(wt_facts("/x", "b", "t", has_nested=True), [], 1))


def sample_rows(tmp):
    ans = Path(tmp) / "a1.answer.md"
    ans.write_text("For you: tidy the editor.\nWhat the change does: stops lines\n  jumping — above the caret.\n"
                   "How far it got: 1 commit.\nWhy it stopped: the thread closed.\nRecommended: Delete\n")
    ab = {"key": "wt-r-ed-abc1234", "repo": "r", "name": "ed", "path": "/x/ed", "branch": "fix/ed", "tip": "abc1234ff",
          "reason": "1 commit(s) on no default branch", "detached": False, "dirty_files": [], "dirty_count": 0,
          "untracked_count": 0, "commits": 1, "ahead_of_remote_default": 1, "log": "abc1234 fix",
          "handoffs": [], "closings": [], "session": None, "delete_safe": False, "answer_path": str(ans),
          "diff": {"text": "+a — b", "lines": 1, "truncated": False, "stat": ""},
          "options": [M.MERGE, M.PARK, M.DELETE], "recommendation": M.PARK}
    ab2 = dict(ab, key="wt-r-new-def5678", name="new", answer_path=None, delete_safe=True,
               options=[M.PARK, M.DELETE], recommendation=M.DELETE, diff={"text": "", "lines": 0, "truncated": False, "stat": ""})
    push = {"key": "push-r-0123456", "repo": "r", "path": "/x", "default_branch": "main",
            "commits": [{"sha": "0123456789", "subject": "merge feat into main", "date": "2026-11-01", "from": "feat"},
                        {"sha": "1111111999", "subject": "fix | pipe", "date": "2026-11-02", "from": ""}],
            "running": [], "held": [{"thread": "t1", "key": "r:push", "state": "waiting-on-user", "note": "range has others"}],
            "ready": ["feat"], "options": [M.PUSH_NOW, M.PUSH_LATER, M.HOLD], "recommendation": M.HOLD}
    return {"run_id": "2026-11-27-1400", "brief_id": "cleanup-2026-11-27-1400", "generated": "2026-11-27 14:00",
            "counts": {"repos": 2, "worktrees": 6}, "groups": {}, "running": [{"name": "w1", "repo": "r", "doing": "build (in-progress)"}],
            "pruned": [{"name": "old", "repo": "r", "landing": False, "why": "merged"}], "push": [push],
            "abandoned": [ab, ab2], "skipped": [], "parked": 1, "landing_left": 0, "fetch_failed": []}


def test_brief(tmp):
    md = M.render(sample_rows(tmp), read_only=True)
    parts = re.findall(r"^# (.+)$", md, re.M)
    check("four parts in order, then definitions",
          parts == ["Running", "Pruned", "Ready to push", "Looks abandoned", "Words used here"], parts)
    check("per-run brief id", "brief-id: cleanup-2026-11-27-1400" in md)
    groups = re.findall(r"<fieldset data-note-group.*?</fieldset>", md, re.S)
    check("one fieldset per decision row (1 push + 2 abandoned)", len(groups) == 3, len(groups))
    notes = dict(re.findall(r'<textarea data-note="([^"]+)"[^>]*hidden>([^<]*)</textarea>', md))
    check("push pre-filled Hold", notes.get("push-r-0123456") == M.HOLD, notes)
    check("unsafe Delete from a subagent falls back to Park", notes.get("wt-r-ed-abc1234") == M.PARK, notes)
    check("no answer file: default recommendation kept", notes.get("wt-r-new-def5678") == M.DELETE, notes)
    check("no hand-written checked attribute", " checked" not in md)
    check("every commit listed", "0123456" in md and "1111111" in md and "fix \\| pipe" in md)
    check("held claim shown", "t1 holds r:push at waiting-on-user" in md)
    check("multi-line answer joined", "stops lines jumping, above the caret." in md)
    check("four row labels present",
          all(f"**{l}:**" in md for l in ["For you", "What the change does", "How far it got", "Why it stopped"]))
    check("diff embedded collapsed", '<details class="example">' in md and "&#8212;" in md)
    check("no raw em dash anywhere", "—" not in md)
    check("Q numbering 1..3", re.findall(r"^## (Q\d+)", md, re.M) == ["Q1", "Q2", "Q3"])
    check("read-only said up front", "read-only run" in md)
    verdict = md.split("## Contents")[0].strip().splitlines()[-1]
    check("verdict under 400 chars and states what untouched approves",
          len(verdict) <= 400 and verdict.startswith("Sending this back untouched approves 3 decisions: push 0 repos now"), verdict)


BUILD = Path.home() / ".claude" / "skills" / "peakstate-brief" / "assets" / "build-brief.mjs"


def build_html(md, tmp, name):
    src = Path(tmp) / f"{name}.md"
    src.write_text(md)
    out = src.with_suffix(".html")
    r = subprocess.run(["node", str(BUILD), str(src), str(out)], capture_output=True, text=True)
    return out.read_text() if r.returncode == 0 and out.is_file() else ""


def test_untrusted_text_cannot_escape(tmp):
    """A diff line, a commit subject, a name or a subagent line that starts with ::: or carries raw HTML."""
    rows = sample_rows(tmp)
    ab = rows["abandoned"][0]
    ab["diff"] = {"text": " :::\n:::html\n<img src=x onerror=alert(1)>\n :::html\n<b>z</b>", "lines": 5,
                  "truncated": False, "stat": ""}
    Path(ab["answer_path"]).write_text("For you: x\n:::\n:::html\n<img src=x onerror=alert(1)>\nRecommended: Park\n")
    rows["push"][0]["commits"][1]["subject"] = "::: <img src=x onerror=alert(1)>"
    rows["push"][0]["held"][0]["note"] = "a\n:::html\n<img src=x onerror=alert(1)>\n:::"
    rows["skipped"] = [{"name": ":::html", "repo": "r", "why": "<img src=x onerror=alert(1)>\n:::"}]
    md = M.render(rows, read_only=True)
    fences = [l for l in md.splitlines() if l.strip().startswith(":::")]
    check("no untrusted line starts a container in the markdown",
          fences.count(":::html") == fences.count(":::") == 5 and len(fences) == 10, fences)
    page = build_html(md, tmp, "inject")
    page = page.split("<script")[0]  # the runtime's own comments name the fieldset
    check("built through build-brief.mjs", bool(page), BUILD)
    check("no live <img from untrusted text", "<img src=" not in page)
    details = re.findall(r'<details class="example">.*?</details>', page, re.S)
    check("diff stays inside one details, with no tick boxes in it",
          len(details) == 1 and "data-note-group" not in details[0] and "&lt;img" in details[0], len(details))
    check("every row's tick boxes are rendered", page.count("<fieldset data-note-group") == 3, page.count("<fieldset data-note-group"))


def test_costs():
    base = {"options": [M.MERGE, M.PARK, M.DELETE], "handoffs": [], "tip": "abc1234ff", "commits": 3,
            "ahead_of_remote_default": 0, "dirty_count": 2, "untracked_count": 1, "delete_safe": False}
    why = M.road_costs(base)
    check("0 ahead is not missing: Merge ships 0 commits", why[M.MERGE].startswith("ships 0 commits"), why[M.MERGE])
    check("0 ahead: Delete loses no commit but loses the files",
          why[M.DELETE].startswith("loses no commit, but does lose 3 uncommitted or untracked files"), why[M.DELETE])
    why = M.road_costs(dict(base, ahead_of_remote_default=None))
    check("unknown ahead falls back to the branch's own commits", why[M.MERGE].startswith("ships 3 commits"), why[M.MERGE])
    check("unsafe Delete tags first and says the tag holds commits only",
          "will tag the tip first" in why[M.DELETE] and "the tag holds commits only, so 3 uncommitted" in why[M.DELETE]
          and "recoverable)" not in why[M.DELETE], why[M.DELETE])
    words = ("cost", "ship", "lose")
    for o, t in M.road_costs(dict(base, options=[M.RESUME] + base["options"], handoffs=["h"])).items():
        check(f"{o}: cost, benefit and likelihood in its own text",
              any(w in t for w in words) and "Buys" in t and any(w in t for w in ("Certain", "Likely", "refuse")), t)
    push = {"commits": [{}] * 4, "running": ["w1"], "ready": [], "held": [], "default_branch": "main"}
    for o, t in M.push_costs(push).items():
        check(f"{o}: numbers, benefit and likelihood", re.search(r"\d", t) and "Buys" in t and
              any(w in t for w in ("likely", "Certain", "If it has not landed")), t)
    md = M.render(sample_rows(tempfile.mkdtemp()), read_only=False)
    labels = re.findall(r'<label[^>]*><input [^>]*> ([^<]*)</label>', md)
    check("every option label carries its own cost text", len(labels) == 8 and all(": " in l for l in labels), labels)
    sub = re.search(r"^sub: (.*)$", md, re.M).group(1)
    check("sub line opens with the call and its price in numbers",
          sub.startswith("Sending this back untouched approves 3 decisions: push 0 repos now (0 commits to the remote)"), sub)


def main():
    tmp = os.path.realpath(tempfile.mkdtemp())
    test_abandoned_inputs(tmp)
    test_rules()
    test_brief(tmp)
    test_costs()
    test_untrusted_text_cannot_escape(tmp)
    if FAILS:
        print(f"\nFAILED {len(FAILS)}: {FAILS}")
        sys.exit(1)
    print("\nPASS")


if __name__ == "__main__":
    main()
