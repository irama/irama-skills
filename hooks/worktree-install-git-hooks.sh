#!/usr/bin/env bash
# worktree-install-git-hooks.sh
#
# Global Claude Code hook (PostToolUse on EnterWorktree). Makes sure every git
# worktree actually RUNS its repo's git hooks.
#
# Why this exists (2026-07-26): repos here set
# `core.hooksPath = .husky/_`, and `.husky/_` is husky's generated runtime dir —
# gitignored, so a freshly-created worktree does not have it. Git then finds no
# pre-commit/pre-push hook and runs NOTHING: the local gate (typecheck + lint +
# tests) silently does not fire, the push goes out ungated, and no attestation
# reaches the status hub. Two books pushes went out that way before anyone
# noticed. A gate that silently doesn't run is worse than no gate.
#
# Fix, cheapest first:
#   1. hardlink/copy `.husky/_` from the main worktree (no npm, instant), or
#   2. `npx husky` if node_modules is present but the main copy isn't.
#
# Fails silent (exit 0) always — a hook must never block the tool it follows.
set -uo pipefail

log() { printf '[worktree-git-hooks] %s\n' "$1" >&2; }

# Hook stdin is JSON; `cwd` is the session dir (already inside the new worktree).
input="$(cat 2>/dev/null || true)"
cwd="$(printf '%s' "$input" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("cwd",""))' 2>/dev/null || true)"
[ -n "$cwd" ] || cwd="$PWD"
[ -d "$cwd" ] || exit 0

cd "$cwd" 2>/dev/null || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

hooks_path="$(git config --get core.hooksPath || true)"
[ -n "$hooks_path" ] || exit 0                 # repo uses .git/hooks — shared, nothing to do

top="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$top" ] || exit 0
case "$hooks_path" in /*) target="$hooks_path" ;; *) target="$top/$hooks_path" ;; esac
[ -d "$target" ] && exit 0                     # already installed

# The main worktree's copy: git-common-dir's parent.
common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
main_root="${common%/.git}"
source_dir="$main_root/$hooks_path"

if [ -d "$source_dir" ]; then
  mkdir -p "$(dirname "$target")"
  cp -R "$source_dir" "$target" 2>/dev/null && log "installed $hooks_path from $main_root"
elif [ -d "$top/node_modules/husky" ]; then
  (cd "$top" && npx --no-install husky >/dev/null 2>&1) && log "ran husky in $top"
fi

# Never fail the tool.
exit 0
