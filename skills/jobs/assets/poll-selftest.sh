#!/usr/bin/env bash
# Scripted check of poll.sh with a fake HOME, a fake jobs.py, a fake claude and a fake
# Telegram sender. Covers the pick filter (board jobs included), the run folder and its trust, the untargeted slash job and its default home,
# the once-per-job skip log, the stale and live lock, the at-most-once rule, the In review
# message and the watchdog. Touches no hub, no launchd, no real config.
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
        {"id": 2, "source": "zero", "column": "backlog", "targets": [], "claimed": False, "title": "/looks-like-one"},
        {"id": 4, "source": "zero", "column": "backlog", "targets": [], "claimed": False, "title": "slash job"},
        {"id": 5, "source": "zero", "column": "backlog", "targets": ["o/r"], "claimed": False, "title": "newer"},
        {"id": 3, "source": "zero", "column": "backlog", "targets": ["o/r"], "claimed": False, "title": "oldest"},
        {"id": 6, "source": "board", "column": "backlog", "targets": ["o/r"], "claimed": False, "title": "board job"},
    ], "next_cursor": None}))
elif sys.argv[1] == "repos":
    print(json.dumps({"repos": [{"target": "o/r", "display": "r", "path": os.environ["FAKE_REPO"]}]}))
elif sys.argv[1] == "get":
    # Job 2's title looks like a command but its prompt is not one; only the prompt counts.
    prompts = {2: "file this email", 4: "  /apply-for-jobs the role in the email"}
    print(json.dumps({"data": {"id": int(sys.argv[2]), "column": os.environ.get("FAKE_COLUMN", "in_review"),
                               "prompt": prompts.get(int(sys.argv[2]), "")}}))
EOF
cat >"$tmp/claude" <<'EOF'
#!/usr/bin/env bash
echo "claude $* @ $(pwd -P)" >>"$CALLS"
sid=$(printf '%s\n' "$@" | grep -A1 -x -- --session-id | tail -1)
mkdir -p "$HOME/.claude/projects/p" && echo '{"entrypoint":"sdk-cli"}' >"$HOME/.claude/projects/p/$sid.jsonl"
sleep "${FAKE_RUN_SECS:-0}"
EOF
cat >"$tmp/send.sh" <<'EOF'
#!/usr/bin/env bash
echo "$1" >>"$SENT"
EOF
cat >"$tmp/skill/assets/trust.py" <<'EOF'
import os, sys
open(os.environ["CALLS"], "a").write("trust " + " ".join(sys.argv[1:]) + "\n")
EOF
chmod +x "$tmp/claude" "$tmp/send.sh"
printf 'CLAUDE_BIN=%q\nPYTHON3_BIN=%q\nSKILL_DIR=%q\nTELEGRAM_SEND=%q\nPOLLER_PATH=%q\n' \
  "$tmp/claude" "$py" "$tmp/skill" "$tmp/send.sh" "$PATH" >"$HOME/.config/jobs/poller.env"
mkdir "$tmp/repo"
export CALLS="$tmp/calls" SENT="$tmp/sent" FAKE_REPO="$tmp/repo"
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
grep -Eq 'claude -p /jobs JOB-3 --background --session-id [0-9a-f-]{36} --permission-mode auto --permission-prompts none' "$tmp/calls" \
  || fail "JOB-3 not started with the explicit permission mode"
