#!/usr/bin/env bash
# One tick of the /jobs background poller. launchd (install-poller.sh, macOS) or a systemd
# user timer (install-poller-linux.sh, Linux) runs it every 60 s.
#
# Neither gives a login-shell environment, so every path comes from
# ~/.config/jobs/poller.env, which the installer writes. Each tick:
#   1. Takes the pick lock (a directory holding the tick's PID). A lock whose PID is dead is
#      removed. The tick holds it only while it picks, never while a run works.
#   2. Reads the live runs: one record per run in ~/.config/jobs/runs/<id>.json (pid, kind,
#      lanes). A record whose PID is dead is deleted.
#   3. Picks jobs until JOBS_POLLER_MAX_RUNS runs (default 3, ship runs included) are live or
#      no job is free. Pick order: a ship-approved run, then an operator reply on a job a poller
#      run claimed, then the oldest Backlog job never started here (or whose run failed and the
#      operator has replied since). An untargeted job runs too: the run picks its repo.
#   4. Marks each pick's run folder trusted (trust.py) and starts it DETACHED as a worker
#      (`poll.sh --run ...`, its own process group), then releases the lock and exits.
# Each worker runs `claude -p "/jobs JOB-<id> --background"` from the first target's checkout for
# a targeted job (from the job's own worktree for a targeted slash job; see slash_worktree), from the checkout whose path the prompt names for an untargeted job that names
# one, else from $JOBS_DEFAULT_HOME, and kills it after 45 minutes (90 for a ship; macOS has no
# `timeout`), or after the job's time_limit_s (clamped to 600 to 14400 s) when the hub sends one. Running in the checkout puts the thread under that repo, so the card's "Open
# thread" link finds it from that repo's VS Code window. It sends Telegram when the card reaches
# In review or the run fails, and deletes its run record when it ends.
#
# Lanes. A run holds the repos its job targets (`targets`, else `targets_picked`). A Backlog job
# starts only when none of its repos is busy: a live run holds it, or a job targeting it sits In
# progress or In review with a run not yet shipped (or no run yet), interactive claims included.
# A multi-target job needs all its repos free and holds all of them. A reply or ship run is held
# back only by a live run of another job in its repos, never by the board: two jobs In review on
# one repo would otherwise block each other's ships for ever. Untargeted jobs share one lane
# ("-"), so at most one runs at a time. A scheduled job (source "schedule", from a hub job
# template) holds only its own lane, "schedule:<template_id>" ("schedule" with no template), in
# place of its repos: no other job blocks it and it blocks none, but two runs of one template
# never overlap. It holds that lane In progress, never In review. At most one ship run is live
# on the machine.
# The tick writes nothing to claims.json: jobs.py owns that file.
#
# Optional, for a machine that shares the board with another poller (all unset by default):
#   POLLER_SKIP_UNTARGETED=1  never pick a job with no target, on any of the three pick paths
#   POLLER_SKIP_LOCAL=1       never pick a job with a local/* target, likewise
#   JOBS_POLLER_SOURCES=<s>   start only Backlog jobs whose source is listed (comma-separated); a
#                             "!" entry leaves that source instead: "schedule" takes only scheduled
#                             jobs, "!schedule" takes all but them. Reply and ship runs of jobs this
#                             machine already claimed still run. An unknown source stops the tick
#                             (exit 2)
#   POLLER_MIRROR_SYNC=<cmd>  before a targeted run: `sudo -n -u broker <cmd> <target>`, which
#                             prints {"mirror": <path>}; then clone that mirror into the
#                             target's manifest path (JOBS_TARGET_MANIFEST) when it is missing
#   POLLER_SHIP_CMD=<cmd>     a ship-approved job is handed to
#                             `sudo -n -u broker <cmd> --job <id>` with the claim token, then a
#                             git bundle of the job branch, on stdin, in place of a claude run
#                             (inside the tick: the hand-off returns at once)
set -uo pipefail

CFG_DIR="$HOME/.config/jobs"
CONF="$CFG_DIR/poller.env"
LOCK="$CFG_DIR/poller.lock"
RUNS="$CFG_DIR/runs" # one <id>.json per live run: {"pid", "kind", "lanes"}
TRIED="$CFG_DIR/poller-tried"
SKIPPED="$CFG_DIR/poller-skipped" # "<id>:<reason>" lines, so each skip logs once
OWNED="$CFG_DIR/poller-owned" # ids of jobs a poller run claimed; only these get reply runs
if [ "$(uname -s)" = Darwin ]; then
  LOG="${JOBS_POLLER_LOG:-$HOME/Library/Logs/jobs-poller.log}"
else
  LOG="${JOBS_POLLER_LOG:-${XDG_STATE_HOME:-$HOME/.local/state}/jobs-poller.log}"
fi
LIMIT="${JOBS_POLLER_LIMIT:-2700}"   # seconds; tests shorten it
STEP="${JOBS_POLLER_STEP:-5}"        # watchdog check interval, seconds

# mtime in epoch seconds. GNU stat first: on Linux `stat -f` is filesystem status and prints.
mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0; }
log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }

mkdir -p "$(dirname "$LOG")" "$CFG_DIR" "$RUNS"
[ -f "$CONF" ] || { log "no $CONF: run install-poller.sh"; exit 2; }
# shellcheck disable=SC1090
. "$CONF"
for v in CLAUDE_BIN PYTHON3_BIN SKILL_DIR; do
  [ -n "${!v:-}" ] || { log "poller.env lacks $v"; exit 2; }
