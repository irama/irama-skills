---
name: draft-eval
description: Score a draft deck or article against a versioned rubric, then run the loop that rewrites its weakest units until the bars are met. Use when the user says "score this deck", "evaluate this draft", "score this article", or invokes /draft-eval.
---

# /draft-eval

`<skill-dir>` is the folder holding this SKILL.md. `<folder>` is the target's folder (the deck
folder holding `_gen.py`, or the article's folder), `<run>` the run folder, `<n>` the round.

**The session that invokes this skill is the orchestrator.** It follows this file. Scripts are
deterministic and never call a model: this session runs Codex through Bash, dispatches the Claude
grader with the Agent tool, writes the rewrites itself and calls `/gen-image` itself.

**The loop runs only after calibration has passed** (the calibration step below, and its agreement
report). Until then, score only: run one round with no rewrite.

## The scripts

| Script | Job |
| --- | --- |
| `extract.py` | One unit per logical slide (animation states grouped) or per article part of at most 400 words. |
| `render.mjs` | One screenshot per deck unit, `contact.png` for the arc pass, `shots.json` with sha256 values and the Playwright and Chromium versions. |
| `check.py` | Mechanical gates, floors and warnings for a deck. |
| `packet.py`, `validate.py` | Grading packets per batch; validation and stamping of each grader reply. |
| `arc.py` | The arc pass packet and the validation of its replies. |
| `run.py` | The lock, the run folder, the per-round record, the round commit, the record check. |
| `score_round.py` | Unit scores, the median, the bar, the stop decision, the self-preference check, the split re-grade list and the rewrite list. |
| `prefer.py` | The blind preference page, and `--score` for the 70% rule. |
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

### One device per unit (rubric 0.3)

Each unit carries the base criteria plus ONE device, and the devices vary across the deck.

- **`device`** scores the one trick or twist on the unit and names its `type`: `guess_reveal`,
  `surprise`, `tease_payoff`, `callback`, `live_challenge`, `overturn` or `plain_rule`. A score of 1
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
4. **Grade, both graders, per unit**: the grading step below, into `$R/grading/`.
5. **Arc pass** (decks), one call per grader:

       python3 <skill-dir>/arc.py build $R/units.json $R --shots $R/shots/shots.json --run-sheet <run sheet> > $R/arc.build.json
       codex exec --ephemeral -s read-only --skip-git-repo-check -C $R/arc --output-schema <skill-dir>/arc-schema.json \
         -o $R/arc/arc.codex.json - -i $R/arc/contact.png < $R/arc.prompt.md
       python3 <skill-dir>/arc.py validate $R/arc/arc.codex.json --grader codex --round <n> --model <codex model> -o $R/arc.json

   For Claude, dispatch a fresh `draft-grader` with the arc prompt and the `arc/` directory,
   write its reply to `$R/arc/arc.claude.json`, and validate with `--grader claude`. Retry a
   failed reply once, as for batches.
6. **Record**: `python3 <skill-dir>/run.py record $RUN <n>`.
7. **Stop check**: `python3 <skill-dir>/score_round.py $RUN <n>`, which writes `$R/score.json`.
   - If `regrade` lists units (one grader gave 3 where the other gave 4 or more), re-grade each
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
   - Write `$R/rewrites.json`: `{"round": n, "rewrites": [{"unit", "why", "files", "change"}], "images": [...]}`.
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

- **The bar**: every mechanical gate passes; the arc pass scores at least 4 on flow, delight,
  participation and variety from both graders; every applicable criterion on every unit scores at least 4
  from both graders.
- **A unit's score** is the lower of the two graders' means. The round's **median** is the median
  unit score. Sums change when units change, so the loop compares medians only.
- **Stop** on the first of: the bar is met; 5 rounds done; or two rounds in a row where the median
  did not rise. One non-improving round is noise and does not stop the run.
- **Both graders are needed for "bar met".** If `codex-available -q` fails, the round runs on
  Claude alone. `score_round.py` then reports at best "met by Claude only", and the review brief
  lists the rewrites as suggestions not yet passed.
- **Self-preference.** `score_round.py` computes the Claude-minus-Codex gap on rewritten units and
  on untouched units, beside the calibration baseline gap. An excess of 0.5 or more on rewritten
  units turns "met" into "met by Claude only, possible self-preference", and the brief shows both
  graders' scores for those units.

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
2. **Review brief** (a `peakstate-brief`), at `<brief folder>/<target>-<date>.md`:

       python3 <skill-dir>/brief.py $RUN -o <brief>.md --figures <brief folder>/<target>-<date>-figures [--prefer <score json>]

   `brief.py` fills the data and prints the placeholders still open. Write those by hand:
   - `{{CALL}}` and `{{PRICE}}` open the brief. The first sentence states the call; the second
     gives its price (rounds, rewrites, images, tokens) and what it buys. The reader never has to
     compute the trade from numbers in different sections.
   - `{{Q1_CRUX}}` states the cost, the benefit and the preference result in numbers.
   - `brief.py` sets Q1's Recommended tag. Never add one by hand: a gate passed at a tie is
     reported as a tie, and no option that rests on it is recommended.

   Then `python3 <skill-dir>/brief.py --check <brief>.md`, build with
   `node <peakstate-brief>/assets/build-brief.mjs <brief>.md`, and run `brief-lint.py` on the HTML.

