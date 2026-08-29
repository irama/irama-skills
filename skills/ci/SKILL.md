---
name: ci
description: Check GitHub Actions CI status and extract failure details. Use when user says "check CI", "CI failures", "what's failing in CI", or invokes /ci.
---

Check GitHub Actions CI status for the current repo and surface just the failure details — no massive log dumps.

## Prerequisites

Before doing anything, verify the `gh` CLI is available and authenticated:

```
gh auth status
```

If `gh` is not installed or not authenticated, tell the user and stop. Do not attempt workarounds.

## Arguments

The skill accepts an optional argument:

- `/ci` — check the latest run across all branches
- `/ci main` — check the latest run on the `main` branch
- `/ci 12345` — check a specific run by database ID

Determine which form the user used:

- Pure digits → treat as a run ID
- Any other non-empty string → treat as a branch name filter
- Empty → no filter, latest runs

## Steps

### Fetch recent runs

If a **branch name** was given, add `--branch <name>` to the command. If a **run ID** was given, skip this step and go straight to step 3 using that ID.

```bash
gh run list -L5 --json name,status,conclusion,headBranch,createdAt,databaseId,headSha
```

### Check for failures

Scan the returned runs:

- If all recent runs have `conclusion == "success"` (or are still `in_progress`), report that clearly and stop. Mention the branch, workflow name, and how long ago each completed.
- If any run has `conclusion == "failure"`, pick the **most recent failed run** and continue to the next step.
- If a run is `in_progress`, mention it but still surface the latest failure if one exists.

### Extract failure details

For the failing run (call its `databaseId` `<ID>`):

**a) Identify the failed job(s) and step(s):**

```bash
gh run view <ID> --json jobs --jq '.jobs[] | select(.conclusion=="failure") | {name, conclusion, steps: [.steps[] | select(.conclusion=="failure") | .name]}'
```

**b) Extract error lines from the failed log:**

```bash
gh run view <ID> --log-failed 2>/dev/null | grep '##\[error\]' | grep -v 'Process completed'
```

Deduplicate identical error lines — CI often repeats them.

**c) Special handling for test failures:**

If the failed step name contains "test" (case-insensitive) — e.g. "Test with coverage", "Run tests", "vitest", "jest" — also extract the failing test names:

```bash
gh run view <ID> --log-failed 2>/dev/null | grep -E '(FAIL |FAILED |✕ |✗ |× )' | head -30
```

This catches vitest, jest, and most TAP-style reporters. Limit to 30 lines to keep output manageable.

### Present a clean summary

Format the output as:

```
**Run:** <ID> on `<branch>` (<workflow name>)
**Status:** Failed
**Failed job(s):** <job name(s)>
**Failed step(s):** <step name(s)>

**Errors:**
- <deduplicated error line 1>
- <deduplicated error line 2>
```

If test failures were detected, add:

```
**Failing tests:**
- <test file or test name 1>
- <test file or test name 2>
```

Keep the summary concise. Strip ANSI escape codes and CI timestamp prefixes from error lines so the output is clean.

### Offer next steps

After presenting the summary, ask the user if they want to fix the issues. If the errors are clear enough to act on (e.g. type errors, lint failures, specific test assertions), briefly suggest what the fix might involve.

## Notes

- This is a **project-agnostic** skill — it works on any repo with GitHub Actions. Do not assume any specific CI workflow or tooling.
- `gh` respects the git context of the current directory, so no `cd` or repo flags are needed.
- If `gh run view --log-failed` produces no output (some workflow types), fall back to `gh run view <ID> --log` piped through the same grep filters, but limit to the last 100 lines to avoid dumping the entire log.
- Never dump raw CI logs to the user. The entire point of this skill is to extract signal from noise.
