#!/usr/bin/env python3
"""PreToolUse(Bash): make `gh issue`/`gh pr` writes act as the repo's own identity.

`gh` has no per-repo account setting and ignores the repo-local credential
helper, so it always acts as the globally active account. When the repo pushes
as a bot but `gh issue create` posts as the human, GitHub sees two different
accounts on one thread and emails the human about the bot's activity.

Acting as one identity removes the notification at source: GitHub never notifies
an account about its own actions. That is the whole fix -- clearing the
subscription afterwards cannot match it, because the first notification is
already sent before any thread id exists to clear.

Rewrites `gh issue create ...` into
`GH_TOKEN="$(gh auth token --user <acct>)" gh issue create ...`.
Read-only subcommands are left alone; they work fine under any account.
"""

import json
import re
import subprocess
import sys

# Subcommands that create or change a thread, and so create a subscription.
WRITE_VERBS = (
    "create|comment|close|reopen|edit|delete|lock|unlock|pin|unpin|"
    "transfer|reopen|merge|ready|review"
)
GH_WRITE = re.compile(r"\bgh\s+(issue|pr)\s+(" + WRITE_VERBS + r")\b")


def repo_account(cwd):
    """The account named by the repo's credential helper, or None."""
    try:
        helper = subprocess.run(
            ["git", "-C", cwd, "config", "--local", "credential.helper"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return None
    # e.g. !'/path/to/gh-credential-for-user.sh' peakstate-global
    if "gh-credential-for-user" not in helper:
        return None
    account = helper.split()[-1].strip("'\"")
    return account or None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") or ""
    cwd = payload.get("cwd") or "."

    if not GH_WRITE.search(command) or "GH_TOKEN=" in command:
        return

    account = repo_account(cwd)
    if not account:
        return

    # ponytail: verify the token resolves rather than risk exporting an empty
    # GH_TOKEN, which gh treats as a hard auth failure rather than falling back.
    probe = subprocess.run(
        ["gh", "auth", "token", "--user", account],
        capture_output=True, text=True, timeout=10,
    )
    if probe.returncode != 0 or not probe.stdout.strip():
        return

    prefix = 'GH_TOKEN="$(gh auth token --user %s)" ' % account
    updated = GH_WRITE.sub(lambda m: prefix + m.group(0), command, count=1)
    if updated == command:
        return

    new_input = dict(tool_input, command=updated)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": new_input,
            "systemMessage": "gh write routed through the repo's identity (%s)." % account,
        }
    }))


if __name__ == "__main__":
    main()
