# The overview, the bar and the keys

*Split out of `SKILL.md`. Open this file when its line in that file is true of the work in front of you.*

## What the reader gets


A bar, top right of the deck:

| Control | Does |
|---|---|
| **Slide comment** | A note about the whole page, when the point is not about one phrase. One per slide: a second click edits the first. **It lights up when the slide on screen already carries one**: the label gains a leading **&#9679;**, the button fills, and the tooltip and `aria-label` read `Slide 4 has a slide comment. Click to read or edit it.` The dot and the words carry the state, so it never rests on colour alone. |
| **&#128065;** | Icon only. Shows or hides the highlights on commented text. Not rendered at all where the CSS Custom Highlight API is missing. |
| **&#128221; Notes** | Opens the speaker-notes tray for the slide on screen. Dimmed when that slide has no note. See *Speaker notes*. |
| **&#9734; / &#9733;** | **Icon only, no word.** Stars the slide **you are on**, from that slide. The state is carried by the glyph's shape, hollow against filled, and spelled out in the tooltip and `aria-label`: `Star this slide (S)` or `Slide 4 is starred. Click, or press S, to remove the star.` Never colour alone. Key: `S`. |
| **&#128683;** | Icon only. Hides or shows the slide on screen. Lights up when that slide is hidden. See *Hidden slides and performance mode*. |
| **&#9638; Overview** | Every slide as a live thumbnail. Star, hide, reorder, jump, comment, edit a note. Edit mode only. |
| **&#9654; Present** | Performance mode: full screen, no editing, hidden slides skipped, Esc exits. |
| **Count** | Opens the list. Click a row to jump to its slide, **Edit** to change it, **Delete** twice to remove it. A leading **&#9679;** means unsent changes. |
| **&#128203; Copy** | Puts the whole payload on the clipboard, and clears the unsent-changes mark. |

The bar renders in that order, in four groups separated by a rule: this slide's
content, then this slide's state, then the deck, then the round trip. `S` is the
only one of these with a whole-deck keyboard shortcut; `H` works on an overview
tile, not in the bar.

Selecting text opens the popover **without stealing the selection**, so the text
stays live and copyable; the popover also carries its own *Copy text* button.
Deleting always takes two clicks, in the popover and in the list.

Comments are stored in `localStorage`, keyed by `deck-file`, so they survive a
reload and a rebuild. Surviving a rebuild is the point of the build hash.

## The overview


**Overview** opens a scrollable grid of every slide, in edit mode only. It is the
control surface, not just a navigator.

Each tile is the **real slide**, deep-cloned and scaled with a CSS transform, so
the overview cannot drift from the deck. The clones stay in the light DOM, where
the deck's own CSS still reaches them; the one thing they would lose is any rule
scoped to `deck-stage`, so those rules are copied onto `.dcx-ovstage` the first
time the overview opens. Clones are built lazily as they scroll into view, ids
are stripped, and a custom element inside a slide is replaced by a plain box so
its mount logic does not run once per thumbnail.

Measured on a 33-slide deck: the grid builds in **7 ms**, twenty-four thumbnails
materialise inside the pre-load margin, the rest as you scroll, and a reorder
re-render takes **5 ms**. Real thumbnails were fast enough, so there is no
simplified mini rendering to fall out of date.

Per tile: **star**, **hide or show**, a **comment icon**, and a **note icon** that
opens that slide's speaker note in an editor pinned to the grid. A tick on the
note icon means that note has been edited. Clicking the thumbnail jumps to the
slide.

**The comment icon tells the two kinds of comment apart.** A **&#9679;** on the
icon means the slide carries a slide comment; a number means that many open
comments in total. A slide with a slide comment and two selection comments reads
`&#9679;3`. Under the thumbnail the flags say it in words: `&#9679; SLIDE COMMENT`,
then `3 COMMENTS`. When the slide comment is the only comment, only the first flag
shows, because two flags saying the same thing is noise. The tile's `aria-label`
reads `..., has a slide comment, 3 open comments`.

**Commenting or note-editing from a tile does not leave the overview.** The comment icon, and the
`C` key on a focused tile, open that slide's comment editor **over** the grid, with
the cursor already in it. Saving or cancelling puts focus back on the tile you
started from, so a pass over the whole deck is one uninterrupted sweep.

### Getting in and out

- **Going left off slide 1 opens the overview.** It sits "before" the deck, so the
  left arrow on the first slide walks into it instead of doing nothing. The
  **Overview** button in the bar still opens it from anywhere.
- **`Esc` goes back to the slide you came from**, not to slide 1 and not out of the
  deck. If you walked in from slide 1, slide 1 is where you land. **Close** does the
  same. Clicking a tile is different on purpose: that goes to that slide.
- **Focus is trapped inside the overview, deliberately.** Arrow keys move between
  tiles rather than paging the deck underneath, `Tab` cycles the header controls and
  the tiles, and everything outside is set `inert` so neither the keyboard nor a
  screen reader can reach the deck behind. The grid is an `aria-modal` dialog.
  `Esc` is the way out, and it leaves focus on the **Overview** button.
- **Opening focuses the slide you came from**, so you start where you left off.
- Rebuilding the grid keeps focus where it was, so starring or hiding with the
  keyboard does not throw you back to the top.

