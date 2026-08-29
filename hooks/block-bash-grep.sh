#!/usr/bin/env bash
# PreToolUse hook: block standalone grep/rg/egrep/fgrep in Bash, redirect to ast-grep (sg).
# Reads Claude Code hook JSON on stdin. Exit 2 + stderr blocks the tool call and surfaces
# the message to the model. Pipelines like `cmd | grep ...` are left alone (filtering use).

set -u

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""')

# Strip leading whitespace.
CMD_TRIM=$(printf '%s' "$CMD" | sed -E 's/^[[:space:]]+//')

# Allow `git grep` — operates on the repo index, not a generic grep replacement.
if printf '%s' "$CMD_TRIM" | grep -qE '^git[[:space:]]+grep([[:space:]]|$)'; then
  exit 0
fi

# Block commands that START with grep / rg / egrep / fgrep (with optional env-var prefix is rare; skip).
if printf '%s' "$CMD_TRIM" | grep -qE '^(grep|rg|egrep|fgrep)([[:space:]]|$)'; then
  cat >&2 <<'MSG'
Bash grep/rg/egrep/fgrep disabled globally. Take the FIRST line that fits:

1. ONE FILE YOU ALREADY NAMED -> pipeline, still allowed, cheapest:
     cat path/to/file.ts | grep -n -C3 'needle'

   (The Grep TOOL is disabled globally too -- it is never the answer.)

2. CODE STRUCTURE across a tree (a call, function, JSX element) -> ast-grep (sg):
     sg --pattern 'console.log($A)' --lang ts path/
     sg run -p 'function $NAME($$$) { $$$ }' --lang ts

3. LITERAL TEXT across MANY files (a string/email/path in .md/.json/config),
   and only then -> python walk (sg parses code only, so it cannot do this):
     python3 - <<'PY'
     import os
     ROOT="."; NEEDLE="text-to-find"
     for dp,_,fs in os.walk(ROOT):
         if "/.git/" in dp: continue
         for f in fs:
             p=os.path.join(dp,f)
             try: s=open(p,encoding="utf-8",errors="ignore").read()
             except: continue
             if NEEDLE in s: print(p, s.count(NEEDLE))
     PY

Do NOT reach for the python walk to search a single known file. Line 1 is shorter.
Pipelines (`cmd | grep ...`) are always allowed for filtering.
MSG
  exit 2
fi

exit 0