done
MAX_RUNS="${JOBS_POLLER_MAX_RUNS:-3}" # live runs at once, ship runs included
case "$MAX_RUNS" in ""|*[!0-9]*) MAX_RUNS=3 ;; esac
export PATH="${POLLER_PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"
[ -n "${JOBS_REPOS_ROOT:-}" ] && export JOBS_REPOS_ROOT
[ -n "${JOBS_DEFAULT_HOME:-}" ] && export JOBS_DEFAULT_HOME
[ -n "${JOBS_TARGET_MANIFEST:-}" ] && export JOBS_TARGET_MANIFEST
[ -n "${JOBS_REPOS_READONLY:-}" ] && export JOBS_REPOS_READONLY
export POLLER_SKIP_UNTARGETED="${POLLER_SKIP_UNTARGETED:-}" POLLER_SKIP_LOCAL="${POLLER_SKIP_LOCAL:-}"
export JOBS_POLLER_SOURCES="${JOBS_POLLER_SOURCES:-}"
# A misspelt source would leave every job, or take every job, without a word: stop instead.
IFS=, read -r -a srcs <<<"$JOBS_POLLER_SOURCES"
for s in ${srcs[@]+"${srcs[@]}"}; do # bash 3.2 calls an empty array unbound
  s="${s//[[:space:]]/}"
  [ -n "$s" ] || continue
  case "${s#!}" in
    board|zero|schedule) ;;
    *) log "JOBS_POLLER_SOURCES has an unknown source '$s' (known: board, zero, schedule, each with an optional !)"; exit 2 ;;
  esac
done
J=("$PYTHON3_BIN" "$SKILL_DIR/assets/jobs.py")

notify() {
  if [ -n "${TELEGRAM_SEND:-}" ] && [ -x "$TELEGRAM_SEND" ]; then
    "$TELEGRAM_SEND" "$1" >>"$LOG" 2>&1 || log "telegram send failed"
  fi
}

