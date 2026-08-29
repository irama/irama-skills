# Slide identity, drift and states

*Split out of `SKILL.md`. Open this file when its line in that file is true of the work in front of you.*

## Identity: a minted id, then the label, then never the number


**A slide's id is its permanent address, and it is minted once.** The generator
emits `data-slide-id` on every section and keeps the ledger beside it
(`slide-ids.json`), so a slide can be renamed, moved, or re-themed and the
reader's comments, stars, hides and note edits stay with it.

**The rule: an id is never changed once minted.** A label is a heading and may be
rewritten freely; an id is an address and may not. When a generator meets a label
it has no id for, it mints one AND SAYS SO at build time, because the two causes
are opposite: a genuinely new slide, or a rename that just orphaned that slide's
comments. A rename is fixed by passing the old id explicitly, never by editing the
ledger.

**The id rides back in the payload.** Every entry that names a slide carries
`slideId` beside the number and the label, so the agent acting on the review
locates the slide in the generator by its address rather than by a number that
moved while the reader was commenting. Minting ids in the generator is what turns
that on; without them the payload carries no `slideId` and the agent falls back to
the number and the label.

The runtime resolves identity in order: **`data-slide-id`, then the label, then
nothing.** A deck with no ids still re-anchors by label, and a deck with ids
survives a rename. This is the fix for a real failure: a comment written about
"The stamp" orphaned the moment that slide was renamed "Confabulation stamp".

## Drift: slide identity is the label, never the number


A deck is generated, and slides get inserted. Insert one near the front and every
number after it shifts by one. Anything the reader stored against a number then
sits on whichever slide inherited it, which is how a comment written about one
slide gets painted on another, and how a hide set on one slide hides a different
one two builds later.

So **every save records a `labels` snapshot** — the number-to-label map of the
build it was saved against — and every load compares that snapshot with the deck
on screen and moves each record to wherever its label now lives. This runs before
the first paint, so nothing is ever drawn on a slide it does not belong to.

- **Comments** already carry `slideLabel`, so they re-anchor on their own.
- **Hides, stars and note edits** are keyed by number, and are moved using the
  snapshot's label for that number.
- **A record whose label is gone is not guessed at.** It becomes an **orphan**:
  listed under its own heading with `⚠ ORPHANED · was on "…"`, never painted, and
  carried back in the payload as `orphanedComments[]` with an instruction to ask
  rather than reassign it.
- **Duplicate labels are not resolved either** — two slides with one label make
  that label ambiguous, so those records are left alone.
- **State saved before this mechanism existed** has no snapshot, so its numbers
  cannot be resolved. Typed note prose is kept where it is, because losing it
  costs real work. A stale hide or star is dropped, because an unexplained hidden
  slide is worse than re-doing one click.

The reader is told: a toast on load says how many records moved and how many were
orphaned.

**This is why a slide's `data-screen-label` matters.** Rename one and its records
orphan. Give two slides the same label and neither can be resolved. Labels are the
identity, so a generator should treat them as one.

## States: reviewing a build


A section carrying `data-state-group` is a **state**. States are reviewed as separate slides,
because a comment about the third frame of a build is about that frame. What they share is one job:
exactly one of them is the **primary**, the frame that reaches print and PDF.

| Control | Where | Does |
|---|---|---|
| **&#9671; / &#9670;** | the bar, on a state | Makes the state on screen the page that prints |
| **&#9671; / &#9670;** | an overview tile, or `P` | The same, without leaving the grid |
| `PRINTS` | an overview tile | Marks the state that will be the page |

**Primary is an instruction, like visibility.** The generator's marking is the default, the reader's
choice is an override stored by slide id, and it rides back as `primaryStates[]` for the generator
to apply. An override that agrees with the deck is discarded rather than stored.

**Morph is the default transition between states.** An element that appears in both states travels
rather than cuts: the underline under a chosen word grows for a long word and shrinks for a short
one. Matching is by signature (tag, classes, place among siblings), so states generated from one
template need no labelling. `data-morph="key"` forces two elements to be treated as one thing;
`data-morph="none"` opts out; and an element carrying its own `data-entry` or `data-exit` is left
alone, because an explicit animation is a statement that it arrives its own way.

**Hiding the primary moves the job.** It falls back to the previous visible state, then forward,
because a group whose every state is hidden should contribute no page rather than a hidden one. That
rule lives in `deck-stage.js` with the printing, not here.
