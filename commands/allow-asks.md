---
description: Review the permission-prompt log, propose allow-rule patterns, and append approved ones to ~/.claude/settings.json
---

You are running the `/allow-asks` workflow. Goal: turn captured permission prompts into reusable allow-rules with one approval step.

## Inputs

- Log file: `~/.claude/permission-prompts.log`
  Each line: `ISO-TIMESTAMP [ToolName] command-or-input-json`
- Settings file: `~/.claude/settings.json`
  Append to `.permissions.allow` array.

## Steps

1. **Read log.** If file missing or empty → tell user "No prompts captured yet" and stop.

2. **Parse + group.** For each line:
   - Extract `[ToolName]` and the trailing payload.
   - For `Bash`, normalize the command into a *shape* by collapsing volatile tokens to `*`:
     - Absolute paths (`/Users/...`, `/tmp/...`, `/private/...`) → `*`
     - Quoted strings (`"..."`, `'...'`) → `*`
     - Standalone numbers (e.g. `head -20`, `--timeout 30`) → `*`
     - Hashes / UUIDs / long hex → `*`
   - For `Edit`/`Write`/`Read`, shape = `ToolName(<dirname-of-path>/**)`.
   - Group identical shapes, count occurrences.

3. **Filter.** Drop shapes already covered by an existing rule in `.permissions.allow`. Read settings once, do a string-shape comparison.

4. **Rank.** Sort by count desc. Take top 15.

5. **Propose rules.** For each shape, emit a Claude Code permission-rule string:
   - Bash: `Bash(<shape>)` — keep the `*` wildcards from step 2.
   - File tools: the `ToolName(path/**)` shape from step 2.

6. **Present + ask.** Show a numbered table: `count | shape | proposed rule`. Use `AskUserQuestion` (multiSelect) to let the user pick which to add. Always include an "all" and "none" choice.

7. **Append.** For each approved rule, `Edit` `.permissions.allow` to add it before the closing `]`. Preserve formatting. Skip exact duplicates.

8. **Validate.** Run `jq -e '.permissions.allow | length' ~/.claude/settings.json` — confirm valid JSON and report new length.

9. **Report.** Caveman-style: `N rules added. Log unchanged. Restart or /hooks to activate.` Do NOT delete the log — user may want history.

## Rules

- **Generalize, never literal.** Every proposed rule must contain at least one `*` wildcard. Never propose a rule that bakes in a specific file path, project name, message string, or one-off command — if a shape can't be generalized into a pattern that will plausibly recur across projects, drop it rather than propose it. (The 2026-07 settings cleanup removed ~150 literal one-offs that accumulated this way.)
- Never auto-approve. Always go through `AskUserQuestion`.
- Never widen scope beyond what the log shows. If shape is `Bash(rm -rf *)` flag it as RED and require explicit confirm before proposing.
- Skip shapes containing `rm -rf /`, `> /etc/`, `chmod 777`, or `curl * | bash` — print as "dangerous, not proposed" instead of offering.
- If log has 0 ungrouped entries after filtering: stop, tell user nothing new.