#!/usr/bin/env bash
# One tick of the /jobs background poller. launchd runs it every 60 s (install-poller.sh).
#
# launchd gives no login-shell environment, so every path comes from
# ~/.config/jobs/poller.env, which the installer writes. Each tick:
#   1. Takes the lock (a directory holding the run's PID). A lock whose PID is dead is removed.
#   2. Makes one `jobs.py list --column backlog` call (board and ZERO jobs alike).
#   3. Takes the oldest waiting job that was never started here (or whose run failed and the
#      operator has replied since). An untargeted job runs too: the run picks its repo.
#   4. Marks the run folder trusted (trust.py), then runs `claude -p "/jobs JOB-<id> --background"`
#      in the background, from the first target's checkout for a targeted job, from the checkout
#      whose path the prompt names for an untargeted job that names one, else from
#      $JOBS_DEFAULT_HOME, and kills it after 45 minutes (macOS
#      has no `timeout`). Running in the checkout puts the thread under that repo, so the
#      card's "Open thread" link finds it from that repo's VS Code window.
#   5. Sends Telegram when the card reaches In review or the run fails.
# The tick stays in the foreground while the run lives, so launchd starts no second tick.
# It never reads or writes claims.json: jobs.py owns that file.
set -uo pipefail

CFG_DIR="$HOME/.config/jobs"
CONF="$CFG_DIR/poller.env"
LOCK="$CFG_DIR/poller.lock"
TRIED="$CFG_DIR/poller-tried"
SKIPPED="$CFG_DIR/poller-skipped" # "<id>:<reason>" lines, so each skip logs once
OWNED="$CFG_DIR/poller-owned" # ids of jobs a poller run claimed; only these get reply runs
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
[ -n "${JOBS_DEFAULT_HOME:-}" ] && export JOBS_DEFAULT_HOME
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
touch "$TRIED" "$SKIPPED" "$OWNED"

# First, a job this machine claimed that has an operator reply it has not read. One run per
# reply: the key is "<id>@<newest operator comment id>", so a later reply starts another run.
first_target_dir() { # $1 = owner/repo; prints its checkout, or nothing
  "${J[@]}" repos --dry-run 2>/dev/null | "$PYTHON3_BIN" -c '
import json, sys
m = [r["path"] for r in json.load(sys.stdin)["repos"] if r["target"] == sys.argv[1]]
print(m[0] if m else "")
' "$1" 2>/dev/null
}
id="" title="" run_dir="$HOME" tried_key="" reply_cid="" ship=""
# Before anything else: a run the operator approved to ship. Approving is the instruction to
# ship, so the poller ships it unattended. One run per approved commit: "<id>#ship@<sha>".
if approved=$("${J[@]}" list --ship-approved --all-pages 2>/dev/null); then
  read -r cid ctarget capproval csha ctitle < <(printf '%s' "$approved" | "$PYTHON3_BIN" -c '
import json, os, sys
tried = {l.strip() for l in open(sys.argv[1]) if l.strip()}
try:
    mine = set(json.load(open(os.path.expanduser("~/.config/jobs/claims.json"))))
except (OSError, ValueError):
    mine = set()  # shipping needs this machine claim token
for j in sorted(json.load(sys.stdin).get("jobs", []), key=lambda j: str(j["id"]).zfill(20)):
    runs = [r for r in j.get("runs") or [] if r.get("state") == "approved" and r.get("approved_sha")]
    if not runs or str(j["id"]) not in mine:
        continue
    # The approval time changes with every Approve ship, so a re-approval of the same
    # commit (after a refused ship voided the first) ships again.
    key = ("%s#ship@%s" % (j["id"], j.get("ship_approved_at") or runs[0]["approved_sha"])).replace(" ", "_")
    if key in tried:
        continue
    print(j["id"], runs[0]["target"], key.split("@", 1)[1], runs[0]["approved_sha"][:7],
          (j.get("title") or "")[:120].replace("\n", " "))
    break
' "$TRIED" 2>/dev/null)
  case "$cid" in
    ""|*[!0-9]*) ;;
    *)
      id=$cid title=$ctitle ship=1 tried_key="$cid#ship@$capproval"
      run_dir=$(first_target_dir "$ctarget")
      [ -n "$run_dir" ] && [ -d "$run_dir" ] || run_dir=$HOME
      LIMIT="${JOBS_POLLER_SHIP_LIMIT:-5400}" # merge, review, build and deploy take longer
      log "JOB-$id approved to ship at $csha"
      ;;
  esac
