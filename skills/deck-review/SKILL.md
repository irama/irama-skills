---
name: deck-review
description: Add a review layer to an HTML slide deck so the reader can comment on specific text or whole slides in the browser, then copy one JSON payload back to Claude. Use when delivering a deck the user is meant to review, when they ask for comments/feedback/markup on slides, or when a deck round-trip needs to survive a rebuild. Pairs with html-brief, which does the same job for documents.
---

# Deck review

`html-brief` gives a document selection comments and a Copy-responses payload.
This does the same for a **slide deck**: select text on a slide, write a note,
hit Copy, paste the JSON into chat. The payload says which build was reviewed
and where every note belongs, so no other context is needed.

## Install it into a deck


One file, no dependencies, no build step.

    cp <skill>/assets/deck-comments.js <deck-folder>/

Then, in the deck HTML, after the deck script:

    <script src="deck-comments.js"></script>

And in `<head>`, four meta tags — **this is the part that makes the payload
self-sufficient**, so do not skip it:

    <meta name="deck-file"        content="path/to/deck.html">
    <meta name="deck-source"      content="path/to/generator.py">
    <meta name="deck-build"       content="2026-01-01T00:00:00Z">
    <meta name="deck-build-hash"  content="<12 hex chars>">
    <meta name="deck-resolutions" content="path/to/review-resolutions.json">

- `deck-file` — the deck, repo-relative.
- `deck-source` — the file to EDIT. On a generated deck that is the generator,
  never the emitted HTML. Same value as `deck-file` when the deck is hand-written.
- `deck-build` — UTC timestamp of the build.
- `deck-build-hash` — a short content hash of the slides. It is what lets Claude
  notice that the deck moved after the comments were written.
- `deck-resolutions` — where the ticked-off comments live. See below.

A generator should emit all four. In Python:

    import hashlib, datetime
    body = ''.join(slide_html) + ''.join(speaker_notes)
    build_hash = hashlib.sha256(body.encode()).hexdigest()[:12]
    build_at = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

## Ticking comments off


Across rounds, the expensive mistake is re-reading comments already dealt with.
So Claude ticks them off, and the deck shows it.

Keep a `review-resolutions.json` beside the deck:

```json
{ "resolutions": [
  { "at": "2026-01-01T09:15:22.100Z", "status": "addressed", "build": "84c3ea6ae5e8",
    "note": "Reworded to say what the figures count." },
  { "at": "2026-01-01T09:18:04.900Z", "status": "question",
    "note": "Needs a decision before I can act." }
] }
```

`status` is `addressed`, `wontfix` or `question`. `note` is what to tell the
reader, and it renders under the comment in the list.

The build embeds this file as a JSON block the runtime reads:

    <script type="application/json" id="deck-resolutions"> …the file… </script>

**Entries are keyed by the comment's `at` timestamp, not by an id, and that is
the whole trick.** Editing a comment rewrites its `at`, so the resolution stops
matching and the tick falls off by itself. A comment the user reconsiders comes
back as `new` without anybody having to remember to clear anything.

In the payload every comment then carries `status`, `addressedInBuild` and
`resolutionNote`, and the top level carries `openCount`. In the list, an
addressed comment is dimmed and stamped; its highlight stops being painted; and
the count badge reads `open/total`.

**Work only `new` and `question`.** Do not redo `addressed`, and do not report
on it — the user has read that round already.

## Branding on and off

The reader can hide the branding on every slide: the diamond control in the bar, or **Branding:
on/off** in the overview. It is a view setting, saved with the deck's other review state.

The toggle only puts `deck-nobrand` on `<html>`. **What counts as branding is the deck's own
call**, so a deck opts in by styling it:

    html.deck-nobrand .ft .brand,
    html.deck-nobrand .brandmark { visibility: hidden; }

A deck that never wrote that rule ignores the toggle, which is the right failure: this layer does
not get to guess which marks are yours.

## Companion files

Open one when its line is true of the work in front of you; never preload them.

| File | Read this when |
|---|---|
| `reference/the-payload.md` | A payload has come back and you are working it, or you are changing what one carries |
| `reference/the-overview.md` | You are working on the overview, the bar, or the keyboard |
| `reference/identity.md` | Slides moved or were renamed, or the deck has states |
| `reference/authoring.md` | You are writing or generating the deck itself |
| `reference/internals.md` | You edited `deck-comments.js` and need to know what must still hold |
