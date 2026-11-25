---
name: prune
description: Remove merged worktree(s) and their branches, then resync the VSCode workspace file. "/prune" removes the current worktree/branch; "/prune all" removes every merged one. Refuses to remove anything unmerged or with uncommitted work. Use when the user says "prune", "clean up worktrees", "remove merged branches", "prune all", or invokes /prune.
---

Clean up worktrees and branches after they have been merged and pushed. `/prune` is guarded: it **refuses** to remove any worktree with uncommitted work or any branch not fully merged into the default branch — that is the one operation no tooling can undo. See `~/.claude/docs/multithread-workflow.md`.

> Four-verb flow: `/commit` → `/merge` → `/push` → **`/prune` / `/prune all`** (here). Run after `/push` so you only ever prune work that is safely on prod.

## Scope

- **`/prune`** — remove **the current worktree** (the cwd/worktree you invoked from) and its branch.
- **`/prune all`** — remove **every** merged worktree and branch in each repo the job touched (this thread plus any thread earlier in its handoff chain). Never in a repo the job did not touch. The flush skill defines the scope.

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
   **Orca-managed worktree** (`orca worktree show --worktree path:<path> --json` returns `"ok": true`): replace b) to d) with `orca worktree rm --worktree path:<path> --delete-branch --json`. Orca deletes the folder and the branch and stops that worktree's chats itself, so their cards close cleanly. Never remove an Orca worktree with `git worktree remove`: the chat process outlives its folder, and Orca shows the thread as Failed with no way to open it. `--delete-branch` keeps any branch Orca cannot prove merged; a later `/prune all` deletes it under d). **If the path is the worktree this thread runs in, do not remove it here.** Leave it for step 8.
   b) `git worktree remove <path>` (add `--force` only if the sole reason is an *ignored*-file dirtiness you have confirmed is safe; never to bypass the uncommitted-work guard).
   c) **If the remove still fails on `Directory not empty`:** list what is actually left (`ls -A <path>`). Remove the directory by hand ONLY when every remaining entry is a build artefact — `.next`, `.next-*`, `.turbo`, `node_modules`, `playwright-report`, `test-results`, `coverage`. **Anything else — any source file, any `.env*`, any `.git` file — is a STOP:** report it and leave the directory alone. **One exception: an `.env*` file that `cmp` shows is byte-identical to the same file in the main checkout counts as an artefact.** Worktrees get a copy of the main checkout's `.env.local`, so that copy loses nothing when deleted. Without this exception every orphan holding only that copy is skipped on every run and stays in the editor's Source Control list indefinitely. Delete it by its full literal path. A copy that differs from the main checkout's file is a STOP. A `.git` file means the worktree is still registered and the uncommitted-work guard applies.
   d) `git branch -d <branch>` (safe delete — fails if unmerged, which the guard already ensured passes). If git refuses because the branch is not merged to **its own remote tracking branch** while it IS merged to the default branch, that is safe: confirm with `git merge-base --is-ancestor <branch> origin/<default>` and only then use `-D`.
   e) `rmdir "$(dirname <path>)" 2>/dev/null || true`. This deletes the worktree's parent folder (for example `~/LOCAL-DEV/<repo>-wt/`) only when it is now empty, so pruned runs leave no empty folders behind. It never deletes a folder with anything left in it.
   e) If the branch was pushed to origin: `git push origin --delete <branch>`.
5. **`/prune all` only — sweep orphan directories.** After the loop, list `.claude/worktrees/*` and compare against `git worktree list`. A directory that git no longer knows about is an orphan from an earlier session. Apply 4(c)'s test to each: **no `.git` file AND artefacts only → delete; anything else → leave it and report.** These are invisible to `git worktree list`, so nothing else will ever clean them up.

6. **Resync the VSCode workspace file:** run `node "$HOME/.claude/hooks/sync-worktree-workspace.mjs"` once. Raw `git worktree remove` does not fire the `ExitWorktree` hook, so without this the multi-root `<project>.code-workspace` keeps a stale root pointing at the deleted worktree.

7. **Write and deliver the closing note. Every `/prune` does this, inside Orca or not.** The closing note is the thread's formal end: a short brief that tells Andrew, weeks later and with no memory of the thread, what was asked, what was done and what is left.
   a) Copy `<skill-dir>/closing-template.md` to `~/.claude/closings/<yyyy-mm-dd>-<slug>.md`, where `<slug>` names the app and the change. Fill it in and delete its rules comment. That folder is outside every worktree, so the note survives the prune.
   b) Sections, all plain English, each one readable on its own: **What you asked for** (two or three sentences), **What was done** (bullets: each change, every repo touched with its commits and whether they are merged or pushed, what was deployed and the SHA production serves, and where the results are), **Next steps for you** (numbered steps, one action each, with any command in its own `:::draft` box so it has a copy button), **Next steps for us** (optional: only steps that truly add value, each a command for a new Claude thread that names its repo and carries the closing note's absolute path). With nothing left, write "Nothing. This work is finished." under the heading instead of an empty list.
   c) Build it with the peakstate-brief skill's builder: `node <peakstate-brief-dir>/assets/build-brief.mjs <note>.md`, where `<peakstate-brief-dir>` is the folder that skill loads from.
   d) Deliver it: start `brief-deliver <note>.html` as a background command. Agent X shows it as a **Thread done** bubble, because the file sits in `~/.claude/closings/`.
   e) The chat reply carries the same content, and nothing in it repeats the note's commands a second time outside it. If the thread's own worktree is Orca-managed and passed the guard, offer no next step in this thread: step 8 closes the chat.

8. **Orca only: remove this thread's own worktree, as the very last tool call.** If the thread's own worktree is a candidate, is Orca-managed and passed the guard, run `bash "$HOME/.claude/scripts/localhost-dev.sh" kill-repo <path>`, then `git push origin --delete <branch>` if the branch was pushed, then `orca worktree rm --worktree path:<path> --delete-branch --json`. Orca closes this chat with the record "closed by Orca", and the card leaves the sidebar (tested 2026-11-25). The closing note's Thread done bubble stays in Agent X as the reminder. Nothing runs after this command. The transcript stays on disk under `~/.claude/projects/`.

## Report

The closing note is the report. Add to the chat reply only the mechanics: worktrees and branches removed, any skipped (with the reason: uncommitted or unmerged), orphan directories swept and the disk reclaimed, the workspace file resynced, and, under Orca, that this thread's own worktree is removed next and its card closes.
