---
name: draft-eval
description: Score a draft deck or article against a versioned rubric, then run the loop that rewrites its weakest units until the bars are met. Use when the user says "score this deck", "evaluate this draft", "score this article", or invokes /draft-eval.
---

# /draft-eval

**A full round grades every slide in several batches and takes 15 to 30 minutes, so run it only
for a first full draft or a major change** (more than 20% of slides new, or more than 20% changed
by the user in claim, argument or evidence; state the call in one line so the user can override it).
For anything smaller, score only the audit set that `score_round.py audit` selects.

`<skill-dir>` is the folder holding this SKILL.md. `<folder>` is the target's folder (the deck
folder holding `_gen.py`, or the article's folder), `<run>` the run folder, `<n>` the round.

**The session that invokes this skill is the orchestrator.** It follows this file. Scripts are
deterministic and never call a model: this session runs Codex through Bash, dispatches the Claude
grader with the Agent tool, writes the rewrites itself and calls `/gen-image` itself.

**The loop runs only after calibration has passed** (the calibration step in `grading.md`, and its agreement
report). Until then, score only: run one round with no rewrite.

## The scripts

| Script | Job |
| --- | --- |
| `extract.py` | One unit per logical slide (animation states grouped) or per article part of at most 400 words. |
| `render.mjs` | One screenshot per deck unit (runs from the real path or through the skill symlink), `contact.png` for the arc pass, `shots.json` with sha256 values and the Playwright and Chromium versions. |
| `check.py` | Mechanical gates, floors and warnings for a deck. |
| `packet.py`, `validate.py` | Grading packets per batch; validation and stamping of each grader reply. |
| `arc.py` | The arc pass packet and the validation of its replies. |
| `run.py` | The lock, the run folder, the per-round record, the round commit, the record check. |
| `score_round.py` | Unit scores, the median, the bar, the stop decision, Codex's audit set, the self-preference check, the split re-grade list (calibration rounds) and the rewrite list. |
| `prefer.py` | The blind preference page, and `--score` for the 70% rule. |
| `prefer_rulings.py` | The reader's preference notes as rulings, with each grader's score on the faulted criterion and a grader-missed count. |
| `brief.py`, `review-brief.md` | The review brief: data placeholders filled from the run record. |
| `calibrate.py` | Calibration packets and the scoring page. |

`python3 <skill-dir>/extract.py <index.html | article.md> [--at <git-rev>] -o units.json` and
`python3 <skill-dir>/extract.py --selftest` as before.

### Deck markers the rubric reads

- **`[planted]`** in a slide's speaker notes marks a deliberate fake, planted as a teaching trick.
  `extract.py` sets `planted: true` on the unit, the packet shows it, and `validate.py` requires
  `honest_numbers` to be N/A on it. Without the tag the loop may "fix" the trick.
- **The `evidence` role** is for reference and evidence appendix slides. They skip `visual`,
  `device` and `concrete_first`; `clear`, `economy`, `earns_place` and `honest_numbers` still
  apply. Set `data-role="evidence"`, or `extract.py` infers it from a slide id that starts with
  `evidence`, `references`, `provenance` or `sources`, or a class of the same name.
