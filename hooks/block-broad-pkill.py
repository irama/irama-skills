#!/usr/bin/env python3
"""PreToolUse(Bash): refuse a pkill whose pattern could match half the machine.

macOS pkill stops reading options at the first pattern, so `pkill -f "next dev" -f`
treats the trailing `-f` as a second pattern. Every Chromium and Electron helper
carries flags such as `--field-trial-handle`, so that one typo sent SIGTERM to every
VS Code window and browser tab at once. This hook blocks the two shapes behind it:
more than one pattern, and a pattern under four characters.

Exit 0 = allow. Exit 2 + stderr = block, message goes to the model.
"""

import json
import re
import shlex
import sys

# pkill options that consume the next argument (BSD man page).
TAKES_VALUE = set("FGPUgjstuc")
MIN_PATTERN = 4


def patterns(argv):
    """Return pkill's patterns from argv[1:], mirroring BSD getopt."""
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            return argv[i + 1:]
        if not a.startswith("-") or a == "-":
            return argv[i:]  # first non-option: everything after is a pattern
        if a[-1] in TAKES_VALUE and not a[1:].isdigit() and len(a) == 2:
            i += 1  # `-U user` style: skip the value
        i += 1
    return []


def problem(command):
    for segment in re.split(r"&&|\|\||[;|&\n]", command):
        try:
            words = shlex.split(segment)
        except ValueError:
            continue
        while words and ("=" in words[0] or words[0] in ("sudo", "exec", "command")):
            words = words[1:]
        if not words or words[0].rsplit("/", 1)[-1] != "pkill":
            continue
        pats = patterns(words[1:])
        if len(pats) > 1:
            return f"pkill got {len(pats)} patterns {pats}. Options after the first pattern are read as patterns, so a stray `-f` matches every Chromium and VS Code process."
        if pats and len(pats[0]) < MIN_PATTERN:
            return f"pkill pattern {pats[0]!r} is under {MIN_PATTERN} characters and would match far more than intended."
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    why = problem(payload.get("tool_input", {}).get("command", ""))
    if not why:
        return 0
    print(
        f"Blocked: {why}\n"
        "Put every option before one specific pattern: pkill -f \"next dev --port 3001\".\n"
        "To free a port, kill by port instead: lsof -ti :3001 | xargs kill",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