grep -q 'list --column backlog --all-pages' "$tmp/calls" || fail "list call"
grep -q 'source' "$tmp/calls" && fail "list still filters by source"
grep -q 'JOB-3 is In review' "$tmp/sent" || fail "no In review message"
grep -q sdk-cli "$HOME"/.claude/projects/p/*.jsonl && fail "transcript not retagged"
grep -q '"entrypoint":"cli"' "$HOME"/.claude/projects/p/*.jsonl || fail "transcript lost its entrypoint"
repo_real=$(cd "$tmp/repo" && pwd -P)
grep -q "JOB-3 --background .* @ $repo_real\$" "$tmp/calls" || fail "targeted job not run from its checkout"
grep -q "^trust $repo_real\$" "$tmp/calls" || fail "run folder not trusted before the run"

# ii) The next tick does not start JOB-3 again; it takes JOB-5, then board job 6. Untargeted job 2 never starts.
FAKE_COLUMN=backlog bash "$here/poll.sh"
[ "$(grep -c 'JOB-3 --background' "$tmp/calls")" = 1 ] || fail "JOB-3 started twice"
grep -q 'JOB-5 run failed' "$tmp/sent" || fail "no failure message for JOB-5"
bash "$here/poll.sh"
grep -q 'JOB-6 --background' "$tmp/calls" || fail "board job 6 not started"
grep -Eq 'JOB-(2|4) ' "$tmp/calls" && fail "untargeted job started"
# With no JOBS_DEFAULT_HOME, an untargeted job is skipped, logged once, and its prompt is not read.
[ "$(grep -c 'JOB-4 skipped: no target and JOBS_DEFAULT_HOME is unset' "$tmp/log")" = 1 ] \
  || fail "missing default home not logged exactly once"
grep -q '^get 4$' "$tmp/calls" && fail "prompt read with no default home"

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

# vi) A default home that is missing on disk still skips; JOB-5 (tagged) starts instead.
printf 'JOBS_DEFAULT_HOME=%q\n' "$tmp/nohome" >>"$HOME/.config/jobs/poller.env"
bash "$here/poll.sh"
grep -q 'JOB-5 --background' "$tmp/calls" || fail "tagged JOB-5 not started"
grep -Eq 'JOB-4 --background' "$tmp/calls" && fail "JOB-4 started with a missing default home"

# vii) With the default home present, the untargeted slash job starts there. The
# untargeted job whose prompt is not a slash command is skipped and logged once.
mkdir "$tmp/xcoach"
printf 'JOBS_DEFAULT_HOME=%q\n' "$tmp/xcoach" >>"$HOME/.config/jobs/poller.env"
bash "$here/poll.sh"
xc_real=$(cd "$tmp/xcoach" && pwd -P)
grep -Eq "claude -p /jobs JOB-4 --background --session-id [0-9a-f-]{36} --permission-mode auto --permission-prompts none @ $xc_real\$" \
  "$tmp/calls" || fail "slash JOB-4 not started in JOBS_DEFAULT_HOME"
bash "$here/poll.sh"
bash "$here/poll.sh"
[ "$(grep -c 'JOB-2 skipped: no target and not a slash command' "$tmp/log")" = 1 ] \
  || fail "non-slash skip not logged exactly once"
[ "$(grep -c '^get 2$' "$tmp/calls")" = 1 ] || fail "non-slash prompt read more than once"
grep -q 'JOB-2 --background' "$tmp/calls" && fail "non-slash untargeted job started"

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
# viii) A reply on a job this machine claimed starts one run per reply, before any backlog job,
# in the target's checkout, with heartbeats on and off around it.
cat >"$tmp/skill/assets/jobs.py" <<'EOF'
import json, os, sys
open(os.environ["CALLS"], "a").write(" ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
if a[0] == "list" and "--awaiting" in a:
    print(json.dumps({"jobs": [
        {"id": 8, "column": "in_review", "claimed": True, "awaiting": True, "targets": ["o/r"], "title": "reply job"},
        {"id": 9, "column": "in_review", "claimed": True, "awaiting": True, "targets": ["o/r"], "title": "not mine"},
    ]}))
elif a[0] == "list":
    print(json.dumps({"jobs": [{"id": 10, "column": "backlog", "targets": ["o/r"], "claimed": False, "title": "backlog"}]}))
elif a[0] == "get":
    last = int(os.environ.get("FAKE_LAST", "40"))
    print(json.dumps({"data": {"id": int(a[1]), "column": "in_review", "ack_comment_id": 30,
        "comments": [{"id": 20, "author": "you"}, {"id": last, "author": "you"}, {"id": 35, "author": "agent"}]}}))
elif a[0] == "repos":
    print(json.dumps({"repos": [{"target": "o/r", "display": "r", "path": os.environ["FAKE_REPO"]}]}))
EOF
echo '{"8": "tok"}' >"$HOME/.config/jobs/claims.json"
: >"$HOME/.config/jobs/poller-tried"
: >"$tmp/calls"
bash "$here/poll.sh"
grep -q "claude -p /jobs JOB-8 --background .* @ $repo_real\$" "$tmp/calls" || fail "reply job 8 not started in its checkout"
grep -q 'JOB-10 ' "$tmp/calls" && fail "backlog job started before the reply"
grep -q 'JOB-9 ' "$tmp/calls" && fail "job claimed elsewhere started"
grep -qx '8@40' "$HOME/.config/jobs/poller-tried" || fail "reply key not recorded"
grep -q '^patch 8 --active on$' "$tmp/calls" || fail "no heartbeat on"
grep -q '^patch 8 --active off$' "$tmp/calls" || fail "no heartbeat off"
: >"$tmp/calls"
bash "$here/poll.sh"
grep -q 'JOB-8 ' "$tmp/calls" && fail "same reply started twice"
grep -q 'JOB-10 --background' "$tmp/calls" || fail "backlog job not taken once the reply was handled"
: >"$tmp/calls"
FAKE_LAST=41 bash "$here/poll.sh"
grep -q 'JOB-8 --background' "$tmp/calls" || fail "a new reply did not start a run"
echo "poll.sh selftest: ok"
