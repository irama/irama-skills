#!/usr/bin/env bash
# Scripted check of poll.sh with a fake HOME, a fake jobs.py, a fake claude and a fake
# Telegram sender. Covers the pick filter (board jobs included), the run folder and its trust, untargeted jobs and their run folder,
# the once-per-job skip log, the stale and live lock, the at-most-once rule, the In review
# message, the watchdog, the failure comment with its retry on reply, the POLLER_SKIP_* switches
# on all three pick paths, and box mode (mirror-sync, clone, ship through the broker) with a fake
# sudo, and the lanes: runs in different repos start in one tick, a busy repo waits, the cap,
# one ship and one untargeted run at a time, and a dead run record pruned; the job time limit
# (time_limit_s, clamped), the scheduled-job lane per template, the JOBS_POLLER_SOURCES filter and the
# targeted slash job worktree (fetch, dirty main refused, reuse on reply). Touches no hub, no
# launchd or systemd, no real config. Runs on macOS and Linux.
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
    # Job 2's prompt names a file inside the checkout, so it runs from there.
    prompts = {2: os.environ["FAKE_REPO"] + "/.scratch/handoff.md", 4: "  /apply-for-jobs the role in the email"}
    print(json.dumps({"data": {"id": int(sys.argv[2]), "column": os.environ.get("FAKE_COLUMN", "in_review"),
                               "prompt": prompts.get(int(sys.argv[2]), ""),
                               "ship_approved_at": os.environ.get("FAKE_SHIP_APPROVED")}}))
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
runs="$HOME/.config/jobs/runs"
# Every run lives 2 s unless a check says otherwise, so a run started early in a tick is still
# live when the same tick picks again (a real run lasts minutes).
export FAKE_RUN_SECS=2
# One tick, then wait for the detached runs it started to end, so each check reads their output.
settle() {
  local f p n=0 alive=1
  while [ "$alive" = 1 ]; do
    alive=0
    for f in "$runs"/*.json; do
      [ -f "$f" ] || continue
      p=$(sed -n 's/.*"pid": *\([0-9]*\).*/\1/p' "$f" 2>/dev/null || true) # the run may delete it meanwhile
      [ -n "$p" ] && kill -0 "$p" 2>/dev/null && alive=1
    done
    n=$((n + 1))
    [ "$n" -lt 600 ] || fail "detached runs did not end"
    [ "$alive" = 0 ] || sleep 0.2
  done
}
tick() { local rc=0; bash "$here/poll.sh" || rc=$?; settle; return "$rc"; }

# i) A stale lock (dead PID) is removed; the oldest ZERO job with a target starts.
mkdir "$lock"
sleep 0 & dead=$!
wait "$dead"
echo "$dead" >"$lock/pid"
tick
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
FAKE_COLUMN=backlog tick
[ "$(grep -c 'JOB-3 --background' "$tmp/calls")" = 1 ] || fail "JOB-3 started twice"
grep -q 'JOB-5 run failed' "$tmp/sent" || fail "no failure message for JOB-5"
# A pre-approved job ends In progress with its ship approved: that is success, not a failure.
FAKE_COLUMN=in_progress FAKE_SHIP_APPROVED=w tick
grep -q 'JOB-6 --background' "$tmp/calls" || fail "board job 6 not started"
grep -q 'JOB-6 finished, shipping (pre-approved)' "$tmp/sent" || fail "pre-approved end read as a failure"
grep -Eq 'JOB-(2|4) ' "$tmp/calls" && fail "untargeted job started"
# With no JOBS_DEFAULT_HOME, an untargeted job is skipped, logged once, and its prompt is not read.
[ "$(grep -c 'JOB-4 skipped: no target and JOBS_DEFAULT_HOME is unset' "$tmp/log")" = 1 ] \
  || fail "missing default home not logged exactly once"
grep -q '^get 4$' "$tmp/calls" && fail "prompt read with no default home"

# iii) A live lock means a run is active: the tick makes no list call.
mkdir "$lock"
echo $$ >"$lock/pid"
before=$(wc -l <"$tmp/calls")
tick
[ "$(wc -l <"$tmp/calls")" = "$before" ] || fail "tick ran under a live lock"
rm -rf "$lock"

# iv) The watchdog kills a run past the limit and comments on the card.
: >"$HOME/.config/jobs/poller-tried"
JOBS_POLLER_LIMIT=2 FAKE_RUN_SECS=60 tick
grep -q 'comment 3 --kind event --body Stopped after 0 minutes' "$tmp/calls" || fail "no watchdog comment"
grep -q 'JOB-3 stopped after' "$tmp/sent" || fail "no watchdog message"

# vi) A default home that is missing on disk still skips; JOB-5 (tagged) starts instead.
printf 'JOBS_DEFAULT_HOME=%q\n' "$tmp/nohome" >>"$HOME/.config/jobs/poller.env"
tick
grep -q 'JOB-5 --background' "$tmp/calls" || fail "tagged JOB-5 not started"
grep -Eq 'JOB-4 --background' "$tmp/calls" && fail "JOB-4 started with a missing default home"

# vii) With the default home present, untargeted jobs run. JOB-2's prompt names a file in
# the checkout, so it starts there; the slash job JOB-4 starts in JOBS_DEFAULT_HOME.
mkdir "$tmp/xcoach"
printf 'JOBS_DEFAULT_HOME=%q\n' "$tmp/xcoach" >>"$HOME/.config/jobs/poller.env"
tick
grep -q "JOB-2 --background .* @ $repo_real\$" "$tmp/calls" || fail "JOB-2 not run from the checkout its prompt names"
tick
xc_real=$(cd "$tmp/xcoach" && pwd -P)
grep -Eq "claude -p /jobs JOB-4 --background --session-id [0-9a-f-]{36} --permission-mode auto --permission-prompts none @ $xc_real\$" \
  "$tmp/calls" || fail "slash JOB-4 not started in JOBS_DEFAULT_HOME"
