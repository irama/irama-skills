---
name: draft-eval
description: Score a draft deck or article against a versioned rubric, then run the loop that rewrites its weakest units until the bars are met. Use when the user says "score this deck", "evaluate this draft", "score this article", or invokes /draft-eval.
---

# /draft-eval

`<skill-dir>` is the folder holding this SKILL.md.

Stub. The full procedure (extract, render, mechanical checks, graders, calibration, loop) lands in a
later ticket. What exists now:

- `rubric.json`: the versioned rubric. Every record carries its `rubric_version`.
- `python3 <skill-dir>/extract.py <index.html | article.md> [--at <git-rev>] -o units.json`: one unit per logical slide
  (animation states grouped, scored on the primary state) or per article section part of at most
  400 words. `python3 <skill-dir>/extract.py --selftest` checks the state grouping and the notes alignment.

## Grading step

Two graders, reported per grader and never pooled. No script calls a model: this session
runs Codex through Bash and dispatches the Claude grader with the Agent tool. `<run>` is the
run folder, `<n>` the round number.

1. Build the packets. Decks pass the screenshots from `render.mjs`; articles have none.

       python3 <skill-dir>/packet.py <run>/units.json <run>/grading/r<n> --shots <run>/shots/shots.json > <run>/grading/r<n>/batches.json

   Each batch is a directory of up to 8 unit folders, and the rendered prompt sits beside it
   as `batch-NN.prompt.md`. Nothing but packets goes in the batch directory.

2. Codex, per batch. Run `codex-available -q` first. If it exits non-zero, skip Codex for the
   round and say so in the report: the round is Claude only and cannot meet the bar.
   Read the model id from the `model =` line of `${CODEX_HOME:-$HOME/.codex}/config.toml`.

       codex exec --ephemeral -s read-only --skip-git-repo-check -C <batch dir> \
         --output-schema <skill-dir>/schema.json -o <run>/grading/r<n>/<batch>.codex.json \
         - -i <png 1> -i <png 2> ... < <batch prompt>

   Give each PNG in the batch's `pngs` its own `-i`, and put the `-` (prompt from stdin) before
   them: `-i` takes several values, so a `-` after it is read as an image.

   The Codex grader runs inside the packet directory only, read-only and ephemeral.

3. Claude, per batch. Dispatch a fresh `draft-grader` agent for every batch, never reused:

       Agent(subagent_type="draft-grader",
             prompt="Packet directory: <batch dir>. Grader prompt: <batch prompt>. Return the JSON only.")

   Write its reply verbatim to `<run>/grading/r<n>/<batch>.claude.json`. Send it nothing else:
   no earlier scores, no author reasoning, no list of rewritten units.

4. Validate each reply and append the stamped records:

       python3 <skill-dir>/validate.py <reply> --units <run>/units.json --batch <ids,comma,separated> \
         --grader codex|claude --round <n> [--model <codex model id>] -o <run>/grading/r<n>/<grader>.jsonl

   For Claude, leave out `--model`; the record keeps the model id the agent reported.

5. If a batch fails validation, run that grader on that batch once more. If it fails again,
   log the batch as failed in `<run>/grading/r<n>/failed.json` (grader, batch, errors) and
   carry on. A failed batch leaves its units unscored for that grader.

Every record carries `grader`, the full `model` id, `rubric_version`, `round`,
`prompt_sha256` (of `grader-prompt.md`) and `schema_sha256`. `python3 <skill-dir>/validate.py --selftest`
proves a bad record is rejected.

Tests: `python3 -m unittest discover -s skills/draft-eval/tests` from the repo root.
