---
name: options
description: Lay out a crossroad in plain English — an ELI5 of what is actually being decided, then the mutually exclusive roads with benefits, risks, cost (build + run + maintenance) and reversibility. Always includes a costed "do nothing". Use when the user says "options", "what are my options", "which way should we go", replies to a `DECIDE:` item, or invokes /options.
argument-hint: "The decision to lay out options for"
---

# /options — a costed crossroad

The user is deciding, not coding. Make the decision **legible**: the real roads, what each
one costs him, and which one you would take.

**Scope: crossroads only.** Roads that exclude each other — picking one forecloses the
rest. A list of independent tasks is a *menu*, not a crossroad: that belongs in the
response's *Next steps for us* section, one line each. See CLAUDE.md § Menu vs. crossroad.

**Inherits CLAUDE.md § Next steps for us** — tag set, digit reply, one `(Recommended)`,
never pad to a count, options listed once. Not restated here. This skill adds only the
costing.

## Before writing

- **Check, don't guess.** Read the repo, the docs, the live surface, the pricing page. If
  a fact decides an option, get the fact. Never ask what the repo answers.
- **Find the real fork.** Two to four genuinely different roads. Variants of one approach
  are one option. One road plus "do nothing" is a valid answer.
- **Cost it in units he can use** — hours or sessions to build, dollars per month to run.
  State the assumption behind an estimate in half a line.

## Open with the ELI5 — mandatory, before any option

Two or three sentences, in everyday words, that say **what is actually being decided and why
it matters**. Then one plain line per road. No jargon, no numbers, no hedging. Someone who
has never seen the codebase should be able to pick after reading only this.

    **In plain terms:** The books already told the tax office what was owed for that
    quarter. Now we are copying that quarter into the app. The question is whether the app
    should treat it as a real bill to pay again, or just as a record of what happened.
    - **A) History only** — write down what happened, do not touch tax.
    - **B) Full replay** — treat it as live, and check the app reaches the same figure.
    - **C) Do nothing** — leave it in the spreadsheet.

Rules: no term the user has not used first; expand or drop every acronym; say the
consequence, not the mechanism. If it needs a clause starting "which means", the sentence
before it was too technical — rewrite it. Keep the whole block under six lines.

This is not a summary of the options below — it is the fork itself, stripped to its stakes.
The costed detail that follows is for confirming the choice, not making it.

## Per-option shape — four lines, no more

    ### 1 — Self-host on the local GPU box
    Run the converter on the local GPU box over the tailnet. On the table because it
    removes the per-page fee entirely.
    - **Get:** no page fee, no third-party egress, GPU already idle
    - **Risk:** box offline = capture lane down (medium, hours to notice)
    - **Cost:** ~4h build · $0/mo · +1 service to monitor, +1 tailnet dependency
    - **Undo:** cheap — old path stays as fallback

Opening sentence carries what it is *and* why it is on the table. `Cost:` carries build
time, running dollars, and the maintenance load in one line — new services, secrets,
crons, failure modes, and code to keep working through dependency upgrades all count.
`Undo:` is one word: cheap / awkward / one-way door.

## "Do nothing" is mandatory

Always last, always present, same four lines, even when it is obviously wrong — it is the
baseline the others are judged against. Its `Risk:` line is the one that otherwise goes
unsaid: what gets worse, how fast, and the point of no return. Never write "not viable"
and move on — say what breaks and when.

## Close with

- **Order:** ELI5 → options → comparison table → recommendation → what you need from him.
- **Comparison table** — one row per option; columns Build · Run/mo · Maintenance · Risk ·
  Undo. This carries the scanning load, so the prose above stays short.
- **Recommendation** — one option, named, ≤2 sentences, plus the single fact that would
  change your mind. "It depends" is not an answer; if torn, say which way you lean and
  what would settle it.
- **What you need from him** — only genuinely his: taste, risk appetite, budget, business
  intent, anything irreversible. Nothing you could decide yourself.

## Rules

- **Plain English, ASD-STE100.** Short sentences, active voice, one word one meaning.
  Use the project's `CONTEXT.md` ubiquitous language. Expand acronyms on first use.
- **Numbers or ranges, never adjectives.** "~4h", "$0–5/mo" — not "quick", "cheap".
- **No false balance.** One road clearly better → say so, keep the rest brief.
- **No hidden costs.** Complexity a future session must carry is a cost. Count it.
- **Deliver inline** for up to three options. Use the `html-brief` skill for 4+, for
  trade-offs needing diagrams, or when the decision needs sign-off — one file, questions
  inline (§ Detailed plans → visual HTML report).