### The two filters

Two toggles at the top of the overview, both remembered like the rest of the review
state:

| Toggle | Reads | Does |
|---|---|---|
| **Starred only** | `☆ Starred only: off` / `★ Starred only: on` | Shows every slide, or only the ones you starred. |
| **Hidden slides** | `◉ Hidden slides: shown` / `⊘ Hidden slides: left out` | Keeps the hidden slides in the grid, or leaves them out. |

Each toggle names its filter **and** its state in words, carries `aria-pressed`, and
fills gold when on, so the state never rests on colour alone. The header count reads
`All 8 slides` or `Showing 3 of 8`, so a filtered view can never be mistaken for the
whole deck.

**A filter never takes away the slide you are acting on.** The slide you came in
from, and whichever tile has focus, stay on the grid even when the filter excludes
them. They are drawn with a dashed border and a `FILTERED OUT` flag, so it is clear
why they are there. Unstar a slide under **Starred only** and it stays put, flagged,
rather than vanishing under your hands.

**Reorder is off while a filter is on.** Positions belong to the whole deck, so
moving a slide past tiles you cannot see would be moving it somewhere unseen. Drag
and `Alt`+arrow both refuse, and say why.

**The filters are view state, not review state.** They are saved next to the
comments, they never make the deck dirty, and they add nothing to the payload.

**A reorder moves the deck, and is still an instruction to the file.** Dragging a
tile, or holding Alt with the arrow keys, moves the section in the light DOM, so
the flow, the thumbnails, presentation mode and the page numbers all follow at
once. It used to change the grid alone, which left the deck flowing in an order
the grid said it had abandoned.

**The file is not touched.** The deck is generated, so the order rides back in the
payload as `slideOrder[]` for the generator to apply, and it persists by slide id
in `localStorage` so a rebuild does not lose it. Once the generator catches up,
the stored order and the built order agree and the record clears itself.
**Reset order** puts it back.

**`wasSlide` is measured against `BUILD_IDS`** — the order the file was built in,
captured once at load before anything moves. That is what makes a second reorder
on top of a first still describe itself correctly.

A starred slide is marked three ways, because colour alone is not a signal every
reader can see: a gold border, a filled star on the button, and the word
`STARRED`. Hidden and moved slides carry `HIDDEN` and `MOVED` the same way, and a
slide comment carries the **&#9679;** and the words `&#9679; SLIDE COMMENT`.

**What the lit state means.** Lit is a boolean, not a count, because the model
allows exactly one slide comment per slide. Selection comments never light it:
they have the highlights on the text and the count badge in the bar already. Both
the bar control and the tile count **open** comments only, so a comment Claude has
addressed stops asking for attention. The signal repaints the moment a comment is
saved or deleted, and on every slide change, with no reload.

## Keys


| Key | Where | Does |
|---|---|---|
| `Esc` | in a comment editor | Closes it and saves nothing |
| `Cmd`+`Enter` / `Ctrl`+`Enter` | in a comment editor | Saves and closes |
| `Esc` | in the speaker-notes tray | Closes it (notes save as you type) |
| `S` | on any slide, in edit mode | Stars or unstars the slide you are on |
| `←` | on slide 1 | Opens the overview |
| `Esc` | in the overview | Closes it and returns to the slide you came from |
| `Esc` | presenting | Leaves presentation mode |
| `Enter` / `Space` | on an overview tile | Jumps to that slide |
| `S` | on an overview tile | Stars or unstars |
| `H` | on an overview tile | Hides or shows |
| `C` | on an overview tile | Writes that slide's comment, without leaving the overview |
| `Alt`+`←` / `Alt`+`→` | on an overview tile | Moves the slide one place |
| `←` `→` | in the overview | Moves focus one tile along the sequence. It never pages the deck behind |
| `↑` `↓` | in the overview | Moves focus a whole row, measured from the laid-out grid |
| `Home` `End` | in the overview | First or last tile |
| `Tab` / `Shift`+`Tab` | in the overview | Cycles the header controls and the tiles. It cannot leave |

An editor owns its own keys: a keystroke inside a comment box, the notes tray or
the overview never reaches the deck, so `Esc` in a comment cannot drop the
presenter out of full screen.

**Every key here has a control you can click.** `S` has the **Star** button, whose
tooltip prints `(S)`; `H` has the hide button; `C` has the comment icon; the
overview has its **Overview** button as well as the left arrow off slide 1. A key
nobody can find is not a feature, so nothing here is keyboard-only.

**None of this exists outside edit mode.** Presentation mode hides the whole bar and
`S` does nothing while presenting; `?export` and `?audit` never load the script at
all.

## The unsent-changes mark


**Any change that has not been copied yet makes the deck dirty**: a new comment,
a deleted one, a rewritten speaker note, a star, a slide shown or hidden, a new
order. While the deck is dirty:

- the count badge turns gold and grows a leading **&#9679;**, and its title spells
  out what is waiting, so the state is readable without relying on the colour;
- the comment list opens with an **UNSENT CHANGES** row naming each kind of change.

**Copy clears it**, and only once the payload is really on the clipboard. That
makes the badge answer one question at a glance: does this deck need resubmitting?
