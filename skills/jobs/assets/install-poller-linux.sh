#!/usr/bin/env bash
# Install, or remove, the systemd user timer that runs poll.sh every 60 s (Linux).
#
#   install-poller-linux.sh [--env-file FILE] [--repos-root DIR] [--default-home DIR] [--dry-run]
#   install-poller-linux.sh --uninstall [--dry-run]
#
# Install resolves the absolute paths of claude, python3 and this skill from the current shell,
# because a systemd user unit gives poll.sh no login-shell PATH. It writes them to
# ~/.config/jobs/poller.env (mode 600), then appends FILE when given: that is where a machine's
# own settings go (POLLER_SKIP_*, JOBS_POLLER_SOURCES, POLLER_MIRROR_SYNC, POLLER_SHIP_CMD, JOBS_TARGET_MANIFEST,
# JOBS_REPOS_READONLY), so none of them lives in this repo. It writes jobs-poller.service and
# jobs-poller.timer under ~/.config/systemd/user and enables the timer. --dry-run prints the
# three files and writes nothing.
# The timer runs only while the user's systemd manager does: for a user who is never logged in,
# root must run `loginctl enable-linger <user>` once.
set -euo pipefail

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
CONF="$HOME/.config/jobs/poller.env"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd -P)"

# shellcheck disable=SC1090
prev_home=$( [ -f "$CONF" ] && . "$CONF" 2>/dev/null; printf '%s' "${JOBS_DEFAULT_HOME:-}")
mode=install dry=0 repos_root="" env_file="" default_home="${prev_home:-${JOBS_DEFAULT_HOME:-}}"
while [ $# -gt 0 ]; do
  case "$1" in
    --uninstall) mode=uninstall ;;
    --dry-run) dry=1 ;;
    --env-file) env_file="${2:?--env-file needs a file}"; shift ;;
    --repos-root) repos_root="${2:?--repos-root needs a folder}"; shift ;;
    --default-home) default_home="${2:?--default-home needs a folder}"; shift ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ "$mode" = uninstall ]; then
  if [ "$dry" = 1 ]; then
    echo "would stop jobs-poller.timer and jobs-poller.service, and delete its units and $CONF"
    exit 0
  fi
  systemctl --user disable --now jobs-poller.timer 2>/dev/null || true
  systemctl --user stop jobs-poller.service 2>/dev/null || true
  rm -f "$UNIT_DIR/jobs-poller.timer" "$UNIT_DIR/jobs-poller.service" "$CONF"
  systemctl --user daemon-reload
  echo "removed jobs-poller. The log and ~/.config/jobs/claims.json are kept."
  exit 0
fi

# Default repos root as install-poller.sh does: the folder holding the main checkouts.
if [ -z "$repos_root" ]; then
  top=$(git -C "$SKILL_DIR" rev-parse --show-toplevel 2>/dev/null) || {
    echo "skill is not in a git checkout; pass --repos-root DIR" >&2; exit 1; }
  common=$(cd "$top" && cd "$(git rev-parse --git-common-dir)" && pwd -P)
  repos_root=$(dirname "$(dirname "$common")")
fi
claude_bin=$(command -v claude) || { echo "claude is not on PATH" >&2; exit 1; }
python_bin=$(command -v python3) || { echo "python3 is not on PATH" >&2; exit 1; }
[ -z "$env_file" ] || [ -f "$env_file" ] || { echo "no such file: $env_file" >&2; exit 1; }
[ -z "$repos_root" ] || [ -d "$repos_root" ] || { echo "no such folder: $repos_root" >&2; exit 1; }
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
  [ -z "$env_file" ] || cat "$env_file"
)
# Type=oneshot: the tick picks, starts each run detached, and exits. KillMode=process keeps the
# detached runs alive when the tick ends (each run has its own 45 or 90 minute watchdog). The
# timer fires 10 s after it starts (boot or enable), then 60 s after each tick ends.
# Quote the path for systemd: double quotes, with \ " and % escaped (% is a specifier).
unit_path=$(printf '%s' "$SKILL_DIR/assets/poll.sh" | sed 's/[\\"]/\\&/g; s/%/%%/g')
service_body="[Unit]
Description=One tick of the /jobs board poller

[Service]
Type=oneshot
TimeoutStartSec=infinity
KillMode=process
ExecStart=/bin/bash \"$unit_path\""
timer_body="[Unit]
Description=Run the /jobs board poller every 60 s

[Timer]
OnActiveSec=10
OnUnitInactiveSec=60
AccuracySec=5

[Install]
WantedBy=timers.target"

if [ "$dry" = 1 ]; then
  printf '# %s\n%s\n\n# %s\n%s\n\n# %s\n%s\n' "$CONF" "$env_body" \
    "$UNIT_DIR/jobs-poller.service" "$service_body" "$UNIT_DIR/jobs-poller.timer" "$timer_body"
  exit 0
fi

mkdir -p "$(dirname "$CONF")" "$UNIT_DIR"
(umask 077; printf '%s\n' "$env_body" >"$CONF.tmp")
chmod 600 "$CONF.tmp"
mv "$CONF.tmp" "$CONF"
printf '%s\n' "$service_body" >"$UNIT_DIR/jobs-poller.service"
printf '%s\n' "$timer_body" >"$UNIT_DIR/jobs-poller.timer"
systemctl --user daemon-reload
systemctl --user enable --now jobs-poller.timer
echo "enabled jobs-poller.timer. Log: ${XDG_STATE_HOME:-$HOME/.local/state}/jobs-poller.log. Remove with: $0 --uninstall"
