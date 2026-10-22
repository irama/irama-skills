#!/usr/bin/env python3
"""PreToolUse(Bash): deny a full test suite or a production build that runs without a slot.

A heavy job is a full vitest suite, `next build`, `vite build`, or a package script whose
body runs one of those. Two at once is the most this machine takes before timing tests
fail on load alone, so `heavy-job run -- <command>` makes each one wait for a slot.
The deny reason gives the exact slotted command; the agent retries once.

Also denied, always: `heavy-job record` (it marks a tree as passed) and any
`HEAVY_JOB_HELD=` assignment (it steps around the slots).

Allowed: a vitest run that names test files or a `-t` filter, anything already under
`heavy-job`, `git push` and `ci-gate.sh` (they slot themselves).

Fails open: a hook error, an unparseable command, or no heavy-job installed lets
the command run. Output: exit 0, plus a JSON `deny` on stdout when it denies.
"""

import json
import os
import re
import shlex
import sys

HJ = "~/.claude/scripts/heavy-job"
SEPARATORS = {"&&", "||", ";", "|", "&", "|&", ";;", "(", ")", "\n"}
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
SHELLS = {"bash", "sh", "zsh", "dash"}
# vitest options that take a value as the next word (so the value is not a filter).
VITEST_VALUE_OPTS = {
    "-c", "--config", "-r", "--root", "--dir", "--project", "--reporter", "--outputFile",
    "--shard", "--pool", "--environment", "--maxWorkers", "--minWorkers", "--mode",
    "--exclude", "--bail", "--retry", "--testTimeout", "--hookTimeout", "--sequence.seed",
    "--coverage.reporter", "--coverage.include", "--coverage.exclude", "--browser",
}
PM_VALUE_OPTS = {"-C", "--dir", "--filter", "-F", "--prefix", "-w", "--workspace", "--cwd"}
HEAVY_SCRIPT_NAMES = {"build", "test", "test:run", "check"}
MAX_DEPTH = 6


class Deny(Exception):
    pass


def strip_heredocs(command):
    """Drop here-document bodies: they are data, not commands."""
    out, lines, i = [], command.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for m in HEREDOC.finditer(line):
            while i < len(lines) and lines[i].strip() != m.group(2):
                i += 1
            i += 1  # the delimiter line
    return "\n".join(out)


