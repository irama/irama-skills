#!/bin/bash
# Git credential helper that routes a repo to a specific gh account.
#
# Usage in .git/config:
#   [credential "https://github.com"]
#     helper = !'$HOME/.claude/scripts/gh-credential-for-user.sh' <github-user>
#
# It asks gh for that account's token directly. The previous version switched
# the ACTIVE account, read the token, then switched back — which raced: a push
# could be handed the wrong account's token and fail with a 403 naming the other
# user. Never switch a global setting to read a per-repo value.

set -e
TARGET_USER="$1"
ACTION="$2"

[ "$ACTION" = "get" ] || exit 0

# Drain the git credential request; the target account is the argument, not
# anything git tells us.
while IFS= read -r line; do
  [ -z "$line" ] && break
done

TOKEN=$(gh auth token --user "$TARGET_USER" 2>/dev/null) || {
  echo "gh-credential-for-user: no gh token for '$TARGET_USER' — run: gh auth login --user $TARGET_USER" >&2
  exit 1
}

printf 'protocol=https\nhost=github.com\nusername=%s\npassword=%s\n' "$TARGET_USER" "$TOKEN"
