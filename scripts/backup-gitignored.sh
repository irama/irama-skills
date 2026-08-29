#!/usr/bin/env bash
# Periodic backup of the VALUABLE gitignored files in tracked repos — the local
# work git does not protect (.env.local and other secrets, WIP-LOCAL and similar
# work-in-progress dirs, local config/seed data). Runs on session start and once
# a day. Pure local file copy — no network, no tokens, no model calls.
#
#   backup-gitignored.sh [repo_root ...]
#     no args → discover git repos under DISCOVER_ROOTS
#
# NEVER backs up regenerable bulk: node_modules, .next* / build / dist / out,
# venvs, server & tool caches, coverage, worktrees, or large binaries. Three
# defences, in order of how much they actually catch: a per-file SIZE CAP
# (valuable gitignored work is text), a pruned-directory name list, and git's
# --directory flag, which lists a wholly-ignored dir as ONE entry so node_modules
# is never walked.
#
# Snapshots are HARDLINK TREES, not tarballs:
#   ~/.claude/gitignored-backups/<repo-slug>/<ISO>/<the files>   (+ a `latest`
#   symlink), keeps $KEEP.
# rsync --link-dest points every unchanged file at the previous snapshot's inode,
# so N snapshots of a mostly-static tree cost about one. Restoring needs no tool:
#   cp ~/.claude/gitignored-backups/<slug>/latest/.env.local .
# ponytail: hardlinks over restic — the goal was dedup, and restic would add a
# brew dep plus an encryption key living on the same disk as the data it
# protects. Revisit if these ever need to leave this machine.
set -uo pipefail

DISCOVER_ROOTS=("$HOME/LOCAL-DEV")
# repos backed up by explicit path rather than discovery
EXTRA_REPOS=("$HOME/.claude")
BACKUP_ROOT="$HOME/.claude/gitignored-backups"
KEEP=14
MAX_FILE_KB=2048     # per-file size cap — valuable gitignored work is text
WARN_NEW_MB=20       # new (non-hardlinked) bytes per snapshot above this = a leak

# regenerable/bulk directory NAMES — pruned from the git stub list and from the
# find walk. ponytail: name-based, not path-based; a repo with a genuinely
# valuable dir called "temp" loses it — none do, revisit if one appears.
# Entries may use a trailing '*' glob (matched by find -name and, translated, by
# the regex) — .next-test etc. are why.
SKIP_NAMES=('node_modules' '.next*' '.turbo' 'dist' 'build' 'out' 'coverage' '.cache'
  '.parcel-cache' '.vercel' '.swc' '.eslintcache' '.venv' 'venv' 'env' '__pycache__'
  '.pytest_cache' '.mypy_cache' '.ruff_cache' 'venvs' 'worktrees' 'temp' 'tmp' '.git'
  '.terraform' 'vendor' 'Pods' 'DerivedData' 'playwright-report' 'test-results'
  'blob-report' '.nyc_output' 'storybook-static' '.gradle' 'target'
  # ~/.claude's own ephemera — session transcripts, tool-output spill files,
  # reinstallable plugins, and gitignored-backups itself (which would otherwise
  # recursively back up the backups)
  'gitignored-backups' 'file-history' 'plugins' 'shell-snapshots' 'tool-results'
  'statsig' 'ide' 'session-env' 'sessions' 'driver-runs*' 'cache')

SKIP_DIR_RE="$(printf '%s|' "${SKIP_NAMES[@]}" | sed 's/\./\\./g; s/\*/[^\/]*/g; s/|$//')"
SKIP_DIR_RE="(^|/)($SKIP_DIR_RE)(/|$)|\.DS_Store$"

# find -prune args for the same names
FIND_PRUNE=()
for n in "${SKIP_NAMES[@]}"; do FIND_PRUNE+=(-name "$n" -o); done
unset 'FIND_PRUNE[${#FIND_PRUNE[@]}-1]'   # drop trailing -o

# belt for binary/regenerable file types the size cap lets through
SKIP_FILE_RE='\.(bin|mp3|mp4|mov|wav|aiff|flac|m4a|zip|gz|tgz|dump|log|jsonl|tsbuildinfo|psd|sketch|pt|safetensors|ckpt|onnx)$|\.DS_Store$'

# real snapshot dirs (timestamps), oldest first — never the `latest` symlink
snapshots() {
  find "$1" -mindepth 1 -maxdepth 1 -type d -name '2*' 2>/dev/null | sort
}

