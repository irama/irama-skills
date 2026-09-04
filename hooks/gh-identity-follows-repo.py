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


def _git(cwd, *args):
    try:
        return subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return ""


def gh_accounts():
    """Every account logged into gh."""
    try:
        out = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return set()
    return set(re.findall(r"account ([A-Za-z0-9_-]+)", out))


def repo_account(cwd):
    """The account this repo should act as, or None.

    First choice is the credential helper, because that is the identity the repo
    already pushes as and is set deliberately. Failing that, fall back to the
    remote's owner when it happens to be one of the logged-in accounts -- an
    owner acting on their own repo is never the mismatch this hook exists to
    prevent, and it covers repos that predate the helper convention.
    """
    helper = _git(cwd, "config", "--local", "credential.helper")
    # e.g. !'/path/to/gh-credential-for-user.sh' peakstate-global
    if "gh-credential-for-user" in helper:
        account = helper.split()[-1].strip("'\"")
        if account:
            return account

    remote = _git(cwd, "remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]([^/]+)/", remote)
    if not m:
        return None
    owner = m.group(1)
    return owner if owner in gh_accounts() else None


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
