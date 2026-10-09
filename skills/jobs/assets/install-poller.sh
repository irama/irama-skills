#!/usr/bin/env bash
# Install, or remove, the launchd agent that runs poll.sh every 60 s.
#
#   install-poller.sh [--repos-root DIR] [--default-home DIR] [--dry-run]   install and load
#   install-poller.sh --uninstall [--dry-run]          unload and delete
#
# Install resolves the absolute paths of claude, python3 and this skill from the current
# shell, because launchd gives poll.sh no login-shell PATH. It writes them to
# ~/.config/jobs/poller.env (mode 600), writes ~/Library/LaunchAgents/org.<user>.jobs-poller.plist
# (StartInterval 60, RunAtLoad true) and loads it. --dry-run prints both files and writes nothing.
# --default-home DIR is where a ZERO job with no target runs (JOBS_DEFAULT_HOME). Without it,
# the value already in poller.env is kept, else $JOBS_DEFAULT_HOME from this shell.
# It never changes the Mac's sleep or Energy settings.
set -euo pipefail

LABEL="org.$(id -un).jobs-poller"   # resolved at run time: no user name in the repo
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
CONF="$HOME/.config/jobs/poller.env"
LOG="$HOME/Library/Logs/jobs-poller.log"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd -P)"

# shellcheck disable=SC1090
prev_home=$( [ -f "$CONF" ] && . "$CONF" 2>/dev/null; printf '%s' "${JOBS_DEFAULT_HOME:-}")
mode=install dry=0 repos_root="" default_home="${prev_home:-${JOBS_DEFAULT_HOME:-}}"
while [ $# -gt 0 ]; do
  case "$1" in
    --uninstall) mode=uninstall ;;
    --dry-run) dry=1 ;;
    --repos-root) repos_root="${2:?--repos-root needs a folder}"; shift ;;
    --default-home) default_home="${2:?--default-home needs a folder}"; shift ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ "$mode" = uninstall ]; then
  if [ "$dry" = 1 ]; then
    echo "would unload $LABEL and delete $PLIST and $CONF"
    exit 0
  fi
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST" "$CONF"
  echo "removed $LABEL. The log and ~/.config/jobs/claims.json are kept."
  exit 0
fi

claude_bin=$(command -v claude) || { echo "claude is not on PATH" >&2; exit 1; }
python_bin=$(command -v python3) || { echo "python3 is not on PATH" >&2; exit 1; }
# The run needs the user's tools (git, node, pnpm), so poll.sh gets this shell's PATH.
# Repos root: the folder holding the main checkouts, by default the one beside this skill's repo.
if [ -z "$repos_root" ]; then
  top=$(git -C "$SKILL_DIR" rev-parse --show-toplevel 2>/dev/null) || {
    echo "skill is not in a git checkout; pass --repos-root DIR" >&2; exit 1; }
  # A worktree's parent is not where the main checkouts live; use the main checkout's.
  common=$(cd "$top" && cd "$(git rev-parse --git-common-dir)" && pwd -P)
  repos_root=$(dirname "$(dirname "$common")")
fi
[ -d "$repos_root" ] || { echo "no such folder: $repos_root" >&2; exit 1; }
# poll.sh logs and skips an untargeted job while this is unset or missing, so only warn.
[ -n "$default_home" ] && [ -d "$default_home" ] \
  || echo "warning: no default home (${default_home:-unset}): untargeted jobs will be skipped; pass --default-home DIR" >&2
send="$SKILL_DIR/../telegram/send.sh"
if [ -x "$send" ]; then send=$(cd "$(dirname "$send")" && pwd -P)/send.sh; else send=""; fi

env_body=$(
  printf 'CLAUDE_BIN=%q\n' "$claude_bin"
  printf 'PYTHON3_BIN=%q\n' "$python_bin"
  printf 'SKILL_DIR=%q\n' "$SKILL_DIR"
  printf 'TELEGRAM_SEND=%q\n' "$send"
  printf 'JOBS_REPOS_ROOT=%q\n' "$repos_root"
  printf 'JOBS_DEFAULT_HOME=%q\n' "$default_home"
  printf 'POLLER_PATH=%q\n' "$PATH"
)
# ponytail: paths go into the plist unescaped; a path holding & or < breaks the XML.
plist_body=$(cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$SKILL_DIR/assets/poll.sh</string>
  </array>
  <key>StartInterval</key><integer>60</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
)

if [ "$dry" = 1 ]; then
  printf '# %s\n%s\n\n# %s\n%s\n' "$CONF" "$env_body" "$PLIST" "$plist_body"
  exit 0
fi

mkdir -p "$(dirname "$CONF")" "$(dirname "$PLIST")" "$(dirname "$LOG")"
(umask 077; printf '%s\n' "$env_body" >"$CONF.tmp")
chmod 600 "$CONF.tmp"
mv "$CONF.tmp" "$CONF"
printf '%s\n' "$plist_body" >"$PLIST"
plutil -lint "$PLIST" >/dev/null
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
# bootout returns before the service is actually gone; a bootstrap that races it can fail
# with "Bootstrap failed: 5: Input/output error". Poll (bounded) until it's really unloaded.
wait_tries=0
while [ "$wait_tries" -lt 10 ] && launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; do
  wait_tries=$((wait_tries + 1))
  sleep 0.5
done
boot_tries=0
until launchctl bootstrap "gui/$(id -u)" "$PLIST"; do
  boot_tries=$((boot_tries + 1))
  [ "$boot_tries" -lt 3 ] || {
    echo "launchctl bootstrap failed 3 times for $LABEL; check: launchctl print gui/$(id -u)/$LABEL" >&2
    exit 1
  }
  sleep 1
done
echo "loaded $LABEL. Log: $LOG. Remove with: $0 --uninstall"