def tokens(command):
    lex = shlex.shlex(strip_heredocs(command), posix=True, punctuation_chars="();<>|&\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    return list(lex)


def is_redirect(tok):
    return bool(tok) and set(tok) <= set("<>&") and tok not in ("&&", "&")


def segments(command):
    """Split a shell string into word lists, one per simple command."""
    seg, out, skip_next = [], [], False
    for tok in tokens(command):
        if skip_next:
            skip_next = False
            continue
        if tok in SEPARATORS:
            if seg:
                out.append(seg)
            seg = []
        elif is_redirect(tok):  # a redirection: drop it, its target, its fd
            if seg and seg[-1].isdigit():
                seg.pop()
            skip_next = True
        else:
            seg.append(tok)
    if seg:
        out.append(seg)
    return out


def base(word):
    return word.rsplit("/", 1)[-1]


def unwrap(words):
    """Strip env assignments and wrapper commands. Deny a HEAVY_JOB_HELD assignment."""
    while words:
        w = words[0]
        if ASSIGN.match(w):
            if w.startswith("HEAVY_JOB_HELD="):
                raise Deny("HEAVY_JOB_HELD")
            words = words[1:]
        elif base(w) in ("export", "declare", "typeset", "local", "readonly"):
            if any(a.startswith("HEAVY_JOB_HELD=") for a in words[1:]):
                raise Deny("HEAVY_JOB_HELD")
            return []
        elif base(w) in ("env", "nice", "nohup", "time", "command", "exec", "sudo", "npx"):
            words = words[1:]
            while words and words[0].startswith("-"):
                takes = words[0] in ("-n", "-u", "-p", "--package")
                words = words[2:] if takes else words[1:]
        elif base(w) == "timeout":
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[2:] if words[0] in ("-s", "-k") else words[1:]
            words = words[1:]  # the duration
        elif base(w) == "rtk":
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[1:]
            if words and words[0] in ("err", "test", "summary", "proxy"):
                words = words[1:]
            elif words and words[0] == "run":  # `rtk run '<cmd>'` runs it via sh -c
                return ["sh", "-c"] + words[1:]
        else:
            return words
    return words


def package_scripts(cwd):
    d = cwd
    while True:
        p = os.path.join(d, "package.json")
        if os.path.isfile(p):
            with open(p) as f:
                return json.load(f).get("scripts") or {}
        parent = os.path.dirname(d)
        if parent == d:
            return {}
        d = parent


def vitest_is_full(args, cwd):
    """args follow the `vitest` word. True when nothing narrows the run to some files."""
    if args and args[0] in ("run", "watch", "dev"):
        args = args[1:]
    elif args and not args[0].startswith("-"):
        if args[0] in ("bench", "list", "init", "related", "typecheck"):
            return False
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-t", "--testNamePattern") or a.startswith(("-t=", "--testNamePattern=")):
            return False
        if a in VITEST_VALUE_OPTS:
            i += 2
            continue
        if a.startswith("-") or a.isdigit():
            i += 1
            continue
        path = os.path.join(cwd, os.path.expanduser(a))
        if not (a.endswith("/") or os.path.isdir(path)):
            return False  # a test file or a filename filter
        i += 1
    return True


def heavy(words, cwd, depth):
    """Return 'vitest' or 'build' if this unwrapped command starts a heavy job, else None."""
    if not words or depth > MAX_DEPTH:
        return None
    cmd = base(words[0])
    if cmd == "vitest":
        return "vitest" if vitest_is_full(words[1:], cwd) else None
    if cmd in ("next", "vite") and len(words) > 1 and words[1] == "build":
        return "build"
    if cmd in SHELLS:
        for i, w in enumerate(words[1:], 1):
            if w.startswith("-") and not w.startswith("--") and "c" in w and i + 1 < len(words):
                return scan(words[i + 1], cwd, depth + 1)
        return None
    if cmd == "eval":
        return scan(" ".join(words[1:]), cwd, depth + 1)
    if cmd in ("pnpm", "npm", "yarn"):
        return package_manager(cmd, words[1:], cwd, depth)
    return None


def package_manager(pm, args, cwd, depth):
    recursive = False
    while args and args[0].startswith("-"):
        if args[0] in PM_VALUE_OPTS and len(args) > 1:
            if args[0] in ("-C", "--dir", "--prefix", "--cwd"):
                cwd = os.path.join(cwd, os.path.expanduser(args[1]))
            else:
                recursive = True  # a workspace filter
            args = args[2:]
        else:
            recursive = recursive or args[0] in ("-r", "--recursive", "-ws", "--workspaces")
            args = args[1:]
    if not args:
        return None
    if args[0] in ("exec", "dlx", "x"):
        return heavy(unwrap(args[1:]), cwd, depth + 1)
    if args[0] in ("run", "run-script"):
        args = args[1:]
    elif pm == "npm" and args[0] == "t":
        args = ["test"] + args[1:]
    if not args:
        return None
    name, extra = args[0], args[1:]
    if extra and extra[0] == "--":
        extra = extra[1:]
    scripts = package_scripts(cwd)
    if name in scripts:
        body = scripts[name]
        if extra:
            body += " " + shlex.join(extra)
        return scan(body, cwd, depth + 1)
    if recursive and name in HEAVY_SCRIPT_NAMES:
        return "build" if name in ("build", "check") else "vitest"
    if pm != "npm":  # pnpm and yarn run a bin when no script has that name
        return heavy(args, cwd, depth + 1)
    return None


def scan(command, cwd, depth=0):
    """Return the kind of the first heavy job in a shell string, or None."""
    found = None
    for seg in segments(command):
        if any(base(a) == "heavy-job" and b == "record" for a, b in zip(seg, seg[1:])):
            raise Deny("record")
        words = unwrap(seg)
        if not words:
            continue
        if base(words[0]) in ("cd", "pushd"):
            if len(words) > 1 and words[1] != "-":
                cwd = os.path.join(cwd, os.path.expanduser(words[1]))
            continue
        if base(words[0]) == "heavy-job":
            if len(words) > 1 and words[1] == "run":
                rest = words[words.index("--") + 1:] if "--" in words else words[2:]
                scan(shlex.join(rest), cwd, depth + 1)  # for its Deny only: it is slotted
            continue
        found = found or heavy(words, cwd, depth)
    return found


def suggestion(command, kind, cwd):
    toks = tokens(command)
    if toks and toks[-1] == "&":  # keep it backgrounded, outside the slot wrapper
        return suggestion(command.rstrip()[:-1], kind, cwd) + " &"
    segs = segments(command)
    if len(segs) == 1 and not any(is_redirect(t) for t in toks):
        # heavy-job execs argv without a shell, so a leading VAR=x needs `env`.
        env = ["env"] if ASSIGN.match(segs[0][0]) else []
        words = unwrap(segs[0])
        if kind == "vitest":
            # Keep RTK's compression: rewrite to `rtk vitest run <args>` when the
            # command, or the script it names, is one plain vitest call.
            args = vitest_args(words, cwd)
            if args is not None:
                lead = [w for w in segs[0][:len(segs[0]) - len(words)] if ASSIGN.match(w)]
                cmd = (["env"] + lead if lead else []) + ["rtk", "vitest", "run"] + args
                return f"{HJ} run -- " + shlex.join(cmd)
        return f"{HJ} run -- " + shlex.join(env + segs[0])
    return f"{HJ} run -- bash -c {shlex.quote(command)}"


def vitest_args(words, cwd, depth=0):
    """The args of the one vitest call this command runs, or None if it is not that simple."""
    if not words or depth > MAX_DEPTH:
        return None
    if base(words[0]) == "vitest":
        args = words[1:]
        return args[1:] if args and args[0] in ("run", "--run") else args
    if base(words[0]) in ("pnpm", "npm", "yarn"):
        args = words[1:]
        if args and args[0] in ("run", "run-script", "exec"):
            args = args[1:]
        if not args or args[0].startswith("-"):
            return None
        body = package_scripts(cwd).get(args[0])
        if body is None:
            return vitest_args(args, cwd, depth + 1)
        extra = args[1:]
        if extra and extra[0] == "--":
            extra = extra[1:]
        segs = segments(body + (" " + shlex.join(extra) if extra else ""))
        return vitest_args(unwrap(segs[0]), cwd, depth + 1) if len(segs) == 1 else None
    return None


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))


def main():
    payload = json.load(sys.stdin)
    if payload.get("tool_name") != "Bash":
        return
    if not os.path.exists(os.path.expanduser(HJ)):
        return  # no slots on this machine: run unslotted
    command = (payload.get("tool_input") or {}).get("command") or ""
    cwd = payload.get("cwd") or os.getcwd()
    try:
        kind = scan(command, cwd)
    except Deny as d:
        if str(d) == "record":
            deny("Blocked: `heavy-job record` marks a tree as passed. Only a gate script "
                 "records, after its own full run passes.")
        else:
            deny("Blocked: HEAVY_JOB_HELD is set by heavy-job inside a slot. Setting it "
                 f"yourself steps around the slots. Run `{HJ} run -- <command>` instead.")
        return
    if not kind:
        return
    what = "a full test suite" if kind == "vitest" else "a production build"
    deny(f"Blocked: this starts {what} without a heavy-job slot. At most two heavy jobs "
         f"run at once on this machine. Run this instead (it waits for a slot):\n"
         f"{suggestion(command, kind, cwd)}\n"
         "A run that names test files or a -t filter needs no slot.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail open
    sys.exit(0)
