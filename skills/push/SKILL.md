---
name: push
description: Deploy the local default branch to production — apply migrations, run the production build, push main, confirm deploy. Use when the user says "push", "push to prod", "deploy", or invokes /push. The ONLY verb that touches the remote default branch and prod. No "all" variant.
---

Deploy `main` to production. `/push` is the **only** actor that touches the remote default branch and prod — it owns the migration gate (moved here from the old `/git`/`/flatten` because migrations must hit the prod DB *before* the push that triggers the deploy). Run it after `/merge` has landed the branches onto local `main`. See `~/.claude/docs/multithread-workflow.md`.

> Four-verb flow: `/commit` → `/merge` (branch → local main) → **`/push`** (here) → `/prune`.

## Preconditions

- `git rev-parse --abbrev-ref HEAD` must be the **default branch** (`main`/`master`) in the **main checkout** (not a worktree). If not, stop — run `/merge` first, or switch to the main checkout.
- `git remote get-url origin`; confirm the per-repo push identity is configured (`~/.claude/docs/git-auth-per-repo-routing.md`).
- `git status` should show the merged, committed state `/merge` left. Uncommitted stray changes → stop and ask.

## Claim the verb before the first gate, sign it off at the end

Other threads cannot see this run, and the migration and build gates below take minutes before the push happens. Claim it by name so
`/threads` shows what this thread is doing, and so another thread's shipping verb
is refused while it is in flight:

```bash
reg=<skill-dir>/../threads/assets/register.py
[ -f "$reg" ] && python3 "$reg" claim --verb push --note "<what you are deploying>"
```

Held → say who holds it and stop; do not work around it. The `threads` skill is a
sibling of this one in the same skills root; if it is not installed the guard makes
both lines a no-op and this skill behaves exactly as it did before.

The last thing this skill does, after the report, is release it:

```bash
[ -f "$reg" ] && python3 "$reg" sign-off --verb push --status done
```

**Stopped part-way? Sign off anyway, with what actually happened** — `--status blocked` if something outside this thread stopped it, `--status incomplete` if it simply did not finish. Both are honest; a claim left open is not. `blocked` keeps the key held, so nobody else ships a half-deployed repo.

The `PreToolUse` gate claims `<repo>:push` on the bare git command too, but only
for the seconds that command runs. This claim covers the whole verb, which is the
window that matters.

Step 4 below records what a thread that could not see another thread cost: eight
commits landed on local `main` during this skill's own gates, and the push
carried them to prod. The claim is what makes that window visible while it is
open, rather than only detectable afterwards.

## Steps

1. **Confirm a code review actually ran at `/merge`.** Codex reviews the diff during `/merge`, not here. Codex clean → proceed. **`adversarial-reviewer` clean → also proceed** — a completed fallback review satisfies the gate and is not a reason to stop and ask (~/.claude/CLAUDE.md § Codex unavailable; revised 2026-08-03, and there is no exempt class for auth/payments/deletion/migrations). Report which reviewer ran and that the cross-model axis was missing; that disclosure IS the requirement, not permission-seeking. Stop only if **no** review ran at all, or one left a P0/P1/P2 finding unresolved — don't silently push past a gate that never ran.
2. **Migration gate (hard rule — `~/.claude/CLAUDE.md`).** All projects auto-deploy on push; migrations must be applied to the linked/prod DB *before* the push.
   a) Check the migrations dir (`data/supabase/migrations/`, `supabase/migrations/`, `prisma/migrations/`).
   b) Check for unapplied migrations: Supabase `npx supabase migration list --linked`; Prisma `npx prisma migrate status`.
   c) If pending, apply: `supabase db push --linked` / `prisma migrate deploy`.
   d) On success, if the project has type-gen (`npm run db:types`, `prisma generate`), run it and **commit** the regenerated types.
   e) **Apply through the repo's own applier script if it has one** (`scripts/db/apply-migration.mjs` or equivalent), never bare `psql -f`. A repo that tracks applied migrations in a table records that row from inside the applier; applying by hand leaves the table silently stale, and a ledger that stops recording gives no warning — it just quietly stops being the answer to "what is on prod". Check for such a script before reaching for the CLI in (c). Then update the migrations-applied log if one exists.
   f) **If any migration fails, STOP — do not push.** Fix first.
   Skip only when there are zero migration files and no schema-touching changes on `main`.
