---
name: commit
description: Stage, gate, and commit the current changes; push the feature branch if on one. Use when the user says "commit", "commit and push my branch", or invokes /commit. Never pushes the default branch — that is /push. (Formerly /git.)
---

Commit the current repo's changes and, when on a feature branch, push **that branch only**. `/commit` **never** pushes the default branch and never applies migrations — deploying `main` is `/push`, merging is `/merge`. This keeps every `/commit` fully reversible until you `/push`. See [~/.claude/docs/multithread-workflow.md](../../docs/multithread-workflow.md).

> Part of the four-verb multi-thread flow: **`/commit`** (here) → `/merge` (branch → local main) → `/push` (deploy main) → `/prune` (clean up worktrees). `/commit` replaces the old `/git`.

**Standing rule — stop at the branch.** Committing is the default terminal state of a task; `/merge` and `/push` are separate, explicitly-requested steps. Never chain into merging to `main` or pushing the default branch after a `/commit` (or after any "go"/"build it" instruction) unless the user asked for that step by name. When done, report the branch is committed (and the dev server is up for testing) and offer `/merge` + `/push` as options — do not run them. This holds on green gates and trivial diffs.

## Confirm the target repo and mode first

`git` operates on the repo whose `.git/` contains the cwd. Before staging, in parallel: `git rev-parse --show-toplevel`, `git remote get-url origin`, `git rev-parse --abbrev-ref HEAD`. Then:

- **Branch mode** — HEAD is a feature branch (not the default branch), typically inside a worktree under `.claude/worktrees/`. Commit + push **this branch**.
- **Trunk mode** — normal checkout on the default branch. Commit **only**; do NOT push (deploying the default branch is `/push`). Tell the user to run `/push` when ready to deploy.

State repo, remote, branch, and mode back in one sentence before proceeding, so a wrong-repo/wrong-mode mistake is caught early. If asked to commit work in a *different* repo than the cwd, stop and tell the user — do not `cd` and commit on their behalf.

## Steps

1. `git status` and `git diff` (staged + unstaged) in parallel to see what changed.
2. `git log -5 --oneline` to match the repo's commit style.
3. **If the diff touches UI** (components, pages, styles, canvas/shape code, any rendered surface) → run `/verify-ui` first; do not commit until it passes. Skip only for non-UI diffs.
4. Stage. Default `git add -A` — the repo's `.gitignore` is the safety net. Stage by name only when: unrelated changes should not be in this commit, the user asked for a partial commit, or a tracked file looks sensitive (e.g. a committed `.env` — stop and flag instead of committing).
5. Typecheck + tests + lint if the project has them. Stop on failure and fix before committing — never commit a red tree.
   - **UI/render diffs also need a browser run.** If the diff touches a rendered surface AND the project has a browser/e2e tier (Playwright, Cypress), run it — typecheck + unit tests do NOT catch render-time crashes (Rules-of-Hooks / React #310, bad context reads, effect throws) that only surface when a real browser mounts the component. Stop on failure and fix first.
6. Write a concise Conventional-Commits message focused on *why*. End with:

       Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
7. Commit, then:
   - **Branch mode:** `git push -u origin <this-branch>`. Never the default branch. Tell the user the branch is shipped and ready for `/merge`.
   - **Trunk mode:** do not push. Remind the user that `/push` deploys.
8. Confirm with a final `git status`.

If there is nothing to commit, say so — do not create an empty commit.

## Auth

If `git push` prompts for credentials, the credential helper is missing or expired. Don't paste tokens into commands. Tell the user to push once interactively to seed the credential store (Keychain on macOS), or rotate their PAT. Per-repo identity routing: [~/.claude/docs/git-auth-per-repo-routing.md](../../docs/git-auth-per-repo-routing.md).
