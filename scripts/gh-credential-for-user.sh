#!/bin/bash
# Git credential helper that routes to a specific gh account.
# Usage in .git/config:
#   [credential "https://github.com"]
#     helper = !'$HOME/.claude/scripts/gh-credential-for-user.sh' <github-user>

set -e
TARGET_USER="$1"
ACTION="$2"

if [ "$ACTION" != "get" ]; then
  exit 0
fi

# Read stdin (git credential protocol)
while IFS= read -r line; do
  [ -z "$line" ] && break
done

# Get current active user
CURRENT=$(gh auth status 2>&1 | awk '/Active account: true/{found=1} found && /account /{print $NF; exit}' | tr -d '()')
CURRENT=$(gh api user --jq '.login' 2>/dev/null || echo "")

SWITCHED=false
if [ "$CURRENT" != "$TARGET_USER" ]; then
  gh auth switch --user "$TARGET_USER" 2>/dev/null
  SWITCHED=true
fi

printf 'protocol=https\nhost=github.com\nusername=%s\n\n' "$TARGET_USER" | gh auth git-credential get

if [ "$SWITCHED" = true ] && [ -n "$CURRENT" ]; then
  gh auth switch --user "$CURRENT" 2>/dev/null
fi