- **The terms slide** (rubric 0.4.1) is the deck's glossary: one hidden section early in the deck,
  `<section data-role="terms" data-hidden ...>`, holding each term as `<dt>term</dt><dd>definition</dd>`.
  A visible slide that introduces a term carries `data-introduces="term"` (commas separate several).
  `extract.py` writes the `terms` list (term, definition, `introduced_by`, `introduced_at` as the
  slide's ordinal) and keeps the terms slide as a hidden unit, so it is never graded. `packet.py`
  gives graders the list as data: a listed term is not a `clear` guess from its introducing slide
  onwards, and still is before it. `arc.py` writes it as `terms.md`, and `check.py` warns
  (`terms_before_intro`) on a term that appears before its introducing slide or has none.

- **The sources field** is a slide's non-spoken provenance: `<script type="application/json"
  id="slide-sources">`, an array of `{index, sources}` keyed like the speaker notes (see the
  `peakstate-deck` skill). `extract.py` writes it as the unit's `sources`, `packet.py` as
  `sources.txt`, and graders count a number sourced there for `honest_numbers`. It is neither
  notes for `notes_actionable` nor visible text for `economy`.
- **The keep list** is `<folder>/keep.json`, committed with the draft:
  `{"keep": [{"unit": "<slide id>", "element": "<what the reader praised>"}]}`. Every element the
  reader praises in a review goes on it. The rewrite step reads it, and the review brief reports
  each element against the run's rewrites.

### Rubric 0.6

Fitted to the deck-authoring rules on motion and visuals. Rounds scored under 0.5 are not
comparable on the two new criteria.

- **`motion`** (decks): does the slide's declared motion act out its point or metaphor, settle by
  7s and keep any loop subtle and meaningful, and does a slide whose idea moves use that movement?
  Authors declare intent on the section, `data-motion="..."`; `extract.py` carries it as the unit's
  `motion` and `packet.py` writes it as `motion.txt`, so graders judge it beside the static
  screenshot. N/A for evidence slides, and for `data-motion="none"` when the idea has no movement.
- **Arc**: `visual_journey`, in the bar, asks for a visual on about nine presented slides in ten,
  varied kinds with no two neighbours alike, metaphors that work as a set, and immersive
  transitions where the next slide continues the same scene.
- **`check.py`** gains a `motion` gate from the runtime's `?motion` report: a slide that settles
  after 7s or an unmarked loop fails it. A deck whose `deck-tools.js` predates `?motion` skips it.

### Rubric 0.5

Fitted to the eight lesson groups the reader confirmed from five rounds of deck notes. Each lesson
is now something a grader checks, and `rubric.json` carries them as a `lessons` list of checks.

- **`clear`**: slides build on earlier slides. A term introduced on an earlier slide is not a guess
  where it is reused; context clues on the reusing slide are the ideal. A question or label that
  makes sense only beside the speaker is a guess.
- **`economy`**: a hedge or provenance caveat on the face of a slide is filler. **`honest_numbers`**
  can be met in the notes or the sources field. **`notes_actionable`**: a caveat written for the
  presenter to say aloud belongs in the sources field.
- **`visual`**: draw the shape the idea already has, true to the rules of what it depicts and
  recognisable at a glance, with the fewest encodings the story needs.
- **Arc**: `taxonomy_ids` asks for one distinct look per framework; `variety` names curiosity. The
  arc pass now reads the deck-level rulings (`arc.py build --examples`).

Earlier versions (0.3 to 0.4.2), whose rules still hold, are in `rubric-history.md`: open it when a
score turns on a rule this section does not name.

The rubric's `changelog` says what each version changed and what it was fitted to.

## The loop

### Before round 1

1. Start the run. It refuses unless `git status --porcelain <folder>` is empty and no
   `<folder>/.draft-eval.lock` exists, so a second start while a run holds the lock is refused.

       RUN=$(python3 <skill-dir>/run.py start <folder> --target <name> --session <session id> --baseline-gap <G>)

   `<G>` is the calibration baseline gap: the Claude mean minus the Codex mean over the
   calibration units (from the agreement report). The run folder is `<folder>/eval-runs/<UTC>/`,
   kept out of git through `.git/info/exclude`. It holds `rubric.json` as used, `run.json` (Codex
   CLI and Chrome versions) and `images.json`.
2. **From here, every exit releases the lock**, on success, on a stop, on an error and when the
   user interrupts: `python3 <skill-dir>/run.py release <folder> --reason "<why>"`.
3. The unit list is fixed for the run. Add or delete no units: an article unit that grows is still
   one unit. `score_round.py` saves round 1's unit ids as `$RUN/units.fixed.json` and refuses a
   later round whose ids differ, and refuses records for a unit outside the list. Deleting a slide is a
   proposal in the review brief, never a loop action.
4. Decks: after the round 1 build and render, write the floors once with
   `check.py ... --baseline --floors $RUN/floors.json`. Later rounds use `--floors $RUN/floors.json`.

### One round, in this order

`R=$RUN/rounds/r<n>`.

1. **Build.** Decks: `python3 _gen.py` in `<folder>`. Articles have no build.
2. **Audit and mechanical.** `python3 <skill-dir>/extract.py <index.html> -o $R/units.json`, then
   `python3 <skill-dir>/check.py <index.html> $R/units.json --floors $RUN/floors.json > $R/mechanical.json`
   (exit 1 only means a gate failed; the JSON is the result). `?audit` runs inside `check.py`.
   Articles: extract to `$R/units.json` and skip `mechanical.json`.
3. **Render** (decks): `node <skill-dir>/render.mjs <index.html> $R/units.json $R/shots`.
4. **Grade** into `$R/grading/`, the grading step in `grading.md`. Claude grades every unit. Codex grades only
   the audit set: `python3 <skill-dir>/score_round.py audit $RUN <n>` prints the units rewritten in
   the round before plus as many untouched units as a baseline, and its `select` value goes to
   `packet.py --select` for Codex's packets. Round 1 has no rewrites, so Codex grades nothing.
   A calibration round (`--graders both`) has both graders grade every unit.
5. **Arc pass** (decks), Claude only; Codex runs it too only in a calibration round:

       python3 <skill-dir>/arc.py build $R/units.json $R --shots $R/shots/shots.json --run-sheet <run sheet> \
         --examples <rulings.jsonl> > $R/arc.build.json
       codex exec --ephemeral -s read-only --skip-git-repo-check -C $R/arc --output-schema <skill-dir>/arc-schema.json \
         -o $R/arc/arc.codex.json - -i $R/arc/contact.png < $R/arc.prompt.md
       python3 <skill-dir>/arc.py validate $R/arc/arc.codex.json --grader codex --round <n> --model <codex model> -o $R/arc.json

   For Claude, dispatch a fresh `draft-grader` with the arc prompt and the `arc/` directory,
   write its reply to `$R/arc/arc.claude.json`, and validate with `--grader claude`. Retry a
   failed reply once, as for batches.
6. **Record**: `python3 <skill-dir>/run.py record $RUN <n>`.
7. **Stop check**: `python3 <skill-dir>/score_round.py $RUN <n> [--graders both]`, which writes
   `$R/score.json`.
   - Calibration rounds only: if `regrade` lists units (one grader gave 3 where the other gave 4 or more), re-grade each
     listed unit once with the listed grader. Pack it from the round's full unit list, so it keeps
     its real previous unit: `python3 <skill-dir>/packet.py $R/units.json $R/regrade/<grader> --shots
     $R/shots/shots.json --select <ids>`. Grade, validate against `$R/units.json` with
     `-o $R/grading/<grader>.regrade.jsonl`, and run `score_round.py` again. The second score stands.
   - If `stop.stop` is true, write `$R/rewrites.json` as `{"rewrites": []}`, release the lock
     and go to the review brief. The stop check comes after grading and before any rewrite, so
     the run always ends on a graded state.
8. **Rewrite** the units in `rewrite` (at most 8, mechanical failures first, then the lowest).
   - Edit the source (`_gen.py`, or the article `.md`), never the generated `index.html`.
   - Obey the deck's `BUILD.md`. Keep the approved spine's act order. Add or delete no slide.
   - Never read earlier grader reasoning into a packet: the graders see only the draft.
   - **Read `<folder>/keep.json` first.** A rewrite of a unit on the keep list keeps the praised
     element, or says in its `keep` note why it goes.
   - **Worse means revert.** Where the reader marked a change worse, restore the previous version
     first, then apply the new idea to it.
   - **Fix the pattern, not the slide.** When a fault is flagged on one unit, check every unit for
     the same fault, and list each unit fixed.
   - Write `$R/rewrites.json`: `{"round": n, "rewrites": [{"unit", "why", "files", "change", "keep"}], "images": [...]}`.
9. **Images**: at most 10 new images per run, with `/gen-image`, following the robot monkey rules
   in the `peak-state-design` skill (`assets/characters/robot-monkey/README.md`). Log each one in
   `$RUN/images.json` (`round`, `unit`, `prompt`, `model`, `path`). Ideas past the tenth go into
   the review brief as proposals.
10. **Commit** only the target's files. `run.py` refuses a path outside `<folder>` and commits
    only the paths named, whatever else is staged:

        python3 <skill-dir>/run.py commit $RUN <n> <folder>/_gen.py <folder>/index.html [<new image> ...]

    The message is `draft-eval(<target>): round <n>`. Rollback is `git revert`.
11. Next round.

### The bar and the stop rules

- **Claude sets the bar; Codex audits.** Codex's role is to catch Claude marking its own rewrites
  up, so its scores never set the bar or the median in a loop round.
- **The bar**: every mechanical gate passes; Claude's arc pass scores at least 4 on every arc
  criterion in the rubric's `bars.arc_criteria`; every applicable criterion on every unit scores at
  least 4 from Claude.
- **A unit's score** is Claude's mean. The round's **median** is the median unit score. Sums change
  when units change, so the loop compares medians only.
- **Stop** on the first of: the bar is met (or met but blocked); 5 rounds done; or two rounds in a
  row where the median did not rise. One non-improving round is noise and does not stop the run.
- **Self-preference audit.** `score_round.py` computes the Claude-minus-Codex gap on the audited
  rewritten units and on the baseline units (the calibration baseline gap when there are none). An
  excess of 0.5 or more turns the bar into "blocked: possible self-preference". A rewritten unit
  Codex did not grade (`codex-available -q` failed, or its batch failed) turns it into "blocked:
  rewrites not audited by Codex". Either way the run is not finished: it stops as
  `bar_met_blocked`, and the review brief shows both graders' scores for those units and lists the
  rewrites as suggestions not yet passed.
- **`--graders both`** runs a calibration round: both graders grade every unit and run the arc pass,
  a unit's score is the lower of the two means, the bar needs both graders, the split re-grade
  applies, and the gap covers every unit rewritten so far. Use it to measure the graders against
  each other, never as the loop's default.

### The run record

`python3 <skill-dir>/run.py check $RUN` must print `run record complete` before the review brief.
Per round it holds `units.json`, `mechanical.json`, the raw replies (`grading/*.<grader>.json`,
`arc/arc.<grader>.json`) and the parsed records (`grading/<grader>.jsonl`, `arc.json`),
`rewrites.json`, `score.json`, and `record.json` (source commit, screenshot sha256 values, grader
prompt and schema sha256, full model ids, Codex CLI, Chrome and Playwright versions, and the
round's rewrite commit). A grader whose every batch failed has an entry in `grading/failed.json`
in place of its parsed file.

### After the loop

1. **Blind preference test** (decks): before is round 1's `shots.json`; after is the last round's.

       python3 <skill-dir>/prefer.py $RUN/rounds/r1/shots/shots.json $RUN/rounds/r<last>/shots/shots.json \
         --units <every rewritten unit> -o <brief folder>/<target>-<date>-prefer

   The user opens `prefer.html`, answers every pair and files `prefer-answers.json` beside it.
   `prefer.py --score prefer-answers.json prefer-key.json` applies the 70% rule. If after wins
   fewer than 70% of the pairs where a side was chosen, the result goes back to calibration, not
   to the user as a finished deck.

   **Every preference test ends by filing its notes as rulings**, so the reader's notes always
   feed the next run:

       python3 <skill-dir>/prefer_rulings.py prefer-answers.json prefer-key.json \
         --units $RUN/rounds/r<last>/units.json --label <target>-prefer \
         --records $RUN/rounds/r<last>/grading/{codex,claude}.jsonl [<the round's *.regrade.jsonl>] \
         [--criteria '{"<pair>": ["clear"]}'] -o <rulings.jsonl>

   Each note becomes one ruling per criterion it bears on (keywords in the note pick `clear`,
   `visual` or `economy`; `--criteria` overrides a pair, and a note that matches nothing stops the
   script so no note is dropped). Each line carries both graders' scores on that criterion and
   `missed`, the graders that scored 4 or more on a criterion the reader faulted. The summary on
   stderr gives the grader-missed count per grader: report it in the brief. A high count means the
   rubric, not only the deck, needs the next change. Pass the rulings file to `packet.py
   --examples` in the next run.
2. **Pre-review against the lessons**, before the reader sees anything. Dispatch a fresh
   general-purpose agent with the changed slides' screenshots, `<folder>/keep.json` and the
   rubric's `lessons` checks. It returns every check a changed slide breaks and every kept element
   a rewrite lost. Fix those, rebuild, and say in the brief what the pre-review caught, so the
   reader only catches what the lessons do not yet cover.
3. **Review brief** (a `peakstate-brief`), at `<brief folder>/<target>-<date>.md`:

       python3 <skill-dir>/brief.py $RUN -o <brief>.md --figures <brief folder>/<target>-<date>-figures [--prefer <score json>]

   The brief shows each slide itself, asks only about what changed, never re-asks a settled
   ruling, and reports the keep list (`{{KEEP_TABLE}}`, filled from `<folder>/keep.json`).

   `brief.py` fills the data and prints the placeholders still open. Write those by hand:
   - `{{CALL}}` and `{{PRICE}}` open the brief. The first sentence states the call; the second
     gives its price (rounds, rewrites, images, tokens) and what it buys. The reader never has to
     compute the trade from numbers in different sections.
   - `{{Q1_CRUX}}` states the cost, the benefit and the preference result in numbers.
   - `brief.py` sets Q1's Recommended tag. Never add one by hand: a gate passed at a tie is
     reported as a tie, and no option that rests on it is recommended.

   Then `python3 <skill-dir>/brief.py --check <brief>.md`, build with
   `node <peakstate-brief>/assets/build-brief.mjs <brief>.md`, and run `brief-lint.py` on the HTML.
4. **Lessons step, after every review round.** When the reader's answers come back:
   - File each note as a ruling (`prefer_rulings.py` for a preference test, by hand otherwise) and
     report the grader-missed count: notes on a criterion a grader scored 4 or more.
   - Add every element the reader praised to `<folder>/keep.json`.
   - For each note, ask whether the rubric and the `lessons` checks would have caught it. A note
     no anchor or check covers is a lesson: propose the anchor change and the check as the next
     rubric version, for the reader to confirm.
   - Silence is not approval: a slide the reader did not comment on is not a passed slide.

## Grading and calibration

The grading step (how both graders run, packet by packet, and how a bad record is rejected), the
calibration step and the rulings the graders learn from all live in `<skill-dir>/grading.md`. Read it
before the first grading step of a run, and before any calibration round.
