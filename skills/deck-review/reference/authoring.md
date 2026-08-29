# What a deck must do to be reviewable

*Split out of `SKILL.md`. Open this file when its line in that file is true of the work in front of you.*

## Nothing may sit on the footer line


`index.html?audit` fails a slide when any leaf element crosses into the footer
band, alongside the two overflow checks. The footer carries the brand mark, the
slide's own note and the page number, so a chart label or a stray line landing
there reads as a clash and hides attribution in a screenshot. Absolutely
positioned artwork is exempt, because it is meant to run behind.

**"all N slides clean" is still the pass.** A `FOOTER clash` line names the
element and both edges, so the fix is a padding change, not a hunt.

## A slide never describes or narrates itself


**Standing rule for any deck this skill touches.** A slide may carry explanation,
evidence and argument. It may not carry a description of its own layout, an
announcement of what is coming, or a line written only because the space looked
empty.

- Out: *"The same seven tiles, in the same seven places."* *"No solutions on this
  page."* *"Three things we will cover."*
- In: the seven tiles. The reader can see how many there are.

**Narration belongs in the speaker note**, where it is spoken once and never
printed. **Nothing beats vacuous content**: an empty half of a slide is a
composition, a sentence about the slide is noise the room has to read past.

## Speaker notes


A deck that ships its notes as a JSON block (`<script type="application/json"
id="speaker-notes">`, an array of `{index, note}`) gets an editable tray. The
**Notes** button opens it, it follows the slide on screen, an `EDITED` badge marks
a note the reader changed, and **Revert** restores the original.

**Do not author notes.** The tray edits and returns them; nothing in this skill should write one
unasked. A speaker note is an instruction to the presenter, a line read aloud, or an acronym
expanded for the moment they blank on it. Reasoning about the slide belongs in a run sheet.

**Only edited notes travel back**, as `noteEdits[]`, each with `slide`,
`slideLabel`, the new `note` and the `previousNote` it replaces — so the generator
can be updated from the same round trip that carries the comments. Unedited notes
are never copied; they are already in the source.

## Hidden slides and performance mode


A deck usually carries slides that are not in every delivery. They stay in the file, dimmed, and
never appear when presenting. **Dimming always darkens** (`filter: brightness(.3)`), never a light
wash: a faded-to-white slide reads as a rendering fault, a darkened one reads as switched off.

| Control | Does |
|---|---|
| **&#128683;** | Hides or shows the slide on screen. Dimmed in edit mode, skipped when presenting |
| **&#9654; Present** | Full screen, chrome gone, arrows navigate, hidden slides skipped, Esc exits |

**The generator's marking is the default, not the verdict.** `data-hidden-src` in the markup is what
the deck says; the button is an override on top of it, stored in `localStorage`, and it goes **both
ways**. A source-hidden slide can be shown and a visible slide can be hidden. An override that
happens to agree with the deck is discarded rather than stored, so the state stays readable.

The payload carries both halves:

- **`hiddenSlides[]`** — everything that should end up hidden, each with `inSource` saying whether
  the generator already knows.
- **`visibilityChanges[]`** — only the slides that now differ from the generator, with `from` and
  `to`. This is the list to act on.

**Copy sends a payload whenever anything has changed** — a comment, a rewritten note, or a slide
shown or hidden. Refusing to copy because nobody left a comment is how the other two get lost.

Skipping is directional: the runtime remembers whether the last move was forward or back, so a run
of hidden slides is stepped over the way it was entered rather than trapping the presenter.