grep -q 'not a slash command' "$tmp/log" && fail "untargeted job still skipped as not a slash command"

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
tick || rc=$?
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
tick
grep -q "claude -p /jobs JOB-8 --background .* @ $repo_real\$" "$tmp/calls" || fail "reply job 8 not started in its checkout"
grep -q 'JOB-10 ' "$tmp/calls" && fail "backlog job started before the reply"
grep -q 'JOB-9 ' "$tmp/calls" && fail "job claimed elsewhere started"
grep -qx '8@40' "$HOME/.config/jobs/poller-tried" || fail "reply key not recorded"
grep -q '^patch 8 --active on$' "$tmp/calls" || fail "no heartbeat on"
grep -q '^patch 8 --active off$' "$tmp/calls" || fail "no heartbeat off"
: >"$tmp/calls"
tick
grep -q 'JOB-8 ' "$tmp/calls" && fail "same reply started twice"
grep -q 'JOB-10 --background' "$tmp/calls" || fail "backlog job not taken once the reply was handled"
grep -q 'JOB-8 reply run failed' "$tmp/sent" || fail "an unacked reply run was not reported as failed"
grep -qx 10 "$HOME/.config/jobs/poller-owned" || fail "backlog run not recorded as poller-owned"
: >"$tmp/calls"
FAKE_LAST=41 tick
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
FAKE_STATE=approved tick
grep -q "claude -p /jobs JOB-12 --background --ship .* @ $repo_real\$" "$tmp/calls" || fail "approved job 12 not shipped in its checkout"
grep -q 'JOB-13 ' "$tmp/calls" && fail "job without this machine's claim shipped"
grep -q 'JOB-10 ' "$tmp/calls" && fail "backlog started before an approved ship"
grep -q 'JOB-12 ship did not complete' "$tmp/sent" || fail "an unshipped run was not reported as incomplete"
grep -qx '12#ship@2026-10-10T05:00:00+00:00' "$HOME/.config/jobs/poller-tried" || fail "ship key not recorded"
: >"$tmp/calls"
tick
grep -q 'JOB-12 ' "$tmp/calls" && fail "same approval shipped twice"
: >"$tmp/calls"
FAKE_WHEN=2026-10-10T06:00:00+00:00 tick
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
FAKE_COLUMN=backlog tick
grep -qx 'comment 20 --kind event --body Background run failed: never claimed. Reply on this card to retry.' "$tmp/calls" \
  || fail "no failure comment for a run that left the card in Backlog"
grep -qx '20~50' "$HOME/.config/jobs/poller-tried" || fail "failure not recorded with the newest comment id"
: >"$tmp/calls"
FAKE_COLUMN=backlog tick
grep -q 'JOB-20 ' "$tmp/calls" && fail "failed job retried without a reply"
: >"$tmp/calls"
FAKE_YOU=60 FAKE_RC=3 FAKE_COLUMN=backlog tick
grep -q 'claude -p /jobs JOB-20 --background' "$tmp/calls" || fail "a reply after the failure did not retry"
grep -qx '20~60' "$HOME/.config/jobs/poller-tried" || fail "retry key not recorded"
grep -qx 'comment 20 --kind event --body Background run failed: exit 3. Reply on this card to retry.' "$tmp/calls" \
  || fail "no failure comment for a non-zero exit"
: >"$tmp/calls"
FAKE_YOU=60 FAKE_COLUMN=backlog tick
grep -q 'JOB-20 ' "$tmp/calls" && fail "the same reply retried twice"
: >"$tmp/calls"
FAKE_YOU=70 FAKE_COLUMN=backlog JOBS_POLLER_LIMIT=2 FAKE_RUN_SECS=60 tick
grep -qx 'comment 20 --kind event --body Background run failed: stopped after 0 minutes. Reply on this card to retry.' "$tmp/calls" \
  || fail "no failure comment for a watchdog kill in Backlog"
