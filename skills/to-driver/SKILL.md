---
name: to-driver
description: Take a rough idea all the way to a paste-ready /driver command — grill it into decisions, write the spec and ADR, run an adversarial plan review, cut the tickets, hand back the invocation. Use when the user says "to driver", "/to-driver", "get this ready for driver", or wants an idea turned into buildable tickets end to end.
argument-hint: "the idea, feature or plan to take to tickets — e.g. `/to-driver a /council page with three arguing personas`"
disable-model-invocation: true
---

# /to-driver

The phase chain from `~/.claude/CLAUDE.md` § "How I work — phases", compressed into one verb:

    assess → /grill-with-docs → write-up → adversarial review → /to-tickets → the /driver command

It ends by **handing back** the `/driver` invocation. It does **not** run it — `/driver` is
expensive and user-triggered, and that boundary is the point.

## Explore before you coalesce — three optional front doors

Step 1 may conclude the idea is not ready to be grilled into a spec. Say so, name the door,
and run it before step 2 — a little more exploration up front is cheaper than tickets built
on an unproven design:

- **`/wayfinder`** — the work is huge and foggy, spanning many sessions. Wayfind first, then
  run `/to-driver` per leg rather than trying to spec the whole thing at once.
- **`/prototype`** — the design is unproven. Build the crude end-to-end version, look at it,
  *then* grill. Skipping this on an unproven design is a flag, not a shortcut.
- **`/impeccable`** — there is a UI surface. Shape the interface before the prototype, so the
  prototype tests a considered design rather than the first one that occurred to you.

These are exploration, not gates: pick at most the ones that apply, say which and why in one
line, and skip all three when the design is already settled.

## This is a conductor, not a fire-and-forget

It runs the verbs in order and **stops at every human gate**, exactly like `/flush`. Two gates are
non-negotiable, because automating them produces tickets built on unexamined assumptions, which is
worse than no tickets:

1. **The grilling.** Every question goes to the user, one at a time, and waits. Decisions are
   theirs; only *facts* are looked up.
2. **The ticket breakdown.** `/to-tickets`' own approval step runs in full.

Do not "save the user time" by answering either gate yourself.

## Process

### 1. Assess — show the working, don't judge silently

Before anything, say what is already decided and what is not:

    Decided already: A, B, C
    Still open: D, E
    → grill those two first, or go straight to the write-up?

Wait for the answer. If the conversation already contains enough agreed context — a long design
discussion, a `/grill-with-docs` run earlier in the thread — skip to step 3 and say so. If the ask
is one sentence with no context, step 2 is not optional.

**Never claim there is enough context in order to skip the interview.** An unexamined assumption
survives all the way into a built feature.

### 2. Grill (`/grill-with-docs`)

Invoke the `grilling` skill. One question at a time, each with a recommended answer, each waiting
for a reply. Look up every fact in the repo rather than asking. Walk the design tree in dependency
order — the answer to one question usually changes which question comes next.

Track decisions as they land; do **not** write files mid-interview. Batch the writing into step 3
so the docs are coherent rather than a churn of half-decisions.

### 3. Write it up

Per the repo's conventions (`/setup-matt-pocock-skills`, or the global default: `CONTEXT.md` at
the repo root, ADRs in `docs/adr/`):

- **The spec** — the buildable document. Include an explicit **"what this does NOT include"**
  section; it is the cheapest way to stop a ticket agent inventing scope.
- **An ADR** for any decision a future reader would otherwise re-litigate, with the rejected
  alternatives and *why* they lost.
- **`CONTEXT.md`** — domain language. If it already has a section on this, **update it in place**
  rather than adding a second one.

Remember these are *outputs*. When a doc conflicts with what the user is asking for, the doc
drifted — never quote one back at them as their own remembered decision.

### 4. Adversarial plan review — before decomposition, not after

Run `/codex-plan-review` on the **spec**. This is the last moment changing the approach is free.

**If Codex is unavailable** — usage limit, auth, offline, or it dies mid-review — fall back to the
`adversarial-reviewer` subagent and **say which one actually ran**. A gate that could not run is
not a pass, and a fallback review shares the session model's blind spots, so treat a clean one as
*no additional signal* rather than a clearance.

Give the reviewer the repo paths for the primitives the spec builds on, and ask it to check the
spec **against the real code** — the highest-value findings are always "the function you are
planning around does not do what you think it does".

### 5. Fold the findings in

Verify each finding yourself before accepting it; reviewers are confidently wrong sometimes.

- **P0/P1** — fix the spec, and rewrite whole sections rather than patching a dozen places, or the
  document ends up incoherent.
- **A finding that changes the build order** (a prerequisite the spec assumed existed) becomes its
  own ticket, first in the run.
- Re-review only if a P0 changed the design's shape. Cap it. Reviewers find *something* every pass.

### 6. `/to-tickets`

Tracer bullets, each sized to one context window, in dependency order. Its approval step runs.

Each ticket body carries: a link to the spec section, what to do, **the traps** (the specific
failure the reviewer found, in the ticket where it will bite), acceptance criteria, and its
dependencies. A ticket agent starts with no context — the trap has to be *in* the ticket, not in a
document it might read.

### 7. Land the prerequisites on the default branch — before the command, not after

**A fresh thread starts from the default branch. Anything this work depends on that is still
sitting on a feature branch does not exist for it.** Merge the prerequisites down first, then hand
back the command.

This is the step that is easy to skip because everything looks fine from here: the branch is
green, the tickets are written, the command is ready. The thread that picks it up is the one that
finds out.

- **Merge every prerequisite branch onto the default branch** — gated as usual, never pushed unless
  that was asked for. A ticket whose first act is "apply the migration the previous phase wrote" is
  a ticket that fails on a checkout where that migration was never merged.
- **A shared development database is a prerequisite too, and it is the one that bites.** Migrations
  living only on a branch are not in it, and a rebuild-from-empty by any other thread silently drops
  them — the replay can only apply what the default branch carries. Apply the merged migrations to
  the shared database, and verify by looking for the *objects or the function body hash*, not for a
  row in the migrations ledger: a hand-run replay applies files without recording rows, so that
  table answers "recorded", not "applied".
- **Where a prerequisite genuinely cannot merge yet** — it is blocked, it is failing, the owner has
  not ruled — say so in the handback in one line, name the branch, and put "merge X first" as the
  first ticket of the run. Never leave the next thread to discover it.

Measured 2026-09-05: two agents built two migrations on two branches. The second rebuilt the shared
database from empty, which could not include the first's migration because it had never been merged.
The next full gate showed thirteen failures across four files, all of them pinning a function body
the database no longer carried. Nothing was wrong with the code, and finding that out cost three
full suite runs.

### 8. Hand back the command

Lead with a **short label naming the work**, then the references, on one line, ready to paste:

    /driver Build the Council MVP https://…/121 https://…/122 https://…/123

- **Cross-repo** (tickets in a hub, code in an app — the fleet pattern): **full GitHub URLs**.
  Bare `#N` only resolves from inside the tracker repo.
- Say which directory to run it from — `/driver` works in the repo where the code changes land.
- Add one line on the suggested grouping if the set splits sensibly.
- **State what was merged in step 7**, so the next thread knows what its checkout already carries.

Then stop. **Never run `/driver` yourself.**

## Report

Close with: which gates ran and which were skipped (and why), **which reviewer actually ran**, the
findings that changed the plan, **what was merged down so the next thread can start**, the ticket
set, and the command.
