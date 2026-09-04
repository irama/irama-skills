#!/usr/bin/env python3
"""Pre-commit guard for a PUBLIC config repo.

Blocks a commit that introduces a hard leak (absolute home paths, personal
emails, credentials). Warns — but does not block — on mentions of the author's
own app domains, which appear deliberately in "why this rule exists" war
stories and are not secret.

Run over the staged diff:   python3 scripts/check-no-leaks.py
Run over the whole tree:    python3 scripts/check-no-leaks.py --all
Run over commit authorship: python3 scripts/check-no-leaks.py --authors <range>

The last one exists because file contents are not the only way a personal
address reaches a public repo. An author line is metadata, not a file, so the
content guard cannot see it.
"""
import re
import subprocess
import sys
from pathlib import Path

# Blocks the commit. Absolute home paths are also a portability bug, not just
# a disclosure one — they break the repo for everyone who is not the author.
HARD = [
    # A trailing `...` or `<placeholder>` is documentation, not a real path.
    (re.compile(r"/Users/(?!\.{2,}|<)[A-Za-z0-9._-]+"), "absolute home path — use $HOME or ~"),
    (re.compile(r"/home/(?!\.{2,}|<)[A-Za-z0-9._-]+"), "absolute home path — use $HOME or ~"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "possible API key"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}"), "Anthropic key"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), "GitHub token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "GitHub fine-grained token"),
    (re.compile(r"\bsbp_[a-f0-9]{20,}"), "Supabase token"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"), "JWT"),
]

# The three rules below are built from a list this file does NOT contain.
#
# A guard that spells out the domains it blocks, the mail domains it watches, and
# the names whose speech it refuses publishes all three to everyone who reads the
# guard. That is the failure it exists to prevent, committed by the guard itself.
#
# Put the list in `.leakrc` at the repo root (gitignored), one entry per line:
#
#     irama.org                 a private domain
#     names: Surname            someone who works on this repo
#
# or set LEAK_PRIVATE_DOMAINS / LEAK_TEAM_NAMES, comma separated. With neither
# set the rules do not run, which is correct for anyone who cloned this and has
# no such list.

def _leakrc(prefix=None):
    import os
    env = "LEAK_TEAM_NAMES" if prefix else "LEAK_PRIVATE_DOMAINS"
    raw = os.environ.get(env, "")
    rc = Path(__file__).resolve().parent.parent / ".leakrc"
    if rc.exists():
        lines = rc.read_text().splitlines()
        if prefix:
            raw += "\n" + "\n".join(l.split(":", 1)[1] for l in lines
                                     if l.strip().startswith(prefix))
        else:
            # Any `group: value` line belongs to another reader of this file
            # (check-publishable.py reads commands:, repos:, libraries:, infra:).
            # A domain never contains a colon, so this is the whole test.
            raw += "\n" + "\n".join(l for l in lines if ":" not in l.split("#")[0])
    return sorted({v.strip() for line in raw.replace(",", "\n").splitlines()
                   for v in [line.split("#")[0]] if v.strip()})


_domains = _leakrc()
if _domains:
    _alt = "|".join(re.escape(d) for d in _domains)
    # A war story that names a private app is how the inventory leaks back one
    # line at a time, so the domain blocks rather than warns.
    HARD.append((re.compile(r"\b(?:[a-z0-9-]+\.)?(?:" + _alt + r")\b", re.I),
                 "private app domain — describe it generically instead"))
    _mail = "|".join(re.escape(d.split(".")[0]) for d in _domains)
    HARD.append((re.compile(r"[A-Za-z0-9._%+-]+@(?:" + _mail + r")\.[a-z.]+"),
                 "personal email"))
    HARD.append((re.compile(r"org\.(?:" + _mail + r")\.[A-Za-z0-9._-]+"),
                 "personal launchd label"))

_names = _leakrc("names:")
if _names:
    # Working conversation is not documentation. A repo records the decision and
    # the reason for it, never a quote of the exchange that produced it.
    # Deliberately narrow: quoting a SOURCE must never be blocked, so this fires
    # only on speech attributed to someone who works on this repo.
    _quote = "[" + chr(34) + chr(0x201C) + chr(0x2018) + "']"
    HARD.append((
        re.compile(r"\b(?:" + "|".join(re.escape(n) for n in _names) + r")\b"
                   + r"[^\n" + chr(34) + r"]{0,60}?"
                   + r"(?::\s*|\bsaid\b|\basked\b|\bwrote\b|\bput it\b|\bcomplained\b)"
                   + r"[^\n]{0,20}" + _quote),
        "quoted working conversation — paraphrase the substance instead"))


# Reported for eyeballing, never blocks.
SOFT = re.compile(r"(?!)")  # nothing soft-flagged at present

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv"}


def staged_files():
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [f for f in out.splitlines() if f.strip()]


def all_files():
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f.strip()]


