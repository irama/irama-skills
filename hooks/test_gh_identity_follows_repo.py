#!/usr/bin/env python3
"""Self-check for gh-identity-follows-repo.py's command rewrite.

The hook exports the token once, at the start of a command that makes a real gh write.
It must never place the substitution anywhere else, and must leave alone commands whose
gh text is only data, or that print their environment.

Run: python3 hooks/test_gh_identity_follows_repo.py  (exits non-zero on failure)
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ghid", os.path.join(HERE, "gh-identity-follows-repo.py"))
ghid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ghid)

P = 'export GH_TOKEN="$(gh auth token --user bot)"; '

WRITES = [
    ("plain write", "gh pr create --fill"),
    ("after cd &&", "cd x && gh issue comment 1 -b hi"),
    ("after a pipe", "cat b.md | gh issue create -F -"),
    ("after an env assignment", "A=1 gh pr merge 3"),
    ("env used to run a command is not a printer", "env A=1 gh pr merge 3"),
    ("export with an assignment is not a printer", "export A=1; gh pr merge 3"),
    ("on its own line", "echo start\ngh pr ready 4"),
    ("inside a subshell", "(gh pr close 5)"),
    ("after a heredoc body", "cat > b.md <<'EOF'\nbody\nEOF\ngh pr create -F b.md"),
    ("comment with an apostrophe, then a quoted body naming gh",
     "# Post it (it's long)\ngh pr comment 5 --body \"Here's the fix; gh pr create was wrong\""),
    ("after a here-string", "cat <<< hi\ngh pr create"),
    ("indented delimiter does not end a plain heredoc", "cat <<EOF\n  EOF\nEOF\ngh pr create"),
]
LEFT_ALONE = [
    ("read-only verb", "gh pr view 3"),
    ("inside double quotes", 'echo "run gh pr create later"'),
    ("inside single quotes", "git commit -m 'gh issue close 2'"),
    ("argument to echo", "echo gh pr create"),
    ("json payload", 'printf \'{"command":"gh pr create"}\' | bash hook'),
    ("heredoc body", "cat <<EOF\ngh pr create\nEOF"),
    ("escaped quote does not end the string", 'echo "a \\" gh pr create"'),
    ("only in a comment", "# later: gh pr create\nls"),
    ("prints its environment", "gh pr create --fill && env | sort"),
    ("prints its environment with set", "gh pr create; set"),
    ("bare export", "export; gh pr create"),
    ("bare declare", "gh pr create && declare"),
    ("declare -px", "gh pr create; declare -px"),
    ("typeset -x", "typeset -x | head; gh pr create"),
    ("env -0", "env -0 | tr '\\0' '\\n'; gh pr create"),
    ("echoes the token", 'gh pr create || echo "$GH_TOKEN"'),
    ("printenv of the token", "printenv GH_TOKEN; gh pr create"),
    ("already sets a token", "GH_TOKEN=x gh pr create"),
]
CASES = [(n, c, P + c) for n, c in WRITES] + [(n, c, c) for n, c in LEFT_ALONE]


def main():
    failed = 0
    for name, cmd, want in CASES:
        got = ghid.rewrite(cmd, "bot")
        ok = got == want
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"\n     got:  {got!r}\n     want: {want!r}"))
    if failed:
        print(f"{failed} case(s) failed")
        sys.exit(1)
    print("all cases passed")


if __name__ == "__main__":
    main()
