---
description: Adversarial Codex review of a PLAN or design (not code) via the local Codex CLI. Read-only second-model challenge — pressure-tests the approach, assumptions, tradeoffs, and failure modes before you build. Use when a plan is agreed but not yet implemented.
argument-hint: '[plan text, or path to a plan file — defaults to the current in-context plan]'
allowed-tools: Bash(codex:*), Bash(git:*), Read
---

Get an independent second model to CHALLENGE the current plan before building.
This reviews a PLAN/design, not a diff. Read-only — Codex applies nothing; you
evaluate its challenge and decide. You hold the plan; Codex's verdict is input,
not law.

Plan source (`$ARGUMENTS`):
- A file path → use its contents.
- Plan text → use it.
- Empty → use the plan you (the orchestrator) currently hold in context; write it
  out in full first.

Steps:

1. Build one temp file containing the adversarial framing followed by the full
   plan (write it out completely — Codex has no other view of your plan):

       F="$(mktemp)"
       cat > "$F" <<'EOF'
       Adversarially review the PLAN below. Do NOT restate it. Challenge the
       chosen approach, the assumptions it depends on, the tradeoffs, and where
       it fails under real-world conditions — scale, concurrency, edge cases,
       ops/rollback, security, data loss. Name concrete failure modes and any
       simpler or safer alternative. Be specific and skeptical; if the plan is
       sound, say precisely what would make it fail. End with a one-line verdict:
       GO / GO-WITH-CHANGES / RETHINK.

       --- PLAN ---
       <paste the full plan here>
       EOF

2. Run read-only, with the repo as context (generous timeout — a minute or two):

       codex exec --color never -s read-only --skip-git-repo-check \
         -C "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" - < "$F" 2>&1

3. Return Codex's output verbatim. Then briefly state which challenges you accept
   and how the plan changes — do not auto-apply Codex's suggestions.

Model/effort from `~/.codex/config.toml` (gpt-5.6-sol / high). On non-zero exit or
an `ERROR`/auth/model rejection, surface the full output + exit code and say the
review failed — do not pretend it passed.
