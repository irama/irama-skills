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

Tests: `python3 -m unittest discover -s skills/draft-eval/tests` from the repo root.
