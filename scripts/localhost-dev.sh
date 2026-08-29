#!/usr/bin/env bash
# localhost-dev.sh — manage local `npm run dev` servers on a rotating 3000-3002 port.
#
# Verbs:
#   start [REPO_DIR] [--clean]   (default) (re)launch dev for a repo/worktree, print URL
#   status                       list dev servers on ports 3000-3002 (port, PID, repo)
#   kill                         kill ALL dev servers on 3000-3002 and clear port state
#   kill-repo REPO_DIR           kill ONLY the server(s) whose cwd is REPO_DIR (or below it)
#
# start port rotation: stable port per repo path; different worktrees take 3000,
# then 3001, then 3002; a fourth reclaims 3000 (killing its server). Prints one
# line: http://localhost:<port>

set -uo pipefail

PORTDIR="/tmp/claude-localhost"; mkdir -p "$PORTDIR"
# 8-port pool: 3 ports thrashed once parallel worktrees exceeded 3 —
# reclaim wars killed each other's servers mid-session (2026-07-10).
PORTS="3000 3001 3002 3003 3004 3005 3006 3007"

listening() { lsof -ti tcp:"$1" 2>/dev/null; }

# Every DISTINCT cwd among the processes listening on a port. More than one is
# normal and is the thing that misled us (2026-08-05): a stale server and the
# live one both held 3000, and reading only the first pid reported the wrong
# repo — `status` blamed a repo that had long since moved on, and `choose_port`
# concluded the port was someone else's and moved to a fresh one, where Next 16
# then refused to start a second dev server for the same dist dir.
port_cwds() {
  local pid
  for pid in $(lsof -ti tcp:"$1" 2>/dev/null); do
    lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1
  done | sort -u
}

