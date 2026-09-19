---
description: Codex code review of the current changes via the local Codex CLI (codex exec review). Read-only second-model review over your ChatGPT-subscription auth. Defaults to uncommitted changes; --base <ref> reviews a branch.
argument-hint: '[--uncommitted | --base <ref> | --commit <sha>] [extra focus instructions…]'
allowed-tools: Bash(codex:*), Bash(codex-review-env:*), Bash(git:*)
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

**Model routing.** Run the review through `codex-review-env`, a thin exec wrapper beside
`codex-auto`/`codex-as` on PATH, instead of calling `codex` directly. It reads
`~/.config/models-route/review.env` per call and inserts its
model/effort after the `exec review` words. A missing file, or one with no `REVIEW_MODEL`,
leaves the argv byte-identical to calling `codex` directly.

Run (foreground, generous timeout — a review can take a minute or two):

    codex-review-env exec review --uncommitted 2>&1
    # or, with custom instructions on the default scope:
    codex-review-env exec review "<focus instructions>" 2>&1

No `codex-review-env` on PATH? Call `codex` exactly as before, with no routing flags; the review then runs on the default model.

**If the diff contains a brief or report** (a rendered brief html, a `docs/plans/` document,
or a `.md` with a brief id in its front matter), run one extra prompt-only pass over that
document asking three questions: does the top of the document state what the body proves, is
any `Recommended` option consistent with the document's own disclosures, and does every
decision question state cost, benefit and likelihood in its own text. Report a failure on any
of the three as a P2 finding. A scope flag and prompt text cannot be combined, so this is a
separate call, and it carries into the `adversarial-reviewer` prompt when that reviewer runs
instead.

Model/effort come from `~/.codex/config.toml` — the account's own default model
(deliberately unset since 2026-08-24, when named models were rejected on a
ChatGPT account) at `high` effort, unless `~/.config/models-route/review.env`
names a `REVIEW_MODEL`, in which case that model (and `REVIEW_EFFORT`, if set)
wins per the flags above. Do not override either by hand.

Return Codex's stdout verbatim. On non-zero exit or an `ERROR`/auth/model
rejection in the output, surface the full output + exit code and state the review
failed — do not pretend it passed. Then run the `adversarial-reviewer` subagent (Opus)
over the same diff. That completes the gate: name the reviewer once and never offer a
Codex re-run later.
