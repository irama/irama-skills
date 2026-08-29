#!/usr/bin/env node
/**
 * sync-worktree-workspace.mjs
 *
 * Global Claude Code hook. Keeps a per-project multi-root `<name>.code-workspace`
 * file in sync with `git worktree list`, so every worktree a thread creates shows
 * up as its own root in one VSCode window — and threads never "disappear" from the
 * Claude panel when a session moves into a worktree.
 *
 * Wired as a PostToolUse hook on EnterWorktree|ExitWorktree. Reconcile-based (not
 * parse-based): it reads the current worktree list and rewrites only the managed
 * folder entries, so it self-heals — adds new worktrees, prunes removed ones,
 * preserves any roots the user added by hand.
 *
 * Fails silent (exit 0) on any error: a hook must never block the tool it follows.
 */

import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, existsSync, copyFileSync } from 'node:fs';
import { basename, join, relative, dirname, resolve, isAbsolute } from 'node:path';

const log = (msg) => process.stderr.write(`[sync-worktree-workspace] ${msg}\n`);

/**
 * Read the hook payload from stdin, and give up quickly if there isn't one.
 *
 * As a PostToolUse hook this gets JSON piped in and an immediate EOF. Run BY
 * HAND — which is exactly what `/prune` step 6 tells you to do — stdin is either
 * a terminal or an inherited pipe that nobody ever closes, and the old
 * `readFileSync(0)` blocked forever waiting for an EOF that was never coming.
 * It looked like an infinite loop and it silently stopped `/prune` from ever
 * resyncing the workspace file, so stale roots accumulated for weeks.
 *
 * The timeout is what makes both callers work. A real hook payload arrives in
 * microseconds; a hand run waits a quarter second and proceeds with the cwd
 * fallback, which is all it needed anyway.
 */
function readStdin(timeoutMs = 250) {
  return new Promise((resolveStdin) => {
    if (process.stdin.isTTY) return resolveStdin('');

    let data = '';
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      process.stdin.removeAllListeners('data');
      process.stdin.removeAllListeners('end');
      process.stdin.removeAllListeners('error');
      resolveStdin(value ?? data);
    };

    const timer = setTimeout(() => finish(''), timeoutMs);
    if (typeof timer.unref === 'function') timer.unref();

    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => {
      data += chunk;
    });
    process.stdin.on('end', () => finish());
    process.stdin.on('error', () => finish(''));
  });
}

function git(args, cwd) {
  return execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
}

