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

# Pass 1 (pre-emptive, GraphQL). Issues/PRs CREATED in the last 10 minutes are
# this run's tickets. GraphQL reaches them by node id, so they can be cleared
# before any notification exists -- which is the whole point: the REST pass below
# cannot see a thread until the first email has already been generated.
#
# Scoped to *created* rather than *updated* so a thread the user later pressed
# Subscribe on is never clobbered: by then it is older than the window.
unsub=0
for acct in $(gh auth status 2>/dev/null | grep -oE 'account [A-Za-z0-9_-]+' | awk '{print $2}' | sort -u); do
  tok=$(gh auth token --user "$acct" 2>/dev/null) || continue
  [ -n "$tok" ] || continue
  owner=${repo%%/*}; name=${repo#*/}

  nodes=$(GH_TOKEN="$tok" gh api graphql -f query="
    { repository(owner: \"$owner\", name: \"$name\") {
        issues(first: 25, orderBy: {field: CREATED_AT, direction: DESC}) {
          nodes { id createdAt viewerSubscription } }
        pullRequests(first: 10, orderBy: {field: CREATED_AT, direction: DESC}) {
          nodes { id createdAt viewerSubscription } } } }" \
    --jq ".data.repository | (.issues.nodes + .pullRequests.nodes)[]
          | select(.createdAt > \"$since\" and .viewerSubscription == \"SUBSCRIBED\") | .id" 2>/dev/null) || continue

  for nid in $nodes; do
    GH_TOKEN="$tok" gh api graphql -f query="
      mutation { updateSubscription(input: {subscribableId: \"$nid\", state: UNSUBSCRIBED}) {
        subscribable { viewerSubscription } } }" >/dev/null 2>&1 && unsub=$((unsub + 1))
  done
done

# Pass 2 (reactive, REST). Catches threads somebody else started, where the
# notification record is the only handle we have. Reasons `manual` and `mention`
# are the user's opt-in and are deliberately left alone.
muted=0
total=$((unsub + muted))
[ "$total" -gt 0 ] && echo "Unsubscribed $total GitHub thread(s) on $repo ($unsub pre-emptive, $muted swept)." >&2
exit 0
