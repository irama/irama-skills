#!/usr/bin/env python3
"""Which repos does this Bash command push, and does any push skip the gate?

Helper for require-git-hooks-before-push.sh. Reads the PreToolUse JSON on stdin and prints
one line per push:

    TARGET<TAB><dir>        a push whose repo is known; the caller checks its hooks
    UNRESOLVED<TAB><text>   a push whose repo cannot be known (a path in a variable)
    NOVERIFY                a push that switches the pre-push gate off

The command is lexed quote-aware, so text inside quotes or a heredoc is never read as a
command. This hook runs on every Bash call, so a false refusal costs more than a missed push:
anything this parser cannot follow is left alone unless it plainly pushes.
"""

import json
import os
import re
import shlex
import sys

LEAD = {"do", "then", "else", "elif", "{", "!", "time", "command", "exec", "env",
        "sudo", "nohup", "nice", "caffeinate"}
GIT = {"git", "/usr/bin/git", "/opt/homebrew/bin/git"}
SHELLS = {"bash", "sh", "zsh"}
SEPARATORS = {";", "&&", "||", "|", "&", "\n", ";;", "|&"}
TOPLEVEL = "\x00TOPLEVEL\x00"
UNKNOWN = "$\x00UNKNOWN\x00"


def strip_heredocs(cmd):
    """Drop heredoc bodies: their lines are data, never commands."""
    out, lines, i = [], cmd.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for delim in re.findall(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line):
            while i < len(lines) and lines[i].strip() != delim:
                i += 1
            i += 1  # skip the delimiter line itself
    return "\n".join(out)


def substitute(cmd):
    """Replace command substitutions before lexing, so their parentheses are not subshells."""
    cmd = re.sub(r"[\"']?\$\(\s*git\s+rev-parse\s+--show-toplevel\s*\)[\"']?", TOPLEVEL, cmd)
    cmd = re.sub(r"\$\([^()]*\)", UNKNOWN, cmd)
    return re.sub(r"`[^`]*`", UNKNOWN, cmd)


def lex(cmd):
    lexer = shlex.shlex(cmd, posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:  # unbalanced quotes: nothing reliable to read
        return []


def resolve(base, dest):
    if dest == TOPLEVEL:
        return base
    if dest == "-":
        return None
    if base is not None:
        dest = dest.replace("${PWD}", base).replace("$PWD", base)
    dest = os.path.expandvars(os.path.expanduser(dest))
    if "$" in dest:
        return None
    if os.path.isabs(dest):
        return os.path.normpath(dest)
    if base is None:
        return None
    return os.path.normpath(os.path.join(base, dest))


def plan(cmd, cwd, out):
    tokens = lex(substitute(strip_heredocs(cmd)))
    stack, eff, seg = [], cwd, []

    def flush():
        nonlocal eff
        if seg:
            eff = segment(seg, eff, out)
            seg.clear()

    for tok in tokens:
        if tok in SEPARATORS:
            flush()
        elif tok == "(":
            flush()
            stack.append(eff)
        elif tok == ")":
            flush()
            if stack:
                eff = stack.pop()
        else:
            seg.append(tok)
    flush()


def segment(toks, eff, out):
    """Handle one simple command. Returns the working directory after it runs."""
    allow_ungated = False
    while toks and (toks[0] in LEAD or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0])):
        if toks[0] == "ALLOW_UNGATED_PUSH=1":
            allow_ungated = True
        toks = toks[1:]
    if toks and toks[0] == "timeout":
        toks = toks[1:]
        while toks and toks[0].startswith("-"):
            toks = toks[1:]
        toks = toks[1:]  # the duration
    if not toks:
        return eff
    head = toks[0]
    if head == "cd":
        return resolve(eff, toks[1] if len(toks) > 1 else "~")
    if head in SHELLS and "-c" in toks[1:]:
        i = toks.index("-c")
        if i + 1 < len(toks):
            plan(toks[i + 1], eff, out)
        return eff
    if head == "xargs":
        if any(t in GIT for t in toks) and "push" in toks:
            out.append("UNRESOLVED\t" + " ".join(toks)[:160])
        return eff
    if head == "rtk":
        toks = toks[1:]
    if not toks or toks[0] not in GIT:
        return eff

    target, i, ungated = eff, 1, False
    while i < len(toks) and toks[i].startswith("-"):
        opt = toks[i]
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if opt == "-C":
            target = resolve(target, nxt)
            i += 2
        elif opt == "-c":
            if nxt.lower().startswith("core.hookspath="):
                ungated = True
            i += 2
        elif opt in ("--work-tree", "--git-dir", "--namespace"):
            if opt != "--namespace":
                target = work_tree(target, opt, nxt)
            i += 2
        elif opt.startswith(("--work-tree=", "--git-dir=")):
            name, value = opt.split("=", 1)
            target = work_tree(target, name, value)
            i += 1
        else:
            i += 1
    if i >= len(toks) or toks[i] != "push":
        return eff
    args = toks[i + 1:]
    if "--dry-run" in args or "-n" in args:
        return eff
    if "--delete" in args or "-d" in args:
        return eff  # deletion-only: no content, nothing to gate
    if (ungated or "--no-verify" in args) and not allow_ungated:
        out.append("NOVERIFY")
    elif target is None:
        out.append("UNRESOLVED\t" + " ".join(toks)[:160])
    else:
        out.append("TARGET\t" + target)
    return eff


def work_tree(base, opt, value):
    path = resolve(base, value)
    if path is None or opt == "--work-tree":
        return path
    return os.path.dirname(path) if os.path.basename(path) == ".git" else None


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    cmd = data.get("tool_input", {}).get("command", "") or ""
    if "push" not in cmd:
        return
    out = []
    plan(cmd, data.get("cwd") or os.getcwd(), out)
    print("\n".join(out))


if __name__ == "__main__":
    main()
