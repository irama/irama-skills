---
name: claude-retro
description: Analyze the user's own Claude Code session history to find how they actually work — repeated requests, correction loops, skill/hook candidates, and built-but-unused tooling. Use when the user says "claude retro", "analyze how I work", "audit my usage", "what do I repeat", or invokes /claude-retro. Optional arg = number of days to look back (default 30).
disable-model-invocation: true
---

> **User-triggered only.** A run fans out up to ~20 background agents over hundreds of MB of
> transcripts, and step 7 writes persistent memory. Both are the user's call, so this skill is
> never auto-invoked on a stray "audit my usage" — it answers to `/claude-retro` and to an
> explicit ask.

> **Config dir.** Every command below reads Claude Code's own data directory via
> `CC="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"` — set it once at the start of the run. The
> fallback is the default location, so this behaves identically when the variable is unset.

Read the user's Claude Code session history and report how they actually work over a lookback window: what they ask for repeatedly, where turns burn on corrections, which manual workflows deserve a skill/hook, and what they built but never use.

**Deliverable is a plan/report, not code changes.** Do not build the skills you propose unless the user then asks.

## Parameters

- Lookback window in days from the invocation arg (e.g. `/claude-retro 14`). Default **30**.

## Constraints (this environment)

- **`grep`/`rg` are blocked by a hook.** For counting/searching use `jq`, `python3`, `awk`, `sort | uniq -c`, or pipe into `grep` only as the *right side* of a pipe (`cmd | grep x` is allowed; a bare `grep`/`rg` invocation is not).
- Transcripts are large (often hundreds of MB, 10k+ files). **Never read raw transcripts into your own context.** Extract compact prompt text to a scratch file first, then analyze that.

## Method

### 1. Survey volume
```
CC="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
find "$CC"/projects -name "*.jsonl" -mtime -<DAYS> | wc -l
find "$CC"/projects -name "*.jsonl" -mtime -<DAYS> -exec du -ch {} + | tail -1
wc -l "$CC"/history.jsonl
```

### 2. Extract genuine user prompts to a scratch JSONL
Skip tool results, hooks, meta, and agent-* subagent transcripts. Capture both string-content and array-content user text. Write `{p:project, m:prompt[:600]}` per line to the scratchpad:
```
SCRATCH=<scratchpad>/retro; mkdir -p $SCRATCH
find "$CC"/projects -name "*.jsonl" -mtime -<DAYS> -not -name "agent-*" | while read f; do
  proj=$(basename $(dirname "$f"))
  jq -rc --arg p "$proj" 'select(.type=="user" and (.message.content|type)=="string") | select(.isMeta!=true) | {p:$p, m:(.message.content[:600])}' "$f" 2>/dev/null
  jq -rc --arg p "$proj" 'select(.type=="user" and (.message.content|type)=="array") | select(.isMeta!=true) | .message.content[] | select(.type=="text") | {p:$p, m:(.text[:600])}' "$f" 2>/dev/null
done > $SCRATCH/user_prompts.jsonl
wc -l $SCRATCH/user_prompts.jsonl
```

