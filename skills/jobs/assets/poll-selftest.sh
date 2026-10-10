#!/usr/bin/env bash
# Scripted check of poll.sh with a fake HOME, a fake jobs.py, a fake claude and a fake
# Telegram sender. Covers the pick filter (board jobs included), the run folder and its trust, the untargeted slash job and its default home,
# the once-per-job skip log, the stale and live lock, the at-most-once rule, the In review
# message, the watchdog, and the failure comment with its retry on reply. Touches no hub, no launchd, no real config.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# A JOBS_DEFAULT_HOME from the caller's shell would run the untargeted job early.
unset JOBS_DEFAULT_HOME
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
exit "${FAKE_RC:-0}"
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
fail() { echo "poll selftest FAIL: $*" >&2; cat "$tmp/log" "$tmp/calls" >&2 2>/dev/null; exit 1; }

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
[ "$(grep -c '^comment 2 --kind event --body Not started by the poller: no target and not a slash command' "$tmp/calls")" = 1 ] \
  || fail "non-slash skip not said on the card exactly once"

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
        "comments": [{"id": 20, "author": "you", "kind": "message"}, {"id": last, "author": "you", "kind": "message"}, {"id": 35, "author": "agent"}]}}))
elif a[0] == "repos":
    print(json.dumps({"repos": [{"target": "o/r", "display": "r", "path": os.environ["FAKE_REPO"]}]}))
