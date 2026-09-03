#!/usr/bin/env bash
# PostToolUse(Bash): mute GitHub notification threads this agent just created.
#
# When Claude runs `gh issue create/comment/close` under one of the user's own
# GitHub identities, GitHub auto-subscribes that identity and emails every later
# comment. The user wants those threads quiet by default and opt-in by hand.
#
# DELETE, not `PUT {"ignored":true}`: the API accepts the ignore flag and silently
# does not store it (verified with raw curl, so it is not a `gh` bug) -- it just
# drops the subscription. Deleting is therefore the only effect available, and it
# is weaker: participating again re-subscribes. This hook running after every
# write is what closes that gap.
#
# Reasons deliberately NOT muted: `manual` (they pressed Subscribe) and `mention`
# (somebody wanted their attention). Those are the opt-in signal.
#
# ponytail: sweeps recent threads on the repo rather than mapping command->thread,
# because the notification does not exist yet when the command returns. Narrow the
# window if a deliberate subscribe ever gets caught.

set -u
payload=$(cat)
cmd=$(printf '%s' "$payload" | jq -r '.tool_input.command // ""' 2>/dev/null) || exit 0

# Fast bail: only issue/PR writes can create a subscription.
printf '%s' "$cmd" | grep -Eq 'gh (issue|pr) +(create|comment|close|reopen|edit)' || exit 0

cwd=$(printf '%s' "$payload" | jq -r '.cwd // ""' 2>/dev/null)
[ -n "$cwd" ] && { cd "$cwd" 2>/dev/null || exit 0; }

command -v gh >/dev/null 2>&1 || exit 0
repo=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null) || exit 0
[ -n "$repo" ] || exit 0

# Threads created in the last 10 minutes are this session's work.
since=$(date -u -v-10M +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
     || date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null) || exit 0

muted=0
for acct in $(gh auth status 2>/dev/null | grep -oE 'account [A-Za-z0-9_-]+' | awk '{print $2}' | sort -u); do
  tok=$(gh auth token --user "$acct" 2>/dev/null) || continue
  [ -n "$tok" ] || continue

  ids=$(GH_TOKEN="$tok" gh api "/repos/$repo/notifications?all=true&since=$since&per_page=50" \
        --jq '.[] | select(.reason != "manual" and .reason != "mention") | .id' 2>/dev/null) || continue

  for id in $ids; do
    code=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE \
      -H "Authorization: token $tok" \
      "https://api.github.com/notifications/threads/$id/subscription" </dev/null)
    case "$code" in 204|404) muted=$((muted + 1)) ;; esac
  done
done

[ "$muted" -gt 0 ] && echo "Unsubscribed $muted GitHub notification thread(s) on $repo." >&2
exit 0
