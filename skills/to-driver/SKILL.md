---
name: to-driver
description: Take a rough idea all the way to a paste-ready /driver command — grill it into decisions, write the spec and ADR, run an adversarial plan review, cut the tickets, hand back the invocation. Use when the user says "to driver", "/to-driver", "get this ready for driver", or wants an idea turned into buildable tickets end to end.
argument-hint: "the idea, feature or plan to take to tickets — e.g. `/to-driver a /council page with three arguing personas`"
disable-model-invocation: false
---

# /to-driver

The phase chain from `~/.claude/CLAUDE.md` § "How I work — phases", compressed into one verb:

    assess → /grill-with-docs → write-up → adversarial review → /to-tickets → /merge all → the /driver command

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

## Claim the planning cycle — by topic, never the bare verb

Several `/to-driver` threads can plan in one repo at once. The claim does not block anything; it
tells the dashboard and the other threads what this one is planning. The register is last claim
wins per key, so a bare `<repo>:to-driver` key lets a second planning thread silently overwrite
the first and hide it. Key the claim to the topic:

```bash
common="$(git rev-parse --path-format=absolute --git-common-dir)"
REPO="$(basename "$([ "$(basename "$common")" = .git ] && dirname "$common" || echo "$common")")"
reg=<skill-dir>/../threads/assets/register.py
KEY="$REPO:to-driver:<topic-slug>"   # kebab-case, names the work: watch-dashboard, likelihood-round-v13
[ -f "$reg" ] && python3 "$reg" claim "$KEY" --note "<one line: what is being planned>"
```

- **Claim on pick-up**, in step 1, before the first question.
- **At every human gate**, sign off `waiting-on-user` with the gate in the note
  (`--note "grill Q3 of ~6"`, `"ticket breakdown awaiting approval"`), and claim `$KEY` again
  when the answer lands. Claiming again reopens the same key.
- **In step 8**, sign off `handed-off`, with the `/driver` command's label in the note. From
  there, `/driver` claims its own per-run key.
- **Stopping part-way**, with no command handed back, signs off `waiting-on-user` and says why.

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
`adversarial-reviewer` subagent (Opus) and **say which one actually ran**, in one clause. A gate
that could not run is not a pass; a gate the fallback ran IS a pass. The fallback closes the gate:
never offer a later Codex re-run of it, and never list one under next steps.

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

**A ticket with a UI surface carries its mockup, not a sentence about it.** The mockup is the
spec for how the thing looks, and one line of prose ("a dot per future on a year axis") describes
both the mockup and a page that looks nothing like it. So the ticket names the mockup file and
the section anchor, and if the mockup lives in another repo it says the full path from the
worker's own checkout. The ticket lists the mockup's visible elements as acceptance items
(headline treatment, picker form, chart marks, axes, labels, colours, captions, block order),
and its last acceptance item is a side-by-side screenshot of the build against the mockup with
every deviation listed and given a reason. A deviation with a reason is allowed. A silent one
is a defect. Measured 2026-09-18: a ten-ticket run named its mockup in one ticket, and the FIRE
page shipped with none of the mockup's visual structure while every numeric acceptance item
passed.

**A ticket that produces a brief, report or decision document carries two more acceptance
items, verbatim.** `/to-tickets` cannot be edited (it is a versioned plugin skill), so it
includes them because the prompt this step hands it says to: state that the two items below
are mandatory on every document-producing ticket, and repeat them word for word in that
prompt, not as a summary of them.

- "The first sentence states the call and its price; the reader does not have to compute the trade from numbers in different sections."
- "Every Recommended option survives the document's own disclosures; a gate passed at a tie is reported as a tie and is not recommended."

Both are reader checks, not author checks. The first fails when the verdict is assembled from
a table on page one and a cost on page four. The second fails when a document discloses a
result and still recommends the option the disclosure undercuts.

### 7. Land the work on the default branch — before the command, not after

**A fresh thread starts from the default branch. Anything still sitting on a feature branch does
not exist for it.** Run `/merge all` first, then hand back the command.

**This is unconditional, and it is wider than the prerequisites.** Merge everything mergeable in
the repo, not only what you can name a dependency for. The thread that picks the command up sees
exactly one thing, the default branch, and whatever is not on it may as well not have been built.
Working out in advance which branches a ticket will turn out to need is guesswork, and the cost of
guessing wrong lands on a thread with no context to diagnose it.

This is the step that is easy to skip because everything looks fine from here: the branch is
green, the tickets are written, the command is ready. The thread that picks it up is the one that
finds out.

- **`/merge all`, gated as usual, never pushed unless that was asked for.** A ticket whose first act is "apply the migration the previous phase wrote" is
  a ticket that fails on a checkout where that migration was never merged.
- **A shared development database is a prerequisite too, and it is the one that bites.** Migrations
  living only on a branch are not in it, and a rebuild-from-empty by any other thread silently drops
  them — the replay can only apply what the default branch carries. Apply the merged migrations to
  the shared database, and verify by looking for the *objects or the function body hash*, not for a
  row in the migrations ledger: a hand-run replay applies files without recording rows, so that
  table answers "recorded", not "applied".
- **Where a branch genuinely cannot merge yet** — it is blocked, it is failing, the owner has
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
  Name the branches, and name anything left unmerged with the reason.

Sign off the planning claim: `python3 "$reg" sign-off "$KEY" --status handed-off --note "<label>"`.

Then stop. **Never run `/driver` yourself.**

## Report

Close with: which gates ran and which were skipped (and why), **which reviewer actually ran**, the
findings that changed the plan, **what was merged down so the next thread can start**, the ticket
set, and the command.