# Who actually owns a port, live. The saved `.port` files are a hint, not truth:
# they outlive the servers that wrote them, so they are only consulted when
# nothing is listening.
repo_for_port() {
  local want="$1" f p cwds
  cwds=$(port_cwds "$want")
  if [ -n "$cwds" ]; then printf '%s' "$cwds" | tr '\n' ',' | sed 's/,$//'; return; fi
  for f in "$PORTDIR"/*.port; do
    [ -e "$f" ] || continue
    p=$(cat "$f" 2>/dev/null)
    if [ "$p" = "$want" ]; then echo "$(basename "$f" .port) (stale pin, nothing listening)"; return; fi
  done
  echo "?"
}

cmd_status() {
  local any=0 p pids
  printf "%-6s %-8s %s\n" "PORT" "PID" "REPO (tracked)"
  for p in $PORTS; do
    pids=$(listening "$p")
    if [ -n "$pids" ]; then
      any=1
      printf "%-6s %-8s %s\n" "$p" "$(echo "$pids" | tr '\n' ',' | sed 's/,$//')" "$(repo_for_port "$p")"
    fi
  done
  [ "$any" = 0 ] && echo "(no dev servers running on $PORTS)"
  return 0
}

# Kill only the server(s) running INSIDE one repo/worktree, and drop its pin.
# `/prune` calls this before `git worktree remove`: a dev server left running in a
# worktree keeps writing `.next` into the directory being deleted, so the remove
# fails with "Directory not empty" and leaves an orphan behind. Sixteen of those
# had accumulated under one project's .claude/worktrees by 2026-08-10, 185 MB of
# pure build output. Never widen this to `kill` — other worktrees are mid-work.
cmd_kill_repo() {
  local target="${1:-}" killed=0 p pids cwd key
  [ -n "$target" ] || { echo "kill-repo needs a repo dir" >&2; return 1; }
  # Resolve to an absolute real path so the prefix match below is meaningful even
  # when called with a relative path or through a symlink.
  target=$(cd "$target" 2>/dev/null && pwd -P) || { echo "no such dir: $1" >&2; return 1; }
  for p in $PORTS; do
    pids=$(listening "$p")
    [ -n "$pids" ] || continue
    for pid in $pids; do
      cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)
      # Match the worktree itself or anything under it — a `next dev` child can
      # sit in a subdirectory.
      case "$cwd" in
        "$target"|"$target"/*)
          kill -9 "$pid" 2>/dev/null && killed=1
          echo "killed pid $pid on port $p (cwd $cwd)"
          ;;
      esac
    done
  done
  key=$(printf '%s' "$target" | sed 's#[/. ]#-#g')
  rm -f "$PORTDIR/$key.port" 2>/dev/null || true
  [ "$killed" = 0 ] && echo "(no dev server was running in $target)"
  return 0
}

cmd_kill() {
  local killed=0 p pids
  for p in $PORTS; do
    pids=$(listening "$p")
    if [ -n "$pids" ]; then kill -9 $pids 2>/dev/null && killed=1; echo "killed port $p (pids: $(echo "$pids" | tr '\n' ' '))"; fi
  done
  rm -f "$PORTDIR"/*.port 2>/dev/null || true
  [ "$killed" = 0 ] && echo "(nothing was running on $PORTS)"
  return 0
}

# Warn (never block) when this repo points at a LOCAL Supabase that is not
# answering. A dead local stack does not break the dev server — it breaks the
# LOGIN, three clicks later, as a bare ERR_CONNECTION_REFUSED on a 5434x port
# with nothing in any log. Diagnosed by hand once (2026-08-04); this is that
# diagnosis, automated.
#
# The failure worth naming: containers alive INSIDE the Colima VM while the
# host->VM port forwards are gone, so `docker ps` in the VM looks perfectly
# healthy and the browser still cannot connect. `colima restart` re-registers
# the forwards for every running container.
check_supabase() {
  local url host port
  # `.env.local` wins, as Next itself loads it last.
  url=$(cat .env.local .env 2>/dev/null \
    | sed -n 's/^[[:space:]]*NEXT_PUBLIC_SUPABASE_URL=//p' \
    | tr -d '\042\047[:space:]' | head -1)   # \042 " and \047 ' — quoted values
  [ -n "$url" ] || return 0
  case "$url" in
    *127.0.0.1*|*localhost*) ;;
    *) return 0 ;;  # a hosted project — not ours to check
  esac

  # 200 from GoTrue means the whole path (host -> forward -> kong -> auth) works.
  [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$url/auth/v1/health")" = "200" ] && return 0

  host=${url#*://}; port=${host##*:}
  echo "warn: local Supabase at $url is not answering — LOGIN WILL FAIL" >&2

  if [ -n "$(listening "$port")" ]; then
    echo "  port $port is listening but /auth/v1/health did not return 200 — the stack is still booting, or kong/auth is unhealthy." >&2
    echo "  wait a few seconds, then: docker ps | grep supabase_auth" >&2
  elif command -v colima >/dev/null 2>&1 && colima ssh -- sudo docker ps --format '{{.Ports}}' 2>/dev/null | grep -q ":$port->"; then
    echo "  the containers ARE running inside the Colima VM, but nothing is listening on $port here — the host port-forwards were lost." >&2
    echo "  fix: colima restart   (re-registers forwards for every running container; bounces other projects' stacks too)" >&2
  else
    echo "  nothing is listening on $port and no container publishes it — the stack is down." >&2
    echo "  fix: ./scripts/supa start   (or: supabase start)" >&2
  fi
  echo "  starting the dev server anyway." >&2
}

cmd_start() {
  local REPO="$PWD" CLEAN=0 a
  for a in "$@"; do
    case "$a" in
      --clean) CLEAN=1 ;;
      *) [ -d "$a" ] && REPO="$a" ;;
    esac
  done
  cd "$REPO" 2>/dev/null || { echo "no such dir: $REPO" >&2; exit 1; }

  local KEY PORTFILE PORT pids p
  KEY=$(printf '%s' "$REPO" | sed 's#[/. ]#-#g')
  PORTFILE="$PORTDIR/$KEY.port"

  # cwd of whatever process currently listens on a port ("" if free).
  # OURS WINS when several processes share it: one of them being ours means this
  # is our own server to restart, whoever else is squatting alongside.
  owner_cwd() {
    local cwds c
    cwds=$(port_cwds "$1")
    [ -n "$cwds" ] || return 0
    while IFS= read -r c; do
      [ "$c" = "$REPO" ] && { printf '%s' "$REPO"; return 0; }
    done <<EOF
$cwds
EOF
    printf '%s' "$cwds" | head -1
  }
  # is this port pinned by a DIFFERENT repo's portfile?
  claimed_by_other() {
    local want="$1" f
    for f in "$PORTDIR"/*.port; do
      [ -e "$f" ] || continue
      [ "$(basename "$f" .port)" = "$KEY" ] && continue
      [ "$(cat "$f" 2>/dev/null)" = "$want" ] && return 0
    done
    return 1
  }
  # Port wars (2026-07-17): two repos pinned to one port kept kill -9'ing each
  # other's servers. Rules now: keep the saved port only if it's free or WE
  # own the listener (restart); if another repo's server holds it, move to a
  # free unclaimed port and re-pin. Never kill a server whose cwd isn't ours.
  choose_port() {
    local pp p ocwd
    # ONE server per repo, and a LIVE server outranks any saved pin. Without
    # this, a pin left behind by a failed launch sends the restart to a fresh
    # port while our real server is still up on the old one — and Next 16 then
    # refuses ("Another next dev server is already running"), so the restart
    # silently does nothing. Reuse the port we actually hold and restart there.
    for p in $PORTS; do
      if [ "$(owner_cwd "$p")" = "$REPO" ]; then echo "$p"; return; fi
    done
    if [ -f "$PORTFILE" ]; then
      pp=$(cat "$PORTFILE" 2>/dev/null)
      if [ -n "$pp" ]; then
        ocwd=$(owner_cwd "$pp")
        if [ -z "$ocwd" ] || [ "$ocwd" = "$REPO" ]; then echo "$pp"; return; fi
      fi
    fi
    for p in $PORTS; do
      [ -z "$(listening "$p")" ] && ! claimed_by_other "$p" && { echo "$p"; return; }
    done
    for p in $PORTS; do [ -z "$(listening "$p")" ] && { echo "$p"; return; }; done
    echo 3000  # truly all busy — legacy last resort
  }
  PORT=$(choose_port)
  pids=$(listening "$PORT")
  if [ -n "$pids" ]; then
    ocwd=$(owner_cwd "$PORT")
    if [ -z "$ocwd" ] || [ "$ocwd" = "$REPO" ]; then
      kill -9 $pids 2>/dev/null || true
    else
      echo "warn: port $PORT held by $ocwd — not killing it" >&2
    fi
  fi
  printf '%s' "$PORT" > "$PORTFILE"

  check_supabase

  [ "$CLEAN" = 1 ] && rm -rf .next node_modules/.cache 2>/dev/null || true

  local LOG="$PORTDIR/$KEY.$PORT.log"
  # localhost is one shared origin and cookies IGNORE the port, so every app ever
  # run on ANY of 3000-3010 contributes to the same cookie jar. With several
  # Supabase apps up at once the Cookie header passed 64KB and Chrome showed
  # HTTP ERROR 431 (2026-08-24). Raise Node's request-header cap (default 16KB)
  # generously — a big cap costs nothing, a 431 costs a debugging session.
  # If 431 returns even at this cap, the jar is the problem, not the cap: clear
  # cookies for localhost in the browser.
  #
  # Detach into a NEW SESSION (setsid) — plain `nohup … &` leaves the server in
  # the launching shell's process group, and a Claude session's cleanup reaping
  # that group kills the server mid-testing (bit twice, 2026-07-16). macOS has
  # no setsid(1), so use python's start_new_session.
  PORT="$PORT" NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--max-http-header-size=262144" \
    python3 - "$LOG" <<'PYEOF'
import subprocess, sys
log = open(sys.argv[1], "ab")
subprocess.Popen(["npm", "run", "dev"], stdout=log, stderr=log, start_new_session=True)
PYEOF
  echo "http://localhost:$PORT"
}

case "${1:-start}" in
  status) cmd_status ;;
  kill)   cmd_kill ;;
  kill-repo) shift; cmd_kill_repo "$@" ;;
  start)  shift; cmd_start "$@" ;;
  *)      cmd_start "$@" ;;  # back-com_compat: first arg is a dir/flag, not a verb
esac
