#!/bin/zsh
# Reap stale Next.js build caches across ~/LOCAL-DEV (main checkouts AND worktrees).
#
# Deletes only `.next/cache` (the big webpack/turbopack .pack/.sst blobs), never the
# whole `.next` — so a project's compiled output survives; only the regenerable cache
# goes. Next rebuilds it on the next `dev`/`build`. Guarded by mtime: a cache dir touched
# within DAYS (i.e. an actively-running dev server) is fresh and skipped automatically.
#
# Usage: reap-next-cache.sh [DAYS]   (default 3). Run by the daily LaunchAgent, or by hand.
set -u
DAYS="${1:-3}"
ROOT="$HOME/LOCAL-DEV"
LOG="$HOME/.claude/logs/reap-next-cache.log"
mkdir -p "$(dirname "$LOG")"

reaped=0
freed_note=""
# -prune stops find descending into the matched cache dir; -mtime +DAYS = stale only.
while IFS= read -r d; do
  [ -d "$d" ] || continue
  sz=$(du -sk "$d" 2>/dev/null | awk '{print $1}')
  rm -rf "$d" && reaped=$((reaped + 1)) && freed_note="$freed_note $((sz/1024))M:$d"
done < <(find "$ROOT" -type d -path '*/.next/cache' -prune -mtime +"$DAYS" 2>/dev/null)

echo "$(date '+%Y-%m-%d %H:%M') reaped $reaped stale .next/cache (>${DAYS}d)$freed_note" >> "$LOG"

# Bound the Claude Desktop HTTP cache: nuke it only when it has bloated past a threshold.
# It's a Chromium cache — safe to clear, the app refills it. Size-gated (not mtime) since it
# stays "fresh" while the app runs, so mtime would never let it go.
CLAUDE_CACHE="$HOME/Library/Application Support/Claude/Cache"
CAP_MB=500
if [ -d "$CLAUDE_CACHE" ]; then
  cur=$(du -sm "$CLAUDE_CACHE" 2>/dev/null | awk '{print $1}')
  if [ "${cur:-0}" -gt "$CAP_MB" ]; then
    rm -rf "$CLAUDE_CACHE/"* 2>/dev/null
    echo "$(date '+%Y-%m-%d %H:%M') cleared Claude Cache (${cur}M > ${CAP_MB}M cap)" >> "$LOG"
  fi
fi
