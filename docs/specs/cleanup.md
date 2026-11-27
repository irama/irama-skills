# Spec: the `/cleanup` skill

Status: agreed 27 November 2026; revised the same day after the adversarial plan review (Opus `adversarial-reviewer`; Codex was out of quota). Decision record: [ADR 0001](../adr/0001-cleanup-acts-on-the-returned-brief.md).

## The problem

The owner runs several Claude Code threads per repo, each in its own git worktree, across many repos. Closing them out means running `/flush` or `/prune all` in thread after thread. Many worktrees are left behind: some finished, some still running, some abandoned part-way with nobody remembering why.

`/cleanup` replaces that with one run. It walks every repo on the machine, prunes what is safe to prune, and returns **one brief** with four groups. The owner ticks boxes and sends the brief back. The same thread then carries out exactly what the brief approved.

A prototype round on 27 November 2026 (46 worktrees across 15 repos) proved the brief's shape and produced the six rules in "Classification" below.

## Words used here

- **Worktree:** a git worktree, including a repo's main checkout. One thread uses one worktree.
- **Default branch:** `origin/HEAD`'s branch, else `main`, else `master`.
- **On the remote:** the worktree's tip is an ancestor of `origin/<default>` after a fetch.
- **Live session:** any one of these, for the worktree or any folder under it:
  - a conductor session record whose pid is alive (`register.alive`) and whose transcript's most recent `cwd` field is under the worktree (a session that started in the parent repo and entered the worktree counts);
  - any process whose working directory is under the worktree (`lsof`);
  - an Orca worktree row that is `isUnread`, `isPinned`, or has `lastActivityAt` in the last 30 minutes;
  - a conductor claim on the repo in an open or held status (read the status names from `register.py`; the takeable statuses `incomplete` and `abandoned`, which include claims auto-released from dead threads, do NOT count). A claim carries no path, so a claim makes only the worktree its session record points at live.

  A thread waiting on an ask or a brief writes nothing for hours, which is why a transcript's age alone never decides liveness.
- **Conductor:** the thread register, `skills/threads/assets/register.py` (`list`, `claim`, `sign-off`, `declines`).
- **Driver run:** a `/driver` run, recorded in `<repo>/.scratch/driver-runs/<run-id>/state.json` and `journal.ndjson`, owned by `skills/driver/driver_state.py`. Ticket statuses are exactly `pending`, `in-progress`, `merged`, `blocked`, `skipped` (`VALID_STATUSES`). `state.json` keeps no per-ticket worktree or branch; its `_run` object holds `base`, `default_ref`, `integration_branch`, `run_dir`, `run_id`, `work`.
- **Row:** one line of the brief that may carry a decision. A push row is per repo; every other row is per worktree.
- **Recommendation:** the option pre-ticked on a row.
- **Park:** a record that hides a row until a date; nothing on disk changes.

## The run, end to end

```
discover → classify → auto-prune → write rows → brief → wait for Save → apply → result round
```

A run takes the conductor claim `cleanup:run` first and checks that the output says `claimed` (`cmd_claim` exits 0 with "not claiming" when the session has no identity record). If the claim is not held, or another live session holds it, the run stops and says why. Only one run happens at a time on a machine.

Each run has its own id, `<YYYY-MM-DD-HHMM>`, used as the brief id and the run folder name, so last week's saved ticks never repaint this week's brief.

### 1. Discover (script, no model)

`skills/cleanup/discover.py` prints JSON. It is read-only except for one `git fetch origin <default>` per repo, run with `GIT_TERMINAL_PROMPT=0` through the repo's own credential helper (timeout 20 s). On failure the repo's rows carry `fetch_failed: true` and nothing in that repo is auto-pruned or pushed. A repo with no `origin` is never fetched and never gets a push row.

- **Roots:** the user's home folder. Skip: `~/Library` (this also keeps out the iCloud and Google Drive mounts), `~/.Trash`, `~/.claude/plugins` (plugin caches are git repos), any `node_modules`, `.next`, `.venv`, `venv`, `dist`, `build`, `.cache`, and every hidden folder except `~/.claude`. Depth cap 5 below the root. An optional private file `~/.claude/cleanup.json` (`{"exclude": [paths], "extra_roots": [paths]}`) adds excludes or roots. The skill ships no path of its own.
- **Repos:** a folder holding a `.git` directory. Its worktrees come from `git worktree list --porcelain`, so a worktree outside the roots (an Orca workspace, a `*-wt/` folder) is still found through its main repo.
- **Per worktree:** path, branch, tip, dirty files (count and names), untracked count, commits ahead of local `<default>` and of `origin/<default>`, whether the tip is on the remote, age of the last commit, creation time of the worktree folder (its `ctime`, used for age), creation point of the branch (first reflog entry, which may have expired after 90 days; then unknown), whether the branch's changes are already in `<default>` by patch (`git cherry`, so squash and rebase merges count as merged), detached or locked state, whether the path is nested inside another worktree or has worktrees nested inside it, whether Orca manages it (`orca worktree list --json`), and a `prunable` flag from git.
- **Per repo:** local `<default>` ahead of `origin/<default>`: the full commit list (sha, subject, author date), and the conductor claims that name the repo.
- Target: under 60 seconds on the owner's machine with about 50 worktrees.

