---
name: threads
description: See every Claude Code session running on this machine, what work each one holds, and which have gone quiet — then release a stalled thread's claims, or end it. Reads the cross-thread work register that sessions claim shipping verbs and work items in. Use when the user says "threads", "what else is running", "who has the push", "what is thread X doing", "clear that thread", "kill that thread", when a shipping verb was refused because another thread holds it, or when they invoke /threads.
argument-hint: "nothing, or a thread name, or: clear <name> / kill <name>"
---

# /threads — who is doing what, and who has stopped

Twenty sessions run at once and none of them can see the others. The register at
`~/.claude/state/work-register.jsonl` is the shared store they claim work in. This
skill reports it and, when asked, releases or ends a thread.

Every verb below is already implemented in `assets/register.py`. Run that script;
do not reimplement any of it, and do not read the register file by hand.

> **Paths.** `<skill-dir>` means the folder holding this SKILL.md — resolve it from
> wherever the skill was loaded, never a hardcoded home path. This skill installs as
> a plugin, as a project `.claude/skills/` folder, and on Windows, so its location
> varies.

**The one rule that is not in the script: ask, never resurrect.** Nothing here may
restart, resume, re-prompt or message a stalled thread. Report what it holds and
what it looks like, then let the user decide. A thread that has gone quiet may be
mid-thought, waiting on a build, or waiting on the user.

## `/threads` — list

```bash
python3 <skill-dir>/assets/register.py list
```

Prints every live thread: its status, how many minutes it has been quiet, the
directory it is working in, and each item it holds. Stalled threads are named
again at the end, because those are the ones worth acting on.

Add `--json` when you need to reason over the output rather than show it.

Read it back in one or two sentences — which threads matter, and what is stuck.
Do not paste the whole table and stop there.

## `/threads <name>` — inspect one

```bash
python3 <skill-dir>/assets/register.py show <name>
```

Takes a thread name, the first characters of a session id, or a full session id.
Prints when it started, its directory, its process and whether that process is
alive, its quiet time, and everything it holds.

## `/threads clear <name>` — release its work

```bash
python3 <skill-dir>/assets/register.py clear <name>
```

Releases every claim the thread holds, as `incomplete`, so another thread may take
them. **It does not touch the process.** The session keeps running and its window
is untouched — say that plainly, because the user will otherwise assume `clear`
ended something.

This is the right answer almost every time. Offer it first.

## `/threads kill <name>` — end the process

```bash
python3 <skill-dir>/assets/register.py kill <name>          # refuses, explains
python3 <skill-dir>/assets/register.py kill <name> --yes    # actually ends it
```

Sends the thread's process a terminate signal, after releasing its claims.

**Never run this without `--yes` having been asked for in words, and never propose
it as the first option.** An interactive session may hold uncommitted work that
exists nowhere else, and ending it cannot be undone. Run the bare form first, show
the user what it says, and wait. `clear` is what they usually want.

## Two status vocabularies, and why they are separate

A **work status** is what happened to the job. A thread writes it at sign-off.

| Work status | Means | Can another thread take it? |
|---|---|---|
| `claimed`, `in-progress` | Taken, not yet signed off | No |
| `blocked` | Stopped on something outside this thread | No — still owned |
| `waiting-on-user` | Stopped on an answer only the user can give | No — still owned |
| `incomplete` | Stopped part-way and handed back | Yes |
| `abandoned` | Deliberately dropped | Yes |
| `done` | Finished | Finished |
| `handed-off` | Written up for another thread to pick up | Finished |

A **thread status** is what happened to the session. It is derived from the
process and the transcript's quiet time, never written by hand.

| Thread status | Means |
|---|---|
| `live` | The process is running and wrote something in the last 15 minutes |
| `idle` | Running, quiet 15–90 minutes, holding nothing that matters |
| `stalled` | Running, quiet over 90 minutes, still holding work |
| `dead` | The process is gone. Its claims release automatically on the next read |

They are separate because a frozen thread cannot report that it has frozen. The
work status is a claim the thread makes; the thread status is an observation about
the thread. A thread can be `live` and holding `blocked` work, or `stalled` while
holding something it believes is `in-progress` — and it is that second combination
this skill exists to surface.

## The hooks that fill it

Three hooks write the register, all in this repo's `hooks/`:
`thread-register-identity.py` (`SessionStart`) records a thread,
`thread-register-signoff.py` (`Stop`) makes it sign off open work before the turn
ends, and `thread-register-gate.py` (`PreToolUse`/`PostToolUse` on Bash) refuses
`git push` or `git merge` on a repo another live thread has claimed.

If `/threads` lists nothing, those hooks are not wired. See `settings.example.json`.