# The email pattern, reused for authorship. Kept as a lookup into HARD rather
# than a second copy, because two copies of a guard rule drift and the drift is
# silent.
# `None` when there is no .leakrc and no env list — a fresh clone has no private
# list to protect, so the rule does not exist. This was `next(...)` with no
# default, which raised StopIteration at import and broke the guard entirely for
# anyone but us.
EMAIL_RULE = next((p for p, label in HARD if label == "personal email"), None)


def check_authors(rev_range) -> int:
    """Refuse a push carrying a commit authored from a personal address.

    Git hands a pre-push hook the range it is about to send. Everything in that
    range gets its author and committer lines read; a noreply address passes,
    a real one does not."""
    if EMAIL_RULE is None:
        return 0                      # no private list configured, nothing to match
    try:
        out = subprocess.run(
            ["git", "log", "--format=%H%x1f%an <%ae>%x1f%cn <%ce>", rev_range],
            capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError:
        return 0                      # nothing to compare against, nothing to check
    bad = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, author, committer = line.split("\x1f")
        for role, ident in (("author", author), ("committer", committer)):
            for hit in EMAIL_RULE.findall(ident):
                bad.append((sha[:9], role, hit))
    if bad:
        print("\nBLOCKED — a commit in this push is signed with a personal address.")
        for sha, role, hit in bad:
            print(f"  {sha}  {role}: {hit}")
        print("\nThis is a public repo, and an author line is as visible as a file.")
        print("Set the identity, then rewrite the commits that carry it:")
        print("  git config --local user.email <id>+<user>@users.noreply.github.com")
        print("  git rebase -i --exec 'git commit --amend --no-edit --reset-author' <base>")
        print("\nOverride once (you are sure it is safe): git push --no-verify")
        return 1
    return 0


# ── Portability rules ────────────────────────────────────────────────────────
# A skill that only works in one folder on one machine is broken for everyone
# else, and the failure is silent: the path simply is not there. All three of
# these caught a real defect in this repo before they were written down.
PORTABILITY = [
    (re.compile(r"[~$](?:HOME)?/\.claude/skills/"),
     "hardcoded skill path — address <skill-dir>, resolved from where the skill loaded"),
]

CODE_SPAN = re.compile(r"`[^`]*`")
MD_LINK = re.compile(r"\[[^\]]*\]\((?!https?:|mailto:|#|<)([^)\s]+)\)")


def check_portability(name, path, text, hits):
    """Three checks a leak guard cannot express as one line pattern."""
    parts = set(path.parts)

    # 1. A skill must not name its own install location.
    if "skills" in parts:
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, label in PORTABILITY:
                for hit in pattern.findall(line):
                    hits.append((name, lineno, label, hit))

    # 2. A relative markdown link must point at something that exists. Ten dead
    #    links shipped in this repo pointing at a docs/ directory it never had.
    if path.suffix == ".md":
        fenced = False
        for lineno, line in enumerate(text.splitlines(), 1):
            # Code shows what a link should LOOK like; it is not a link. Skip
            # fenced and indented blocks. This trades a little coverage — a real
            # link indented four spaces under a list item goes unchecked — for no
            # false positives, because a guard that cries wolf gets switched off.
            if line.lstrip().startswith("```"):
                fenced = not fenced
                continue
            if fenced or line.startswith("    ") or line.startswith("\t"):
                continue
            # A link inside a code span is documentation OF link syntax, not a
            # link. So is anything carrying a <placeholder>, or a site-root path
            # that is served rather than stored.
            for target in MD_LINK.findall(CODE_SPAN.sub("", line)):
                rel = target.split("#", 1)[0]
                if not rel or rel.startswith("/") or "<" in target or ">" in target:
                    continue
                if not (path.parent / rel).exists():
                    hits.append((name, lineno, "dead relative link", target))


def check_shell(files, hits):
    """3. shellcheck every shell script. `bash -n` proves syntax, not correctness:
    it passed a quoting bug that word-split any path containing a space."""
    import shutil
    if not shutil.which("shellcheck"):
        return
    # A .sh extension is not a promise: this repo has a .sh file that is Python
    # and another that is zsh, neither of which shellcheck can parse. Trust the
    # shebang, so an unparseable *bash* file is still reported.
    scripts = []
    for f in files:
        if not f.endswith(".sh"):
            continue
        try:
            first = Path(f).read_text(errors="ignore").split("\n", 1)[0]
        except OSError:
            continue
        if re.search(r"\b(bash|sh|dash|ksh)\b", first):
            scripts.append(f)
    if not scripts:
        return
    out = subprocess.run(
        ["shellcheck", "--severity=warning", "--exclude=SC1090", "--format=gcc", *scripts],
        capture_output=True, text=True).stdout
    for line in out.splitlines():
        bits = line.split(":", 4)
        if len(bits) >= 5 and "warning" in bits[3] or len(bits) >= 5 and "error" in bits[3]:
            hits.append((bits[0], bits[1], "shellcheck" + bits[3], bits[4].strip()))


def selftest_no_leakrc() -> bool:
    """The guard must import and run with no .leakrc in any parent directory.

    Everyone who clones a public repo is in that state. This shipped broken: the
    email rule only exists when a private list does, and the authorship check
    looked it up with no default, so merely importing the module raised."""
    import os, tempfile, shutil
    with tempfile.TemporaryDirectory() as d:
        dst = Path(d) / "scripts"
        dst.mkdir()
        shutil.copy(Path(__file__).resolve(), dst / "check-no-leaks.py")
        env = {k: v for k, v in os.environ.items()
               if k not in ("LEAK_PRIVATE_DOMAINS", "LEAK_TEAM_NAMES")}
        r = subprocess.run([sys.executable, str(dst / "check-no-leaks.py"),
                            "--authors", "no-such-ref..no-such-ref"],
                           capture_output=True, text=True, env=env, cwd=d)
        if r.returncode != 0:
            print(f"selftest FAIL: no-.leakrc run exited {r.returncode}\n{r.stderr}")
            return False
    return True


def selftest() -> int:
    """Three rules, three known answers. Both false positives these rules shipped
    with — a link inside a code span, and a format example in a code block — are
    cases here, because that is how they came back."""
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "skills").mkdir()
        (root / "skills" / "real.md").write_text("see [it](real.md)\n")
        md = root / "skills" / "SKILL.md"
        md.write_text(
            "python3 ~/.claude/skills/x/y.py\n"          # 1 hardcoded install path
            "[live](real.md)\n"                          # 2 fine, target exists
            "[dead](nope.md)\n"                          # 3 dead link
            "`[shown](example.md)`\n"                    # 4 code span, not a link
            "```\n[fenced](example.md)\n```\n"          # 5 fenced, not a link
            "    [indented](example.md)\n"               # 6 indented, not a link
            "[site](/served/path)\n"                     # 7 site-root, not a file
            "[ph](<placeholder>.md)\n")                  # 8 placeholder
        hits = []
        check_portability("SKILL.md", md, md.read_text(), hits)
        labels = sorted(h[2] for h in hits)
        want = ["dead relative link",
                "hardcoded skill path — address <skill-dir>, resolved from where the skill loaded"]
        if labels != want:
            print(f"selftest FAIL: expected {want}, got {labels}")
            ok = False
    ok = selftest_no_leakrc() and ok
    print("selftest passed" if ok else "selftest FAILED")
    return 0 if ok else 1