### 2. Classify (script, no model)

`discover.py` also assigns each worktree one group, applying these rules **in this order**. Each rule came from a real case in the prototype round.

0. **Locked worktrees are skipped** (counted in one line). **Landing scratch is left alone:** a detached `driver-land-*` worktree under the temp folder (made by `driver_state.py land`, which `/merge` also uses) is only cleared with `git worktree prune` once its folder is gone, or removed when it is older than 24 hours and no process has its working directory inside it.
1. **Nesting works both ways.** A worktree inside another worktree is classified after its parent and inherits the parent's group if the parent is Running. A worktree that has any worktree nested inside it is never auto-pruned and never offered Delete, because removing it deletes the child's folder (a nested folder is often gitignored, so the parent still looks clean).
2. **Driver worktrees belong to their run.** For each driver run in the repo, read `state.json`. A worktree belongs to the run if its branch is the run's `integration_branch` or listed in `_run.work`, or its branch was cut from the integration branch (`git merge-base --is-ancestor <run base or integration tip> <branch>`; ticket worktrees come from `EnterWorktree` and are named `worktree-<name>`, never `driver-t*`). Folder names never decide ownership. A run is **active** when any ticket is `pending`, `in-progress` or `blocked` and its journal was written in the last 24 hours, or a live session holds its claim. `skipped` and `merged` are terminal. Worktrees of an active run are Running.
3. **A live session blocks every prune.** Any worktree with a live session is Running, whatever its git state. Find the session that **entered** the worktree, not only one that started there: a transcript's `cwd` field, or an `EnterWorktree` tool result naming the path, counts. Read transcripts by streaming lines, never into model context.
4. **Only a branch that moved and then merged is finished.** A worktree is an auto-prune candidate only if it is clean, not detached, its branch has at least one commit of its own after its creation point, and its changes are on the remote (tip is an ancestor of `origin/<default>`, or `git cherry origin/<default>` shows no unmerged patch). A branch whose tip still equals its creation point "never moved": it is a brand-new thread, never auto-pruned. If it also has no live session, is clean, its creation point is on `<default>`, and its folder is older than 3 days, it is Abandoned with the recommendation Delete (no commits are lost). A creation point that is unknown (reflog expired) never yields a Delete recommendation.
4a. **Detached worktrees** (not landing scratch) are Running when live, else Abandoned with no Delete option.
5. **Merged locally but not pushed** (clean, tip in local `<default>`, not on the remote) goes to Ready to push and prune, under its repo's push row.
6. **A push is decided per repo, never per worktree.** A repo whose local `<default>` is ahead of the remote gets one push row listing **every** commit the push would ship, with the threads each commit came from where the conductor or branch names say so.

Everything else is **Abandoned**: dirty, or holding commits that are on no default branch, with no live session. A worktree that would be Abandoned only because its squash-merged patch is not an ancestor goes to auto-prune instead (rule 4's `git cherry` check), so it does not come back every week.

A **parked** worktree (see Apply) whose park has not expired and whose tip has not changed is left out of every group and counted in one line.

The run's own worktree is always Running.

### 3. Auto-prune (script, no model)

Every auto-prune candidate goes through the same guards `/prune` uses (refuse dirty or unmerged work), plus a fresh liveness check taken just before removal, and is removed without asking:

- Stop its dev server first: `bash "$HOME/.claude/scripts/localhost-dev.sh" kill-repo <path>`.
- Orca-managed worktree: `orca worktree rm --worktree path:<path> --delete-branch --json`. This closes its Orca chat card; the transcript stays on disk. The Pruned group names every card closed.
- Other worktree: `git worktree remove <path>` then `git branch -d <branch>` (never `-D`).
- Delete the remote branch only if `origin/<branch>` itself is an ancestor of `origin/<default>` (checking the local tip would miss extra commits on the remote branch).
- Orca's removal result does not confirm branch deletion without branch evidence; read the evidence before reporting the branch as gone.

A failed prune moves the row to Abandoned with the error in its "Why it stopped" line. Nothing else is retried.

### 4. Write rows

- **Running** rows come from the conductor: the claim note, status and ETA. A template, no model.
- **Pruned** rows: folder, repo, why it was safe. A template.
- **Push rows:** what ships (every commit), what else is still running in that repo, and whether another thread already holds this push at `waiting-on-user`. A template plus the commit list.
- **Abandoned rows** are written by one Sonnet subagent per row, in parallel batches. The subagent gets the worktree's diff against its merge base (capped at 400 lines; a longer diff is summarised by file and marked truncated), its commit log, any handoff file in the worktree or repo that names its branch, any closing note in `~/.claude/closings/` that names it, and a streamed excerpt of the session that entered it (the first user message and the last assistant message, each capped at 2,000 characters). It returns at most 12 lines: **For you** (what the work was trying to achieve for the owner, in plain words), **What the change does** (readable cold, by someone with no memory of the work), **How far it got**, **Why it stopped** (waiting on the owner's decision, the thread died or closed, or other, with the evidence), and a recommended option chosen from the table below.