EOF
echo 8 >"$HOME/.config/jobs/poller-owned"
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
grep -q 'JOB-8 reply run failed' "$tmp/sent" || fail "an unacked reply run was not reported as failed"
grep -qx 10 "$HOME/.config/jobs/poller-owned" || fail "backlog run not recorded as poller-owned"
: >"$tmp/calls"
FAKE_LAST=41 bash "$here/poll.sh"
grep -q 'JOB-8 --background' "$tmp/calls" || fail "a new reply did not start a run"
# ix) An approved run ships first, once per approved commit, with the --ship flag.
cat >"$tmp/skill/assets/jobs.py" <<'EOF'
import json, os, sys
open(os.environ["CALLS"], "a").write(" ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
run = {"state": os.environ.get("FAKE_STATE", "approved"), "target": "o/r", "approved_sha": "abc1234"}
when = os.environ.get("FAKE_WHEN", "2026-10-10T05:00:00+00:00")
if a[0] == "list" and "--ship-approved" in a:
    print(json.dumps({"jobs": [{"id": 12, "claimed": True, "title": "ship me", "ship_approved_at": when, "runs": [run]},
                               {"id": 13, "claimed": True, "title": "not mine", "ship_approved_at": when, "runs": [run]}]}))
elif a[0] == "list":
    print(json.dumps({"jobs": [{"id": 10, "column": "backlog", "targets": ["o/r"], "claimed": False, "title": "backlog"}]}))
elif a[0] == "get":
    print(json.dumps({"data": {"id": int(a[1]), "column": "in_review", "runs": [run]}}))
elif a[0] == "repos":
    print(json.dumps({"repos": [{"target": "o/r", "display": "r", "path": os.environ["FAKE_REPO"]}]}))
EOF
echo '{"12": "tok"}' >"$HOME/.config/jobs/claims.json"
: >"$HOME/.config/jobs/poller-tried"
: >"$tmp/calls"
: >"$tmp/sent"
FAKE_STATE=approved bash "$here/poll.sh"
grep -q "claude -p /jobs JOB-12 --background --ship .* @ $repo_real\$" "$tmp/calls" || fail "approved job 12 not shipped in its checkout"
grep -q 'JOB-13 ' "$tmp/calls" && fail "job without this machine's claim shipped"
grep -q 'JOB-10 ' "$tmp/calls" && fail "backlog started before an approved ship"
grep -q 'JOB-12 ship did not complete' "$tmp/sent" || fail "an unshipped run was not reported as incomplete"
grep -qx '12#ship@2026-10-10T05:00:00+00:00' "$HOME/.config/jobs/poller-tried" || fail "ship key not recorded"
: >"$tmp/calls"
bash "$here/poll.sh"
grep -q 'JOB-12 ' "$tmp/calls" && fail "same approval shipped twice"
: >"$tmp/calls"
FAKE_WHEN=2026-10-10T06:00:00+00:00 bash "$here/poll.sh"
grep -q 'JOB-12 --background --ship' "$tmp/calls" || fail "a re-approval of the same commit did not ship"
# x) A Backlog run that leaves the card in Backlog posts one failure comment and records
# "<id>~<newest comment id>". No reply, no retry; one reply, one retry; the same reply never twice.
cat >"$tmp/skill/assets/jobs.py" <<'EOF'
import json, os, sys
open(os.environ["CALLS"], "a").write(" ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
if a[0] == "list":
    print(json.dumps({"jobs": [{"id": 20, "column": "backlog", "targets": ["o/r"], "claimed": False, "title": "flaky"}]}))
elif a[0] == "get":
    cs = [{"id": 50, "author": "agent"}]
    if os.environ.get("FAKE_YOU"):
        cs.append({"id": int(os.environ["FAKE_YOU"]), "author": "you", "kind": "message"})
    print(json.dumps({"data": {"id": int(a[1]), "column": os.environ.get("FAKE_COLUMN", "in_review"), "comments": cs}}))
elif a[0] == "repos":
    print(json.dumps({"repos": [{"target": "o/r", "display": "r", "path": os.environ["FAKE_REPO"]}]}))
EOF
: >"$HOME/.config/jobs/poller-tried"
: >"$tmp/calls"
FAKE_COLUMN=backlog bash "$here/poll.sh"
grep -qx 'comment 20 --kind event --body Background run failed: never claimed. Reply on this card to retry.' "$tmp/calls" \
  || fail "no failure comment for a run that left the card in Backlog"
grep -qx '20~50' "$HOME/.config/jobs/poller-tried" || fail "failure not recorded with the newest comment id"
: >"$tmp/calls"
FAKE_COLUMN=backlog bash "$here/poll.sh"
grep -q 'JOB-20 ' "$tmp/calls" && fail "failed job retried without a reply"
: >"$tmp/calls"
FAKE_YOU=60 FAKE_RC=3 FAKE_COLUMN=backlog bash "$here/poll.sh"
grep -q 'claude -p /jobs JOB-20 --background' "$tmp/calls" || fail "a reply after the failure did not retry"
grep -qx '20~60' "$HOME/.config/jobs/poller-tried" || fail "retry key not recorded"
grep -qx 'comment 20 --kind event --body Background run failed: exit 3. Reply on this card to retry.' "$tmp/calls" \
  || fail "no failure comment for a non-zero exit"
: >"$tmp/calls"
FAKE_YOU=60 FAKE_COLUMN=backlog bash "$here/poll.sh"
grep -q 'JOB-20 ' "$tmp/calls" && fail "the same reply retried twice"
: >"$tmp/calls"
FAKE_YOU=70 FAKE_COLUMN=backlog JOBS_POLLER_LIMIT=2 FAKE_RUN_SECS=60 bash "$here/poll.sh"
grep -qx 'comment 20 --kind event --body Background run failed: stopped after 0 minutes. Reply on this card to retry.' "$tmp/calls" \
  || fail "no failure comment for a watchdog kill in Backlog"
grep -q 'body Stopped after' "$tmp/calls" && fail "watchdog comment doubled up with the failure comment"
: >"$tmp/calls"
FAKE_YOU=80 FAKE_COLUMN=in_review bash "$here/poll.sh"
grep -q 'JOB-20 --background' "$tmp/calls" || fail "a newer reply did not retry"
grep -q 'Background run failed' "$tmp/calls" && fail "failure comment on a run that left Backlog"
echo "poll.sh selftest: ok"
