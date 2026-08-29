#!/bin/bash
# Statusline composer for Claude Code.
#
# Claude Code allows exactly one statusLine command, so this joins the
# segments. It captures stdin ONCE (the segment JSON) and feeds a copy to each
# segment script, since stdin can only be consumed once.
#
#   "statusLine": { "type": "command", "command": "bash \"$HOME/.claude/hooks/statusline.sh\"" }
#
# Segments are independent: one failing must never blank the line, so each is
# run with its failure swallowed.

DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks"
STDIN=$(cat)

# Debug aid: `touch ~/.claude/.statusline-debug` to capture the raw payload
# once, then inspect it and delete the marker. Off by default.
DEBUG_MARKER="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.statusline-debug"
if [ -f "$DEBUG_MARKER" ]; then
  printf '%s' "$STDIN" > /tmp/statusline-stdin.json 2>/dev/null
  rm -f "$DEBUG_MARKER"
fi

OUT=""
add() { [ -n "$1" ] && OUT="${OUT:+$OUT }$1"; }

add "$(printf '%s' "$STDIN" | bash "$DIR/caveman-statusline.sh" 2>/dev/null)"
add "$(printf '%s' "$STDIN" | python3 "$DIR/session-cost-statusline.py" 2>/dev/null)"

printf '%s' "$OUT"