fi
if [ -z "$id" ] && awaiting=$("${J[@]}" list --awaiting --all-pages 2>/dev/null); then
  while read -r cid ctarget ctitle; do
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
        [ -f "$t" ] && [ $(( $(date +%s) - $(stat -f %m "$t") )) -lt 180 ] && live=1
      done
      [ "$live" = 0 ] || continue
    fi
    grep -qxF "$cid@$last" "$TRIED" && continue
    id=$cid title=$ctitle tried_key="$cid@$last" reply_cid=$last
    if [ "$ctarget" != - ]; then
      run_dir=$(first_target_dir "$ctarget")
    else
      run_dir=${JOBS_DEFAULT_HOME:-}
    fi
    [ -n "$run_dir" ] && [ -d "$run_dir" ] || run_dir=$HOME
    log "JOB-$id has a reply to read (comment $last)"
    break
  done < <(printf '%s' "$awaiting" | "$PYTHON3_BIN" -c '
import json, sys
from datetime import datetime, timezone
# Only jobs a poller run claimed: an interactive thread answers replies on its own jobs.
mine = {l.strip() for l in open(sys.argv[1]) if l.strip()}
def fresh(ts):  # a live heartbeat means some run is already on it
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() < 180
for j in sorted(json.load(sys.stdin).get("jobs", []), key=lambda j: str(j["id"]).zfill(20)):
    if j.get("awaiting") and j.get("claimed") and str(j["id"]) in mine \
            and j.get("column") in ("in_progress", "in_review") and not fresh(j.get("active_at")):
        t = j.get("targets") or j.get("targets_picked") or []
        print(j["id"], t[0] if t else "-", (j.get("title") or "")[:120].replace("\n", " "))
' "$OWNED" 2>/dev/null)
fi

if [ -z "$id" ]; then
# --all-pages: without it, a full first page of tried/stuck backlog jobs could hide
# every newer job behind them.
if ! listing=$("${J[@]}" list --column backlog --all-pages 2>&1); then
  log "list failed: $(printf '%s' "$listing" | tr '\n' ' ' | cut -c1-300)"
  exit 1
fi
# One line per candidate, oldest first: "<id> <T|U> <first target|-> <after|-> <title>" (T has a
# tagged target, U has none).
# A started job is left out too, unless its run failed: "<id>~<n>" in poller-tried records the
# newest comment id at the failure, and <after> carries the highest such n. That job is a
# retry candidate, retried only when the operator has commented since.
cands=$(printf '%s' "$listing" | "$PYTHON3_BIN" -c '
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
        and not j.get("claimed") and wanted(j)]
for j in sorted(jobs, key=lambda j: str(j["id"]).zfill(20)):
    t = j.get("targets") or []
    i = str(j["id"])
    print(j["id"], "T" if t else "U", t[0] if t else "-", after[i] if i in skip and i in after else "-",
          (j.get("title") or "")[:120].replace("\n", " "))
' "$TRIED") || { log "could not parse the job list"; exit 1; }

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

retry_key=""
while read -r cid kind ctarget cafter ctitle; do
  [ -n "$cid" ] || continue
  case "$cid" in
    *[!0-9]*) log "bad id: refusing ($cid)"; exit 1 ;;
  esac
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
  if [ "$kind" = T ]; then
    id=$cid title=$ctitle
    # The first target's checkout, else $HOME (the run then fails that target on the card).
    run_dir=$(first_target_dir "$ctarget")
    [ -n "$run_dir" ] && [ -d "$run_dir" ] || run_dir=$HOME
    break
  fi
  # No target: the run works out the repo from the prompt (Background mode in SKILL.md), and
  # refuses on the card only when it cannot. Run it from the checkout whose path the prompt
  # names, so the thread and that repo's permission rules belong to it; else from the
  # default home. The title and the email comment are never read for this.
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
  id=$cid title=$ctitle run_dir=$JOBS_DEFAULT_HOME
  [ "$named" != - ] && [ -d "$named" ] && run_dir=$named
  break
done <<<"$cands"
fi
[ -n "$id" ] || exit 0

# ── Run ──────────────────────────────────────────────────────────────────────
# A job is started at most once. A failed run stays in Backlog and is not retried every
# minute: an operator reply on the card retries it once (see Report), or delete its lines
# from poller-tried to let the poller start it again.
echo "${tried_key:-${retry_key:-$id}}" >>"$TRIED"
[ -n "$tried_key" ] || echo "$id" >>"$OWNED" # this run claims it
log "JOB-$id start in $run_dir: $title"
cd "$run_dir" || exit 1
# Drive for desktop keeps most files online-only, and a headless run reading one gets
# "Resource deadlock avoided". Download the folders runs need first ("|"-separated paths).
if [ -n "${JOBS_PREFETCH:-}" ]; then
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
run_dir=$(pwd -P) # absolute, for trust.py and the claim's session folder
# A folder that was never trusted drops its permission allow rules in a headless run.
[ "$run_dir" = "$HOME" ] || "$PYTHON3_BIN" "$SKILL_DIR/assets/trust.py" "$run_dir" >>"$LOG" 2>&1 \
  || log "JOB-$id could not mark $run_dir trusted"
# jobs.py claim sends this folder with the session id, for the card's VS Code links.
export JOBS_RUN_DIR="$run_dir"
# auto is the defaultMode the interactive /jobs runs use. --permission-prompts none denies
# anything that would prompt, so an unattended run cannot stall on a question.
# Its own process group, so the watchdog can kill the whole tree (claude plus whatever
# it spawns) by group instead of chasing children one `pkill -P` level deep.
# A known session id, so the transcript can be found after the run (see Retag).
sid=$(uuidgen | tr '[:upper:]' '[:lower:]')
set -m
"$CLAUDE_BIN" -p "/jobs JOB-$id --background${ship:+ --ship}" --session-id "$sid" \
  --permission-mode auto --permission-prompts none >>"$LOG" 2>&1 &
run=$!
set +m
pid_tmp="$LOCK/pid.$$"
echo "$run" >"$pid_tmp"
mv "$pid_tmp" "$LOCK/pid"

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

# ── Retag ────────────────────────────────────────────────────────────────────
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

# ── Report ───────────────────────────────────────────────────────────────────
job_column() {
  "${J[@]}" get "$id" 2>/dev/null | "$PYTHON3_BIN" -c '
import json, sys
print(json.load(sys.stdin)["data"]["column"])
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
else
  notify "JOB-$id run failed (exit $rc, card in $column): $title"
fi
