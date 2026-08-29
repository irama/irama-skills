# deck-review tests

A browser harness for `assets/deck-comments.js`. It drives the real runtime in a
real browser, because that is the only thing that has ever found a fault in it.

## Run it

```
cd skills/deck-review/tests
npm install
npm test
```

`npm install` fetches Playwright once. If it has never run on this machine, add
`npx playwright install chromium` after it. `npm test` starts a small static
server on Node's standard library, loads the fixture decks, and runs 40 checks.
A full run takes about five seconds.

Other commands:

- `npm run test:headed` watches it happen in a visible browser.
- `npx playwright test specs/overview.spec.mjs` runs one file.
- `npx playwright test -g "Escape"` runs the cases whose name matches.
- `npm run report` opens the HTML report after a failure.

## Why a browser harness, and why it does not break the skill's contract

The shipped asset is deliberately dependency-free: one script tag, plain browser
APIs, no build step. That contract is about **what a deck loads at run time**.

These tests are **development-time only**. They are never copied into a deck,
they are not imported by the asset, and the asset does not know they exist. The
install step of this skill is still one line:

```
cp <skill>/assets/deck-comments.js <deck-folder>/
```

Nothing in `tests/` is part of that. `package.json` here declares Playwright as
a `devDependency` of the tests folder alone, and it sits below the asset rather
than beside it, so the boundary is visible in the directory listing.

**The alternative was considered and rejected.** A no-browser suite, running the
asset against a DOM shim, would keep the folder dependency-free. It would also
have caught none of the six faults this harness exists for. Escape closing the
whole overview, a header that would not wrap, a toggle announcing the action
instead of the state, an emoji rendering as a blob, the deck ghosting through
the overlay, and tiles scrolling into a dead gap are all facts about layout,
focus and paint. A shim has no layout, no focus ring and no pixels, so it cannot
see any of them. A suite that cannot fail on the faults that actually happen is
worse than no suite, because it reads as coverage.

**Do not relitigate this.** If the dependency ever has to go, the thing to
delete is the harness, not the browser.

## What the fixtures are

`fixtures/` holds three decks and a minimum `deck-stage`, so a run is
reproducible and nothing is generated into a temporary folder.

| File | Is |
|---|---|
| `deck-minted.html` | Eight slides, every one carrying `data-slide-id`, three speaker notes, slide 7 marked `data-hidden-src`. |
| `deck-minted-relabelled.html` | The next build of the same deck, same `deck-file` and same ids, with slide 5 renamed. This is the re-anchoring case. |
| `deck-legacy.html` | Four slides, no minted ids. The deck that predates `data-slide-id`. |
| `deck-stage.js` | The smallest runtime that satisfies the asset's three assumptions: `deck-stage > section`, `data-deck-active`, and `goTo(i)`. |

`serve.mjs` maps `/deck-comments.js` straight onto `../assets/deck-comments.js`,
so the suite always drives the shipped file and never a copy that can drift.

The fixture decks need a real `http` origin rather than `file://`, because the
whole review lives in `localStorage` and a `file://` page has an opaque origin
that cannot write to it.

## What is covered

- **The overview.** Opening it from the bar and by going left off slide 1, and
  that going left off slide 2 still pages the deck. `Esc` returning to the origin
  slide and leaving focus on the Overview button. `Esc` in a tile comment editor
  closing the editor only. Everything outside going `inert`. `Tab` cycling and
  never escaping. Row-wise `ArrowUp` and `ArrowDown`, measured against the
  laid-out grid. Arrows never paging the deck behind. Tiles rendering real,
  visible slide content. The header keeping every control on screen at 1440 and
  1024.
- **The four tile controls.** Star and hide, by click and by key. Comment from a
  tile staying on the overview, taking the keyboard, and giving focus back to the
  tile it started from. The note editor, its `EDITED` mark, Revert, and `Esc`.
- **Starring.** From a slide by button and by `S`, from a tile, and the two
  agreeing. The state following the slide rather than the button.
- **The two filters.** Both naming their state in words and carrying
  `aria-pressed`. The header count reading `Showing N of 8`. The slide you came
  in from kept and flagged `FILTERED OUT`. Reorder refusing while filtering, by
  `Alt`+arrow and by `draggable`, and saying why. Reorder working when no filter
  is on, and moving the section in the light DOM rather than the grid alone.
- **The lit Slide comment state.** Going on when a comment is saved and off when
  it is deleted, with no reload, and the overview tile agreeing with the bar. A
  second click editing the first comment rather than stacking a duplicate. A
  selection comment never lighting it.
- **The payload.** Valid version 3, with every slide-identifying array checked
  for `slideId`. The legacy deck producing a valid payload with `slideId` simply
  absent, never an empty string and never the label wearing an id's name. The
  unsent-changes mark clearing only after the payload reaches the clipboard.
  Copy refusing when nothing has changed.
- **Re-anchoring.** A comment surviving its slide being relabelled between two
  builds, landing back on slide 5, with no orphan row.
- **The chrome-free modes.** `?export` and `?audit` rendering no `.dcx` element
  at all, and presentation mode hiding the bar with `S` doing nothing.

## Screenshots: look at them

Assertions alone missed three of the six faults. So `specs/screens.spec.mjs`
captures the states where that class of fault lives, into `out/screens/`. That
folder is gitignored on purpose: no screenshot binaries in this repo.

After a run, open them and look. What to look for:

| Shot | Look for |
|---|---|
| `bar-plain`, `bar-lit` | Every glyph legible at bar size. An emoji that renders as a featureless blob is the fault. The lit state must read from the leading dot and the fill, not from colour alone. |
| `overview-header-1440`, `overview-header-1024` | The header wrapping, with both toggles and both buttons fully on screen. Nothing clipped at the right edge. |
| `overview-grid-top`, `overview-grid-bottom` | Thumbnails showing real slide content, not blank frames. No deck ghosting through the backdrop. At the bottom, the last row fully visible and no dead gap scrolled past it. |
| `overview-filter-starred` | The kept-back tile dashed and flagged `FILTERED OUT`, and the count reading `Showing 4 of 8`. |
| `tile-controls` | The four icons distinct from each other. The star filled, the `STARRED` and `● SLIDE COMMENT` flags present. |
| `popover-selection`, `comment-list`, `overview-note-editor` | Nothing clipped, nothing overlapping, the quote readable. |
| `presenting` | No review chrome anywhere on the slide. |

**One known observation, unfixed.** In `bar-plain` and `bar-lit` the eye glyph
for the highlights toggle renders as a dark brown ellipse at 13px and is hard to
tell apart from a smudge. It is the platform emoji at that size, not a bug in
the asset, and the control still carries its title text. It is recorded here
because it is exactly the class of fault a screenshot exists to surface.

## Adding a case

Put it in the spec that already owns that surface. Reach for a new fixture deck
only when the case is about the deck, not about the runtime, and give it its own
`deck-file` meta unless it is deliberately the next build of an existing one.

Before believing a new assertion, break the asset on purpose and check the test
goes red. An assertion that has never failed has never been tested.
