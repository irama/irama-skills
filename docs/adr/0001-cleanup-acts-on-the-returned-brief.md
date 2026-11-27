# ADR 0001: `/cleanup` acts only on the returned brief, and acts on all of it

Date: 27 November 2026. Status: accepted.

## Context

`/cleanup` touches every repo on the machine. Some of what it finds is safe to remove without asking (clean, merged, pushed, unused). Some of it ships to production (`/push` sends the whole of local `main`). Some of it is unread work that only the owner can judge.

## Decision

1. **Safe prunes need no approval.** A worktree that passes the `/prune` guards, moved and then merged, is on the remote and has no live session is pruned during discovery, including Orca-managed worktrees (whose chat cards close). The brief reports them.
2. **The returned brief is the approval, row by row.** An untouched row takes its recommendation, because the brief runtime exports a group only when the reader changes it. A row the reader emptied exports `none` (a one-line runtime change, made first) and does nothing. Two ticks in one row do nothing. Every row re-checks its tip, cleanliness and liveness before acting, because a brief can sit for days. Approving one row never approves another.
3. **A push approves a commit range, not a repo.** A push runs only when local `main` still matches the range the row listed. A deferred push ("when the running work lands") may ship extra commits only if every one is reachable from the running work the row named; any other change goes back to the owner as an Agent X ask.
4. **Approved resumes start themselves.** A ticked "Resume from its handoff" launches the thread in Orca, at most three per run, so the owner does not paste commands into new threads.
5. **Discovery walks the whole home folder**, so a repo the owner forgot about still appears.
6. **It runs on demand and weekly.** The weekly run is an Orca automation that starts an ordinary chat thread; it waits for Save like any other run.

## Rejected alternatives

- **A brief for everything, including safe prunes.** Rejected: 18 of 46 worktrees in the prototype were safe prunes, and asking about each one recreates the thread-by-thread chore.
- **Push approval per worktree.** Rejected: a push ships every commit on `main`, so the prototype found one thread holding four pushes because each range carried other threads' commits.
- **Push on landing, whatever arrives.** Rejected: prod would receive commits the owner never saw listed.
- **Hand back resume commands for the owner to paste.** Considered and recommended at first; rejected by the owner in favour of cleanup launching the threads. The cap of three bounds unattended spend.
- **A private list of roots.** Rejected by the owner in favour of the whole home folder, with a skip list and an optional private exclude file.
- **Never pre-tick a push or a delete** (the reviewer's simpler fix for the untick problem). Rejected: the owner accepted pre-ticked pushes in the prototype; making an emptied group export `none` fixes the cause, and Hold becomes the default wherever a thread held its push back.
- **Delete with no undo.** Rejected: a delete tags the tip first, so an unread commit is never lost for good.
- **Park as archive (remove the folder, keep a tag).** Rejected: a park is fully reversible only if nothing on disk changes.
