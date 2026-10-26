# draft-eval rubric history

What rubric versions 0.3 to 0.4.2 and 0.7 added. Every rule here still holds in later versions;
the rubric's `changelog` says what each version was fitted to.

## Rubric 0.7: the moments group

Our decks were strong on argument and evidence and thin on the moments a room remembers: a
designed peak, a person to care about, a laugh, a speaker who shows a failure. A review of the
best-analysed talks found those moments are what an audience repeats afterwards. The rubric had
nothing that marked their absence down, so a dry deck could meet the bar. The group adds that
check now, before any deck has been built to it, so it is a first guess at the target.

- **`moments`** is a deck-level group, graded in the arc pass, one pass or fail per check:
  `star_moment` (a S.T.A.R. moment, "Something They'll Always Remember", named and built),
  `peak_and_end` (a designed peak and last 60 seconds, the close echoing the open),
  `five_moves` (one of five persuasion moves on each presented content slide, all five across
  the deck, confirm or justify before the first promise), `people_and_stories` (a story or a
  named person in every section, no statistic without a person or a physical scale),
  `wrong_and_credible` (an "I was wrong" beat and a credibility story in the first three
  minutes), `light_moment` (at least one planned laugh) and `stage_directions` ([PAUSE], [ASK],
  [STORY], [MOVE: ...] in the notes).
- **The five moves** are Blair Warren's, with the fifth changed: encourage their dreams, justify
  their failures, allay their fears, confirm their suspicions, and always on your side.
- **No ethics guard.** The rubric judges whether a move is there, never whether it is fair; the
  author makes that call.
- **In the bar.** The group passes only when every check passes, and `bars.moments_must_pass`
  holds it in the bar. An arc record with no `moments` block fails it.
- **Phase.** The rest of the rubric keeps its phase; the moments group is in its experimental
  phase, so its checks may change round to round. Unit scores and the eight arc criteria are
  unchanged, so they stay comparable with 0.6. A round scored under 0.6 or earlier is not
  comparable with a 0.7 round on moments or on whether the bar was met.

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


## Rubric 0.8: but or therefore at every join

The flow criterion passed a deck whose sections only followed one another in order. Story
writers test a plot by the word between its beats: "but" (a turn) or "therefore" (a
consequence) drives the story forward, and "and then" marks scenes strung together. The arc
grader now names the link at each join between sections and lists every join where only "and
then" fits. A run of parallel items (a set of moves, the steps of a method) counts as one beat
when each item carries its own cause and the run is joined in and out by a but or a therefore.
Flow is in its experimental phase, and rounds under 0.7 or earlier are not comparable on flow.

## Rubric 0.9: the confession beat is optional

Andrew ruled (26 October 2026) that the "I was wrong" confession beat in a deck or talk is
optional. Use one only when a true story serves the throughline; otherwise leave it out and
say so in one line on the arc sheet. Never ask for one by default, never block an arc or a
build on its absence, and never fail a draft for its absence.

`wrong_and_credible` now passes on the credibility story alone. A confession, if present, must
still serve the argument: it moves the room toward the throughline and does not concede a
counter-argument. Rounds scored under 0.8 or earlier are not comparable on `wrong_and_credible`.
