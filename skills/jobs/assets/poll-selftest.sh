#!/usr/bin/env bash
# Scripted check of poll.sh with a fake HOME, a fake jobs.py, a fake claude and a fake
# Telegram sender. Covers the pick filter, the stale and live lock, the at-most-once rule,
# the In review message and the watchdog. Touches no hub, no launchd, no real config.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp/home" JOBS_POLLER_LOG="$tmp/log" JOBS_POLLER_STEP=1
mkdir -p "$HOME/.config/jobs" "$tmp/skill/assets"
py=$(command -v python3)

cat >"$tmp/skill/assets/jobs.py" <<'EOF'
import json, os, sys
open(os.environ["CALLS"], "a").write(" ".join(sys.argv[1:]) + "\n")
if sys.argv[1] == "list":
    print(json.dumps({"jobs": [
        {"id": 1, "source": "board", "column": "backlog", "targets": ["o/r"], "claimed": False, "title": "board job"},
        {"id": 2, "source": "zero", "column": "backlog", "targets": [], "claimed": False, "title": "no target"},
        {"id": 5, "source": "zero", "column": "backlog", "targets": ["o/r"], "claimed": False, "title": "newer"},
        {"id": 3, "source": "zero", "column": "backlog", "targets": ["o/r"], "claimed": False, "title": "oldest"},
    ], "next_cursor": None}))
elif sys.argv[1] == "get":
    print(json.dumps({"data": {"id": int(sys.argv[2]), "column": os.environ.get("FAKE_COLUMN", "in_review")}}))
EOF
cat >"$tmp/claude" <<'EOF'
#!/usr/bin/env bash
echo "claude $*" >>"$CALLS"
sleep "${FAKE_RUN_SECS:-0}"
EOF
cat >"$tmp/send.sh" <<'EOF'
#!/usr/bin/env bash
echo "$1" >>"$SENT"
EOF
chmod +x "$tmp/claude" "$tmp/send.sh"
printf 'CLAUDE_BIN=%q\nPYTHON3_BIN=%q\nSKILL_DIR=%q\nTELEGRAM_SEND=%q\nPOLLER_PATH=%q\n' \
  "$tmp/claude" "$py" "$tmp/skill" "$tmp/send.sh" "$PATH" >"$HOME/.config/jobs/poller.env"
export CALLS="$tmp/calls" SENT="$tmp/sent"
lock="$HOME/.config/jobs/poller.lock"
fail() { echo "poll selftest FAIL: $*" >&2; cat "$tmp/log" "$tmp/calls" 2>/dev/null >&2; exit 1; }

# i) A stale lock (dead PID) is removed; the oldest ZERO job with a target starts.
mkdir "$lock"
sleep 0 & dead=$!
wait "$dead"
echo "$dead" >"$lock/pid"
bash "$here/poll.sh"
[ ! -d "$lock" ] || fail "lock left after the run"
grep -q "removed stale lock (pid $dead)" "$tmp/log" || fail "stale lock not logged"
grep -q 'claude -p /jobs JOB-3 --background --permission-mode auto --permission-prompts none' "$tmp/calls" \
  || fail "JOB-3 not started with the explicit permission mode"
grep -q 'list --column backlog --source zero' "$tmp/calls" || fail "list call"
grep -q 'JOB-3 is In review' "$tmp/sent" || fail "no In review message"

# ii) The next tick does not start JOB-3 again; it takes JOB-5. Board job 1 and untargeted job 2 never start.
FAKE_COLUMN=backlog bash "$here/poll.sh"
[ "$(grep -c 'JOB-3 --background' "$tmp/calls")" = 1 ] || fail "JOB-3 started twice"
grep -q 'JOB-5 run failed' "$tmp/sent" || fail "no failure message for JOB-5"
bash "$here/poll.sh"
grep -Eq 'JOB-(1|2) ' "$tmp/calls" && fail "board or untargeted job started"

# iii) A live lock means a run is active: the tick makes no list call.
mkdir "$lock"
echo $$ >"$lock/pid"
before=$(wc -l <"$tmp/calls")
bash "$here/poll.sh"
[ "$(wc -l <"$tmp/calls")" = "$before" ] || fail "tick ran under a live lock"
rm -rf "$lock"

# iv) The watchdog kills a run past the limit and comments on the card.
: >"$HOME/.config/jobs/poller-tried"
JOBS_POLLER_LIMIT=2 FAKE_RUN_SECS=60 bash "$here/poll.sh"
grep -q 'comment 3 --kind event --body Stopped after 0 minutes' "$tmp/calls" || fail "no watchdog comment"
grep -q 'JOB-3 stopped after' "$tmp/sent" || fail "no watchdog message"

# v) A non-numeric id from the hub is refused, not run.
cat >"$tmp/skill/assets/jobs.py" <<'EOF'
import json, os, sys
open(os.environ["CALLS"], "a").write(" ".join(sys.argv[1:]) + "\n")
if sys.argv[1] == "list":
    print(json.dumps({"jobs": [
        {"id": "x1", "source": "zero", "column": "backlog", "targets": ["o/r"], "claimed": False, "title": "bad id"},
    ], "next_cursor": None}))
EOF
: >"$HOME/.config/jobs/poller-tried"
claude_calls_before=$(grep -c '^claude ' "$tmp/calls" || true)
rc=0
bash "$here/poll.sh" || rc=$?
[ "$rc" = 1 ] || fail "bad id did not exit 1 (got $rc)"
grep -q 'bad id: refusing (x1)' "$tmp/log" || fail "bad id not logged"
[ "$(grep -c '^claude ' "$tmp/calls" || true)" = "$claude_calls_before" ] || fail "claude ran for a bad id"
[ ! -d "$lock" ] || fail "lock left after a bad id"
echo "poll.sh selftest: ok"
