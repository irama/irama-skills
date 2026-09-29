---
title: {{TARGET_NAME}}: draft-eval run {{RUN_ID}}
brief-id: draft-eval-{{TARGET}}-{{RUN_ID}}
eyebrow: Review brief · {{DATE}} · rubric {{RUBRIC_VERSION}}
sub: What the draft-eval loop changed in {{TARGET_NAME}}, what each grader now says, and the blind preference test that decides whether the changes are better or only score better.
---

## Answers

Is the draft ready for your review?
: {{ANSWER_READY}}

What did the loop change?
: {{ANSWER_CHANGED}}

Do both graders agree?
: {{ANSWER_GRADERS}}

What is left for you to do?
: {{ANSWER_LEFT}}

## Contents

# The result

**{{CALL}}** {{PRICE}}

## Verdict {#s-verdict} :: the bar, the stop reason and the two checks on the graders

:::verdict
**{{VERDICT_LINE}}**

- **Stop reason:** {{STOP_REASON}}
- **Self-preference:** {{SELF_PREFERENCE_LINE}}
- **Blind preference test:** {{PREFER_LINE}}
:::

## Definitions :: the words the scores turn on

:::html
<p class="defs-h">Used here</p>
<div class="defs-in">
<div class="term"><h4>Unit</h4><ul><li><span class="k">In this brief</span> The thing one score is about. In a deck, one logical slide: a group of animation states counts as one slide.</li></ul></div>
<div class="term"><h4>Bar</h4><ul><li><span class="k">In this brief</span> The pass line. Every mechanical gate passes, and the arc pass and every judged score reach at least 4 from both graders.</li></ul></div>
<div class="term"><h4>Median unit score</h4><ul><li><span class="k">In this brief</span> Each unit's score is the lower of the two graders' mean scores for it. The median of those is the number the stop rule watches.</li></ul></div>
<div class="term"><h4>Arc pass</h4><ul><li><span class="k">In this brief</span> One grading call per round per grader over the whole deck, for flow, surprise and delight, and audience participation.</li></ul></div>
<div class="term"><h4>Self-preference gap</h4><ul><li><span class="k">In this brief</span> The Claude grader's mean minus the Codex grader's mean. The run compares it on rewritten units with untouched units, because the author and the Claude grader are the same model family.</li></ul></div>
<div class="term"><h4>Blind preference test</h4><ul><li><span class="k">In this brief</span> You pick the better slide from before and after pairs without knowing which is which. After must win at least 70% of the pairs where you chose a side.</li></ul></div>
<div class="term"><h4>Passed at a tie</h4><ul><li><span class="k">In this brief</span> A gate whose measured value equals its threshold exactly. It is reported as a tie, and no option that rests on it is recommended.</li></ul></div>
</div>
:::

# The evidence

What each grader scored, which gates passed, and what the loop changed.

## Scores per grader {#s-graders} :: never pooled

The two graders are reported side by side and never averaged together.

{{GRADER_TABLE}}

## Gates {#s-gates} :: each with its margin

A gate passed at exactly its threshold reads "passed at a tie" in the last column.

{{GATE_TABLE}}

## Rewritten slides {#s-rewrites} :: before and after

{{REWRITE_FIGURES}}

## Units still under the bar {#s-under} :: with each grader's quoted reason

{{UNDER_BAR}}

## Proposals the loop may not act on {#s-proposals} :: images past the cap, slide deletions

{{PROPOSALS}}

## What did not work {#s-failed} :: failed batches, dead ends, anything worse after a rewrite

{{FAILED}}

# Your review

Two calls are yours: whether the rewrites stay, and the blind preference test.

## Q1 Keep the rewrites of {{TARGET_NAME}}? :: keep or revert

My assumption: {{Q1_ASSUMPTION}}
If wrong: each round is one commit, so `git revert` of the round commits restores the draft exactly.

{{Q1_CRUX}}

a) Keep every rewrite. {{Q1_REC_A}}
b) Keep the rewrites except the slides I name in the answer box.
c) Revert every round commit and keep the draft as it was.

## Q2 Take the blind preference test now? :: about 10 minutes

My assumption: yes. The test takes about 10 minutes for {{PAIR_COUNT}} pairs, and it is the only check that the loop improved the deck for you rather than for the graders.
If wrong: the rewrites stay unconfirmed, and the rubric cannot move to the locked phase.

Open the page, answer every pair, press Download JSON and file `prefer-answers.json` beside the page.

    {{PREFER_URL}}

# Provenance

Who produced this brief and what it rests on.

## Provenance :: attribution, accountability, limits, sources

Attribution
: Scores from the Codex grader ({{CODEX_MODEL}}) and a fresh Claude grader ({{CLAUDE_MODEL}}); rewrites and this brief by the orchestrating Claude Code session, following the draft-eval skill.

Accountable
: {{ACCOUNTABLE}}

Limitations
: {{LIMITATIONS}}

References
: The run record in `{{RUN_RECORD}}` holds every raw grader reply, the rubric as used and each round's source commit.
