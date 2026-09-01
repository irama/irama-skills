---
name: prune
description: Remove merged worktree(s) and their branches, then resync the VSCode workspace file. "/prune" removes the current worktree/branch; "/prune all" removes every merged one. Refuses to remove anything unmerged or with uncommitted work. Use when the user says "prune", "clean up worktrees", "remove merged branches", "prune all", or invokes /prune.
---

Clean up worktrees and branches after they have been merged and pushed. `/prune` is guarded: it **refuses** to remove any worktree with uncommitted work or any branch not fully merged into the default branch — that is the one operation no tooling can undo. See `~/.claude/docs/multithread-workflow.md`.

> Four-verb flow: `/commit` → `/merge` → `/push` → **`/prune` / `/prune all`** (here). Run after `/push` so you only ever prune work that is safely on prod.

## Scope

- **`/prune`** — remove **the current worktree** (the cwd/worktree you invoked from) and its branch.
- **`/prune all`** — remove **every** merged worktree and branch.

## Guard (do this before removing anything)

For each candidate worktree/branch:

1. `git -C <path> status --porcelain` — if it has **uncommitted** changes, SKIP it and report "not pruned: uncommitted work at `<path>`".
2. `git branch --merged <default-branch>` — the branch must appear (fully merged). If not merged, SKIP and report "not pruned: `<branch>` not merged into `<default>`".
3. Never prune the default branch or the main checkout.

For `/prune all`, collect the skips and report them at the end — never remove an unmerged/dirty worktree just because others qualified. If `/prune` (current) targets an unmerged/dirty worktree, stop and explain rather than removing.

## Steps

1. Determine the default branch and main checkout root (`git rev-parse --path-format=absolute --git-common-dir` → parent is the main root).
2. Enumerate candidates: `git worktree list` (+ `git branch --list 'feature/*'`). For `/prune`, the single candidate is the current worktree/branch.
3. Apply the **Guard** above to each. Keep only the ones that pass.
4. For each qualifying candidate:
   a) **Stop that worktree's dev server FIRST** — `bash "$HOME/.claude/scripts/localhost-dev.sh" kill-repo <path>`. A server left running keeps writing `.next` into the directory being removed, so `git worktree remove` fails with `Directory not empty` and leaves an orphan behind (2026-08-10: sixteen of them under one project, 185 MB of pure build output, every one a deregistered worktree whose dev server outlived it). `kill-repo` matches on the process's **cwd**, so it only ever kills servers inside this worktree — never use plain `kill`, which stops every other thread's server too.
   b) `git worktree remove <path>` (add `--force` only if the sole reason is an *ignored*-file dirtiness you have confirmed is safe; never to bypass the uncommitted-work guard).
   c) **If the remove still fails on `Directory not empty`:** list what is actually left (`ls -A <path>`). Remove the directory by hand ONLY when every remaining entry is a build artefact — `.next`, `.next-*`, `.turbo`, `node_modules`, `playwright-report`, `test-results`, `coverage`. **Anything else — any source file, any `.env*`, any `.git` file — is a STOP:** report it and leave the directory alone. A `.git` file means the worktree is still registered and the uncommitted-work guard applies.
   d) `git branch -d <branch>` (safe delete — fails if unmerged, which the guard already ensured passes). If git refuses because the branch is not merged to **its own remote tracking branch** while it IS merged to the default branch, that is safe: confirm with `git merge-base --is-ancestor <branch> origin/<default>` and only then use `-D`.
   e) If the branch was pushed to origin: `git push origin --delete <branch>`.
5. **`/prune all` only — sweep orphan directories.** After the loop, list `.claude/worktrees/*` and compare against `git worktree list`. A directory that git no longer knows about is an orphan from an earlier session. Apply 4(c)'s test to each: **no `.git` file AND artefacts only → delete; anything else → leave it and report.** These are invisible to `git worktree list`, so nothing else will ever clean them up.

6. **Resync the VSCode workspace file:** run `node "$HOME/.claude/hooks/sync-worktree-workspace.mjs"` once. Raw `git worktree remove` does not fire the `ExitWorktree` hook, so without this the multi-root `<project>.code-workspace` keeps a stale root pointing at the deleted worktree.

## Report

End with: worktrees/branches removed, any skipped (with the reason — uncommitted or unmerged), orphan directories swept and how much disk that reclaimed, and confirmation the workspace file was resynced.
