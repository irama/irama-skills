---
name: verify-ui
description: Before claiming a UI change done, launch the app and screenshot the affected screen at desktop and mobile to confirm it actually renders correctly. Use after any UI edit, when the user says "verify", "check it renders", "screenshot it", or invokes /verify-ui. /git runs this automatically for UI diffs.
---

Prove a UI change renders correctly by **driving the real app and looking at it** — not by trusting the diff, the typecheck, or the tests. This exists because the biggest recurring waste is claiming a UI fix done, the user hard-refreshing prod, finding it broken, and pasting a screenshot back. Close that loop here, before commit.

Related: `/run` launches the app; `/verify` drives a flow end-to-end. `verify-ui` is the narrow **visual gate**: render the affected screen at two widths, look, compare to the intended state.

## Per-project bootstrap (first run in a repo)

Look for `.claude/verify-ui.md` in the repo. If it doesn't exist, discover and write it, then use it:

- **dev command** — from `package.json` scripts (`dev`/`start`) and framework (Vite, Next, etc.).
- **base URL + how the port is set** — most dev servers accept `--port` / `PORT=`.
- **key routes** — the handful of routes worth screenshotting, and any auth needed to reach them (test user, bypass flag). Check the project's e2e/CLAUDE.md for an existing login shortcut.

Save these as a short `.claude/verify-ui.md` so later runs skip discovery. Keep it current when routes change.

## Port (parallel-worktree safe)

Concurrent worktrees each run their own dev server, so **never hardcode a port**. Derive a stable per-worktree port: `PORT=$(( 4000 + $(pwd | cksum | cut -d' ' -f1) % 1000 ))` (or the project's documented scheme). Same worktree → same port across runs; different worktrees → different ports, no collision.

## Steps

1. Identify the **affected screen(s)** from the diff — which route(s)/component(s) changed. Only screenshot what the change touches (plus one obvious neighbour if layout could bleed).
2. Ensure the app is running on this worktree's port (start it if not; reuse if already up). Wait for it to be ready (poll the URL, don't fixed-sleep).
3. Drive to each affected route (handle auth via the bootstrap's shortcut). Screenshot at:
   - **desktop** — 1280×800,
   - **mobile** — 375×812 (the mandatory 375px gate).
   Use Playwright (`npx playwright`) if installed; otherwise the project's browser-driver, or install Playwright as a dev dependency if the repo has none.
4. **Look at the screenshots.** Check against the change's intent and the standing UI gates: nothing clipped/cut off by a bounding box or overflow ancestor; no layout overflow at 375px; text fits its container; contrast holds in both light and dark if the change touches theming; the specific thing the task asked for is actually visible and correct.
5. If a prior screenshot of the same screen exists in the scratchpad, diff against it to catch regressions the change shouldn't have caused.
6. Report pass/fail with the screenshots attached. On **fail**, do not declare done — fix and re-run. On **pass**, the change is cleared for commit.

## Output

Attach the desktop + mobile screenshots for each affected screen and a one-line verdict per screen. If it failed, state exactly what's wrong (clipped element, overflow, missing control) so the fix is targeted, not guesswork.
