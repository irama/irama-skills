#!/bin/bash
# SessionStart hook: kill Claude Code shell-snapshot processes that have been
# orphaned (reparented to launchd, PPID 1) and are older than an hour.
#
# Why: a crashed session leaves its background Bash tasks spinning. Measured
# 2026-09-06: six orphans at ~100% CPU each, 34 hours, ~180 CPU-hours burned.
# Their output files were already deleted, so nothing could ever read them.
#
# PPID 1 is the whole safety story: a live session's shells are parented to the
# claude process, so they can never match.
#
# ponytail: fixed 1h threshold, no config. Add one when a real case needs it.

MIN_AGE_SECONDS=3600

# Reads `ps -Ao pid,ppid,etime,command` lines on stdin, prints reapable PIDs.
# Kept as a function so --self-test can drive it with fixtures.
select_orphans() {
  awk -v min="$MIN_AGE_SECONDS" '
    $2 != 1 { next }
    $0 !~ /shell-snapshots/ { next }
    {
      # etime is [[DD-]HH:]MM:SS
      days = 0
      clock = $3
      if (split($3, t, "-") > 1) { days = t[1]; clock = t[2] }
      n = split(clock, c, ":")
      secs = 0
      for (i = 1; i <= n; i++) secs = secs * 60 + c[i]
      secs += days * 86400
      if (secs >= min) print $1
    }
  '
}

if [ "$1" = "--self-test" ]; then
  got=$(printf '%s\n' \
    "111 1 02:30 /bin/zsh -c source /x/shell-snapshots/s.sh" \
    "222 1 01:02:30 /bin/zsh -c source /x/shell-snapshots/s.sh" \
    "333 1 3-01:02:30 /bin/zsh -c source /x/shell-snapshots/s.sh" \
    "444 900 9-00:00:00 /bin/zsh -c source /x/shell-snapshots/s.sh" \
    "555 1 9-00:00:00 /usr/sbin/some-daemon" \
    | select_orphans | tr '\n' ' ')
  [ "$got" = "222 333 " ] || { echo "FAIL: got [$got], want [222 333 ]"; exit 1; }
  echo "ok"
  exit 0
fi

pids=$(ps -Ao pid,ppid,etime,command | select_orphans)
[ -n "$pids" ] || exit 0

csv=$(echo "$pids" | tr '\n' ',')
# shellcheck disable=SC2086
kill $pids 2>/dev/null
sleep 2
still=$(ps -o pid= -p "${csv%,}" 2>/dev/null)
# shellcheck disable=SC2086
[ -n "$still" ] && kill -9 $still 2>/dev/null

echo "Reaped $(echo "$pids" | wc -l | tr -d ' ') orphaned shell(s) from a dead session: ${csv%,}"