## Grading step

Two graders, reported per grader and never pooled. No script calls a model: this session
runs Codex through Bash and dispatches the Claude grader with the Agent tool. In the loop,
`$R` is `$RUN/rounds/r<n>`. For calibration, `$R/grading` is the calibration folder's `packets/<set>`
and `graders/`, as the calibration step says.

1. Build the packets. Decks pass the screenshots from `render.mjs`; articles have none.

       mkdir -p $R/grading
       python3 <skill-dir>/packet.py $R/units.json $R/grading --shots $R/shots/shots.json > $R/grading/batches.json

   Each batch is a directory of up to 8 unit folders, and the rendered prompt sits beside it
   as `batch-NN.prompt.md`. Nothing but packets goes in the batch directory.

2. Codex, per batch. Run `codex-available -q` first. If it exits non-zero, skip Codex for the
   round and say so in the report: the round is Claude only and cannot meet the bar.
   Read the model id from the `model =` line of `${CODEX_HOME:-$HOME/.codex}/config.toml`.

       codex exec --ephemeral -s read-only --skip-git-repo-check -C <batch dir> \
         --output-schema <skill-dir>/schema.json -o $R/grading/<batch>.codex.json \
         - -i <png 1> -i <png 2> ... < <batch prompt>

   Give each PNG in the batch's `pngs` its own `-i`, and put the `-` (prompt from stdin) before
   them: `-i` takes several values, so a `-` after it is read as an image.

   The Codex grader runs inside the packet directory only, read-only and ephemeral.

3. Claude, per batch. Dispatch a fresh `draft-grader` agent for every batch, never reused:

       Agent(subagent_type="draft-grader",
             prompt="Packet directory: <batch dir>. Grader prompt: <batch prompt>. Return the JSON only.")

   Write its reply verbatim to `$R/grading/<batch>.claude.json`. Send it nothing else:
   no earlier scores, no author reasoning, no list of rewritten units.

4. Validate each reply and append the stamped records:

       python3 <skill-dir>/validate.py <reply> --units $R/units.json --batch <ids,comma,separated> \
         --grader codex|claude --round <n> [--model <codex model id>] -o $R/grading/<grader>.jsonl

   For Claude, leave out `--model`; the record keeps the model id the agent reported.

5. If a batch fails validation, run that grader on that batch once more. If it fails again,
   log the batch as failed in `$R/grading/failed.json` as `{"failed": [{grader, batch, errors}]}`
   and carry on. A failed batch leaves its units unscored for that grader, and `score_round.py`
   leaves those units out of the median and reports each grader's coverage.

Every record carries `grader`, the full `model` id, `rubric_version`, `round`,
`prompt_sha256` (of `grader-prompt.md`) and `schema_sha256`. `python3 <skill-dir>/validate.py --selftest`
proves a bad record is rejected.

## Calibration step

Run once, before the loop, to test both graders against a human scorer.

    python3 <skill-dir>/calibrate.py -o <cal dir> \
      --deck <name> <units.json> <shots.json> <n> [--deck ...] \
      --article <name> <units.json> <n> [--article ...]

It picks the units (spread across roles, layouts and position; no animation states where it can),
builds their packets with `packet.build` (each unit keeps its real previous unit), and writes
`units.json`, `sources/<name>.units.json`, `packets/<name>/batch-NN/`, `packets.sha256` and
`score.html`. Grade every batch with both graders as in the grading step, validating against
`sources/<name>.units.json`. Commit the grader records and `packets.sha256` before any human
score exists. The scorer opens `score.html` from disk, scores with radio buttons (answers save in
the browser), and downloads the scores JSON: one entry per unit and criterion.

### Rulings: the graders learn from corrections

When the human scorer rules on a contested score or corrects one, file it as a worked example in
`<run-or-calibration-dir>/rulings.jsonl`, one JSON object per line:

    {"criterion": "honest_numbers", "excerpt": "<the unit text the score turns on>", "score": "n/a", "reason": "<the ruling>"}

`score` is 1 to 5 or `"n/a"`. Extra fields (set, unit, ruling id) are kept in the file and not
shown to graders. Pass the file to `packet.py --examples <file>`: each batch prompt gains the
examples whose criterion applies to the draft's kind, labelled as calibration examples in a fenced
data block, and the batch list gains `examples_sha256`. The file holds draft text, so it lives with
the draft's private repo, never in this skill.

Tests: `python3 -m unittest discover -s skills/draft-eval/tests` from the repo root.