Transcript reads stay cheap: `~/.claude/projects` holds about 19 GB. Liveness reads only transcripts modified in the last 30 minutes, tail first. The Abandoned-row excerpt finds its session through the conductor's session `cwd` index first, then scans only transcripts modified after the worktree folder was created.

Every Abandoned row embeds its diff in a collapsed `details.example` block. There is no "Show me the diff" option, because the diff is always shown.

### 5. The brief

The brief is built with the peakstate-brief skill (`build-brief.mjs`) and lives in a private folder outside every repo: `~/.claude/cleanup/<run-id>/cleanup.md` and `.html`, with `brief-id: cleanup-<run-id>`. Each row's note key includes the tip SHA (`wt-<repo>-<name>-<sha7>`), so a row cannot pick up a tick saved against a different tip. It is delivered with `brief-deliver` and the run waits for Save.

Answers block, then four parts in this order: Running, Pruned, Ready to push and prune, Abandoned. Each decision row is a `fieldset[data-note-group]` of tick boxes, one box per row.

**Pre-ticking:** a hand-written `checked` attribute is ignored by the runtime. Pre-fill the group's hidden `textarea[data-note]` with the recommended value; that ticks the box. (The prototype's `choices()` function in `make_brief.py` does this.)

**Unticking must be distinguishable from leaving alone.** Today the runtime cannot tell them apart: when the reader unticks every box, the group's change handler writes an empty string (`brief.js`, tick-box groups), the note handler then deletes the key, and the export only carries keys that exist. So an unticked Delete comes back as an absent group and would be applied. Prerequisite change in the peakstate-brief runtime (peakstate-skills repo): a tick-box group the reader has emptied stores and exports the value `none`. `/cleanup` reads `none` as "do nothing this run; ask again next run".

**One box per row.** If the reader ticks two or more boxes in one group, the row does nothing and becomes an Agent X ask.

| Row | Options | Recommended when |
| --- | --- | --- |
| Push (per repo) | Push now · Push when the running work lands · Hold, ask me again next cleanup | **Hold** when any claim in the repo is `waiting-on-user` or `blocked` (a thread that held its push back may know `main` is not deployable). Otherwise **Push now** when nothing else runs in the repo, and **Push when the running work lands** when a Running worktree or driver run in that repo will merge to `<default>`. |
| Abandoned | Resume from its handoff · Merge and push · Park for 30 days · Delete | **Resume** when a handoff exists. **Merge and push** when the work is complete and its tests pass on the branch. **Park** otherwise. **Delete** only when no commit would be lost (never-moved branch, or every commit already on a default branch). |

**Delete is never the recommendation where it loses a commit nobody has read.**

### 6. Apply

The run reads the responses JSON. **A row whose group is absent from `notes` takes its recommendation**, because the runtime exports a tick-box group only when the reader changes it. A group whose note is `none` does nothing. The returned brief approves exactly the rows it covers. Approving one row never approves another.

**Re-check before acting.** The brief may have sat for days. Before every row that changes something, check again that the tip is the SHA the row showed, the worktree is as clean or dirty as the row showed, and it has no live session. On any mismatch, the row does nothing and becomes an Agent X ask.

Rows run in this order: parks, deletes, merges, resumes, pushes now, then deferred pushes. A deferred push waits in a `Monitor` and blocks nothing else: the result round is delivered as soon as the other rows finish, with the deferred push shown as waiting, and updated when it lands. A failure on one row is reported and the others continue.

Every push and merge runs with that repo's own folder as the working directory, so its `/push` or `/merge` claim is keyed to the right repo. A repo whose main checkout is not on `<default>` is skipped with a one-line reason.

