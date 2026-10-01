# draft-eval rubric history

What rubric versions 0.3 to 0.4.2 added. Every rule here still holds in later versions; the
rubric's `changelog` says what each version was fitted to.

## Rubric 0.4.2

- **`device`** gains the type `curiosity`: the unit signals that a mental model is coming, such as
  framework ids shown ahead of the framework. The model must arrive later.
- **`clear`**: items in a list or sequence are parallel in form, and questions in a sequence share
  one polarity (every "yes" continues). A non-parallel list counts as one guess.
- **`visual` and `clear`**: a chart states what it measures, for whom, and its takeaway; a
  recommendation says what to do and in what situation. Missing either caps visual at 3 and counts
  as one guess under clear.
- **Arc**: `taxonomy_ids` also asks that a recurring emblem or id has exactly the same visual
  treatment every time. A new arc criterion in the bar, `one_model`, asks for one model per idea:
  two slides that model the same idea with different axes or terms lower it.

## Rubric 0.4.1

- **`clear`**: loaded wording such as "kill" is a guess only when its object is not clear on the
  slide, a neighbour or an earlier slide. A term from the terms slide is not a guess once introduced.
- **`visual`**: findings and recommendations on one slide need visibly different treatment; mixing
  them caps visual at 3.
- **Two arc criteria**, both in the bar: `terms_introduced` (every non-plain term is introduced
  visually, with a metaphor or example, on or before its first use) and `taxonomy_ids` (an id such
  as D1 uses a letter that means something and is reused wherever its item appears).

## One device per unit (rubric 0.3)

Each unit carries the base criteria plus ONE device, and the devices vary across the deck.

- **`device`** scores the one trick or twist on the unit and names its `type`: `guess_reveal`,
  `surprise`, `tease_payoff`, `callback`, `live_challenge`, `overturn`, `plain_rule` or `curiosity`. A score of 1
  or N/A has type `none`. Title and evidence units may be N/A. An exercise with no fixed answer
  scores on its own device, usually a live challenge.
- **`economy`** counts filler on the unit's visible text: meta-commentary, instructions on how to
  read the slide, the "not X, but Y" pattern, lines added for completeness. `check.py` gates the
  rubric's `filler_patterns` (for example "do not read", "on this slide") on slide text, never on notes.
- **`notes_actionable`** (decks) asks that every instruction in the notes names the exact move and
  defines what it refers to. N/A only on a unit with no notes.
- **The arc's `variety`** scores whether the device types vary. `score_round.py` writes
  `device_variety` per grader (consecutive units that share a type, and the most common type's
  share) as a cross-check.

