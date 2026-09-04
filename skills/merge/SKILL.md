---
name: merge
description: Merge shipped feature branch(es) down onto the default branch locally — no migrations, no push. "/merge" merges the current branch; "/merge all" merges every feature branch oldest-first. Use when the user says "merge", "merge down", "merge to main", "merge all", or invokes /merge. (Formerly /flatten.)
---

Merge feature branch(es) onto the default branch **locally**. `/merge` does NOT apply migrations and does NOT push — those are `/push`. Merging locally first gives you a checkpoint: land the branches, inspect `main`, then `/push` to deploy when ready. See `~/.claude/docs/multithread-workflow.md`.

> Four-verb flow: `/commit` (each worktree) → **`/merge` / `/merge all`** (here) → `/push` (deploy) → `/prune` (clean up). `/merge` replaces the old `/flatten`.

## Scope

- **`/merge`** — merge **the current branch** (the branch of the cwd/worktree you invoked from) onto the default branch.
- **`/merge all`** — merge **every** feature branch, oldest-committed first. Run from one coordinator thread after the others have each run `/commit`.

## Preconditions

- Confirm repo + remote (`git rev-parse --show-toplevel`, `git remote get-url origin`).
- The coordinator may itself be in a worktree — merge operates on the shared repo's refs, not the cwd's tree.

## Claim the verb before the first gate, sign it off at the end

Other threads cannot see this run, and the merges are minutes long once the review gate runs. Claim it by name so
`/threads` shows what this thread is doing, and so another thread's shipping verb
is refused while it is in flight:

```bash
reg=<skill-dir>/../threads/assets/register.py
[ -f "$reg" ] && python3 "$reg" claim --verb merge --note "<what you are merging>"
```

Held → say who holds it and stop; do not work around it. The `threads` skill is a
sibling of this one in the same skills root; if it is not installed the guard makes
both lines a no-op and this skill behaves exactly as it did before.

The last thing this skill does, after the report, is release it:

```bash
[ -f "$reg" ] && python3 "$reg" sign-off --verb merge --status done
```

**Stopped part-way? Sign off anyway, with what actually happened** — `--status blocked` if something outside this thread stopped it, `--status incomplete` if it simply did not finish. Both are honest; a claim left open is not. `blocked` keeps the key held, so nobody else ships a half-merged repo.

The `PreToolUse` gate claims `<repo>:merge` on the bare git command too, but only
for the seconds that command runs. This claim covers the whole verb, which is the
window that matters.

## Steps