- **Push now:** before pushing, compare local `<default>`'s range with the commit list the row showed. If it is identical, run the `/push` skill's steps in that repo (migrations, production build, push, deploy confirmed by SHA). The returned brief counts as the owner invoking `/push` for that repo. If the range has changed, push nothing and post an Agent X ask listing the new range.
- **Push when the running work lands:** start a `Monitor` that waits for the named running work (its conductor claims cleared, or its driver run's tickets all `merged`) with a 24-hour limit. When it lands, compare the new range with the approved one. If every extra commit is reachable from a branch or driver integration branch the row named as running work, push. Otherwise, or when the limit passes, post an Agent X ask listing the final range.
- **Hold:** nothing. The row appears again next run.
- **Merge and push:** run `/merge`'s steps for that branch from its worktree (its own squash, gates and code review). `/merge` squashes the branch into a new commit, so record `<default>`'s tip before and after: the approved push range for that repo becomes the range the push row showed plus exactly the commits this merge landed. Then push as above.
- **Park for 30 days:** write `{repo, path, branch, tip, until}` to `~/.claude/cleanup/parked.json`. Nothing on disk changes. A park ends early if the tip moves. When it expires, the row comes back in Abandoned marked "park expired".
- **Delete:** refused for a worktree with worktrees nested inside it. Otherwise: tag the tip `cleanup/deleted/<branch>-<YYYYMMDD>` in the repo (local tag, never pushed; if the tag already exists, stop and report). Move every ignored secret file (`.env*`, `*.pem`, `*.key`, `credentials*`, `.npmrc`) into `~/.claude/cleanup/<run-id>/kept/<repo>/<worktree>/` with mode 600, because git is not their backup. Then remove the worktree (`--force` only for this option) and `git branch -D` the branch. The result lists the tag and the kept-files folder, so a delete can be undone.
- **Resume from its handoff:** if the worktree's Orca card had activity in the last 24 hours, do not start a second session beside it; send a done bubble instead. Otherwise, for an Orca-managed worktree, `orca agent launch --agent claude --worktree id:<repoId>::<path> --prompt "<the handoff's verb and path>" --json`. Launch one at a time, at most 3 per run; any beyond 3, and any worktree Orca cannot target, get a done bubble with the same command instead. The result lists every thread started.
- After a push succeeds, prune that repo's Ready worktrees through the auto-prune path.

### 7. Result round

The same brief is rebuilt as round two (same `brief-id`, fresh `consumed:`): each row shows what ran, the outcome, and any tag, thread or ask it produced. It is delivered with `brief-deliver`. The run signs off `cleanup:run`.

## Schedule

`/cleanup` runs on demand, and weekly through an Orca automation.

- `/cleanup schedule` creates the automation with `orca automations create`: weekly, Monday 08:00, `--timezone Australia/Brisbane`, provider Claude, prompt `/cleanup --scheduled`, targeting a permanent Orca folder workspace with `--workspace` (create it first if it does not exist). It never uses `--repo`, which would create a fresh worktree on every run for cleanup to then classify. That folder workspace is never pruned. It reports the automation id. `/cleanup unschedule` removes it. Read `orca automations create --help` when building it; do not guess flags.
- A scheduled run is the same run. It discovers, auto-prunes, delivers the brief, and waits for Save like any thread. It pushes, merges, deletes and starts nothing until the brief comes back.
- If the claim `cleanup:run` is held by a live session, the scheduled run exits with one line.

## Files

```
skills/cleanup/
  SKILL.md            the run, the gates, the option table
  discover.py         discover + classify, JSON out
  prune_auto.py       auto-prune with the /prune guards
  make_brief.py       rows JSON -> brief markdown (pre-ticked groups, embedded diffs)
  apply.py            responses JSON + rows JSON -> ordered action plan, park/delete/tag helpers
  test_discover.py    fixture repos built in a temp folder
  test_apply.py
```

Tests follow the stdlib style of `scripts/test_heavy_job.py`: fixtures are real git repos made in a temporary folder.

## Public-repo constraints

The skill ships in irama-skills, which is public. No absolute `/Users/...` path, no personal name or email, no app domain, and none of the private literals in `.leakrc`. Every path is built from `$HOME` or `Path.home()` at run time. The prototype folder and its real snapshot stay private and are never copied into the repo.

## What this does NOT include

- No pushing, merging, deleting or thread-starting that the returned brief did not approve.
- No auto-prune of anything dirty, unmerged, never-moved, driver-owned while its run is active, nested inside a Running worktree, or with a live session.
- No editing of other threads' conductor claims, beyond reading them.
- No closing notes for pruned threads. A pruned thread's own closing note, if it wrote one, stays.
- No cross-machine discovery. One machine per run.
- No GUI beyond the brief. No dashboard.
- No change to `/prune`, `/merge`, `/push` or `/flush`. `/cleanup` calls their steps.
- No remote-branch cleanup beyond deleting the branch of a worktree it pruned.
- No change to the peakstate-brief runtime beyond the one `none` export for an emptied tick-box group.
