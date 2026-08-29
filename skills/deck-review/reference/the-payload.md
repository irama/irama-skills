# The payload, and what to do with one

*Split out of `SKILL.md`. Open this file when its line in that file is true of the work in front of you.*

## The payload


```json
{
  "kind": "deck-comments",
  "version": 3,
  "instruction": "…what to do with this…",
  "deck": { "title": "…", "file": "…", "source": "…", "build": "…", "buildHash": "…" },
  "slideCount": 20,
  "capturedAt": "…",
  "commentCount": 2,
  "comments": [
    { "n": 1, "slide": 7, "slideId": "the-board", "slideLabel": "The board",
      "target": "selection", "quote": "the exact words selected",
      "comment": "what to change", "at": "…" }
  ]
}
```

Alongside those, and all optional:

| Field | Shape | Means |
|---|---|---|
| `starredSlides` | `[{slide, slideId, slideLabel}]` | Slides flagged for attention. A marker, **not** an edit. |
| `orderChanged` | `true` / `false` | Whether the reader asked for a new order. |
| `slideOrder` | `[{position, wasSlide, slideId, slideLabel}]` | Present only when `orderChanged`. The full order the reader wants. `position` is the new place, `wasSlide` the number in the build they reviewed, `slideId` the address that does not move. |
| `orderInstruction` | string | What to do with `slideOrder`. |
| `starInstruction` | string | What a star means, so a star is never read as an edit. |
| `hiddenSlides` | `[{slide, slideId, slideLabel, inSource}]` | Everything that should end up hidden. |
| `visibilityChanges` | `[{slide, slideId, slideLabel, from, to}]` | Only what now differs from the generator. |
| `noteEdits` | `[{slide, slideId, slideLabel, note, previousNote}]` | Speaker notes the reader rewrote. |
| `orphanedComments` | `[{slideId, slideLabel, target, quote, comment, at}]` | Comments whose slide is gone. Ask, never reassign. |

`target` is `selection` (anchored to `quote`) or `slide` (the whole page).

**`slideId` is how the receiving agent finds the slide, and the number is not.**
Every array above that names a slide carries it, alongside the `slide` number and
the `slideLabel` a human reads. Search `deck.source` for the id: it is the one
thing in the payload that does not move when the deck is renumbered or a heading
is rewritten, which is exactly when a number or a label sends you to the wrong
slide. A deck that grew from 28 to 62 slides in an evening moved every number in
it.

**When `slideId` is absent, the deck predates minted ids.** The key is simply
omitted, never empty and never the label wearing an id's name. Fall back to the
slide number, then check `slideLabel` matches the slide you landed on before you
edit anything, and say so in your reply if it does not. Adding `data-slide-id` to
the generator stops this happening again.

**`slideId` is additive and did NOT bump the version.** It is an extra key on
entries that already existed, so a consumer that ignores it parses a version-3
payload exactly as before, and a deck with no minted ids emits the same payload it
always did. There is nothing to migrate.

**Version 3 adds `starredSlides`, `orderChanged`, `slideOrder`, `orderInstruction`
and `starInstruction`, and nothing else.** Every version-2 field keeps its name and
shape, so a consumer that ignores the new fields still parses a version-3 payload,
and a version-2 payload from an older deck still reads correctly. The bump is a
signal, not a break: a payload that can carry a reorder instruction asks more of
the agent than one that cannot, and the version is how the agent knows to look.

The UI rename from "Comment slide" to "Slide comment" touched **no payload key**.
A whole-page comment is still `"target": "slide"`, so saved payloads and existing
`review-resolutions.json` files are untouched.

**`comments[]` carries the OPEN ones only.** Anything already ticked off has been
read, acted on and reported, so copying it back is noise in both directions;
`addressedCount` records how many were left out. `noteEdits[]` sits alongside.

## The payload is a diff, not an inventory


Every array in a copied payload is something the reader **changed**. What they left alone is a
count in `unchanged`, never a row. A slide already hidden in the generator, a primary already
marked there, a note that matches the note in the deck: none of them appear, because an
instruction to make a change that is already made is noise that teaches the reader to skim.

Two consequences worth knowing. A note edit whose text equals the deck's own note is dropped at
copy time, which is what stops slide renumbering from manufacturing phantom edits — the bag is
keyed by slide number, so an edit stored against 7 gets compared with a different slide after a
build inserts one. And the long instruction that used to ride in every payload lives here instead;
the payload carries a short one that names this file.

## Acting on a payload


1. **Locate every slide by `slideId`, not by its number.** Search `deck.source`
   for the id. Use the number and `slideLabel` only when an entry carries no
   `slideId`, and confirm the label matches before you edit.
2. **Check `deck.buildHash` against the current build first.** If it differs the
   deck changed after the review; say so before touching anything, because a
   quote may no longer exist.
3. Edit **`deck.source`**, never the generated HTML. A generated deck overwrites
   hand edits at the next build.
4. **If `orderChanged` is true, apply `slideOrder` last.** Every slide number in
   the payload, in `comments[]`, `hiddenSlides[]`, `visibilityChanges[]`,
   `noteEdits[]` and `starredSlides[]`, is the numbering of the build the reader
   reviewed. Their `slideId` does not move, so work from that wherever it is
   present and the reorder costs you nothing. Resolve all of those first, then
   move the slide-building calls in `deck.source` so the emitted order matches
   `slideOrder`, changing nothing else about those slides. Say in your reply what the new numbering is.
5. **A star is not a task.** `starredSlides[]` says where the reader's attention
   was. Look at those slides first and lead your reply with what you found, but do
   not change one unless a comment asks you to.
6. Rebuild, then re-run the deck's own layout check if it has one.
7. Answer the questions as questions. A comment ending in `?` wants a reply, not
   a silent edit.
8. **Tick off what you did** — write every handled comment into
   `review-resolutions.json` and rebuild, so the next round starts from what is
   still open rather than from all of it.
