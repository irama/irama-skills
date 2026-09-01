---
name: flush
description: Run the whole shipping pipeline end-to-end — /commit, /merge, /push, /prune — skipping the steps that don't apply. Use when the user says "flush", "ship it all", "take it all the way to prod", or invokes /flush. Pushes prod, so it is only ever user-invoked.
---

Flush the current work all the way out: **`/commit` → `/merge` → `/push` → `/prune`**, running only the verbs that are relevant to the repo's actual state. It is exactly the four-verb flow from `~/.claude/docs/multithread-workflow.md`, invoked in one word instead of four turns.

**Invoking `/flush` IS the explicit request for every verb in it — including `/push`.** That is the whole point of the verb, so it does not re-ask for permission to merge or deploy. This is the one place where the standing "never merge or push without being asked" rule is already satisfied up-front: the user asked, by name, for the pipeline. Nothing else — not "go", not "ship it", not a green gate — expands into a `/flush`.

## Read the state first, then pick the verbs

Do NOT run all four blindly. Establish state before touching anything, in parallel:

    git rev-parse --show-toplevel
    git rev-parse --abbrev-ref HEAD
    git status --short
    git log --oneline @{u}..HEAD
    git worktree list
    git branch -vv

Then include each verb only if it has work to do:

| Verb | Include when | Skip when |
|---|---|---|
| `/commit` | working tree is dirty | tree is clean — say "nothing to commit", don't fake an empty commit |
| `/merge` | HEAD is a feature branch, or unmerged local feature branches exist | already on the default branch with no feature branches |
| `/push` | local default branch is ahead of its remote | nothing ahead — say so |
| `/prune` | merged worktrees/branches exist | no worktrees beyond the main checkout |

**Say which verbs you're running and which you're skipping, and why, before the first mutation.** A `/flush` on a clean trunk with nothing ahead should do nothing and report that — not manufacture work.

## Running the verbs

Invoke each applicable skill and follow it in full — `/flush` is a conductor, not a reimplementation. Do not inline a shortcut version of any verb; their gates exist for a reason.

Order is fixed and non-negotiable: **commit → merge → push → prune**. Each step's output is the next step's input, and `/push` must run against a `main` that already has the branches merged into it.

**Stop the pipeline at the first failure.** A red gate, a merge conflict, a failed migration, a build error — halt, report where it stopped and why, and leave the remaining verbs unrun. A half-flushed repo is recoverable; a force-pushed one is not. Never work around a gate to keep the chain moving.

## Hard rules inherited from the verbs

These come from the underlying skills and `/flush` does not soften any of them:

- **`/push` owns the migration gate.** Migrations hit the prod DB *before* the push that triggers the deploy. If the diff touches migrations or schema, `/push` applies them first — no exceptions.
- **UI diffs need `/verify-ui`** before the commit lands, and a browser/e2e run if the project has that tier. Typecheck and unit tests do not catch render-time crashes.
- **Never force-push, never rewrite shared history.** If `/push` would need either, stop and ask.
- **A sensitive tracked file in the diff (a committed `.env`, a key) halts the flush.** Flag it; do not commit it.
- **One repo.** `/flush` acts on the repo containing the cwd. If the user meant a different repo, stop and say so rather than `cd`-ing on their behalf.

## Report

Finish with a one-line-per-verb read-out — what ran, what it did, what was skipped:

    /commit  → 3 files, feat(x): …
    /merge   → skipped (already on main, no feature branches)
    /push    → 7546fe8 → origin/main, no migrations, deploy green
    /prune   → skipped (no worktrees)

Then the deploy's actual state — confirmed live, or still building, or failed. Never report a deploy as done on the strength of the push alone.