grep -q 'body Stopped after' "$tmp/calls" && fail "watchdog comment doubled up with the failure comment"
: >"$tmp/calls"
FAKE_YOU=80 FAKE_COLUMN=in_review tick
grep -q 'JOB-20 --background' "$tmp/calls" || fail "a newer reply did not retry"
grep -q 'Background run failed' "$tmp/calls" && fail "failure comment on a run that left Backlog"
# xi) POLLER_SKIP_UNTARGETED and POLLER_SKIP_LOCAL leave untargeted and local/* jobs alone on
# all three pick paths, before any side effect. Each path is checked with a control tick
# (switches off: the job starts) and a skip tick (switches on: no call but the listing).
cat >"$tmp/skill/assets/jobs.py" <<'EOF'
import json, os, sys
open(os.environ["CALLS"], "a").write(" ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
path, t = os.environ.get("FAKE_PATH"), json.loads(os.environ.get("FAKE_TARGETS", "[]"))
jobs = []
if a[0] == "list" and "--ship-approved" in a and path == "ship":
    jobs = [{"id": 40, "claimed": True, "title": "ship", "ship_approved_at": "w",
             "runs": [{"state": "approved", "target": t[0] if t else "", "approved_sha": "abc1234"}]}]
elif a[0] == "list" and "--awaiting" in a and path == "awaiting":
    jobs = [{"id": 40, "column": "in_review", "claimed": True, "awaiting": True, "targets": t, "title": "reply"}]
elif a[0] == "list" and "--column" in a and path == "backlog":
    jobs = [{"id": 40, "column": "backlog", "targets": t, "claimed": False, "title": "backlog"}]
if a[0] == "list":
    print(json.dumps({"jobs": jobs}))
elif a[0] == "get":
    print(json.dumps({"data": {"id": int(a[1]), "column": "in_review", "prompt": "do it",
        "comments": [{"id": 90, "author": "you", "kind": "message"}]}}))
elif a[0] == "repos":
    print(json.dumps({"repos": [{"target": "o/r", "display": "r", "path": os.environ["FAKE_REPO"]}]}))
EOF
echo '{"40": "tok"}' >"$HOME/.config/jobs/claims.json"
echo 40 >"$HOME/.config/jobs/poller-owned"
for path in ship awaiting backlog; do
  for targets in '[]' '["local/x"]'; do
    [ "$path" = ship ] && [ "$targets" = '[]' ] && continue # a ship run always names its target
    : >"$HOME/.config/jobs/poller-tried"
    : >"$HOME/.config/jobs/poller-skipped"
    : >"$tmp/calls"
    FAKE_PATH=$path FAKE_TARGETS=$targets tick
    grep -q 'JOB-40 ' "$tmp/calls" || fail "control: $path job with targets $targets did not start"
    : >"$HOME/.config/jobs/poller-tried"
    : >"$tmp/calls"
    FAKE_PATH=$path FAKE_TARGETS=$targets POLLER_SKIP_UNTARGETED=1 POLLER_SKIP_LOCAL=1 tick
    if grep -v '^list ' "$tmp/calls" | grep -q .; then
      fail "$path job with targets $targets had a side effect: $(grep -v '^list ' "$tmp/calls" | head -1)"
    fi
    [ -s "$HOME/.config/jobs/poller-tried" ] && fail "$path job with targets $targets recorded as tried"
  done
done
# Set in poller.env (not only the caller's env), the switches still apply.
printf 'POLLER_SKIP_UNTARGETED=1\nPOLLER_SKIP_LOCAL=1\n' >>"$HOME/.config/jobs/poller.env"
: >"$tmp/calls"
FAKE_PATH=backlog FAKE_TARGETS='["local/x"]' tick
grep -q 'JOB-40 ' "$tmp/calls" && fail "POLLER_SKIP_LOCAL in poller.env ignored"
"$py" -c 'import sys; p = sys.argv[1]; k = [l for l in open(p) if not l.startswith("POLLER_SKIP_")]; open(p, "w").writelines(k)' \
  "$HOME/.config/jobs/poller.env"

# xiii) Lanes. Backlog jobs in different repos start in one tick; a job whose repo a sibling job
# holds (In review, a run not shipped) waits until the sibling's runs ship; the cap holds; at
# most one ship run and one untargeted run are live; a dead run record is pruned.
mkdir -p "$tmp/repo-s" "$tmp/repo-t"
cat >"$tmp/skill/assets/jobs.py" <<'EOF'
import json, os, sys
open(os.environ["CALLS"], "a").write(" ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
scene = os.environ.get("FAKE_SCENE")
jobs = []
if scene == "lanes":
    jobs = [{"id": 60, "column": "backlog", "targets": ["o/r"], "claimed": False, "title": "a"},
            {"id": 61, "column": "backlog", "targets": ["o/s"], "claimed": False, "title": "b"},
            {"id": 62, "column": "in_review", "targets": [], "targets_picked": ["o/r"], "claimed": True, "title": "sibling",
             "runs": [{"target": "o/r", "state": os.environ.get("FAKE_SIBLING", "committed")}]},
            {"id": 63, "column": "backlog", "targets": ["o/t"], "claimed": False, "title": "c"}]
elif scene == "untargeted":
    jobs = [{"id": 80, "column": "backlog", "targets": [], "claimed": False, "title": "u1"},
            {"id": 81, "column": "backlog", "targets": [], "claimed": False, "title": "u2"}]
ships = []
if scene == "ships":
    ships = [{"id": i, "claimed": True, "title": "ship", "ship_approved_at": "w",
              "runs": [{"state": "approved", "target": t, "approved_sha": "abc1234"}]} for i, t in ((70, "o/r"), (71, "o/s"))]
if a[0] == "list" and "--ship-approved" in a:
    print(json.dumps({"jobs": ships}))
elif a[0] == "list" and "--awaiting" in a:
    print(json.dumps({"jobs": []}))
elif a[0] == "list" and "--column" in a:
    c = a[a.index("--column") + 1]
    print(json.dumps({"jobs": [j for j in jobs if j["column"] == c]}))
elif a[0] == "list":
    print(json.dumps({"jobs": jobs}))
elif a[0] == "get":
    print(json.dumps({"data": {"id": int(a[1]), "column": "in_review", "prompt": "do it", "comments": []}}))
elif a[0] == "repos":
    print(json.dumps({"repos": [{"target": t, "display": t, "path": p} for t, p in
        (("o/r", os.environ["FAKE_REPO"]), ("o/s", os.environ["FAKE_REPO"] + "-s"), ("o/t", os.environ["FAKE_REPO"] + "-t"))]}))
EOF
started() { cat "$tmp/calls" | grep -c "^claude -p /jobs JOB-$1 " || true; }
: >"$HOME/.config/jobs/poller-tried"; : >"$tmp/calls"
FAKE_SCENE=lanes tick
[ "$(started 61)" = 1 ] || fail "JOB-61 (o/s free) did not start"
[ "$(started 63)" = 1 ] || fail "JOB-63 (o/t free) did not start in the same tick"
[ "$(started 60)" = 0 ] || fail "JOB-60 started while sibling JOB-62 holds o/r unshipped"
: >"$tmp/calls"
FAKE_SCENE=lanes FAKE_SIBLING=shipped tick
[ "$(started 60)" = 1 ] || fail "JOB-60 did not start once the sibling's runs shipped"
# The cap: three free repos, two runs.
: >"$HOME/.config/jobs/poller-tried"; : >"$tmp/calls"
FAKE_SCENE=lanes FAKE_SIBLING=shipped JOBS_POLLER_MAX_RUNS=2 tick
[ "$(cat "$tmp/calls" | grep -c '^claude -p /jobs JOB-6[013] ' || true)" = 2 ] || fail "cap of 2 runs not kept"
# A live run record holds its repo; a dead one is pruned and frees it.
: >"$HOME/.config/jobs/poller-tried"; : >"$tmp/calls"
echo "{\"pid\": $$, \"kind\": \"backlog\", \"lanes\": [\"o/r\"]}" >"$runs/99.json"
FAKE_SCENE=lanes FAKE_SIBLING=shipped bash "$here/poll.sh"
rm -f "$runs/99.json"
settle
[ "$(started 60)" = 0 ] || fail "JOB-60 started while a live run holds o/r"
sleep 0 & dead=$!
wait "$dead"
echo "{\"pid\": $dead, \"kind\": \"backlog\", \"lanes\": [\"o/r\"]}" >"$runs/99.json"
: >"$tmp/calls"
FAKE_SCENE=lanes FAKE_SIBLING=shipped tick
[ -e "$runs/99.json" ] && fail "dead run record not pruned"
cat "$tmp/log" | grep -q "JOB-99 run record pruned (pid $dead" || fail "pruned record not logged"
[ "$(started 60)" = 1 ] || fail "JOB-60 did not start once the dead record was pruned"
# One ship at a time: two approved ships in different repos, one per tick.
echo '{"70": "t", "71": "t"}' >"$HOME/.config/jobs/claims.json"
: >"$HOME/.config/jobs/poller-tried"; : >"$tmp/calls"
FAKE_SCENE=ships tick
[ "$(cat "$tmp/calls" | grep -c '^claude -p /jobs JOB-7[01] --background --ship ' || true)" = 1 ] || fail "two ship runs in one tick"
FAKE_SCENE=ships tick
[ "$(started 70)" = 1 ] && [ "$(started 71)" = 1 ] || fail "second ship did not run on the next tick"
# One untargeted run at a time.
: >"$HOME/.config/jobs/poller-tried"; : >"$tmp/calls"
JOBS_DEFAULT_HOME="$tmp/xcoach" FAKE_SCENE=untargeted tick
[ "$(cat "$tmp/calls" | grep -c '^claude -p /jobs JOB-8[01] ' || true)" = 1 ] || fail "two untargeted runs in one tick"

# xiv) Time limit. The job's time_limit_s reaches the worker (`poll.sh --run`, last argument),
# clamped to 600 to 14400 s; none keeps JOBS_POLLER_LIMIT; a reply run carries it too. With the
# floor lowered for the test, a short limit stops the run at about that limit.
cat >"$tmp/skill/assets/jobs.py" <<'EOF'
import json, os, sys
open(os.environ["CALLS"], "a").write(" ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
tl = json.loads(os.environ.get("FAKE_TL", "null"))
if a[0] == "list" and "--awaiting" in a and os.environ.get("FAKE_PATH") == "awaiting":
    print(json.dumps({"jobs": [{"id": 91, "column": "in_review", "claimed": True, "awaiting": True,
                                "targets": ["o/r"], "time_limit_s": tl, "title": "reply"}]}))
elif a[0] == "list" and "--column" in a and os.environ.get("FAKE_PATH") == "backlog":
    print(json.dumps({"jobs": [{"id": 90, "column": "backlog", "targets": ["o/r"], "claimed": False,
                                "time_limit_s": tl, "title": "limited"}]}))
elif a[0] == "list":
    print(json.dumps({"jobs": []}))
elif a[0] == "get":
    print(json.dumps({"data": {"id": int(a[1]), "column": "in_review", "ack_comment_id": 1,
                               "comments": [{"id": 5, "author": "you", "kind": "message"}]}}))
elif a[0] == "repos":
    print(json.dumps({"repos": [{"target": "o/r", "display": "r", "path": os.environ["FAKE_REPO"]}]}))
EOF
for case in 'null 2700' '10 600' '99999 14400' '99999999999999999999 14400' '1800 1800'; do
  read -r tl want <<<"$case"
  : >"$HOME/.config/jobs/poller-tried"; : >"$tmp/log"
  FAKE_PATH=backlog FAKE_TL=$tl FAKE_RUN_SECS=0 tick
  cat "$tmp/log" | grep -q "JOB-90 limit ${want}s" || fail "time_limit_s $tl did not give a ${want}s limit"
done
echo 91 >>"$HOME/.config/jobs/poller-owned"
: >"$HOME/.config/jobs/poller-tried"; : >"$tmp/log"
FAKE_PATH=awaiting FAKE_TL=10 FAKE_RUN_SECS=0 tick
cat "$tmp/log" | grep -q 'JOB-91 limit 600s' || fail "reply run did not carry the job time limit"
: >"$HOME/.config/jobs/poller-tried"; : >"$tmp/log"; : >"$tmp/calls"
t0=$(date +%s)
FAKE_PATH=backlog FAKE_TL=3 JOBS_POLLER_LIMIT_MIN=1 FAKE_RUN_SECS=60 tick
took=$(( $(date +%s) - t0 ))
cat "$tmp/log" | grep -q 'JOB-90 limit 3s' || fail "short limit not applied"
cat "$tmp/log" | grep -q 'JOB-90 stopped after 0 minutes' || fail "run past its time_limit_s not stopped"
[ "$took" -lt 30 ] || fail "run with a 3 s limit lived ${took}s"

# xv) A scheduled job (source "schedule") has its own lane, "schedule:<template_id>": no other
# job holds it and it holds no other job's lane. Job 95 sits on the board (FAKE_COL, FAKE_SRC,
# FAKE_TPL, FAKE_T targets); job 96 is in Backlog (FAKE_NEXT_SRC, FAKE_NEXT_TPL, FAKE_NEXT_T).
# A scheduled job In review holds nothing: the weekly card waits there until it is archived.
# A scheduled job held by a run of its own template says why on its card, once.
# JOBS_POLLER_SOURCES (schedule, !schedule) picks which sources this poller takes.
cat >"$tmp/skill/assets/jobs.py" <<'EOF'
import json, os, sys
open(os.environ["CALLS"], "a").write(" ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
e = os.environ.get
jobs = [{"id": 95, "source": e("FAKE_SRC", "board"), "template_id": e("FAKE_TPL") or None,
         "column": e("FAKE_COL", "in_review"), "targets": json.loads(e("FAKE_T", "[]")), "claimed": True, "title": "held",
         "active_at": e("FAKE_ACTIVE") or None, "awaiting": bool(e("FAKE_AWAIT"))},
        {"id": 96, "source": e("FAKE_NEXT_SRC", "schedule"), "template_id": e("FAKE_NEXT_TPL") or None,
         "column": "backlog", "targets": json.loads(e("FAKE_NEXT_T", "[]")), "claimed": False, "title": "weekly"}]
if a[0] == "list" and "--awaiting" in a and e("FAKE_AWAIT"):
    print(json.dumps({"jobs": [jobs[0]]}))
elif a[0] == "list" and ("--awaiting" in a or "--ship-approved" in a):
    print(json.dumps({"jobs": []}))
elif a[0] == "list" and "--column" in a:
    c = a[a.index("--column") + 1]
    print(json.dumps({"jobs": [j for j in jobs if j["column"] == c]}))
elif a[0] == "list":
    print(json.dumps({"jobs": jobs}))
elif a[0] == "get":
    cs = [{"id": 5, "author": "you", "kind": "message"}] if e("FAKE_AWAIT") else []
    print(json.dumps({"data": {"id": int(a[1]), "column": "in_review", "prompt": "/echo-test", "comments": cs}}))
elif a[0] == "repos":
    print(json.dumps({"repos": [{"target": "o/r", "display": "r", "path": os.environ["FAKE_REPO"]}]}))
EOF
sched() {
  : >"$HOME/.config/jobs/poller-tried"; : >"$HOME/.config/jobs/poller-skipped"; : >"$tmp/calls"
  JOBS_DEFAULT_HOME="$tmp/xcoach" tick
}
side_effects() { cat "$tmp/calls" | grep -v '^list ' | grep -c . || true; }
# An untargeted board job In review (the 28 Oct case) does not hold an untargeted scheduled job.
FAKE_SRC=board sched
[ "$(started 96)" = 1 ] || fail "an untargeted board job In review held a scheduled job"
# Control: the same board job still holds an untargeted board job.
FAKE_SRC=board FAKE_NEXT_SRC=board sched
[ "$(started 96)" = 0 ] || fail "a board job In review no longer holds the shared lane"
# A targeted board job In progress does not hold a scheduled job on the same repo, and the
# scheduled job still runs from its target's checkout.
FAKE_SRC=board FAKE_COL=in_progress FAKE_T='["o/r"]' FAKE_NEXT_T='["o/r"]' FAKE_NEXT_TPL=7 sched
[ "$(started 96)" = 1 ] || fail "a board job on o/r held a scheduled job"
cat "$tmp/calls" | grep -q "JOB-96 --background .* @ $repo_real\$" || fail "targeted scheduled job not run from its checkout"
# A scheduled job of template 8 In progress does not hold template 7; template 7 holds template 7.
FAKE_SRC=schedule FAKE_TPL=8 FAKE_COL=in_progress FAKE_NEXT_TPL=7 sched
[ "$(started 96)" = 1 ] || fail "template 8 held template 7"
: >"$HOME/.config/jobs/poller-tried"; : >"$HOME/.config/jobs/poller-skipped"; : >"$tmp/calls"
for _ in 1 2; do
  JOBS_DEFAULT_HOME="$tmp/xcoach" FAKE_SRC=schedule FAKE_TPL=7 FAKE_COL=in_progress FAKE_NEXT_TPL=7 tick
done
[ "$(started 96)" = 0 ] || fail "two runs of template 7 at once"
[ "$(cat "$tmp/calls" | grep -c '^comment 96 --kind event --body Not started by the poller: another run of its job template holds its lane (schedule:7)' || true)" = 1 ] \
  || fail "scheduled job held by its own template not explained exactly once"
# The weekly card of template 7 left In review holds nothing.
FAKE_SRC=schedule FAKE_TPL=7 FAKE_COL=in_review FAKE_NEXT_TPL=7 sched
[ "$(started 96)" = 1 ] || fail "a scheduled job In review held its template"
# A live run of template 7 holds template 7; a live untemplated scheduled run ("schedule") does not.
: >"$HOME/.config/jobs/poller-tried"; : >"$tmp/calls"
echo "{\"pid\": $$, \"kind\": \"backlog\", \"lanes\": [\"schedule:7\"]}" >"$runs/99.json"
JOBS_DEFAULT_HOME="$tmp/xcoach" FAKE_SRC=board FAKE_COL=archived FAKE_NEXT_TPL=7 bash "$here/poll.sh"
[ "$(started 96)" = 0 ] || fail "a live run of template 7 did not hold template 7"
echo "{\"pid\": $$, \"kind\": \"backlog\", \"lanes\": [\"schedule\"]}" >"$runs/99.json"
JOBS_DEFAULT_HOME="$tmp/xcoach" FAKE_SRC=board FAKE_COL=archived FAKE_NEXT_TPL=7 bash "$here/poll.sh"
rm -f "$runs/99.json"
settle
[ "$(started 96)" = 1 ] || fail "a live untemplated scheduled run held template 7"
# A scheduled job In review whose reply run is live (a fresh active_at heartbeat, on any
# machine) holds its template lane.
FAKE_SRC=schedule FAKE_TPL=7 FAKE_COL=in_review FAKE_NEXT_TPL=7 \
  FAKE_ACTIVE="$("$py" -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')" sched
[ "$(started 96)" = 0 ] || fail "a scheduled job In review with a live run did not hold its template"
# An untargeted scheduled run has no worktree: it also holds the folder it runs in, the shared
# untargeted lane "-" and the repo whose checkout that folder is, against live runs only.
: >"$HOME/.config/jobs/poller-tried"; : >"$tmp/calls"
for l in '"-"' '"o/r"'; do
  echo "{\"pid\": $$, \"kind\": \"ship\", \"lanes\": [$l]}" >"$runs/99.json"
  FAKE_REPO="$tmp/xcoach" FAKE_SRC=board FAKE_COL=archived FAKE_NEXT_TPL=7 bash "$here/poll.sh"
  [ "$(started 96)" = 0 ] || fail "a live run holding lane $l shared its checkout with a scheduled run"
done
rm -f "$runs/99.json"
: >"$tmp/log"
FAKE_REPO="$tmp/xcoach" FAKE_SRC=board FAKE_COL=archived FAKE_NEXT_TPL=7 tick
cat "$tmp/log" | grep -q 'JOB-96 start in .* (backlog, lanes schedule:7,-,o/r)' || fail "an untargeted scheduled run did not hold its folder"
# An untargeted board job In review (no live run) still does not hold it there.
FAKE_REPO="$tmp/xcoach" FAKE_SRC=board sched
[ "$(started 96)" = 1 ] || fail "an In review board job held a scheduled run's folder"
# JOBS_POLLER_SOURCES: "!schedule" leaves scheduled jobs alone before any side effect;
# "schedule" takes only them; unset takes all (every case above).
FAKE_SRC=board FAKE_COL=archived JOBS_POLLER_SOURCES='!schedule' sched
[ "$(side_effects)" = 0 ] || fail "!schedule: a scheduled job had a side effect"
FAKE_SRC=board FAKE_COL=archived JOBS_POLLER_SOURCES=schedule sched
[ "$(started 96)" = 1 ] || fail "JOBS_POLLER_SOURCES=schedule did not take a scheduled job"
FAKE_SRC=board FAKE_COL=archived FAKE_NEXT_SRC=board JOBS_POLLER_SOURCES=schedule sched
[ "$(side_effects)" = 0 ] || fail "JOBS_POLLER_SOURCES=schedule took a board job"
# The filter is for Backlog picks only: a reply on a scheduled job this machine already claimed
# still runs after a switch to "!schedule".
echo 95 >>"$HOME/.config/jobs/poller-owned"
FAKE_SRC=schedule FAKE_TPL=8 FAKE_AWAIT=1 FAKE_NEXT_SRC=board FAKE_NEXT_T='["o/r"]' JOBS_POLLER_SOURCES='!schedule' sched
[ "$(started 95)" = 1 ] || fail "!schedule stopped a reply run of a claimed scheduled job"
# Unknown sources, and a lone "!", stop the poller at start-up with exit 2.
for v in 'shedule' '!' 'board,!nope'; do
  : >"$tmp/log"; : >"$tmp/calls"; rc=0
  JOBS_POLLER_SOURCES=$v bash "$here/poll.sh" || rc=$?
  [ "$rc" = 2 ] || fail "JOBS_POLLER_SOURCES=$v: exit $rc, not 2"
  cat "$tmp/log" | grep -q "JOBS_POLLER_SOURCES" || fail "JOBS_POLLER_SOURCES=$v not logged"
  [ ! -s "$tmp/calls" ] || fail "JOBS_POLLER_SOURCES=$v still read the board"
done
# install-poller.sh --sources VAL sets the filter on a reinstall; an empty VAL clears it.
mkdir -p "$tmp/bin2"; cp "$tmp/claude" "$tmp/bin2/claude"
echo "JOBS_POLLER_SOURCES='!schedule'" >>"$HOME/.config/jobs/poller.env"
inst() { PATH="$tmp/bin2:$PATH" bash "$here/install-poller.sh" --dry-run --repos-root "$tmp" "$@" 2>/dev/null; }
# Capture first: grep -q exits on the first match and, under pipefail, the writer's SIGPIPE fails the check.
out=$(inst); grep -qx 'JOBS_POLLER_SOURCES=\\!schedule' <<<"$out" || fail "reinstall dropped the source filter"
out=$(inst --sources schedule); grep -qx 'JOBS_POLLER_SOURCES=schedule' <<<"$out" || fail "--sources did not set the filter"
out=$(inst --sources ''); grep -q JOBS_POLLER_SOURCES <<<"$out" && fail "--sources '' did not clear the filter"
"$py" -c 'import sys; p = sys.argv[1]; k = [l for l in open(p) if not l.startswith("JOBS_POLLER_SOURCES")]; open(p, "w").writelines(k)' \
  "$HOME/.config/jobs/poller.env"
# Set in poller.env, the filter still applies.
echo "JOBS_POLLER_SOURCES='!schedule'" >>"$HOME/.config/jobs/poller.env"
FAKE_SRC=board FAKE_COL=archived sched
[ "$(side_effects)" = 0 ] || fail "JOBS_POLLER_SOURCES in poller.env ignored"
"$py" -c 'import sys; p = sys.argv[1]; k = [l for l in open(p) if not l.startswith("JOBS_POLLER_SOURCES")]; open(p, "w").writelines(k)' \
  "$HOME/.config/jobs/poller.env"

# xii) Box mode: before a targeted run, mirror-sync through sudo, then clone the mirror into the
# manifest path when missing. A ship-approved job then goes to POLLER_SHIP_CMD through sudo,
# with the claim token on the first stdin line and a bundle of the job branch after it; no claude.
mkdir -p "$tmp/bin"
cat >"$tmp/bin/sudo" <<'EOF'
#!/usr/bin/env bash
echo "sudo $*" >>"$CALLS"
[ "$1 $2 $3" = "-n -u broker" ] || { echo "fake sudo: unexpected $*" >&2; exit 1; }
shift 3
exec "$@"
EOF
cat >"$tmp/mirror-sync" <<'EOF'
#!/usr/bin/env bash
echo "mirror-sync $*" >>"$CALLS"
echo "{\"mirror\": \"$FAKE_MIRROR\"}"
EOF
cat >"$tmp/ship-request" <<'EOF'
#!/usr/bin/env bash
echo "ship-request $*" >>"$CALLS"
[ -z "${FAKE_SHIP_FAIL:-}" ] || { cat >/dev/null; exit 1; }
cat >"$SHIPPED_STDIN"
EOF
chmod +x "$tmp/bin/sudo" "$tmp/mirror-sync" "$tmp/ship-request"
g() { git -c user.name=t -c user.email=t@example.invalid -c init.defaultBranch=main "$@"; }
g init -q "$tmp/seed"
g -C "$tmp/seed" commit -q --allow-empty -m base
g clone -q --bare "$tmp/seed" "$tmp/mirror.git"
cat >"$tmp/skill/assets/jobs.py" <<'EOF'
import json, os, sys
open(os.environ["CALLS"], "a").write(" ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
t = os.environ.get("FAKE_TARGET", "o/r")
run = {"state": "approved", "target": t, "approved_sha": "abc1234", "branch": os.environ.get("FAKE_BRANCH", "job-50")}
runs = [run, dict(run, target="o/s")][: int(os.environ.get("FAKE_RUNS", "1"))]
if a[0] == "list" and "--ship-approved" in a and os.environ.get("FAKE_PATH") == "ship":
    print(json.dumps({"jobs": [{"id": 50, "claimed": True, "title": "ship me", "ship_approved_at": "w", "runs": runs}]}))
elif a[0] == "list" and "--column" in a and os.environ.get("FAKE_PATH") == "backlog":
    print(json.dumps({"jobs": [{"id": 50, "column": "backlog", "targets": [t], "claimed": False, "title": "box job"}]}))
elif a[0] == "list":
    print(json.dumps({"jobs": []}))
elif a[0] == "get":
    print(json.dumps({"data": {"id": int(a[1]), "column": "in_review", "runs": [run]}}))
elif a[0] == "repos":
    print(json.dumps({"repos": [] if os.environ.get("FAKE_NODEST") else [{"target": "o/r", "display": "r", "path": os.environ["FAKE_CLONE"]}]}))
elif a[0] == "claim-token":
    print({"50": "tok-50"}[a[1]])
EOF
echo '{"50": "tok-50"}' >"$HOME/.config/jobs/claims.json"
printf 'POLLER_PATH=%q\nPOLLER_MIRROR_SYNC=%q\nPOLLER_SHIP_CMD=%q\n' \
  "$tmp/bin:$PATH" "$tmp/mirror-sync" "$tmp/ship-request" >>"$HOME/.config/jobs/poller.env"
export POLLER_MIRROR_ROOT="$tmp" FAKE_MIRROR="$tmp/mirror.git" FAKE_CLONE="$tmp/repos/o/r" SHIPPED_STDIN="$tmp/shipped"
: >"$HOME/.config/jobs/poller-tried"
: >"$tmp/calls"
# A target missing from the manifest is a logged skip, and nothing is cloned or run.
: >"$tmp/calls"; : >"$tmp/log"
FAKE_PATH=backlog FAKE_NODEST=1 tick
grep -q 'JOB-50 skipped: target o/r is not in the target manifest' "$tmp/log" || fail "empty dest not logged as a skip"
grep -q '^claude ' "$tmp/calls" && fail "claude ran for a target outside the manifest"
# A mirror path with shell metacharacters, or outside the mirror root, is refused before any clone.
for bad in "$tmp/m;touch $tmp/pwned.git" "$tmp/../x.git" "/elsewhere/m.git"; do
  : >"$tmp/calls"; : >"$tmp/log"; rm -f "$HOME/.config/jobs/poller-skipped"
  FAKE_MIRROR=$bad FAKE_PATH=backlog tick
  grep -q 'JOB-50 skipped: mirror path' "$tmp/log" || fail "bad mirror path not refused: $bad"
  if [ -e "$tmp/pwned.git" ] || [ -d "$tmp/repos/o/r" ]; then fail "bad mirror path was used: $bad"; fi
done
: >"$tmp/calls"; : >"$tmp/log"; rm -f "$HOME/.config/jobs/poller-skipped"
FAKE_PATH=backlog tick
grep -qx 'sudo -n -u broker .*/mirror-sync o/r' "$tmp/calls" || fail "mirror-sync not called through sudo for the target"
[ -d "$tmp/repos/o/r/.git" ] || fail "mirror not cloned into the manifest path"
clone_real=$(cd "$tmp/repos/o/r" && pwd -P)
grep -q "claude -p /jobs JOB-50 --background .* @ $clone_real\$" "$tmp/calls" || fail "box job not run from its fresh clone"
grep -q 'safe.directory' "$tmp/repos/o/r/.git/config" || fail "clone fetches would refuse the mirror"
# The run committed on its job branch; now the job is approved to ship.
g -C "$tmp/repos/o/r" checkout -q -b job-50
g -C "$tmp/repos/o/r" commit -q --allow-empty -m "job work"
# A branch that is a ref expression is refused before any bundle is made.
for bad in 'job-50~1' 'job-50^' 'a..b' 'x@{1}' 'a:b'; do
  : >"$tmp/calls"; : >"$tmp/log"; rm -f "$tmp/shipped" "$HOME/.config/jobs/poller-tried"
  FAKE_BRANCH=$bad FAKE_PATH=ship tick
  grep -q 'ship refused' "$tmp/log" || fail "branch $bad not refused"
  [ -e "$tmp/shipped" ] && fail "branch $bad was bundled and shipped"
done
tried="$HOME/.config/jobs/poller-tried"
# A broker that does not accept the hand-off leaves the approval untried, so the next tick retries.
: >"$tried"; : >"$tmp/calls"; : >"$tmp/log"
FAKE_SHIP_FAIL=1 FAKE_PATH=ship tick
grep -q 'ship-request' "$tmp/calls" || fail "broker not called"
grep -qx '50#ship@w' "$tried" && fail "failed hand-off recorded as tried, so it never retries"
grep -q 'JOB-50 ship request failed: the broker did not accept it' "$tmp/log" || fail "failed hand-off not logged"
# A branch missing from the clone fails the hand-off; the token is never sent without the bundle.
: >"$tmp/calls"; : >"$tmp/log"
FAKE_BRANCH=no-such-branch FAKE_PATH=ship tick
grep -q 'ship-request' "$tmp/calls" && fail "token sent alone for a branch that is not in the clone"
grep -qx '50#ship@w' "$tried" && fail "git error recorded as tried"
grep -q 'JOB-50 ship request failed: branch no-such-branch' "$tmp/log" || fail "missing branch not logged"
# A job with two approved runs is refused, not shipped in part, and is not retried.
: >"$tmp/calls"; : >"$tmp/log"
FAKE_RUNS=2 FAKE_PATH=ship tick
grep -q 'ship-request' "$tmp/calls" && fail "a two-run job was handed to the broker"
grep -q 'JOB-50 ship refused: 2 approved runs' "$tmp/log" || fail "two-run job not refused"
grep -qx '50#ship@w' "$tried" || fail "refusal not recorded"
: >"$tried"
: >"$tmp/calls"
FAKE_PATH=ship tick
grep -qx 'sudo -n -u broker .*/ship-request --job 50' "$tmp/calls" || fail "ship not handed to POLLER_SHIP_CMD through sudo"
grep -q '^claude ' "$tmp/calls" && fail "claude ran for a broker ship"
[ "$(head -1 "$tmp/shipped")" = tok-50 ] || fail "claim token is not the first stdin line"
tail -n +2 "$tmp/shipped" >"$tmp/shipped.bundle"
head -1 "$tmp/shipped.bundle" | grep -Eq '^# v[23] git bundle$' || fail "no git bundle after the token"
git -C "$tmp/repos/o/r" bundle list-heads "$tmp/shipped.bundle" | grep -q ' refs/heads/job-50$' \
  || fail "bundle lacks the job branch"
grep -qx '50#ship@w' "$HOME/.config/jobs/poller-tried" || fail "broker ship key not recorded"
grep -q 'JOB-50 ship request sent to the broker' "$tmp/sent" || fail "no broker hand-off message"
: >"$tmp/calls"
FAKE_PATH=ship tick
grep -q 'ship-request' "$tmp/calls" && fail "same approval sent to the broker twice"
# Mirror mode takes every target jobs.py takes ("." and "_" in the owner too), and no "." or ".." part.
for t in 'o.x/r_y' 'O_x/r.y'; do
  : >"$tmp/calls"; : >"$tmp/log"; rm -f "$HOME/.config/jobs/poller-skipped"
  FAKE_TARGET=$t FAKE_PATH=backlog tick
  grep -qx "sudo -n -u broker .*/mirror-sync $t" "$tmp/calls" || fail "valid target $t refused"
done
for t in '../r' 'o/..' './r'; do
  : >"$tmp/calls"; : >"$tmp/log"; rm -f "$HOME/.config/jobs/poller-skipped"
  FAKE_TARGET=$t FAKE_PATH=backlog tick
  grep -q 'mirror-sync' "$tmp/calls" && fail "target $t reached mirror-sync"
  grep -q "target $t is not owner/repo" "$tmp/log" || fail "target $t not refused"
done
# xvi) Targeted slash job: one tagged target and a slash prompt. Before claude starts, the poller
# fetches the target's checkout, refuses a dirty main checkout with a card comment, and adds a
# worktree on job/<id>-<slug> from the fetched origin/<default>; the run starts in that worktree. A
# reply run reuses it. A targeted job whose prompt is not a slash command still starts in the main
# checkout. First on a Mac (no mirror), then in box mode, where mirror-sync runs first.
printf 'CLAUDE_BIN=%q\nPYTHON3_BIN=%q\nSKILL_DIR=%q\nTELEGRAM_SEND=%q\nPOLLER_PATH=%q\n' \
  "$tmp/claude" "$py" "$tmp/skill" "$tmp/send.sh" "$PATH" >"$HOME/.config/jobs/poller.env"
cat >"$tmp/skill/assets/jobs.py" <<'EOF'
import json, os, sys
open(os.environ["CALLS"], "a").write(" ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
jid = int(os.environ.get("FAKE_ID", "70"))
prompt = os.environ.get("FAKE_PROMPT", "/exec-news-brief weekly")
t = os.environ.get("FAKE_T", "o/sl")
job = {"id": jid, "source": "schedule", "template_id": "w", "targets": [t], "title": "Weekly exec news!"}
if a[0] == "list" and "--column" in a and os.environ.get("FAKE_PATH") == "backlog":
    print(json.dumps({"jobs": [dict(job, column="backlog", claimed=False)]}))
elif a[0] == "list" and "--awaiting" in a and os.environ.get("FAKE_PATH") == "reply":
    print(json.dumps({"jobs": [dict(job, column="in_review", claimed=True, awaiting=True)]}))
elif a[0] == "list":
    print(json.dumps({"jobs": []}))
elif a[0] == "get":
    # FAKE_GET_T: the job was retagged between the list call and this get.
    print(json.dumps({"data": dict(job, targets=[os.environ.get("FAKE_GET_T", t)], column="in_review", prompt=prompt, ack_comment_id=0,
                                   comments=[{"id": 9, "author": "you", "kind": "message"}])}))
elif a[0] == "repos":
    print(json.dumps({"repos": [{"target": "o/sl", "display": "sl", "path": os.environ["FAKE_SL"]},
                                {"target": "o/ms", "display": "ms", "path": os.environ.get("FAKE_MS", "/nonexistent")}]}))
EOF
g init -q "$tmp/sl-seed"
echo one >"$tmp/sl-seed/f"
g -C "$tmp/sl-seed" add f
g -C "$tmp/sl-seed" commit -q -m A
g clone -q --bare "$tmp/sl-seed" "$tmp/sl-origin.git"
mkdir -p "$tmp/sl"
g clone -q "$tmp/sl-origin.git" "$tmp/sl/r"
# The origin moves on after the clone: only a fetch sees B, and local main stays at A.
g -C "$tmp/sl-seed" commit -q --allow-empty -m B
g -C "$tmp/sl-seed" push -q "$tmp/sl-origin.git" main
head_b=$(git -C "$tmp/sl-seed" rev-parse HEAD)
export FAKE_SL="$tmp/sl/r"
sl_real=$(cd "$tmp/sl/r" && pwd -P)
wt="$sl_real-wt/job-70-weekly-exec-news"
: >"$tried"; : >"$tmp/calls"; : >"$tmp/log"
FAKE_PATH=backlog tick
[ -d "$wt" ] || fail "no worktree at $wt"
[ "$(git -C "$wt" rev-parse HEAD)" = "$head_b" ] || fail "worktree not based on the fetched origin/main"
[ "$(git -C "$wt" rev-parse --abbrev-ref HEAD)" = job/70-weekly-exec-news ] || fail "worktree not on job/70-weekly-exec-news"
[ "$(git -C "$sl_real" rev-parse main)" = "$head_b" ] && fail "the test origin did not move past local main"
git -C "$wt" rev-parse -q --verify '@{upstream}' >/dev/null 2>&1 && fail "job branch tracks the default branch"
grep -q "claude -p /jobs JOB-70 --background .* @ $wt\$" "$tmp/calls" || fail "slash job did not start in its worktree"
grep -q "trust $wt\$" "$tmp/calls" || fail "worktree not trusted before the run"
# A reply run reuses the same worktree, and adds none.
echo 70 >>"$HOME/.config/jobs/poller-owned"
n_wt=$(git -C "$sl_real" worktree list | wc -l)
: >"$tmp/calls"; : >"$tmp/log"
FAKE_PATH=reply tick
grep -q "claude -p /jobs JOB-70 --background .* @ $wt\$" "$tmp/calls" || fail "reply run did not reuse the worktree"
[ "$(git -C "$sl_real" worktree list | wc -l)" = "$n_wt" ] || fail "reply run added a second worktree"
# A dirty main checkout is refused with one card comment, and claude never starts.
echo two >"$sl_real/f"
: >"$tmp/calls"; : >"$tmp/log"
FAKE_ID=71 FAKE_PATH=backlog tick
grep -q '^claude ' "$tmp/calls" && fail "claude ran with a dirty main checkout"
grep -q 'JOB-71 skipped: the main checkout .* has uncommitted changes' "$tmp/log" || fail "dirty main not logged"
grep -q '^comment 71 --kind event --body Not started by the poller: the main checkout' "$tmp/calls" \
  || fail "dirty main not commented on the card"
[ -d "$sl_real-wt/job-71-weekly-exec-news" ] && fail "worktree added for a dirty main checkout"
# A reply run finds the job's worktree first, so a dirty main checkout does not block it.
: >"$tried"; : >"$tmp/calls"
FAKE_PATH=reply tick
cat "$tmp/calls" | grep -q "claude -p /jobs JOB-70 --background .* @ $wt\$" || fail "dirty main checkout blocked a reply run"
git -C "$sl_real" checkout -q -- f
# A targeted job whose prompt is not a slash command keeps today's run folder: the main checkout.
: >"$tmp/calls"
FAKE_ID=72 FAKE_PROMPT="fix the footer" FAKE_PATH=backlog tick
grep -q "claude -p /jobs JOB-72 --background .* @ $sl_real\$" "$tmp/calls" || fail "non-slash targeted job left the main checkout"
[ -d "$sl_real-wt/job-72-weekly-exec-news" ] && fail "worktree added for a non-slash job"
# An origin with only master and no origin/HEAD: the worktree comes from origin/master.
g init -q -b master "$tmp/ms-seed"
g -C "$tmp/ms-seed" commit -q --allow-empty -m M
g clone -q --bare "$tmp/ms-seed" "$tmp/ms-origin.git"
g clone -q "$tmp/ms-origin.git" "$tmp/ms"
g -C "$tmp/ms" remote set-head origin -d
# git 2.48+ recreates origin/HEAD on fetch unless told not to; older git ignores this.
g -C "$tmp/ms" config remote.origin.followRemoteHEAD never
ms_real=$(cd "$tmp/ms" && pwd -P)
: >"$tmp/calls"; : >"$tmp/log"
FAKE_MS="$tmp/ms" FAKE_T=o/ms FAKE_ID=73 FAKE_PATH=backlog tick
[ "$(git -C "$ms_real-wt/job-73-weekly-exec-news" rev-parse HEAD 2>/dev/null)" = "$(git -C "$tmp/ms-seed" rev-parse HEAD)" ] \
  || fail "master-only origin: no worktree from origin/master"
# Retagged from o/sl to o/ms between the list and the get: the run folder is o/sl's checkout, which
# is not the fresh target's, so the job is refused on the card and claude never starts.
: >"$tmp/calls"; : >"$tmp/log"
FAKE_MS="$tmp/ms" FAKE_GET_T=o/ms FAKE_ID=74 FAKE_PATH=backlog tick
grep -q '^claude ' "$tmp/calls" && fail "claude ran for a job retagged between list and get"
grep -q '^comment 74 --kind event --body Not started by the poller' "$tmp/calls" || fail "retag not commented on the card"
ls -d "$sl_real-wt/job-74-"* "$ms_real-wt/job-74-"* >/dev/null 2>&1 && fail "worktree added for a retagged job"
# A missing checkout falls back to $HOME, here a dotfiles repo with an origin: refused, no worktree.
g init -q "$HOME"
g -C "$HOME" remote add origin "$tmp/sl-origin.git"
: >"$tmp/calls"; : >"$tmp/log"
FAKE_SL="$tmp/no-such-checkout" FAKE_ID=75 FAKE_PATH=backlog tick
grep -q '^claude ' "$tmp/calls" && fail "claude ran with a missing checkout"
grep -q '^comment 75 --kind event --body Not started by the poller' "$tmp/calls" || fail "missing checkout not commented on the card"
git -C "$HOME" worktree list | grep -q job/75 && fail "worktree added in \$HOME"
rm -rf "$HOME/.git"
# Box mode: mirror-sync, then the clone is fetched from the mirror, so a later mirror commit is the base.
printf 'POLLER_PATH=%q\nPOLLER_MIRROR_SYNC=%q\n' "$tmp/bin:$PATH" "$tmp/mirror-sync" >>"$HOME/.config/jobs/poller.env"
export FAKE_MIRROR="$tmp/mirror.git" FAKE_SL="$tmp/repos/o/sl"
: >"$tmp/calls"; : >"$tmp/log"
FAKE_ID=80 FAKE_PATH=backlog tick
box_real=$(cd "$tmp/repos/o/sl" && pwd -P)
[ -d "$box_real-wt/job-80-weekly-exec-news" ] || fail "box: no worktree for the fresh clone"
g -C "$tmp/seed" commit -q --allow-empty -m mirror-moves
g -C "$tmp/seed" push -q "$tmp/mirror.git" main
mirror_head=$(git -C "$tmp/seed" rev-parse HEAD)
: >"$tmp/calls"; : >"$tmp/log"
FAKE_ID=81 FAKE_PATH=backlog tick
grep -qx 'sudo -n -u broker .*/mirror-sync o/sl' "$tmp/calls" || fail "box: mirror-sync not run first"
[ "$(git -C "$box_real-wt/job-81-weekly-exec-news" rev-parse HEAD)" = "$mirror_head" ] \
  || fail "box: worktree not based on the clone fetched from the mirror"
grep -q "claude -p /jobs JOB-81 --background .* @ $box_real-wt/job-81-weekly-exec-news\$" "$tmp/calls" \
  || fail "box: slash job did not start in its worktree"
echo "poll.sh selftest: ok"
