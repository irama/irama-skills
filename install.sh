#!/usr/bin/env bash
# Install irama-skills into ~/.claude by symlink.
#
# Symlinks rather than copies, so `git pull` in this repo updates your skills
# with nothing to re-sync. Existing files are never overwritten — anything
# already present is reported and skipped.
#
#   ./install.sh            # link skills, agents, commands, rules
#   ./install.sh --hooks    # also link hooks/ (read README first — they are opinionated)
#   ./install.sh --dry-run  # show what would happen, change nothing
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
DRY=0
HOOKS=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --hooks)   HOOKS=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

linked=0; skipped=0

say() { [ "$DRY" -eq 1 ] && echo "would $*" || echo "$*"; }

link_item() {
  local src="$1" dest="$2"
  if [ -e "$dest" ] && [ ! -L "$dest" ]; then
    echo "  skip    $(basename "$dest") — already exists and is not a symlink"
    skipped=$((skipped + 1))
    return
  fi
  if [ -L "$dest" ] && [ "$(readlink "$dest")" != "$src" ]; then
    echo "  skip    $(basename "$dest") — symlink points elsewhere"
    skipped=$((skipped + 1))
    return
  fi
  say "  link    $(basename "$dest")"
  [ "$DRY" -eq 0 ] && ln -sfn "$src" "$dest"
  linked=$((linked + 1))
}

link_dir_contents() {
  local kind="$1"
  [ -d "$REPO/$kind" ] || return 0
  mkdir -p "$CLAUDE/$kind"
  echo "$kind/"
  for item in "$REPO/$kind"/*; do
    [ -e "$item" ] || continue
    link_item "$item" "$CLAUDE/$kind/$(basename "$item")"
  done
}

echo "repo:   $REPO"
echo "target: $CLAUDE"
[ "$DRY" -eq 1 ] && echo "(dry run — nothing will change)"
echo

mkdir -p "$CLAUDE"
for kind in skills agents commands rules; do
  link_dir_contents "$kind"
done
[ "$HOOKS" -eq 1 ] && link_dir_contents hooks

echo
echo "linked: $linked   skipped: $skipped"
echo
echo "Next:"
echo "  1. Merge settings.example.json into $CLAUDE/settings.json (do not overwrite yours)."
echo "  2. Restart Claude Code — skills are read at session start."
if [ "$HOOKS" -eq 0 ]; then
  echo "  3. Hooks were NOT installed. See README.md, then re-run with --hooks if you want them."
else
  echo "  3. Hooks linked but NOT active until you reference them in settings.json — see README.md."
fi
