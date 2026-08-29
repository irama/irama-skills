#!/usr/bin/env bash
# Restore a gitignored secret/config file from the secret-snapshot backups.
#
#   restore-secret.sh [file] [--apply]
#     file     defaults to .env.local in the current directory
#     (no flag) lists available backups (newest first) and prints the newest
#     --apply  writes the newest backup over <file> (backing up the current
#              <file> first, if non-empty)
#
# Backups live at ~/.claude/secret-backups/<cwd-slug>/<basename>/<ISO>.bak
set -euo pipefail

FILE="${1:-.env.local}"
[[ "${FILE}" == "--apply" ]] && FILE=".env.local"
APPLY=false
for a in "$@"; do [[ "$a" == "--apply" ]] && APPLY=true; done

ABS="$(cd "$(dirname "$FILE")" 2>/dev/null && pwd)/$(basename "$FILE")" || ABS="$PWD/$FILE"
CWD="$(dirname "$ABS")"
NAME="$(basename "$ABS")"
SLUG="$(printf '%s' "$CWD" | sed 's/[^A-Za-z0-9]\{1,\}/-/g; s/^-//; s/-$//' | cut -c1-120)"
BDIR="$HOME/.claude/secret-backups/$SLUG/$NAME"

if [[ ! -d "$BDIR" ]]; then
  echo "No backups for $NAME under $CWD" >&2
  echo "(looked in $BDIR)" >&2
  exit 1
fi

BACKUPS=()
while IFS= read -r line; do BACKUPS+=("$line"); done < <(ls -1 "$BDIR"/*.bak 2>/dev/null | sort -r)
if [[ ${#BACKUPS[@]} -eq 0 ]]; then
  echo "No .bak files in $BDIR" >&2
  exit 1
fi

echo "Backups for $NAME (newest first):"
i=0
for b in "${BACKUPS[@]}"; do
  [[ $i -ge 12 ]] && break
  printf '  %s  (%s bytes)\n' "$(basename "$b")" "$(wc -c <"$b" | tr -d ' ')"
  i=$((i+1))
done
NEWEST="${BACKUPS[0]}"
echo "Newest: $NEWEST"

if $APPLY; then
  if [[ -s "$ABS" ]]; then
    ts="$(date +%Y%m%dT%H%M%S)"
    cp -p "$ABS" "$ABS.pre-restore-$ts"
    echo "Saved current $NAME → $NAME.pre-restore-$ts"
  fi
  cp -p "$NEWEST" "$ABS"
  echo "Restored $NAME from $(basename "$NEWEST")"
else
  echo "Dry run. Re-run with --apply to write the newest backup over $NAME."
fi
