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

Rewrites a command that contains `gh issue create ...` into
`export GH_TOKEN="$(gh auth token --user <acct>)"; <the command unchanged>`.
Commands with only read-only gh subcommands are left alone.

The export goes at the very start and nowhere else. The earlier version inserted
the prefix beside each match, and wherever a match sat inside a string (a double
quoted body, an echo argument, a heredoc) the shell expanded the substitution
without running gh and printed the live token into the output. Position zero can
never be inside a quote, so a mis-scan now costs at most a needless export. A
command that prints its environment (env, printenv, set) is never rewritten.
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


# Words that may sit between a separator and the command they run.
COMMAND_LEAD = re.compile(
    r"\s*(?:(?:[A-Za-z_][A-Za-z0-9_]*=\S*|then|do|else|sudo|command|exec|env)\s+)*"
)


def _scan(cmd):
    """Mark quoted or heredoc characters, and list unquoted separator positions."""
    n = len(cmd)
    quoted = [False] * n
    seps = []
    pending = []  # heredoc delimiters opened on the current line
    quote = None
    i = 0
    while i < n:
        c = cmd[i]
        if quote == "'":
            quoted[i] = True
            if c == "'":
                quote = None
        elif quote == '"':
            quoted[i] = True
            if c == "\\" and i + 1 < n:
                quoted[i + 1] = True
                i += 2
                continue
            if c == '"':
                quote = None
        elif c == "\\" and i + 1 < n:
            quoted[i] = quoted[i + 1] = True
            i += 2
            continue
        elif c in "'\"":
            quote = c
            quoted[i] = True
        elif c == "#" and (i == 0 or cmd[i - 1] in " \t\n;&|("):
            end = cmd.find("\n", i)
            end = n if end < 0 else end
            for k in range(i, end):
                quoted[k] = True
            i = end
            continue
        elif c == "<" and cmd.startswith("<<<", i):
            i += 3
            continue
        elif c == "<":
            m = re.match(r"<<(-?)\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", cmd[i:])
            if m:
                pending.append((m.group(2), m.group(1) == "-"))
                i += m.end()
                continue
        elif c in ";&|(\n":
            seps.append(i)
            if c == "\n" and pending:
                j = i + 1
                for delim, tabs in pending:
                    while j < n:
                        end = cmd.find("\n", j)
                        end = n if end < 0 else end
                        for k in range(j, end):
                            quoted[k] = True
                        line, j = cmd[j:end], end + 1
                        if (line.lstrip("\t") if tabs else line) == delim:
                            break
                pending = []
                seps.append(j - 1)
                i = j
                continue
        i += 1
    return quoted, seps


# Commands that would print the exported token. The export reaches every process in the
# command, not only gh: accepted, because scoping it to gh means inserting it mid-command,
# which is the leak this hook was rewritten to remove.
PRINTS_ENV = re.compile(
    r"(^|[\s;&|(])(printenv|set|(?:env|export|declare|typeset)(?:\s+-\w+)*)(?=\s*($|[;&|)\n]))"
    r"|GH_TOKEN"
)


def has_gh_write(command):
    """True when an unquoted gh write sits in command position."""
    quoted, seps = _scan(command)
    for m in GH_WRITE.finditer(command):
        start = m.start()
        if quoted[start]:
            continue
        prev = max((s for s in seps if s < start), default=-1)
        if COMMAND_LEAD.fullmatch(command[prev + 1:start]):
            return True
    return False


def rewrite(command, account):
    """Export the account's token at the start of a command that makes a gh write."""
    if not has_gh_write(command) or PRINTS_ENV.search(command):
        return command
    return 'export GH_TOKEN="$(gh auth token --user %s)"; %s' % (account, command)


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
    try:
        probe = subprocess.run(
            ["gh", "auth", "token", "--user", account],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return
    if probe.returncode != 0 or not probe.stdout.strip():
        return

    updated = rewrite(command, account)
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