1. `git fetch --all --prune`. For `/merge all`, enumerate candidates: `git worktree list` and `git branch --list 'feature/*'` (plus any other non-default branches). For `/merge`, the single candidate is the current branch.
2. **Readiness check — do not stash anyone's work.** For each candidate worktree, `git -C <path> status --porcelain`. If any has **uncommitted** changes, report "thread at `<path>` (`<branch>`) has not shipped yet — run `/commit` there first" and **STOP**. Nothing merges until every contributing branch is clean. (Offer to list exactly which threads are outstanding.)
3. `git switch <default-branch>` (in the main checkout) and `git pull --ff-only`.
4. **Merge one branch at a time, oldest-committed first** (a single branch for `/merge`):
   a) **Squash the WIP auto-commits first.** The `Stop` hook peppers each branch with `chore: wip auto-commit (...)` commits — collapse them into one clean commit before merging so `main`'s history stays readable:
      - `base=$(git merge-base <branch> <default-branch>)`
      - Capture context for the message: `git log --oneline "$base..<branch>"` (note the non-wip subjects and the overall diff).
      - Only squash if the branch has >1 commit or any `wip auto-commit` commit. Then: `git switch <branch> && git reset --soft "$base" && git commit -m "<clean Conventional-Commits message>"` — author the message from the captured context + `git diff --stat "$base" HEAD` (describe the real change, drop the WIP noise). End it with the `Co-Authored-By` trailer.
      - This rewrites only the local feature branch (auto-commits are never pushed), so no force-push is needed. `git branch --merged` still works afterward → `/prune`'s guard stays valid (this is why we squash-on-branch, NOT `git merge --squash`).
   b) `git switch <default-branch>` then `git merge --no-ff <branch>`.
   c) On conflict, resolve per the playbook below; if unresolvable safely, **stop and surface it** — never force or discard.
   d) After each merge, run typecheck + tests (`npm run typecheck && npm test`, or repo equivalent). Red → the just-merged branch is the culprit; fix or `git merge --abort`/reset and report before touching the next. Testing after *each* merge (not once at the end) is what isolates the bad branch.

      **Skip this ONLY when both hold: (i) the merge was a true fast-forward** — `git merge-base --is-ancestor <default-branch> <branch>` was true before merging, so the merged tree is byte-identical to the branch tip — **and (ii) that tip was gated by a real `/commit` pass** (typecheck + tests + lint green on that exact tree). Then the re-run validates the same tree twice, and every gate command is a full-context API request (§ Session length is the cost driver).

      **Otherwise run it — and that includes the common case.** A `--no-ff` merge onto a `<default-branch>` that other branches have already landed on produces a **new tree that nothing has ever validated**: both sides can be independently green and still conflict semantically. Also always run it for `/merge all`, for any hand-resolved conflict, and whenever the tip's gate is unknown or was skipped. Note the `Stop` hook commits `--no-verify`, so a branch of pure WIP auto-commits is **ungated** — condition (ii) fails and the run is mandatory.
   e) **If the merged branch touched UI/render code and the repo has a browser/e2e tier** (Playwright, Cypress), run it too — a green unit suite will NOT catch a white-screen render crash (Rules-of-Hooks / React #310, bad context read, effect throw); only a real browser mount does. Red → fix or back the branch out before proceeding.
5. **Codex review gate (second-model axis — runs here, not at `/push`).** With the branch(es) merged onto local `<default-branch>` and green, review the merged diff with Codex. **Quota discipline first** (2026-07-18: a review loop burned ~5 full-diff passes in one merge):
   - **Skip if already reviewed.** If a full-diff Codex review of (essentially) this same diff already ran this session — e.g. a user-invoked `/codex-review --base <default-branch>` just before merging — do NOT re-review the whole diff; reuse those findings and only review what changed since (see re-run scoping below).
   - **Scope the first pass to THIS thread's work, not all unpushed main.** Capture `pre=$(git rev-parse <default-branch>)` BEFORE merging, then review with `--base "$pre"`. `--base origin/<default-branch>` re-reviews every other thread's already-merged (and possibly already-reviewed) work on each pass — that's how one merge burns multi-hundred-KB passes and surfaces out-of-thread findings. Use `origin/<default-branch>` only for `/merge all`, where the whole set is genuinely new.
   - **One lens by default.** Run a single default review: `codex-auto exec review --base "$pre"`. Add the second account as a **security lens** (`codex-as <other> exec review --base "$pre"`) ONLY when the diff touches auth, payments/money, data deletion, or externally-reachable input handling. (Note: `codex exec review` cannot combine a scope flag with prompt text — scope-only.) Trivial/docs-only diff → skip and say so.
   - Findings are advisory, not a hard block — but a real correctness/security/data-loss finding means **STOP and ask** before the change can be pushed.

   **Re-run after fixing findings — but only when severity warrants, and scope the re-run to the FIX, not the branch.**
   - **Severity gate:** re-run Codex only if the pass found a **P1 / security / data-loss** issue (the fix to a serious bug is new, unreviewed code, frequently wrong in a new way — 2026-07-17: five consecutive passes, five real defects, each in the previous fix). A pass whose findings are **all P2/minor** (focus handling, copy, layout nits): fix them, verify with the repo's own gates (typecheck/tests/lint), and stop — no Codex re-run. Codex reliably finds *something* every pass; without this gate the loop never converges (2026-07-18: rounds 3–4 of a 5-round loop surfaced only escalating focus-management nits).
   - **Scoping:** re-run as `codex exec review --commit <fix-sha>` (or `--base <sha-of-last-reviewed-state>`), so Codex reads only the delta.
   - **Cap the loop at two re-runs**; anything still open after that gets recorded as KNOWN ITEMS in the report (and on a money/security path, that's the signal to remove the half-built thing, not to guess again). Record the final reviewed `main` SHA in the report so `/push` can skip its own gate when the SHA is unchanged.
   - **Out-of-scope findings** (code another thread merged, outside this branch's diff): report them as KNOWN ITEMS for `/push`, don't fix them in this thread and don't let them drive re-runs.

   **If Codex cannot run** (usage limit — it's on a ChatGPT subscription and this happens for days at a time — auth failure, offline, or a Codex error), fall back to the **`adversarial-reviewer`** subagent (Opus). Report **which reviewer actually ran** — never imply the Codex gate passed when it did not run — and treat a clean fallback as *no additional signal* (it shares the session model's blind spots, so the cross-model axis is missing). Merge is local + reversible, so record the degraded gate and carry it forward: `/push` re-checks and surfaces it before the irreversible prod step.
6. **Do NOT push, do NOT apply migrations, do NOT clean up worktrees.** When the merges are in, green, and reviewed, tell the user: `main` is staged locally — run **`/push`** to apply migrations + production-build + deploy, then **`/prune`** to remove merged worktrees.

7. **If what you just merged is NOT safe to deploy on its own, say so loudly in the report.** Local `main` is shared ground: any thread that runs `/push` drains everything sitting on it, not just its own work. So a knowingly-undeployable intermediate state — phase 2 of a 5-phase package-manager migration, an expand step whose contract half hasn't landed, a schema change awaiting its code — is parked where someone else can ship it. (2026-08-02: pre-cutover pnpm phases 1–3 were merged locally and correctly not pushed; an unrelated thread's `/push` carried them to prod and the deploy failed.) Lead the report with **"`main` is NOT deployable until \<the thing\> lands"** so the user and every other thread know before anyone reaches for `/push`.

## Conflict playbook

Parallel threads usually touch disjoint files → clean auto-merge (~80%). The predictable snags:

- **Migration number clash** — two branches both add `097_*.sql`: renumber the later one; verify it still applies. (Timestamped names `YYYYMMDDTHHMM_*.sql` avoid this project-wide.) Note: migrations are only *applied* in `/push`; here you only resolve the file conflict.
- **Lockfile / package.json** — never hand-merge: take the union of dependency changes in `package.json`, delete the conflicted lockfile, rerun `npm install`.
- **Shared hub files** (route index, `PROJECT_SPEC.md`, registries) — genuine semantic merges; merge by hand, and rely on the per-merge test run (step 4d) to catch a bad merge — a hand-resolved merge never qualifies for 4d's skip, so that run is mandatory here.

## Report

End with: branches merged, tests/e2e result after each, the Codex review verdict (or which fallback reviewer ran), any conflicts resolved, and the reminder that `main` is local-only until `/push`.
