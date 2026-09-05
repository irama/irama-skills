---
description: Codex code review of the current changes via the local Codex CLI (codex exec review). Read-only second-model review over your ChatGPT-subscription auth. Defaults to uncommitted changes; --base <ref> reviews a branch.
argument-hint: '[--uncommitted | --base <ref> | --commit <sha>] [extra focus instructions…]'
allowed-tools: Bash(codex:*), Bash(git:*)
---

Run an independent Codex code review of the current repository and return its
output verbatim. Review-only: do NOT fix anything, apply patches, or say you are
about to make changes.

Raw arguments: `$ARGUMENTS`

Scope and focus text are MUTUALLY EXCLUSIVE in `codex exec review` — a scope flag
cannot be combined with prompt text, and `--color` is NOT accepted here (unlike
plain `codex exec`). Pick one form:
- Scope flag present (`--uncommitted`, `--base <ref>`, or `--commit <sha>`) → run
  it ALONE; drop any focus text the user also typed.
- Focus text only (no scope flag) → pass it as the prompt (reviews Codex's
  default scope with those instructions).
- Neither → default to `--uncommitted` (staged + unstaged + untracked). First
  confirm there is something to review with `git status --short --untracked-files=all`;
  if empty, say so and stop.

Run (foreground, generous timeout — a review can take a minute or two):

    codex exec review --uncommitted 2>&1
    # or, with custom instructions on the default scope:
    codex exec review "<focus instructions>" 2>&1

Model/effort come from `~/.codex/config.toml` — the account's own default model
(deliberately unset since 2026-08-24, when named models were rejected on a
ChatGPT account) at `high` effort. Do not override.

Return Codex's stdout verbatim. On non-zero exit or an `ERROR`/auth/model
rejection in the output, surface the full output + exit code and state the review
failed — do not pretend it passed.