# ── Run (the worker) ─────────────────────────────────────────────────────────
# `poll.sh --run <id> <ship|reply|backlog> <run folder> <reply comment id|-> <title> [<time limit s|->]`:
# one run, started detached by a tick, which has already recorded it as tried and trusted its folder.
# The time limit is the job's `time_limit_s`, clamped to 600 to 14400 s; absent keeps
# JOBS_POLLER_LIMIT, and a ship run always keeps JOBS_POLLER_SHIP_LIMIT.
run_worker() {
  id=$1 kind=$2 run_dir=$3 reply_cid=$4 title=$5 tl=${6:--} ship=""
  [ "$reply_cid" != - ] || reply_cid=""
  if [ "$kind" = ship ]; then
    ship=1
    LIMIT="${JOBS_POLLER_SHIP_LIMIT:-5400}" # merge, review, build and deploy take longer
  elif [[ $tl =~ ^[0-9]+$ ]]; then
    lo="${JOBS_POLLER_LIMIT_MIN:-600}" hi=14400 # tests lower the floor
    [[ $lo =~ ^[0-9]{1,5}$ ]] && [ "$lo" -le "$hi" ] || lo=600
    if [ "${#tl}" -gt 9 ] || [ "$tl" -gt "$hi" ]; then tl=$hi; fi
    [ "$tl" -ge "$lo" ] || tl=$lo
    LIMIT=$tl
  fi
  log "JOB-$id limit ${LIMIT}s"
  trap 'rm -f "$RUNS/$id.json"' EXIT # the tick wrote it; a dead record is pruned anyway
  cd "$run_dir" || exit 1
  # Drive for desktop keeps most files online-only, and a headless run reading one gets
  # "Resource deadlock avoided". Download the folders runs need first ("|"-separated paths).
  if [ -n "${JOBS_PREFETCH:-}" ] && [ "$(uname -s)" = Darwin ]; then # dataless files are macOS only
    n=0 bad=0 seen=0 until=$(( $(date +%s) + 300 )) # 60 s a file, 5 minutes in all
    IFS='|' read -r -a pre <<<"$JOBS_PREFETCH"
    for d in "${pre[@]}"; do
      [ -d "$d" ] || continue
      while IFS= read -r -d '' f; do
        [ "$(date +%s)" -lt "$until" ] || { log "JOB-$id prefetch stopped at 5 minutes"; break 2; }
        seen=$((seen + 1))
        case "$(stat -f %Sf "$f" 2>/dev/null)" in
          *dataless*)
            if perl -e 'alarm 60; exec @ARGV' cat "$f" >/dev/null 2>&1; then n=$((n + 1)); else bad=$((bad + 1)); fi ;;
        esac
      done < <(find "$d" -type f -print0 2>/dev/null)
    done
    # Always log: a launchd process may list nothing at all, and silence hid that once.
    log "JOB-$id prefetch: listed $seen files, downloaded $n, $bad failed"
  fi
  run_dir=$(pwd -P) # absolute, for the claim's session folder
  # jobs.py claim sends this folder with the session id, for the card's VS Code links.
  export JOBS_RUN_DIR="$run_dir"
  # auto is the defaultMode the interactive /jobs runs use. --permission-prompts none denies
  # anything that would prompt, so an unattended run cannot stall on a question.
  # Its own process group, so the watchdog can kill the whole tree (claude plus whatever
  # it spawns) by group instead of chasing children one `pkill -P` level deep.
  # A known session id, so the transcript can be found after the run (see Retag).
  sid=$("$PYTHON3_BIN" -c 'import uuid; print(uuid.uuid4())')
  set -m
  "$CLAUDE_BIN" -p "/jobs JOB-$id --background${ship:+ --ship}" --session-id "$sid" \
    --permission-mode auto --permission-prompts none >>"$LOG" 2>&1 &
  run=$!
  set +m
  "${J[@]}" patch "$id" --active on >/dev/null 2>&1 || true # a reply run is already claimed
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
    # Heartbeat for the card's Agent working sign. Before the run claims the job this fails; quiet.
    if [ "$waited" -gt 0 ] && [ $((waited % 60)) -eq 0 ]; then
      "${J[@]}" patch "$id" --active on >/dev/null 2>&1 & # never stalls the watchdog
      hb=$!
    fi
    sleep "$STEP"
    waited=$((waited + STEP))
  done
  wait "$run" 2>/dev/null
  rc=$?
  [ -z "${hb:-}" ] || wait "$hb" 2>/dev/null # a late "on" must not land after the "off"
  "${J[@]}" patch "$id" --active off >/dev/null 2>&1 || true

  # ── Retag ──
  # `claude -p` records its transcript as entrypoint "sdk-cli", and the VS Code extension will
  # not open an SDK session, so the card's Open thread link showed a blank tab. Relabel it "cli".
  # ponytail: relies on the transcript format; drop this if the extension opens sdk-cli sessions.
  for t in "$HOME"/.claude/projects/*/"$sid".jsonl; do
    [ -f "$t" ] || continue
    "$PYTHON3_BIN" -c '
import os, sys, tempfile
p = sys.argv[1]
s = open(p).read().replace("\"entrypoint\":\"sdk-cli\"", "\"entrypoint\":\"cli\"")
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p))
with os.fdopen(fd, "w") as f:
    f.write(s)
os.chmod(tmp, 0o600)
os.replace(tmp, p)
' "$t" || log "JOB-$id could not retag $t"
  done

  # ── Report ──
  # A pre-approved job ("Ship when ready") reaches In review and the hub approves its ship at
  # once, which moves it back to In progress. That end state reads as "shipping", not a failure.
  job_column() {
    "${J[@]}" get "$id" 2>/dev/null | "$PYTHON3_BIN" -c '
import json, sys
d = json.load(sys.stdin)["data"]
print("shipping" if d["column"] == "in_progress" and d.get("ship_approved_at") else d["column"])
' 2>/dev/null || echo unknown
  }
  # A Backlog run (not a reply run, not a ship run) that leaves the card in Backlog failed. Say
  # so on the card, then record "<id>~<newest comment id>" in poller-tried: an operator comment
  # after it retries the job once (see Pick).
  backlog_failed() { # $1 = short reason
    "${J[@]}" comment "$id" --kind event --body "Background run failed: $1. Reply on this card to retry." >>"$LOG" 2>&1 \
      || log "JOB-$id could not post the failure comment"
    newest=$("${J[@]}" get "$id" 2>/dev/null | "$PYTHON3_BIN" -c '
import json, sys
print(max([c["id"] for c in json.load(sys.stdin)["data"].get("comments", [])], default=0))
' 2>/dev/null)
    case "$newest" in
      ""|*[!0-9]*) log "JOB-$id could not read its comments; a reply will not retry it" ;;
      *) echo "$id~$newest" >>"$TRIED" ;;
    esac
  }
  backlog_run=""
  [ -n "$ship$reply_cid" ] || backlog_run=1
  if [ "$killed" = 1 ]; then
    mins=$((LIMIT / 60))
    if [ -n "$backlog_run" ] && [ "$(job_column)" = backlog ]; then
      backlog_failed "stopped after $mins minutes"
    else
      "${J[@]}" comment "$id" --kind event --body "Stopped after $mins minutes" >>"$LOG" 2>&1 \
        || log "JOB-$id could not post the watchdog comment"
    fi
    if [ -n "$ship" ]; then
      "${J[@]}" comment "$id" --kind event --body "Ship run stopped after $mins minutes, possibly mid-ship. Check in $run_dir: local main against origin (a merge may be unpushed), whether a migration was applied without the deploy, and the conductor merge and push claims (/threads)." >>"$LOG" 2>&1 || true
    fi
    log "JOB-$id stopped after $mins minutes"
    notify "JOB-$id stopped after $mins minutes: $title"
    exit 0
  fi
  column=$(job_column)
  log "JOB-$id ended: exit $rc, card in $column"
  if [ -n "$backlog_run" ] && [ "$column" = backlog ]; then
    if [ "$rc" != 0 ]; then backlog_failed "exit $rc"; else backlog_failed "never claimed"; fi
  fi
  if [ -n "$ship" ]; then
    left=$("${J[@]}" get "$id" 2>/dev/null | "$PYTHON3_BIN" -c '
import json, sys
runs = json.load(sys.stdin)["data"].get("runs") or []
print(sum(1 for r in runs if r.get("state") != "shipped" or not r.get("deployed_sha")) if runs else 1)
' 2>/dev/null || echo 1)
    # Shipped means the hub shows every run shipped with a deployed SHA. A refused or failed
    # ship moves runs to committed or failed, which is not success.
    if [ "$rc" = 0 ] && [ "$left" = 0 ]; then
      notify "JOB-$id shipped: $title"
    else
      notify "JOB-$id ship did not complete (exit $rc, $left run(s) not shipped; see the card): $title"
    fi
  elif [ -n "$reply_cid" ]; then
    # A reply run starts in In review, so the column proves nothing: the ack does.
    ack=$("${J[@]}" get "$id" 2>/dev/null | "$PYTHON3_BIN" -c '
import json, sys
print(json.load(sys.stdin)["data"].get("ack_comment_id") or 0)
' 2>/dev/null || echo 0)
    if [ "$rc" = 0 ] && [ "$ack" -ge "$reply_cid" ]; then
      notify "JOB-$id answered your reply: $title"
    else
      notify "JOB-$id reply run failed (exit $rc, reply not acked): $title"
    fi
  elif [ "$column" = "in_review" ]; then
    notify "JOB-$id is In review: $title"
  elif [ "$column" = "shipping" ]; then
    notify "JOB-$id finished, shipping (pre-approved): $title"
  else
    notify "JOB-$id run failed (exit $rc, card in $column): $title"
  fi
}

if [ "${1:-}" = --run ]; then
  run_worker "$2" "$3" "$4" "$5" "$6" "${7:--}"
  exit 0
fi

# ── Lock (held only while the tick picks) ────────────────────────────────────
if ! mkdir "$LOCK" 2>/dev/null; then
  held=$(cat "$LOCK/pid" 2>/dev/null || true)
  if [ -n "$held" ] && kill -0 "$held" 2>/dev/null; then
    exit 0 # another tick is picking
  fi
  if [ -z "$held" ]; then
    # The pid file is written just below, after mkdir, so a lock dir that still has no
    # pid file can be another tick mid-creation rather than abandoned. Give it ~5s.
    age=$(( $(date +%s) - $(mtime "$LOCK") ))
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
touch "$TRIED" "$SKIPPED" "$OWNED"
# Python prelude for the three pickers. left(targets, j, backlog) is true for a job this machine
# leaves to another poller (POLLER_SKIP_*; JOBS_POLLER_SOURCES on the Backlog path only, so a job
# this machine already claimed still gets its reply and ship runs after a switch). lanes(targets, j) is a scheduled job's
# template lane, else its repos, else "-". held(job, targets, own) is true for a job that is live or was
# already picked this tick, or whose lanes are busy (see Lanes in the header). own marks a reply
# or ship run, which only a live run holds back. Both run inside the pick, before any side effect.
LEFT='
import os
SOURCES = [s.strip() for s in os.environ.get("JOBS_POLLER_SOURCES", "").split(",") if s.strip()]
def left(targets, j, backlog=False):
    src = j.get("source") or ""
    if backlog and ("!" + src in SOURCES or any(not s.startswith("!") for s in SOURCES) and src not in SOURCES):
        return True
    targets = [t for t in targets or [] if t]
    if os.environ.get("POLLER_SKIP_UNTARGETED") == "1" and not targets:
        return True
    return os.environ.get("POLLER_SKIP_LOCAL") == "1" and any(t.startswith("local/") for t in targets)
BUSY = set(os.environ.get("POLL_BUSY", "").split())
LIVE = set(os.environ.get("POLL_LIVE", "").split())
EXCLUDE = set(os.environ.get("POLL_EXCLUDE", "").split())
def lanes(targets, j=None):
    repos = list(dict.fromkeys(t for t in targets or [] if t))
    if j and j.get("source") == "schedule":
        tid = "".join(c for c in str(j.get("template_id") or "") if c.isalnum() or c in "._-")
        # Untargeted, it runs with no worktree in a shared folder, so it also holds "-".
        return ["schedule:" + tid if tid else "schedule"] + ([] if repos else ["-"])
    return repos or ["-"]
def held(j, targets, own):
    # A scheduled job meets the board only in its template lane; its folder lane ("-") waits
    # only for live runs, so no card In review or In progress holds it.
    sched = j.get("source") == "schedule"
    return str(j.get("id")) in EXCLUDE or any(
        l in (LIVE if own or (sched and not l.startswith("schedule")) else BUSY) for l in lanes(targets, j))
def fresh(ts):  # a live heartbeat (active_at) means some run, on any machine, is on the job
    from datetime import datetime, timezone
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() < 180
def limit(j):  # the job time limit for poll.sh --run, "-" when the hub sends none
    v = j.get("time_limit_s")
    return str(v) if type(v) is int and v > 0 else "-"
'

# Log a skip once per job and reason, and say it on the card so a job never sits in
# Backlog with no word. The line in poller-skipped is the memory.
skip_once() {
  if ! grep -qxF "$1:$2" "$SKIPPED"; then
    echo "$1:$2" >>"$SKIPPED"
    log "JOB-$1 skipped: $3"
    "${J[@]}" comment "$1" --kind event --body "Not started by the poller: $3. $4" >>"$LOG" 2>&1 \
      || log "JOB-$1 skip comment failed"
  fi
}

first_target_dir() { # $1 = owner/repo; prints its checkout, or nothing
  "${J[@]}" repos --dry-run 2>/dev/null | "$PYTHON3_BIN" -c '
import json, sys
m = [r["path"] for r in json.load(sys.stdin)["repos"] if r["target"] == sys.argv[1]]
print(m[0] if m else "")
' "$1" 2>/dev/null
}

# An untargeted run works with no worktree in the folder it runs in, so it also holds the repo
# whose checkout that folder is (a ship run there merges in the same index). Adds it to lanes;
# returns 1 when a live run holds it, and the job waits for the next tick.
own_folder() {
  f=$("${J[@]}" repos --dry-run 2>/dev/null | "$PYTHON3_BIN" -c '
import json, os, sys
d = os.path.realpath(sys.argv[1])
m = [r["target"] for r in json.load(sys.stdin)["repos"] if os.path.realpath(r["path"]) == d]
print(m[0] if m else "")
' "$run_dir" 2>/dev/null)
  [ -n "$f" ] || return 0
  case " $POLL_LIVE " in *" $f "*) return 1 ;; esac
  case ",$lanes," in *",$f,"*) ;; *) lanes="$lanes,$f" ;; esac
}

# The live runs: live_n, live_ship, and the POLL_* sets the prelude reads. A record whose PID is
# dead (a worker that crashed or was killed) is deleted, which frees its lanes.
# ponytail: a reused PID reads as alive and holds its lanes until that process ends.
live_state() {
  live_n=0 live_ship="" POLL_LIVE="" POLL_EXCLUDE=$tick_picked
  while read -r rid rpid rkind rlanes; do
    [ -n "$rid" ] || continue
    case "$rpid" in ""|0|*[!0-9]*) rpid=dead ;; esac
    if [ "$rpid" = dead ] || ! kill -0 "$rpid" 2>/dev/null; then
      log "JOB-$rid run record pruned (pid $rpid is not running)"
      rm -f "$RUNS/$rid.json"
      continue
    fi
    live_n=$((live_n + 1))
    [ "$rkind" != ship ] || live_ship=1
    POLL_LIVE="$POLL_LIVE ${rlanes//,/ }"
    POLL_EXCLUDE="$POLL_EXCLUDE $rid"
  done < <("$PYTHON3_BIN" -c '
import glob, json, os, sys
for p in sorted(glob.glob(os.path.join(sys.argv[1], "*.json"))):
    try:
        d = json.load(open(p))
        print(os.path.basename(p)[:-5], int(d["pid"]), d["kind"], ",".join(d["lanes"]))
    except (OSError, ValueError, KeyError, TypeError):
        print(os.path.basename(p)[:-5], "-", "-", "-")
' "$RUNS")
  POLL_BUSY="$board_busy $POLL_LIVE"
  export POLL_BUSY POLL_LIVE POLL_EXCLUDE
}

# The repos the board holds busy: each job In progress or In review with a run not yet shipped,
# or with no run yet, whoever claimed it. One line of lanes per such job. A scheduled job
# In review holds nothing while no run is on it (no fresh active_at heartbeat): the weekly card
# waits there until the operator archives it, and would block the next run of its template.
board_lanes() {
  "${J[@]}" list --all-pages 2>/dev/null | "$PYTHON3_BIN" -c "$LEFT"'
import json, sys
for j in json.load(sys.stdin).get("jobs", []):
    runs = j.get("runs") or []
    if j.get("column") in ("in_progress", "in_review") and not (runs and all(r.get("state") == "shipped" for r in runs)):
        if j.get("column") == "in_review" and j.get("source") == "schedule" and not fresh(j.get("active_at")):
            continue
        print(" ".join(lanes(j.get("targets") or j.get("targets_picked"), j)))
'
}

# One pick into id, kind, title, run_dir, target (the first target, "-" when none), lanes
# (comma-separated; see Lanes in the header) and the bookkeeping keys. Returns 1 when no job is free.
pick() {
  id="" kind="" title="" run_dir="$HOME" tried_key="" retry_key="" reply_cid="" target="" lanes="" branch="" ship_runs=1
  time_limit=""
  # Before anything else: a run the operator approved to ship. Approving is the instruction to
  # ship, so the poller ships it unattended. One run per approved commit: "<id>#ship@<sha>".
  # A ship run merges and pushes the shared default branch, so only one is ever live.
  if [ -z "$live_ship" ] && [ -n "$approved" ]; then
    read -r cid clanes ctarget capproval csha cbranch cruns ctitle < <(printf '%s' "$approved" | "$PYTHON3_BIN" -c "$LEFT"'
import json, os, sys
tried = {l.strip() for l in open(sys.argv[1]) if l.strip()}
try:
    mine = set(json.load(open(os.path.expanduser("~/.config/jobs/claims.json"))))
except (OSError, ValueError):
    mine = set()  # shipping needs this machine claim token
for j in sorted(json.load(sys.stdin).get("jobs", []), key=lambda j: str(j["id"]).zfill(20)):
    runs = [r for r in j.get("runs") or [] if r.get("state") == "approved" and r.get("approved_sha")]
    t = [r.get("target") for r in runs]
    # A ship merges in the checkouts of its repos, so the ship of a scheduled job holds its repos too.
    if not runs or str(j["id"]) not in mine or left(t, j) or held(j, t, True) or any(l in LIVE for l in lanes(t)):
        continue
    # The approval time changes with every Approve ship, so a re-approval of the same
    # commit (after a refused ship voided the first) ships again.
    key = ("%s#ship@%s" % (j["id"], j.get("ship_approved_at") or runs[0]["approved_sha"])).replace(" ", "_")
    if key in tried:
        continue
    print(j["id"], ",".join(dict.fromkeys(lanes(t, j) + lanes(t))), lanes(t)[0], key.split("@", 1)[1], runs[0]["approved_sha"][:7],
          runs[0].get("branch") or "-", len(runs), (j.get("title") or "")[:120].replace("\n", " "))
    break
' "$TRIED" 2>/dev/null)
    case "$cid" in
      ""|*[!0-9]*) ;;
      *)
        id=$cid kind=ship title=$ctitle tried_key="$cid#ship@$capproval" lanes=$clanes target=$ctarget
        branch=$cbranch ship_runs=$cruns
        run_dir=$(first_target_dir "$target")
        [ -n "$run_dir" ] && [ -d "$run_dir" ] || run_dir=$HOME
        log "JOB-$id approved to ship at $csha"
        return 0
        ;;
    esac
  fi

  # Next, a job this machine claimed that has an operator reply it has not read. One run per
  # reply: the key is "<id>@<newest operator comment id>", so a later reply starts another run.
  if [ -n "$awaiting" ]; then
    while read -r cid clanes ctarget ctl ctitle; do
      case "$cid" in *[!0-9]*|"") continue ;; esac
      last=$("${J[@]}" get "$cid" 2>/dev/null | "$PYTHON3_BIN" -c '
import json, sys
d = json.load(sys.stdin)["data"]
ids = [c["id"] for c in d.get("comments", []) if c.get("author") == "you" and c["id"] > (d.get("ack_comment_id") or 0)]
print(max(ids) if ids else "", d.get("session_id") or "")
' 2>/dev/null)
      read -r last sess <<<"$last"
      [ -n "$last" ] || continue
      # A thread resumed by hand (the card's Open thread link) writes its transcript; leave it be.
      if [ -n "$sess" ]; then
        live=0
        for t in "$HOME"/.claude/projects/*/"$sess".jsonl; do
          [ -f "$t" ] && [ $(( $(date +%s) - $(mtime "$t") )) -lt 180 ] && live=1
        done
        [ "$live" = 0 ] || continue
      fi
      grep -qxF "$cid@$last" "$TRIED" && continue
      id=$cid kind=reply title=$ctitle tried_key="$cid@$last" reply_cid=$last lanes=$clanes time_limit=$ctl
      if [ "$ctarget" != - ]; then
        target=$ctarget
        run_dir=$(first_target_dir "$target")
      else
        run_dir=${JOBS_DEFAULT_HOME:-}
      fi
      [ -n "$run_dir" ] && [ -d "$run_dir" ] || run_dir=$HOME
      [ "$ctarget" != - ] || own_folder || continue
      log "JOB-$id has a reply to read (comment $last)"
      return 0
    done < <(printf '%s' "$awaiting" | "$PYTHON3_BIN" -c "$LEFT"'
import json, sys
# Only jobs a poller run claimed: an interactive thread answers replies on its own jobs.
mine = {l.strip() for l in open(sys.argv[1]) if l.strip()}
for j in sorted(json.load(sys.stdin).get("jobs", []), key=lambda j: str(j["id"]).zfill(20)):
    if j.get("awaiting") and j.get("claimed") and str(j["id"]) in mine \
            and j.get("column") in ("in_progress", "in_review") and not fresh(j.get("active_at")):
        t = j.get("targets") or j.get("targets_picked") or []
        if left(t, j) or held(j, t, True):
            continue
        print(j["id"], ",".join(lanes(t, j)), lanes(t)[0], limit(j), (j.get("title") or "")[:120].replace("\n", " "))
' "$OWNED" 2>/dev/null)
  fi

  # Last, the Backlog, read once a tick along with the repos the board holds busy.
  # --all-pages: without it, a full first page of tried/stuck backlog jobs could hide
  # every newer job behind them.
  if [ -z "$board_read" ]; then
    if ! listing=$("${J[@]}" list --column backlog --all-pages 2>&1); then
      log "list failed: $(printf '%s' "$listing" | tr '\n' ' ' | cut -c1-300)"
      exit 1
    fi
    if ! board_busy=$(board_lanes); then
      log "could not read the busy repos from the board; no Backlog job starts this tick"
      return 1
    fi
    board_busy=$(printf '%s' "$board_busy" | tr '\n' ' ')
    board_read=1
    POLL_BUSY="$board_busy $POLL_LIVE"
    export POLL_BUSY
  fi
  # One line per candidate, oldest first: "<id> <T|U|W> <lanes> <target|-> <after|-> <limit|-> <title>"
  # (T has a tagged target, U has none; lanes as in the header; limit is its time_limit_s). W is
  # a scheduled job held by a run of its own template: the poller says why on its card.
  # A started job is left out too, unless its run failed: "<id>~<n>" in poller-tried records the
  # newest comment id at the failure, and <after> carries the highest such n. That job is a
  # retry candidate, retried only when the operator has commented since.
  cands=$(printf '%s' "$listing" | "$PYTHON3_BIN" -c "$LEFT"'
import json, sys
tried = [l.strip() for l in open(sys.argv[1]) if l.strip()]
skip = set(tried)
after = {}
for l in tried:
    i, _, n = l.partition("~")
    if n.isdigit():
        after[i] = max(after.get(i, 0), int(n))
def wanted(j):
    i = str(j.get("id"))
    return i not in skip or i in after
jobs = [j for j in json.load(sys.stdin).get("jobs", [])
        if j.get("column") == "backlog"
        and not j.get("claimed") and wanted(j) and not left(j.get("targets"), j, True)]
for j in sorted(jobs, key=lambda j: str(j["id"]).zfill(20)):
    t = j.get("targets") or []
    i = str(j["id"])
    k = "T" if t else "U"
    if held(j, t, False):
        if j.get("source") != "schedule" or i in EXCLUDE or i in after:  # a failed run retries only after a reply, so "starts when that job ends" would be untrue
            continue
        if lanes(t, j)[0] not in BUSY:  # only its folder lane is held, by a live run: next tick
            continue
        k = "W"
    print(j["id"], k, lanes(t, j)[0] if k == "W" else ",".join(lanes(t, j)), lanes(t)[0], after[i] if i in skip and i in after else "-", limit(j),
          (j.get("title") or "")[:120].replace("\n", " "))
' "$TRIED") || { log "could not parse the job list"; exit 1; }

  while read -r cid ckind clanes ctarget cafter ctl ctitle; do
    [ -n "$cid" ] || continue
    case "$cid" in
      *[!0-9]*) log "bad id: refusing ($cid)"; exit 1 ;;
    esac
    if [ "$ckind" = W ]; then
      skip_once "$cid" lane-busy "another run of its job template holds its lane ($clanes)" \
        "It starts when that run ends or leaves In progress."
      continue
    fi
    time_limit=$ctl
    retry_key=""
    if [ "$cafter" != - ]; then
      # A failed run: retry it once per operator reply posted after the failure.
      you=$("${J[@]}" get "$cid" 2>/dev/null | "$PYTHON3_BIN" -c '
import json, sys
print(max([c["id"] for c in json.load(sys.stdin)["data"].get("comments", []) if c.get("author") == "you" and c.get("kind") == "message"], default=0))
' 2>/dev/null)
      case "$you" in ""|*[!0-9]*) continue ;; esac
      [ "$you" -gt "$cafter" ] || continue
      retry_key="$cid~$you"
      log "JOB-$cid retries after your reply (comment $you)"
    fi
    if [ "$ckind" = T ]; then
      id=$cid kind=backlog title=$ctitle lanes=$clanes target=$ctarget
      # The first target's checkout, else $HOME (the run then fails that target on the card).
      run_dir=$(first_target_dir "$target")
      [ -n "$run_dir" ] && [ -d "$run_dir" ] || run_dir=$HOME
      return 0
    fi
    # No target: the run works out the repo from the prompt (Background mode in SKILL.md), and
    # refuses on the card only when it cannot. Run it from the checkout whose path the prompt
    # names, so the thread and that repo's permission rules belong to it; else from the
    # default home. The title and the email comment are never read for this.
    # ponytail: an untargeted run holds only the shared "-" lane and the repo of the folder it
    # starts in, so it may still pick another repo a run holds busy. Upgrade path: pass the busy
    # repos into the run, which then avoids them.
    if [ -z "${JOBS_DEFAULT_HOME:-}" ] || [ ! -d "$JOBS_DEFAULT_HOME" ]; then
      skip_once "$cid" no-home "no target and JOBS_DEFAULT_HOME is unset or missing (${JOBS_DEFAULT_HOME:-unset})" \
        "Tag a target repo to run it."
      continue
    fi
    if ! named=$("${J[@]}" get "$cid" 2>/dev/null | "$PYTHON3_BIN" -c '
import json, re, sys
p = (json.load(sys.stdin)["data"].get("prompt") or "").strip()
if re.match(r"/[a-z][\w-]*(\s|$)", p):
    print("-")  # a slash command runs in the default home
    sys.exit()
repos = json.load(open(sys.argv[1]))["repos"]
hits = [r["path"] for r in repos if re.search(re.escape(r["path"]) + r"(/|\s|$)", p)]
print(max(hits, key=len) if hits else "-")
' <("${J[@]}" repos --dry-run 2>/dev/null) 2>/dev/null); then
      log "JOB-$cid could not read the prompt"
      continue
    fi
    id=$cid kind=backlog title=$ctitle lanes=$clanes run_dir=$JOBS_DEFAULT_HOME
    [ "$named" != - ] && [ -d "$named" ] && run_dir=$named
    own_folder || continue
    return 0
  done <<<"$cands"
  return 1
}

# ── Mirror and clone (POLLER_MIRROR_SYNC) ────────────────────────────────────
# The clone path comes from the target manifest, which this user cannot write, so a target
# runs only where the manifest already says; a target outside it fails mirror-sync.
# A failing sync leaves the job unpicked this tick; the jobs behind it still get their turn.
# Returns 1 to skip the pick this tick (the job is tried again next tick).
mirror_sync() {
  # The same characters as jobs.py TARGET_RE, either case; a "." or ".." part is no repo name.
  if ! [[ $target =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || [[ /$target/ =~ /\.\.?/ ]]; then
    skip_once "$id" bad-target "target $target is not owner/repo" "Fix the target to run it."
    return 1
  fi
  if ! synced=$(sudo -n -u broker "$POLLER_MIRROR_SYNC" "$target" 2>&1); then
    skip_once "$id" "mirror-sync" "mirror-sync for $target failed: $(printf '%s' "$synced" | tr '\n' ' ' | cut -c1-200)" \
      "The poller tries again every minute."
    return 1
  fi
  dest=$(first_target_dir "$target")
  if [ -z "$dest" ]; then
    skip_once "$id" "no-dest" "target $target is not in the target manifest" "Add it to the manifest to run it."
    return 1
  fi
  if [ ! -d "$dest" ]; then
    mirror=$(printf '%s' "$synced" | "$PYTHON3_BIN" -c 'import json, sys; print(json.load(sys.stdin)["mirror"])' 2>/dev/null)
    # The mirror path comes from the broker and git runs uploadpack through a shell, so it must
    # be a plain absolute path under the mirror root, with no "..", and is quoted below.
    mroot="${POLLER_MIRROR_ROOT:-/srv/mirrors}"
    if [[ $mirror != "$mroot"/* ]] || ! [[ $mirror =~ ^/[A-Za-z0-9._/-]+\.git$ ]] || [[ $mirror == *..* ]]; then
      skip_once "$id" "bad-mirror" "mirror path from the broker is not a plain path under $mroot" "Check mirror-sync."
      return 1
    fi
    # The mirror belongs to another user, and git refuses a repo it does not own unless
    # safe.directory names it; the local clone and every later fetch need it.
    printf -v qmirror '%q' "$mirror"
    up="git -c safe.directory=$qmirror upload-pack"
    if  ! { mkdir -p "$(dirname "$dest")" && git -c safe.directory="$mirror" clone -q \
        -c remote.origin.uploadpack="$up" -u "$up" -- "$mirror" "$dest" >>"$LOG" 2>&1; }; then
      skip_once "$id" "clone" "could not clone ${mirror:-the mirror} into $dest" "The poller tries again every minute."
      rm -rf "$dest"
      return 1
    fi
    log "JOB-$id cloned $target into $dest"
  fi
  [ -d "$dest" ] && run_dir=$dest
  return 0
}

# ── Targeted slash job: its own worktree before Claude starts ────────────────
# A job with exactly one tagged target and a prompt that starts with a slash command runs in a
# worktree of that target, on job/<id>-<slug> from the freshly fetched origin/<default>. Project
# skills resolve from the folder Claude starts in, so the worktree must exist first: started in
# the main checkout, the command would run from main and commit to main's branch. A reply run
# reuses the job's worktree. Any other job keeps run_dir. Returns 1 to skip the pick this tick.
slash_worktree() {
  local is wt br def slug out
  is=$("${J[@]}" get "$id" 2>/dev/null | "$PYTHON3_BIN" -c '
import json, re, sys
d = json.load(sys.stdin)["data"]
t = [x for x in d.get("targets") or [] if x]
print("y" if len(t) == 1 and re.match(r"/[a-z][\w-]*(\s|$)", (d.get("prompt") or "").strip()) else "n")
' 2>/dev/null) || { log "JOB-$id could not read the job; trying again next tick"; return 1; }
  [ "$is" = y ] || return 0
  # No checkout: the run fails the target on the card, as for any targeted job.
  git -C "$run_dir" rev-parse -q --git-dir >/dev/null 2>&1 || return 0
  # On the box mirror_sync has just synced the mirror; this fetches the clone from it.
  if ! out=$(git -C "$run_dir" fetch -q origin 2>&1); then
    skip_once "$id" fetch "git fetch in $run_dir failed: $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-200)" \
      "The poller tries again every minute."
    return 1
  fi
  # ponytail: tracked files only; untracked scratch in the main checkout never blocks a job.
  if [ -n "$(git -C "$run_dir" status --porcelain --untracked-files=no 2>&1)" ]; then
    skip_once "$id" dirty-main "the main checkout $run_dir has uncommitted changes" \
      "Commit or stash them; the poller tries again every minute."
    return 1
  fi
  wt=$(git -C "$run_dir" worktree list --porcelain 2>/dev/null | awk -v p="branch refs/heads/job/$id-" '
    /^worktree /{w=substr($0, 10)} index($0, p) == 1 {print w; exit}')
  if [ -z "$wt" ] || [ ! -d "$wt" ]; then
    git -C "$run_dir" worktree prune 2>/dev/null
    def=$(git -C "$run_dir" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null) || def=origin/main
    br=$(git -C "$run_dir" for-each-ref --count=1 --format='%(refname:short)' "refs/heads/job/$id-*" 2>/dev/null)
    if [ -n "$br" ]; then
      wt="$run_dir-wt/${br//\//-}"
      out=$(git -C "$run_dir" worktree add -q "$wt" "$br" 2>&1)
    else
      slug=$(printf '%s' "$title" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | cut -c1-40 | sed 's/^-*//; s/-*$//')
      br="job/$id-${slug:-job}"
      wt="$run_dir-wt/${br//\//-}"
      # --no-track: the job branch must never push to the default branch.
      out=$(git -C "$run_dir" worktree add -q --no-track -b "$br" "$wt" "$def" 2>&1)
    fi
    # shellcheck disable=SC2181
    if [ $? != 0 ]; then
      skip_once "$id" worktree "could not add the worktree $wt: $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-200)" \
        "The poller tries again every minute."
      return 1
    fi
    log "JOB-$id worktree $wt on $br from $def"
  fi
  run_dir=$wt
  return 0
}

# ── Ship through the broker (POLLER_SHIP_CMD) ────────────────────────────────
# The broker ships; this machine only hands over the claim token and the job branch's commits.
# ship-request spools the request and returns at once; the broker reports the result itself.
# A subshell, so its refusals and failures end the hand-off, not the tick.
broker_ship() (
  # A refusal is final for this approval, so it is recorded; a failed hand-off is not, so the
  # next tick tries again. The operator hears about a failure once per approval.
  refuse() {
    echo "$tried_key" >>"$TRIED"
    log "JOB-$id ship refused: $1"
    notify "JOB-$id ship refused: $1: $title"
    exit 0
  }
  failed() {
    log "JOB-$id ship request failed: $1"
    if ! grep -qxF "$tried_key:ship-failed" "$SKIPPED"; then
      echo "$tried_key:ship-failed" >>"$SKIPPED"
      notify "JOB-$id ship request to the broker failed, retrying every minute (see the poller log): $title"
    fi
    exit 0
  }
  # The broker ships one approved run per job (its runs[0]) from one bundle, so a job with more
  # would ship only part of its approval. Ship those by hand, run by run.
  [ "$ship_runs" = 1 ] || refuse "$ship_runs approved runs, and the broker ships one run per job"
  case "$branch" in -|"") bundle_ref="" ;; *) bundle_ref="refs/heads/$branch" ;; esac
  # A branch that is a ref expression (job~1, a^, x..y) would bundle another commit.
  if [ -n "$bundle_ref" ] && { ! git check-ref-format --branch "$branch" >/dev/null 2>&1 \
      || [[ $branch == *[~^:\?\*\[]* ]] || [[ $branch == *..* ]] || [[ $branch == *@\{* ]]; }; then
    refuse "branch '$branch' is not a plain branch name"
  fi
  token=$("${J[@]}" claim-token "$id" 2>>"$LOG") && [ -n "$token" ] || failed "no claim token"
  # git bundle writes through a lock file with the umask's mode, so the folder keeps it private.
  bdir=$(mktemp -d) || failed "no temp folder"
  trap 'rm -rf "$bdir"' EXIT
  bundle="$bdir/job.bundle"
  : >"$bundle" || failed "no temp file"
  # Only commits origin lacks; none (already on origin) sends the token alone. Any other git
  # error (no such branch, not a repo) fails the hand-off rather than sending the token alone.
  if [ -n "$bundle_ref" ]; then
    git -C "$run_dir" rev-parse -q --verify "$bundle_ref^{commit}" >/dev/null 2>>"$LOG" \
      || failed "branch $branch is not in $run_dir"
    ahead=$(git -C "$run_dir" rev-list -n 1 "$bundle_ref" --not --remotes=origin 2>>"$LOG") \
      || failed "could not list the commits of $branch in $run_dir"
    if [ -n "$ahead" ]; then
      git -C "$run_dir" bundle create -q "$bundle" "$bundle_ref" --not --remotes=origin 2>>"$LOG" \
        || failed "could not bundle $branch in $run_dir"
    fi
  fi
  # shellcheck disable=SC2024 # the log is this user's; sudo is only for the broker command
  { printf '%s\n' "$token"; cat "$bundle"; } | sudo -n -u broker "$POLLER_SHIP_CMD" --job "$id" >>"$LOG" 2>&1 \
    || failed "the broker did not accept it"
  echo "$tried_key" >>"$TRIED"
  log "JOB-$id ship request sent to the broker"
  notify "JOB-$id ship request sent to the broker: $title"
  exit 0
)

# ── Start (a detached worker per pick) ───────────────────────────────────────
# A job is started at most once. A failed run stays in Backlog and is not retried every
# minute: an operator reply on the card retries it once (see Report), or delete its lines
# from poller-tried to let the poller start it again.
start_run() {
  echo "${tried_key:-${retry_key:-$id}}" >>"$TRIED"
  [ -n "$tried_key" ] || echo "$id" >>"$OWNED" # this run claims it
  run_dir=$(cd "$run_dir" && pwd -P) || return 0 # absolute, for trust.py and the worker
  # A folder that was never trusted drops its permission allow rules in a headless run. Done
  # here under the lock, so two runs never rewrite ~/.claude.json at the same time.
  [ "$run_dir" = "$HOME" ] || "$PYTHON3_BIN" "$SKILL_DIR/assets/trust.py" "$run_dir" >>"$LOG" 2>&1 \
    || log "JOB-$id could not mark $run_dir trusted"
  log "JOB-$id start in $run_dir ($kind, lanes $lanes): $title"
  # Its own process group (set -m), so it outlives this tick: launchd (AbandonProcessGroup) and
  # systemd (KillMode=process) leave it running when the tick exits.
  set -m
  "$BASH" "$0" --run "$id" "$kind" "$run_dir" "${reply_cid:--}" "$title" "${time_limit:--}" </dev/null >>"$LOG" 2>&1 &
  worker=$!
  set +m
  "$PYTHON3_BIN" -c '
import json, os, sys
pid, kind, lanes, path = sys.argv[1:]
with open(path + ".tmp", "w") as f:
    json.dump({"pid": int(pid), "kind": kind, "lanes": lanes.split(",")}, f)
os.replace(path + ".tmp", path)
' "$worker" "$kind" "$lanes" "$RUNS/$id.json" || log "JOB-$id could not write its run record"
}

# ── Tick ─────────────────────────────────────────────────────────────────────
# Each board list is read once a tick; each pick re-filters it against the live runs.
approved=$("${J[@]}" list --ship-approved --all-pages 2>/dev/null) || approved=""
awaiting=$("${J[@]}" list --awaiting --all-pages 2>/dev/null) || awaiting=""
listing="" board_busy="" board_read="" tick_picked=""
while :; do
  live_state
  [ "$live_n" -lt "$MAX_RUNS" ] || break
  pick || break
  tick_picked="$tick_picked $id" # never picked twice in one tick, whatever happens below
  if [ -n "${POLLER_MIRROR_SYNC:-}" ] && [ -n "$target" ]; then
    mirror_sync || continue
  fi
  if [ "$kind" != ship ] && [ -n "$target" ]; then
    slash_worktree || continue
  fi
  if [ "$kind" = ship ] && [ -n "${POLLER_SHIP_CMD:-}" ]; then
    broker_ship
    continue
  fi
  start_run
done
exit 0