3. **Production build — authoritative deploy gate.** Run the real production build (`npm run build` / `next build`, or repo equivalent). This enforces checks the fast gates skip: lint-as-error architecture fences (`no-restricted-imports`), stricter type-elision, RSC/client-boundary violations, static analysis. A tree green on `tsc` + `vitest` can still fail `next build` and the deploy — this is the single most common way a red `main` ships. Red → fix and re-run until clean; **never push on a failing build.**

   **Record the tree you built:** `built_tree=$(git rev-parse HEAD^{tree})`. Step 4 verifies you ship exactly this.

4. **Re-verify the push range IMMEDIATELY before pushing — the gates above take minutes, and other threads merge onto `main` during them.** (2026-08-02: verified `origin/main..main` at the start of `/push`, then spent ~5 min on install + build + the visual-regression pre-push hook. Another thread merged 8 commits onto local `main` in that window; `git push` carried its deliberately-unpushed, pre-cutover pnpm migration to prod. The build gate had certified a different tree, and the deploy failed. Prod survived only because Vercel keeps the last good deployment.)

   Immediately before `git push`, with no gate re-runs in between:

   ```
   git rev-parse HEAD^{tree}          # must equal $built_tree from step 3
   git log --oneline origin/main..HEAD  # must be exactly what you reviewed
   ```

   - **Tree changed → STOP.** `main` moved under you. Re-run step 3 against the new tree before pushing; the old build result is void.
   - **Extra commits → STOP and ask.** Commits you didn't merge belong to another thread that ran `/merge` (local, deliberate) but not `/push`. `/merge` not pushing is the *point* — a thread may be mid-sequence with a knowingly-undeployable intermediate state. Never ship another thread's unpushed work on its behalf; surface it and let the user decide.
   - Anything that fails here is cheap to fix *before* the push and expensive after — pushing `main` is the one irreversible step in the four-verb flow.

5. `git push` to the default branch.
6. **Confirm the deploy triggered** (Vercel dashboard / `vercel ls` / the project's deploy check). Report the deploy URL or status. If the push succeeded but no deploy triggered, surface that — don't claim success. **Verify by SHA, not by age** — check the deployed SHA (e.g. `/api/health`) against what you pushed; a failed deploy leaves the *previous* build serving happily and looking fine.

7. **Register background-job functions with their platform — a deploy does NOT do this.** If the repo has an Inngest endpoint (`src/app/api/inngest/route.ts` or similar), sync it *after* step 6 confirms the new SHA is live, so you register the build you just shipped rather than the previous one:

   ```
   curl -s -X PUT https://<prod-domain>/api/inngest
   ```

   `{"message":"Successfully registered","modified":true}` means the function list **changed** — i.e. something was previously unregistered. `modified:false` means it was already in sync. Report which.

   **Why this is a step and not a footnote (2026-08-07):** a newly-shipped Inngest function was never registered, so `inngest.send()` fired an event with no consumer. The row sat at `queued` — not `failed` — for 30+ minutes, looking exactly like work in progress. Every gate was green, the deploy was healthy, and the feature was silently inert. A function that is not registered does not error; it simply never runs. The same applies to any other platform needing an explicit post-deploy registration (cron/webhook registration endpoints) — sync it here, and say so.

## Report

End with: migrations applied (or "none pending"), build result, push SHA range, deploy status/URL, and the background-job sync result (`modified: true/false`, or "no Inngest endpoint"). (The Codex review verdict is reported at `/merge`.)

State explicitly that **the tree you built is the tree you pushed** (step 4's check), and list the commits shipped. If the range contained anything beyond this thread's own work, say whose it was and that the user approved shipping it.
