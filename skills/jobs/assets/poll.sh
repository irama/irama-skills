#!/usr/bin/env bash
# One tick of the /jobs background poller. launchd runs it every 60 s (install-poller.sh).
#
# launchd gives no login-shell environment, so every path comes from
# ~/.config/jobs/poller.env, which the installer writes. Each tick:
#   1. Takes the lock (a directory holding the run's PID). A lock whose PID is dead is removed.
#   2. Makes one `jobs.py list --column backlog --source zero` call.
#   3. Takes the oldest waiting ZERO job with a tagged target that was never started here.
#   4. Runs `claude -p "/jobs JOB-<id> --background"` from $HOME, in the background, and
#      kills it after 45 minutes (macOS has no `timeout`).
#   5. Sends Telegram when the card reaches In review or the run fails.
# The tick stays in the foreground while the run lives, so launchd starts no second tick.
# It never reads or writes claims.json: jobs.py owns that file.
set -uo pipefail

CFG_DIR="$HOME/.config/jobs"
CONF="$CFG_DIR/poller.env"
LOCK="$CFG_DIR/poller.lock"
TRIED="$CFG_DIR/poller-tried"
LOG="${JOBS_POLLER_LOG:-$HOME/Library/Logs/jobs-poller.log}"
LIMIT="${JOBS_POLLER_LIMIT:-2700}"   # seconds; tests shorten it
STEP="${JOBS_POLLER_STEP:-5}"        # watchdog check interval, seconds

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }

mkdir -p "$(dirname "$LOG")" "$CFG_DIR"
[ -f "$CONF" ] || { log "no $CONF: run install-poller.sh"; exit 2; }
# shellcheck disable=SC1090
. "$CONF"
for v in CLAUDE_BIN PYTHON3_BIN SKILL_DIR; do
  [ -n "${!v:-}" ] || { log "poller.env lacks $v"; exit 2; }
done
export PATH="${POLLER_PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"
[ -n "${JOBS_REPOS_ROOT:-}" ] && export JOBS_REPOS_ROOT
J=("$PYTHON3_BIN" "$SKILL_DIR/assets/jobs.py")

notify() {
  if [ -n "${TELEGRAM_SEND:-}" ] && [ -x "$TELEGRAM_SEND" ]; then
    "$TELEGRAM_SEND" "$1" >>"$LOG" 2>&1 || log "telegram send failed"
  fi
}

# ── Lock ─────────────────────────────────────────────────────────────────────
if ! mkdir "$LOCK" 2>/dev/null; then
  held=$(cat "$LOCK/pid" 2>/dev/null || true)
  if [ -n "$held" ] && kill -0 "$held" 2>/dev/null; then
    exit 0 # a run is active
  fi
  if [ -z "$held" ]; then
    # The pid file is written just below, after mkdir, so a lock dir that still has no
    # pid file can be another tick mid-creation rather than abandoned. Give it ~5s.
    age=$(( $(date +%s) - $(stat -f %m "$LOCK" 2>/dev/null || stat -c %Y "$LOCK" 2>/dev/null || echo 0) ))
    [ "$age" -ge 5 ] || exit 0 # another tick is still writing its pid
  fi
  # ponytail: a reused PID reads as alive and holds the lock until that process ends.
  log "removed stale lock (pid ${held:-none})"
  rm -rf "$LOCK"
  mkdir "$LOCK" 2>/dev/null || exit 0
fi
pid_tmp="$LOCK/pid.$$"
echo $$ >"$pid_tmp"
mv "$pid_tmp" "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

# ── Pick ─────────────────────────────────────────────────────────────────────
touch "$TRIED"
# --all-pages: without it, a full first page of tried/stuck backlog jobs could hide
# every newer job behind them.
if ! listing=$("${J[@]}" list --column backlog --source zero --all-pages 2>&1); then
  log "list failed: $(printf '%s' "$listing" | tr '\n' ' ' | cut -c1-300)"
  exit 1
fi
# Client-side check as well, so a hub that ignores ?source can never start a board job.
pick=$(printf '%s' "$listing" | "$PYTHON3_BIN" -c '
import json, sys
tried = {l.strip() for l in open(sys.argv[1]) if l.strip()}
jobs = [j for j in json.load(sys.stdin).get("jobs", [])
        if j.get("source") == "zero" and j.get("column") == "backlog" and j.get("targets")
        and not j.get("claimed") and str(j.get("id")) not in tried]
if jobs:
    j = min(jobs, key=lambda j: j["id"])
    print(j["id"], (j.get("title") or "")[:120].replace("\n", " "))
' "$TRIED") || { log "could not parse the job list"; exit 1; }
[ -n "$pick" ] || exit 0
id=${pick%% *}
title=${pick#* }
case "$id" in
  ''|*[!0-9]*) log "bad id: refusing ($id)"; exit 1 ;;
esac

# ── Run ──────────────────────────────────────────────────────────────────────
# A job is started at most once. A failed run stays in Backlog and is not retried every
# minute; delete its line from poller-tried to let the poller start it again.
echo "$id" >>"$TRIED"
log "JOB-$id start: $title"
cd "$HOME" || exit 1
# auto is the defaultMode the interactive /jobs runs use. --permission-prompts none denies
# anything that would prompt, so an unattended run cannot stall on a question.
# Its own process group, so the watchdog can kill the whole tree (claude plus whatever
# it spawns) by group instead of chasing children one `pkill -P` level deep.
set -m
"$CLAUDE_BIN" -p "/jobs JOB-$id --background" \
  --permission-mode auto --permission-prompts none >>"$LOG" 2>&1 &
run=$!
set +m
pid_tmp="$LOCK/pid.$$"
echo "$run" >"$pid_tmp"
mv "$pid_tmp" "$LOCK/pid"

waited=0
killed=0
while kill -0 "$run" 2>/dev/null; do
  if [ "$waited" -ge "$LIMIT" ]; then
    killed=1
    kill -TERM -- "-$run" 2>/dev/null
    kill -TERM "$run" 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$run" 2>/dev/null || break; sleep 1; done
    kill -KILL -- "-$run" 2>/dev/null
    kill -KILL "$run" 2>/dev/null
    break
  fi
  sleep "$STEP"
  waited=$((waited + STEP))
done
wait "$run" 2>/dev/null
rc=$?

# ── Report ───────────────────────────────────────────────────────────────────
if [ "$killed" = 1 ]; then
  mins=$((LIMIT / 60))
  "${J[@]}" comment "$id" --kind event --body "Stopped after $mins minutes" >>"$LOG" 2>&1 \
    || log "JOB-$id could not post the watchdog comment"
  log "JOB-$id stopped after $mins minutes"
  notify "JOB-$id stopped after $mins minutes: $title"
  exit 0
fi
column=$("${J[@]}" get "$id" 2>/dev/null | "$PYTHON3_BIN" -c '
import json, sys
print(json.load(sys.stdin)["data"]["column"])
' 2>/dev/null || echo unknown)
log "JOB-$id ended: exit $rc, card in $column"
if [ "$column" = "in_review" ]; then
  notify "JOB-$id is In review: $title"
else
  notify "JOB-$id run failed (exit $rc, card in $column): $title"
fi