backup_repo() {
  local REPO="$1"
  [[ -d "$REPO/.git" ]] || return 0
  command -v git >/dev/null || return 0
  local SLUG; SLUG="$(printf '%s' "$REPO" | sed 's#^'"$HOME"'/##; s/[^A-Za-z0-9]\{1,\}/-/g; s/^-//; s/-$//' | cut -c1-120)"
  local DIR="$BACKUP_ROOT/$SLUG"; mkdir -p "$DIR"

  # keep-list of ignored paths. Dir stubs are expanded by find so the per-file
  # size cap applies — that cap, not the exclude patterns, is what keeps venvs,
  # media and model weights out for good.
  local INCL; INCL="$(mktemp)"
  local entry
  while IFS= read -r -d '' entry; do
    entry="${entry%/}"
    printf '%s\n' "$entry" | grep -Eq "$SKIP_DIR_RE" && continue
    printf '%s\n' "$entry" | grep -Eq "$SKIP_FILE_RE" && continue
    if [[ -d "$REPO/$entry" ]]; then
      ( cd "$REPO" && find "$entry" \( \( "${FIND_PRUNE[@]}" \) -prune \) -o \
          -type f -size "-${MAX_FILE_KB}k" -print0 2>/dev/null ) \
        | grep -zEv "$SKIP_FILE_RE" >> "$INCL"
    elif [[ -f "$REPO/$entry" ]]; then
      find "$REPO/$entry" -maxdepth 0 -size "-${MAX_FILE_KB}k" >/dev/null 2>&1 \
        && printf '%s\0' "$entry" >> "$INCL"
    fi
  done < <(git -C "$REPO" ls-files --others --ignored --exclude-standard --directory -z 2>/dev/null)

  [[ -s "$INCL" ]] || { rm -f "$INCL"; return 0; }

  # hardlink snapshot: unchanged files point at the previous snapshot's inodes,
  # so a static tree costs disk once no matter how many snapshots reference it
  local TS; TS="$(date +%Y%m%dT%H%M%S)"
  local PREV; PREV="$(snapshots "$DIR" | tail -1)"
  local LINK=()
  [[ -n "$PREV" ]] && LINK=(--link-dest="../$(basename "$PREV")")
  # ${LINK[@]+…} guard: bash 3.2 + set -u treats an empty array as unbound
  rsync -a --from0 --files-from="$INCL" ${LINK[@]+"${LINK[@]}"} "$REPO/" "$DIR/$TS/" 2>/dev/null || true
  rm -f "$INCL"
  [[ -d "$DIR/$TS" ]] || return 0
  ln -sfn "$TS" "$DIR/latest"

  # leak guard — measures the bytes this snapshot ACTUALLY added, i.e. what did
  # not hardlink to the previous one. Apparent size is the wrong signal here: a
  # big static tree is free after its first snapshot.
  local NEW_KB
  if [[ -n "$PREV" ]]; then
    # du -c dedups hardlinks across both args in one invocation, so
    # total(prev+new) - total(prev) is exactly what this snapshot cost
    NEW_KB=$(du -skc "$PREV" "$DIR/$TS" 2>/dev/null | tail -1 | cut -f1)
    NEW_KB=$(( NEW_KB - $(du -sk "$PREV" 2>/dev/null | cut -f1) ))
  else
    NEW_KB=$(du -sk "$DIR/$TS" 2>/dev/null | cut -f1)
  fi
  if [[ -n "${NEW_KB:-}" && "$NEW_KB" -gt $((WARN_NEW_MB * 1024)) ]]; then
    printf '[backup-gitignored] WARN %s added %sMB of new data (>%sMB) — check for a new bulk dir: du -sh %s/*\n' \
      "$SLUG" "$((NEW_KB / 1024))" "$WARN_NEW_MB" "$DIR/$TS" >&2
  fi

  # prune to newest $KEEP snapshots
  local n; n=$(snapshots "$DIR" | wc -l | tr -d ' ')
  if [[ "$n" -gt "$KEEP" ]]; then
    snapshots "$DIR" | head -n $((n - KEEP)) | while IFS= read -r old; do rm -rf "$old"; done
  fi
  # legacy tarballs go only once the hardlink store has real history of its own
  [[ "$n" -ge 3 ]] && rm -f "$DIR"/*.tar.gz 2>/dev/null
  return 0
}

if [[ $# -gt 0 ]]; then
  for r in "$@"; do backup_repo "$r"; done
else
  for root in "${DISCOVER_ROOTS[@]}"; do
    [[ -d "$root" ]] || continue
    while IFS= read -r gitdir; do backup_repo "$(dirname "$gitdir")"; done \
      < <(find "$root" -maxdepth 3 -name .git -type d -prune 2>/dev/null)
  done
  for r in ${EXTRA_REPOS[@]+"${EXTRA_REPOS[@]}"}; do backup_repo "$r"; done
fi