# A skill in this repo is published to the world the moment it is pushed. The
# rule that keeps internal tooling out is not "remember to check" — it is a
# named allowlist, so adding a skill takes a deliberate line in a file the
# author has to write. This exists because a skill that only ever talked to
# private infrastructure sat here for weeks before anybody noticed.
PUBLIC_SKILLS = Path("skills/PUBLIC")


def approved_skills() -> set:
    if not PUBLIC_SKILLS.is_file():
        return set()
    out = set()
    for line in PUBLIC_SKILLS.read_text(errors="ignore").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line)
    return out


def check_new_skills(files, hits) -> None:
    """Refuse a skill this repo has not been told it may publish."""
    approved = approved_skills()
    seen = set()
    for name in files:
        parts = Path(name).parts
        if len(parts) < 2 or parts[0] != "skills":
            continue
        skill = parts[1]
        if skill in approved or skill in seen or skill == PUBLIC_SKILLS.name:
            continue
        seen.add(skill)
        hits.append((name, 0, "skill not approved for a public repo",
                     f"{skill} — internal tooling stays in claude-config; if it really is "
                     f"public, add '{skill}' to skills/PUBLIC and say so when you ask"))


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--authors" in sys.argv:
        i = sys.argv.index("--authors")
        rng = sys.argv[i + 1] if len(sys.argv) > i + 1 else "@{push}..HEAD"
        return check_authors(rng)

    files = all_files() if "--all" in sys.argv else staged_files()
    if not files:
        return 0

    hard_hits, soft_hits = [], []
    for name in files:
        path = Path(name)
        if not path.is_file() or SKIP_DIRS & set(path.parts):
            continue
        if path.name == "check-no-leaks.py":  # this file names the patterns
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, label in HARD:
                for hit in pattern.findall(line):
                    hard_hits.append((name, lineno, label, hit))
            for hit in SOFT.findall(line):
                soft_hits.append((name, lineno, hit))
        check_portability(name, path, text, hard_hits)

    check_shell(files, hard_hits)
    check_new_skills(files, hard_hits)

    if soft_hits:
        print(f"note: {len(soft_hits)} mention(s) of your own app domains (allowed):")
        for name, lineno, hit in soft_hits[:10]:
            print(f"  {name}:{lineno}  {hit}")
        if len(soft_hits) > 10:
            print(f"  … and {len(soft_hits) - 10} more")

    if hard_hits:
        print("\nBLOCKED — this is a public repo. Fix these before committing:")
        for name, lineno, label, hit in hard_hits:
            print(f"  {name}:{lineno}  {label}: {hit}")
        print("\nOverride once (you are sure it is safe): git commit --no-verify")
        return 1

    print(f"leak check clean — {len(files)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
