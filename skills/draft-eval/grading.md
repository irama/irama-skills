# draft-eval: the grading and calibration steps

Read from SKILL.md when a round reaches its grading step, or before a calibration round.

## Grading step

Two graders, reported per grader and never pooled. In a loop round Claude grades every unit and
Codex grades only the audit set (step 4 of the round); in a calibration round both grade every unit. No script calls a model: this session
runs Codex through Bash and dispatches the Claude grader with the Agent tool. In the loop,
`$R` is `$RUN/rounds/r<n>`. For calibration, `$R/grading` is the calibration folder's `packets/<set>`
and `graders/`, as the calibration step says.

1. Build the packets. Decks pass the screenshots from `render.mjs`; articles have none.

       mkdir -p $R/grading
       python3 <skill-dir>/packet.py $R/units.json $R/grading --shots $R/shots/shots.json > $R/grading/batches.json

   Each batch is a directory of up to 8 unit folders, and the rendered prompt sits beside it
   as `batch-NN.prompt.md`. Nothing but packets goes in the batch directory.

2. Codex, per batch of its own packets (the audit set, built with `--select` into
   `$R/grading/codex-audit`, or every unit in a calibration round). Run `codex-available -q`
   first. If it exits non-zero, skip Codex for the round and say so in the report: the rewrites are
   unaudited and the run cannot finish.
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
   From rubric 0.4 the `clear` entry also carries `point` (what a first-time reader takes from the
   unit) and `guesses` (what they would have to guess at). `validate.py` rejects a `clear` score
   above what the guesses allow: none allows 5, one caps it at 3, two or more (or an empty point)
   give 1.

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
`score.html`. Grade every batch with both graders as in the grading step (a calibration round, so
`--graders both` applies), validating against
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
data block, and the batch list gains `examples_sha256`. Pass the same file to `arc.py build
--examples`: the arc prompt gains the deck-level rulings (an arc-only criterion such as
`taxonomy_ids` or `one_model`, or an arc criterion with `"unit": "deck"`), and `packet.py` skips them. The file holds draft text, so it lives with
the draft's private repo, never in this skill.

Tests: `python3 -m unittest discover -s skills/draft-eval/tests` from the repo root.
