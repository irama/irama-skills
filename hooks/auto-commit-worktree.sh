#!/usr/bin/env bash
# auto-commit-worktree.sh — Stop hook.
# Convention: because worktrees make commits cheap and reversible, auto-commit
# whenever Claude finishes work in a FEATURE-BRANCH worktree. Then restart the
# local dev server so the latest is testable. The user runs /merge manually.
#
# Hard guards (fail-safe, exit 0 always so a stop is never blocked):
#   - only inside a git work tree
#   - NEVER on the default branch (main/master) — those changes reach prod via /push
#   - only when there are actual changes
#   - --no-verify (WIP checkpoint; real gates run at /commit or /merge)

set -uo pipefail

INPUT=$(cat 2>/dev/null || true)
CWD=$(printf '%s' "$INPUT" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("cwd",""))
except Exception: print("")' 2>/dev/null)
[ -z "$CWD" ] && CWD="$PWD"
cd "$CWD" 2>/dev/null || exit 0

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

# Opt-out: a `.claude/no-auto-commit` marker at the MAIN repo root disables
# auto-commit for that repo and all its worktrees.
COMMON=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
MAINROOT=$(dirname "$COMMON" 2>/dev/null)
[ -f "$MAINROOT/.claude/no-auto-commit" ] && exit 0
[ -f "$CWD/.claude/no-auto-commit" ] && exit 0

BR=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
DEF=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')
[ -z "$DEF" ] && DEF=main

# Guard: never auto-commit on the default branch.
[ "$BR" = "$DEF" ] && exit 0
# Guard: skip mid-merge/rebase states.
[ -d "$(git rev-parse --git-dir)/rebase-merge" ] && exit 0
[ -f "$(git rev-parse --git-dir)/MERGE_HEAD" ] && exit 0
# Guard: only if something changed.
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
  exit 0
fi

git add -A 2>/dev/null || exit 0
git commit --no-verify -m "chore: wip auto-commit ($BR)" >/dev/null 2>&1 || exit 0

# Restart the dev server (no --clean, keep it fast) so the latest is testable.
URL=$(bash "$HOME/.claude/scripts/localhost-dev.sh" "$CWD" 2>/dev/null | tail -1)
[ -n "$URL" ] && echo "[auto-commit] $BR committed; dev at $URL" >&2

exit 0
