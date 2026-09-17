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
#
# The guard is on the PUSH, not on worktree creation, because "ungated push" is the
# actual failure — however the worktree came to exist, and whoever made it.
#
# 2026-09-17: the guard used to check only the session's cwd. A fleet sweep ran from
# one repo and pushed twelve others with `git -C "$W" push origin HEAD:main` in a
# loop. The guard checked the repo the session sat in, which had hooks, and allowed
# every push; eleven went out ungated. So the guard now resolves the repo each push
# actually targets (`git -C <dir>`, or a `cd <dir>` earlier in the same command), and
# refuses what it cannot resolve (a path held in a shell variable) or what switches the
# gate off (`--no-verify`, `-c core.hooksPath=`). A leading `ALLOW_UNGATED_PUSH=1` on the
# push is the escape hatch for a push the gate genuinely cannot run for.
#
# Order per target: try to install the hooks (delegating to
# worktree-install-git-hooks.sh, one copy of that logic); allow the push if that
# worked; deny only if the gate still cannot run. Repos using the shared .git/hooks
# are untouched.
set -uo pipefail

input="$(cat 2>/dev/null || true)"

# One line per push in the command: TARGET<TAB>dir, UNRESOLVED<TAB>text, or NOVERIFY.
# The parsing lives in push_guard_targets.py beside this file.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
plan="$(printf '%s' "$input" | python3 "$here/push_guard_targets.py" 2>/dev/null || true)"

[ -n "$plan" ] || exit 0

deny_noverify() {
  cat >&2 <<'EOF'
BLOCKED: `git push --no-verify` skips the pre-push gate. The push would go out with no
typecheck, lint or tests, and no attestation reaches the status hub, so its CI tile
turns amber.

Push without --no-verify. If the gate genuinely cannot run for this push, say so to
the user first, then prefix the command with ALLOW_UNGATED_PUSH=1.
EOF
  exit 2
}

deny_unresolved() {
  cat >&2 <<EOF
BLOCKED: cannot tell which repo this push targets, so cannot check that its pre-push
gate will run.

  push:  $1

The repo path is held in a shell variable (for example \`git -C "\$W" push\` in a loop,
or \`cd "\$dir" && git push\`). Write each push with a literal path instead, one repo per
command, for example:

  git -C /absolute/path/to/repo push origin HEAD:main
EOF
  exit 2
}

check_target() {
  local dir="$1" hooks_path top target
  [ -d "$dir" ] || return 0
  git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0

  hooks_path="$(git -C "$dir" config --get core.hooksPath || true)"
  [ -n "$hooks_path" ] || return 0   # repo uses .git/hooks, shared with every worktree

  top="$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null || true)"
  [ -n "$top" ] || return 0
  case "$hooks_path" in /*) target="$hooks_path" ;; *) target="$top/$hooks_path" ;; esac
  [ -d "$target" ] && return 0       # gate is present

  # Missing. Try to install it rather than just complaining.
  printf '{"cwd":%s}' "$(printf '%s' "$top" | python3 -c 'import sys,json;print(json.dumps(sys.stdin.read()))')" \
    | bash "$HOME/.claude/hooks/worktree-install-git-hooks.sh" >/dev/null 2>&1

  if [ -d "$target" ]; then
    printf '[require-git-hooks] installed missing %s in %s before push\n' "$hooks_path" "$top" >&2
    return 0
  fi

  cat >&2 <<EOF
BLOCKED: this checkout has no git hooks, so \`git push\` would run with NO pre-push gate.

  repo:             $top
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
}

while IFS=$'\t' read -r kind value; do
  case "$kind" in
    NOVERIFY) deny_noverify ;;
    UNRESOLVED) deny_unresolved "$value" ;;
    TARGET) check_target "$value" ;;
  esac
done <<< "$plan"
exit 0
