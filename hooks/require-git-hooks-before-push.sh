#!/usr/bin/env bash
# require-git-hooks-before-push.sh
#
# Global Claude Code hook (PreToolUse on Bash). Refuses a `git push` that would
# run with NO pre-push gate, and self-heals first so it almost never has to.
#
# Why this exists (2026-07-31): the fleet's repos set
# `core.hooksPath = .husky/_`, which is husky's generated, gitignored runtime dir.
# A worktree created by hand with `git worktree add` therefore has no hooks at all
# — git finds nothing and runs NOTHING. `worktree-install-git-hooks.sh` covers the
# EnterWorktree path, but a raw `git worktree add` bypasses it entirely, and a push
# from that worktree went out with no typecheck, no lint, no build, no attestation.
# The same push from the main checkout was refused instantly by the real gate.
#
# The guard is on the PUSH, not on worktree creation, because "ungated push" is the
# actual failure — however the worktree came to exist, and whoever made it.
#
# Order: try to install the hooks (delegating to worktree-install-git-hooks.sh, one
# copy of that logic); allow the push if that worked; deny only if the gate still
# cannot run. Non-push commands and repos using the shared .git/hooks are untouched.
set -uo pipefail

input="$(cat 2>/dev/null || true)"
# Read the two fields separately — the command can contain anything, so splitting one
# combined line on whitespace would mangle it.
cmd="$(printf '%s' "$input" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null || true)"
cwd="$(printf '%s' "$input" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("cwd",""))' 2>/dev/null || true)"

# Only guard a real push. `--dry-run` contacts the remote but changes nothing.
printf '%s' "$cmd" | grep -Eq '(^|[;&|[:space:]])git[[:space:]]+([^;&|]*[[:space:]])?push([[:space:]]|$)' || exit 0
printf '%s' "$cmd" | grep -q -- '--dry-run' && exit 0

[ -n "$cwd" ] || cwd="$PWD"
cd "$cwd" 2>/dev/null || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

hooks_path="$(git config --get core.hooksPath || true)"
[ -n "$hooks_path" ] || exit 0   # repo uses .git/hooks — shared with every worktree, fine

top="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$top" ] || exit 0
case "$hooks_path" in /*) target="$hooks_path" ;; *) target="$top/$hooks_path" ;; esac
[ -d "$target" ] && exit 0       # gate is present, nothing to do

# Missing. Try to install it rather than just complaining.
printf '{"cwd":%s}' "$(printf '%s' "$cwd" | python3 -c 'import sys,json;print(json.dumps(sys.stdin.read()))')" \
  | bash "$HOME/.claude/hooks/worktree-install-git-hooks.sh" >/dev/null 2>&1

if [ -d "$target" ]; then
  printf '[require-git-hooks] installed missing %s before push\n' "$hooks_path" >&2
  exit 0
fi

cat >&2 <<EOF
BLOCKED: this checkout has no git hooks, so \`git push\` would run with NO pre-push gate.

  cwd:              $cwd
  core.hooksPath:   $hooks_path
  missing dir:      $target

That directory is husky's generated, gitignored runtime dir, so a worktree created
with a raw \`git worktree add\` never gets it — typecheck, lint, tests and the status-hub
attestation all silently do not run, and the push goes out unverified.

Fix one of these, then push again:
  * run the gate's install:  (cd "$top" && npx --no-install husky)
  * or push from the main checkout, where the hooks exist
  * or, if this repo genuinely has no gate, unset it: git config --unset core.hooksPath

Do NOT point core.hooksPath at an absolute path — that makes every worktree run the
main checkout's hooks against the wrong tree.
EOF
exit 2