try {
  const input = await readStdin();
  let cwd = process.cwd();
  try {
    const parsed = JSON.parse(input);
    if (parsed && typeof parsed.cwd === 'string') cwd = parsed.cwd;
  } catch {
    /* no/invalid stdin — fall back to process cwd */
  }

  // Find the MAIN worktree root, even when the session sits inside a worktree.
  // git-common-dir points at the main repo's .git; its parent is the main root.
  let mainRoot;
  try {
    const commonDir = git(['rev-parse', '--path-format=absolute', '--git-common-dir'], cwd);
    mainRoot = commonDir.endsWith('/.git') || basename(commonDir) === '.git' ? dirname(commonDir) : commonDir;
  } catch {
    log('not a git repo; nothing to do');
    process.exit(0);
  }

  // Enumerate worktrees.
  const porcelain = git(['worktree', 'list', '--porcelain'], mainRoot);
  const paths = porcelain
    .split('\n')
    .filter((l) => l.startsWith('worktree '))
    .map((l) => l.slice('worktree '.length).trim());

  if (paths.length === 0) process.exit(0);

  // First entry is always the main worktree. The rest are the extra roots.
  const extraPaths = paths.filter((p) => p !== mainRoot);

  // Carry gitignored local secrets (.env.local & peers) from the main root into any
  // worktree missing them. Git never tracks these, so a fresh worktree boots without
  // them and the dev server white-screens ("supabaseUrl is required"). Copy-if-missing,
  // never overwrite a worktree's own edited copy.
  const SECRET_FILES = ['.env.local', '.env', '.env.development.local'];
  for (const wt of extraPaths) {
    for (const f of SECRET_FILES) {
      const src = join(mainRoot, f);
      const dst = join(wt, f);
      if (existsSync(src) && !existsSync(dst)) {
        try {
          copyFileSync(src, dst);
          log(`copied ${f} -> ${basename(wt)}`);
        } catch (e) {
          log(`could not copy ${f} to ${basename(wt)}: ${e && e.message ? e.message : e}`);
        }
      }
    }
  }

  const projName = basename(mainRoot);
  const wsPath = join(mainRoot, `${projName}.code-workspace`);

  // Managed folder entries = main + every current worktree (relative paths).
  const managed = [
    { path: '.', name: `${projName} (main)` },
    ...extraPaths.map((p) => {
      const rel = relative(mainRoot, p);
      return { path: rel, name: `▸ ${basename(p)}` };
    }),
  ];

  // A folder is "ours to manage" if it's the main root or lives in either
  // worktree layout: nested `.claude/worktrees/…`, or the sibling
  // `../<project>-worktrees/…` that most LOCAL-DEV repos actually use.
  //
  // The sibling layout was missing here, so those roots counted as USER roots
  // and were preserved forever — pruning a worktree left its root in the
  // workspace file permanently, and `/prune`'s step 5 silently no-opped. Any
  // new layout added above must be added here too, or it rots the same way.
  const isManaged = (f) => {
    const p = (f.path || '').replace(/\\/g, '/');
    return (
      f.path === '.' ||
      p.startsWith('.claude/worktrees') ||
      p.startsWith(`../${projName}-worktrees/`)
    );
  };

  // Load existing workspace to preserve user-added roots + their settings.
  let ws = { folders: [], settings: {} };
  if (existsSync(wsPath)) {
    try {
      ws = JSON.parse(readFileSync(wsPath, 'utf8'));
    } catch {
      log(`existing ${projName}.code-workspace is invalid JSON; leaving it untouched`);
      process.exit(0);
    }
  }
  if (!Array.isArray(ws.folders)) ws.folders = [];
  if (typeof ws.settings !== 'object' || ws.settings === null) ws.settings = {};

  // A root pointing at a directory that no longer exists is dropped, managed or
  // not. `isManaged` only recognises two worktree layouts, so anything created
  // anywhere else — a sibling folder under a different name, a scratch clone in
  // a temp dir — counted as a USER root and was preserved forever. Sixteen of
  // them had accumulated in one project, two of them outside the repo entirely.
  //
  // Matching layouts one by one is what rotted; existence is the rule that
  // cannot rot, and it is what makes this script self-healing as its header
  // claims. The trade: a root on a network or removable volume that happens to
  // be unmounted right now gets dropped and has to be re-added. That is cheap,
  // and VSCode renders such a root as an error anyway.
  const stillExists = (f) => {
    if (!f || typeof f.path !== 'string') return false;
    if (f.path === '.' || f.path === './') return true;
    return existsSync(isAbsolute(f.path) ? f.path : resolve(mainRoot, f.path));
  };

  const userRoots = ws.folders.filter((f) => !isManaged(f));
  const keptUserRoots = userRoots.filter(stillExists);
  const droppedCount = userRoots.length - keptUserRoots.length;

  // Dedupe by RESOLVED path, managed entries winning. `isManaged` recognises two
  // worktree layouts by prefix, so a repo using any third layout (such as a
  // sibling `../<repo>-wt/` directory) had every one of its worktrees counted as
  // a USER root — preserved on every run, AND re-appended as a managed root on
  // the next. The file grew one duplicate per sync: 326 roots in one large
  // private repository by 2026-08-25, which VSCode opens as 326 file-watcher
  // trees and TS servers (~70 GB resident).
  //
  // Prefix matching is what rots. Identity of the directory cannot.
  const abs = (f) => (isAbsolute(f.path) ? resolve(f.path) : resolve(mainRoot, f.path));
  const seen = new Set();
  const dedupedCount = { n: 0 };
  ws.folders = [...managed, ...keptUserRoots].filter((f) => {
    const key = abs(f);
    if (seen.has(key)) {
      dedupedCount.n += 1;
      return false;
    }
    seen.add(key);
    return true;
  });

  // Hide the nested duplicate copy of worktrees under the main root's explorer.
  ws.settings['files.exclude'] = { ...(ws.settings['files.exclude'] || {}), '**/.claude/worktrees': true };

  writeFileSync(wsPath, JSON.stringify(ws, null, 2) + '\n');

  // Ensure the workspace file + worktrees dir are gitignored (idempotent append).
  const giPath = join(mainRoot, '.gitignore');
  if (existsSync(giPath)) {
    let gi = readFileSync(giPath, 'utf8');
    const need = [];
    if (!/^\.claude\/worktrees\/?$/m.test(gi)) need.push('.claude/worktrees/');
    if (!gi.split('\n').some((l) => l.trim() === `${projName}.code-workspace`)) need.push(`${projName}.code-workspace`);
    if (need.length) {
      if (!gi.endsWith('\n')) gi += '\n';
      gi += `\n# claude multi-thread worktrees + local multi-root workspace file\n${need.join('\n')}\n`;
      writeFileSync(giPath, gi);
    }
  }

  log(
    `synced ${extraPaths.length} worktree root(s) into ${projName}.code-workspace` +
      (droppedCount ? `; dropped ${droppedCount} root(s) whose directory is gone` : '') +
      (dedupedCount.n ? `; dropped ${dedupedCount.n} duplicate root(s)` : '')
  );
  process.exit(0);
} catch (err) {
  log(`error (ignored): ${err && err.message ? err.message : err}`);
  process.exit(0);
}