### 3. Quantitative first pass (cheap, in-context)
- Per-project volume: `jq -r .p $SCRATCH/user_prompts.jsonl | sort | uniq -c | sort -rn | head`.
- Slash-command usage: parse `<command-name>/x</command-name>` tags from the raw transcripts with a `python3` regex counter (they don't appear in plain prompt text).
- Keyword frequency for likely patterns (commit/push, deploy, "still broken"/"again", screenshot/attached, mobile, migration, test, tooltip, correction openers like "no"/"not quite") via a `python3` regex-counter over the scratch file. This gives hard counts to anchor the report.

### 4. Deep pass — fan out parallel subagents
The corpus is too big and too pattern-dense to eyeball. `split` the scratch file into ~3 chunks and launch one **background** Agent per chunk (`run_in_background: true`, so they run concurrently). Give each the identical brief:
> Read the whole chunk (JSONL: p=project, m=user prompt). Report quantitatively:
> (1) Repeated request patterns — name, count, 2-3 verbatim short quotes.
> (2) Corrections — turns correcting prior assistant work ("no", "still broken", "again", "not what I asked", "you didn't"); count, categorize (UI detail, scope, missed instruction, wrong file, regression), quote examples.
> (2b) For each correction category, name the ROOT CAUSE, not the symptom: the one upstream
> thing — a question asked earlier, a file read first, a different verification — that would
> have prevented the whole chain. Where a correction took several rounds, say what caused each
> failed attempt, and distinguish reasonable-given-what-was-known from skipped-a-step.
> (3) Manual workflows repeated 3+ times that should be a skill/hook (multi-step things spelled out each time).
> Return a compact structured data report, not prose.

Wait for all to complete (you'll be notified). While waiting, do step 3 if not already done.

### 5. Built-but-unused inventory
List what exists vs. what the usage data shows invoked:
```
ls "$CC"/skills "$CC"/commands "$CC"/agents 2>/dev/null
ls <project>/.claude/skills <project>/.claude/commands <project>/.claude/agents 2>/dev/null
```
Cross-reference against the slash-usage counts from step 3. Flag skills/commands/agents with **0 invocations** in the window. Note that some skills auto-trigger silently (no slash), so caveat rather than declare dead.

### 6. Compile the report
Merge the subagents' findings (dedupe overlapping patterns, sum counts across chunks) with the step-3 keyword anchors. Output exactly:

1. **Top 5 repeated patterns** — each with a hard count and 2-3 short verbatim quotes.
2. **3 skills you'd create** — each tied to the pattern(s) it kills and the turn-count it would save; note if it should be global vs project.
3. **The single biggest inefficiency in how they prompt** — the one compounding, multi-turn waste (not a cheap single-turn habit), with the evidence.
4. **Never used** — built tooling with 0 invocations in the window.

Keep it evidence-led and quantitative — counts and quotes, not impressions. End the turn as a plan; offer to build the proposed skills as next steps, don't build unprompted.

**Mark every finding proved or suggested.** Proved = the same pattern recurs across more than
one chunk, or the count is large enough that a coder's judgement call can't flip it. Suggested =
one striking quote, a pattern in a single chunk, or a plausible reading of a small count. State
which each finding is. A suggested finding is a watch-item for the next run, never a firm rule,
and never the basis for proposing a skill on its own. If a section genuinely has nothing, say so
plainly rather than filling it.

### 7. Persist the durable findings to memory

The report evaporates otherwise — the whole point is that the next session starts knowing this.
After the user has seen the report, write the **proved** findings that would change how future
work gets handled into Claude Code's per-project memory at
`~/.claude/projects/<project-slug>/memory/` (the slug is derived from the project's working
directory; `MEMORY.md` in that folder is the index loaded every session).

- **Read `MEMORY.md` first.** A finding whose topic already has a file gets a dated addendum in
  that file, matching its existing structure — never a near-duplicate file.
- One fact per new file, `type: feedback` for how-to-work guidance, `type: project` for the state
  of an ongoing effort. Cross-link with `[[name]]`.
- **Every new file gets its one-line pointer in `MEMORY.md`.** A memory nothing indexes is a
  memory that never loads.
- Suggested findings do not go to memory. Name them in the report as watch-items so they don't
  silently disappear, and let the next run's counts settle them.
- A finding purely about this window's content, with no bearing on method, is not durable. Drop it.

## Optional: the collaboration-move census (`/claude-retro census`)

A second, heavier mode. The main method above finds *what the user asks for repeatedly*. This
finds *what kind of move each turn is*, so the mix can be tracked over time and the automatable
part identified. Run it when the user asks for a census, a move breakdown, or wants to know
whether a change to their instructions actually reduced a category.

**Deliverable is a census plus a trend, not a report of impressions.**

### Method

1. **Extract.** `python3 scripts/extract-turns.py $SCRATCH/turns.jsonl [days]`. This applies the
   contamination filters — see the warning below, it is the single biggest trap.
2. **Sample.** Round-robin across projects so no single repo dominates; cap per project. 500
   turns is enough for the ordering; fewer than 300 is not.
3. **Code it twice.** Split into ~20 batches, fan out one agent per batch against
   `CODEBOOK.md`, then **do the whole thing again as an independent second run.** Both runs use
   the same model and the same codebook. Each agent returns CSV only: `id,move,outcome,conf`.
4. **Report.** `python3 scripts/census.py run1.csv run2.csv`.

### Two rules that make the difference between a finding and a number

**Never report a rate from a single coding run.** Measured 2026-08-31 on 499 records: two runs
agreed on the outcome column only 71.9% exactly, 80.4% collapsed to changed-or-not, and the
"changed something" count came out 100 in one and 128 in the other. What *was* stable across
runs was the **ordering** of moves by impact. So report the ordering as the finding and any
ratio as a range across runs. `census.py` prints the warning automatically when agreement drops
below 85%.

**Machine text is not human input, and it is 40% of what looks like it.** Background-agent
completion notices, pasted quiz or brief JSON, and compaction summaries all arrive in the log
as user turns. Measured 2026-08-30 before filtering: 41.8% of all apparent user turns, and
**84% of the long ones**, because they are long and full of the exact vocabulary a
framework-shaped filter looks for. Selecting on message length without filtering measures the
machinery. Three separate kinds were found by reader agents rather than by the filter, so treat
the filter list in `extract-turns.py` as incomplete and have coders flag records with no human
message in them.

### Tracking across runs

Keep each run's CSV plus its date, codebook version and coder model. The point is the trend:
if a standing rule was added to reduce a category, that category should shrink. **Model drift is
a real confound** — different models code the same records differently, so a change in the mix
is only evidence if the coder model held constant. Record which model ran, and when it changes,
re-code one prior run with the new model before comparing.

## Notes
- Homophone typos from voice dictation are common in prompts ("superbase", "versal", "sppon") — don't mistake them for distinct patterns.
- `<task-notification>` / heartbeat / "Resume" lines are automation, not human prompts — exclude from human-prompt counts.
- **File `-mtime` is not message age.** A session file's mtime updates whenever ANY line is appended, including weeks after the file was created. `find -mtime -N` will pull in a message from long before the window if its file was touched again recently (e.g. reopened, or another agent appended to the same session). If a specific quote's date matters for the report, verify it against that line's own `.timestamp` field, not the file's mtime — don't report "flagged in the last N days" off file selection alone.
- **Background task/notification volume is not a proven cost driver.** Investigated 2026-08-02: Claude Code's caching is append-only (new content, including task-notifications, appends without invalidating the cached prefix — [prompt-caching docs](https://code.claude.com/docs/en/prompt-caching)); background processes cost "typically under $0.04 per session" ([costs docs](https://code.claude.com/docs/en/costs#background-token-usage)); Monitor is event-driven, not polling. Whether a `<task-notification>` itself triggers a fresh cache-read the way a real user turn does is undocumented/unconfirmed either way. Don't flag a high count of background wake-ups as a cost problem without that caveat — the documented cost driver is turn/conversation length (cache-read-per-turn), not notification volume per se.
