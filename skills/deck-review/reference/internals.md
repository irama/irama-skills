# How it behaves, and how to test it

*Split out of `SKILL.md`. Open this file when its line in that file is true of the work in front of you.*

## How it stays out of the way


- Hidden under `?export`, `?audit` and when printing, so it can never reach a
  leave-behind or a PDF.
- Highlights are painted with the CSS Custom Highlight API, so **no element is
  inserted into a slide** and nothing can reflow. Where the API is missing the
  eye button is not rendered and comments still work, unhighlighted.
- Keystrokes inside the comment box, the notes tray and the overview are stopped
  before they reach the deck, so typing a space or an arrow never advances a slide.
- The overview is `.dcx` chrome like everything else, so it is hidden when
  presenting, under `?export` and `?audit`, and at print. Entering presentation
  mode closes it.
- Stars, order, hidden slides and the unsent-changes mark all live in the same
  `localStorage` record as the comments, keyed by `deck-file`. An order stored
  against a different build is discarded on load rather than repaired, because a
  permutation of the wrong slide count is not fixable.

## Testing it


`tests/` holds a browser harness that drives this runtime for real. One command:

    cd tests && npm install && npm test

Forty checks, about five seconds. `tests/README.md` says what each one covers.

**Run it before changing `assets/deck-comments.js`, and again after.** Every
fault ever found in this runtime was found by reading a screenshot or driving a
real interaction, and none of them would have been caught by a static check:
`Esc` closing the whole overview instead of one editor, a header that would not
wrap so the toggles sat off screen at 1440, a toggle announcing the action
rather than the state, an emoji rendering as a blob, the deck ghosting through
the overlay, tiles scrolling into a dead gap.

**Playwright is a development-time tool and is not part of the contract.** The
shipped asset is still one dependency-free file with no build step, and the
install is still one `cp`. Nothing under `tests/` is copied into a deck, nothing
imports it, and its `package.json` scopes the dependency to that folder alone. A
no-browser suite was weighed and rejected: it would have caught none of the six
faults above, because they are all facts about layout, focus and paint. The
reasoning is written out in `tests/README.md` so it does not get relitigated.

**Assertions are not enough on their own.** Three of those six faults were only
visible in a picture, so the suite also writes screenshots into the gitignored
`tests/out/screens/`. After a run, open them. `tests/README.md` has the table of
what to look for in each.

The fixture decks live in `tests/fixtures/`, committed rather than generated, so
a run is reproducible: a minted-id deck, its next build with one slide renamed,
and a legacy deck with no ids at all.

## Assumptions it makes


Written against the `deck-stage` custom element: slides are
`deck-stage > section`, the live one carries `data-deck-active`, the label is
`data-screen-label`, and `stage.goTo(i)` navigates. For a different deck runtime,
`currentSlide()`, `slideNode()` and `goTo()` are the only three functions to
change, and they sit together at the top of the file.
