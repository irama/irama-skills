---
name: localhost
description: Manage local dev servers on rotating ports 3000-3002. Bare /localhost (or "start") cleans caches and (re)starts this repo's server, returning a clickable link; "/localhost status" lists running servers; "/localhost kill" stops all of them. Use when the user says "localhost", "start the dev server", "localhost status", "localhost kill", "kill the dev servers", or invokes /localhost.
---

Manage local `npm run dev` servers via `~/.claude/scripts/localhost-dev.sh` (owns port rotation). Route on the argument:

- **`status`** → `bash "$HOME/.claude/scripts/localhost-dev.sh" status` — print the table of running servers (port, PID, tracked repo) and relay it. No link.
- **`kill`** → `bash "$HOME/.claude/scripts/localhost-dev.sh" kill` — stop ALL dev servers on 3000-3002 and clear port state. Confirm what was killed.
- **`kill <dir>`** → `bash "$HOME/.claude/scripts/localhost-dev.sh" kill-repo <dir>` — stop only the server(s) whose **cwd** is that repo/worktree, and drop its port pin. Use this whenever one thread's server must go and the others must live — `/prune` calls it before `git worktree remove`, because a server still running in a worktree writes `.next` back into the directory being deleted. Prefer it over bare `kill` any time the target is a single repo.
- **anything else / bare** → start (steps below).

## Steps (start)

1. Run the launcher **with `--clean`** (manual invocation gets a full cache wipe):

       bash "$HOME/.claude/scripts/localhost-dev.sh" "$PWD" --clean

   It cleans `.next` + `node_modules/.cache`, picks the port, launches `npm run dev` detached, and prints one line: `http://localhost:<port>`.

2. **Port rotation** (handled by the script — don't reimplement): each repo/worktree keeps a stable port across restarts; different worktrees take 3000, then 3001, then 3002; a fourth reclaims 3000 (killing its server). This keeps ports within the 3000–3002 range the user's auth setups are configured for.

3. **Wait for readiness**, then confirm: poll the URL until it responds (up to ~30s), e.g. `until curl -sf http://localhost:<port> >/dev/null; do sleep 1; done`. If it never comes up, tail the log at `/tmp/claude-localhost/<key>.<port>.log` and surface the error.

4. **Return the link** as clickable markdown with the URL itself as the link text:

       [http://localhost:3001](http://localhost:3001)

   (Substitute the actual port. The URL must be visible as the link text — not a word like "here".)

## Notes

- The dev server runs **detached** — it survives the turn; the user tests in the browser.
- This same script runs automatically after each worktree auto-commit (without `--clean`, for fast restarts) via the Stop hook — see `~/.claude/docs/multithread-workflow.md`.
- **431 errors (request header fields too large):** cookies ignore the port, so
  `localhost` is ONE cookie jar shared by every app ever run on 3000-3010. Several
  Supabase apps at once push the `Cookie` header past Node's default 16KB cap and the
  browser shows `HTTP ERROR 431`.
  - **Node dev servers (Next.js et al.):** already handled — the launcher exports
    `NODE_OPTIONS=--max-http-header-size=262144` (256KB) on every start. Raise that
    number in the script rather than working around a 431 per-app. A server started
    outside the launcher does NOT get the cap: restart it with `/localhost`.
  - **A repo's own `dev` script wins over the launcher.** `"dev": "NODE_OPTIONS=--max-http-header-size=32768 next dev"`
    REPLACES the inherited value, so the launcher's cap never applies (seen on one
    app, 2026-08-24 — the real limit was 32KB, not 256KB). On a 431, grep `package.json` for
    `max-http-header-size` and raise it there too. Prove the cap, don't assume it:
    `curl -s -o /dev/null -w '%{http_code}' -H "X-Big: $(python3 -c "print('x'*100000)")" http://localhost:PORT/`
    must NOT be 431.
  - **Still 431 at 256KB?** The jar is the problem, not the cap — clear cookies for
    `localhost` in the browser, then reload.
  - **Astro/Vite servers** don't read `NODE_OPTIONS` for this. In a Vite plugin's
    `configureServer(server)` hook set `server.httpServer.maxHeaderSize = 256 * 1024;`
    — e.g. add `if (server.httpServer) { server.httpServer.maxHeaderSize = 256 * 1024; }`
    to the existing `scopedDevCors()` plugin. Apply to any new Astro project.
