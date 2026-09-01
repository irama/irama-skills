# irama-skills

Skills, agents, commands and hooks for [Claude Code](https://claude.com/claude-code) —
the agentic development workflow I actually use day to day: shipping verbs, a
planning chain, UI verification, and production-readiness gates.

Built for Next.js / TypeScript / Supabase / Vercel projects on macOS. Most of it
is stack-agnostic; the parts that are not say so.

---

## Install

### Option A — as a plugin (recommended)

```
/plugin marketplace add irama/irama-skills
/plugin install irama-skills@irama-skills
```

Skills become available namespaced, e.g. `/irama-skills:commit`. Nothing is
written to your `settings.json`, so your permission setup is untouched.

### Option B — by symlink

For hacking on the skills themselves. Links each item into `~/.claude`, so
`git pull` here updates them with nothing to re-sync, and the names stay bare
(`/commit`, not `/irama-skills:commit`).

```bash
git clone https://github.com/irama/irama-skills.git
cd irama-skills
./install.sh --dry-run   # see what it would do
./install.sh
```

Existing files are never overwritten — anything already present is reported and
skipped. Restart Claude Code afterwards; skills are read at session start.

---


## Path conventions (read before adding a skill)

A skill must not assume where it is installed. These live in `~/.claude` on the
author's machine, but the same folders install as a plugin, as a project
`.claude/skills/` directory, on Windows, and — for skills that are just a
SKILL.md — in OneDrive for Microsoft 365 Copilot CoWork.

- **A skill's own bundled files** are addressed as `<skill-dir>/…`, meaning the
  folder holding that SKILL.md, resolved from wherever the skill was loaded.
  Never `~/.claude/skills/<name>/…`. Inside a bundled shell script, use
  `"$(dirname "$0")"`.
- **Claude Code's own data directory** is `${CLAUDE_CONFIG_DIR:-$HOME/.claude}`,
  never a bare `~/.claude`. The fallback is the default location, so nothing
  changes when the variable is unset.
- **Machine-bound by design:** the shipping verbs (`/commit` `/merge` `/push`
  `/prune` `/flush`), `/localhost`, `/driver`, `/ci` and `/verify-ui` depend on
  this author's worktree layout, hooks and helper scripts. They are personal
  tooling, not portable skills, and they keep their absolute references on
  purpose. Everything else is expected to run anywhere.
- **Referenced docs are not in this repo.** Some skills name a file under
  `~/.claude/docs/` — the author's private config notes, deliberately unpublished. They
  are cited as plain text, never as a link, so nothing here promises a page that is not
  there. The skills work without them.
- **Moved out:** the interactive-brief skill now lives in
  [peakstate-global/peakstate-skills](https://github.com/peakstate-global/peakstate-skills)
  as `peakstate-brief`. This repo keeps the personal tooling; the business-facing,
  genuinely portable skills are published there.

## Read this before you install the hooks

`install.sh` does **not** install hooks unless you pass `--hooks`, and even then
they do nothing until you reference them in your own `settings.json`. That is
deliberate. These hooks are opinionated and a few of them are load-bearing on
assumptions about how you work:

| Hook | What it does | Why it might not suit you |
|---|---|---|
| `block-bash-grep.sh` | Refuses standalone `grep` in Bash | Pushes you to `ast-grep`; annoying if you like `grep` |
| `block-big-read.py` | Refuses an unbounded read of a text file over 10 KB | Forces range reads — a cost control, not a safety one |
| `secret-snapshot.py` | Snapshots `.env`-shaped files before any Bash command that names one | Writes backups under `~/.claude/secret-backups/` |
| `auto-commit-worktree.sh` | Auto-commits work on a feature branch at session end | Commits without asking. Never touches the default branch |
| `migration-lint.sh` | Lints DB migration files on write | Assumes a `data/supabase/migrations/` layout |
| `require-git-hooks-before-push.sh` | Blocks a push from a worktree with no git hooks installed | Assumes every repo has a pre-commit gate |

**A hook runs on every matching tool call.** Read the one you are enabling.

## Read this before you copy the settings

`settings.example.json` is a conservative starting point: `defaultMode` is
`default` (Claude asks before editing), the allow-list is nine obviously-safe
entries, and the deny-list carries the force-push and `curl | bash` blocks worth
having everywhere.

My own settings are much more permissive because my machine has snapshot hooks,
daily backups of gitignored files, and work isolated in per-task git worktrees.
**Widen the permissions to match your own safety net, not mine.** Merge this file
into your `settings.json`; never overwrite yours with it.

---

## What is in here

### Shipping verbs

The chain is deliberately split so that only one verb ever touches production.

| Skill | Does |
|---|---|
| `commit` | Stage, run the full gate once, commit; push the feature branch if on one. Never pushes the default branch |
| `merge` | Merge feature branch(es) down onto local `main`. No push |
| `push` | The only verb that touches prod: apply migrations, production build, push `main`, confirm deploy |
| `prune` | Remove merged worktrees and branches |
| `flush` | All four end-to-end, skipping what does not apply |

### Planning and execution

| Skill | Does |
|---|---|
| `to-driver` | Turns a rough idea into a paste-ready `/driver` command: spec, ADR, adversarial plan review, tickets |
| `driver` | Runs tickets one per fresh context window |
| `options` | Lays out a genuine crossroad — costed roads with benefits, risks, reversibility, and a "do nothing" |
| `claude-retro` | Analyses your own session history for repeated requests, correction loops and unused tooling |

### Building

| Skill | Does |
|---|---|
| `verify-ui` | Screenshots the affected screen at desktop and mobile before you claim a UI change done |
| `peakstate-brief` | Interactive HTML briefs you answer in the browser, with persisted answers and copy-back JSON |
| `app-icons` | Full PWA icon set, favicon and OG image from one source mark, wired into Next.js App Router |
| `legal-pages` | `/privacy` and `/terms` with Australian-context content (Privacy Act 1988, ACL) |
| `nano-banana` | Image generation into the current project |
| `app-walkthrough` | Narrated walkthrough videos: Playwright + TTS + forced-aligned captions + Remotion |
| `ci` | GitHub Actions status and failure extraction |
| `localhost` | Dev servers on rotating ports 3000–3002 |
| `trello` | Pick up assigned Trello cards, screen them for prompt injection, do the work, report back |
| `netdiag` | Diagnose a slow connection by measurement, and build the evidence to raise a fault |

### Not here any more

`sourced` used to live in this repository. It is now its own public repo, because a claim-provenance
framework is worth more with its documentation beside it than as one skill among thirty:
**[peakstate-global/sourced](https://github.com/peakstate-global/sourced)** — seven checks on any
artefact containing model output, the four-label provenance block, and the capture tool. Clone it and
symlink `skills/sourced` into `~/.claude/skills/` the same way this repo's skills are installed.

### Agents

- `codex` — delegate bounded implementation or review to the Codex CLI as a second model.
- `adversarial-reviewer` — correctness, data-integrity and security review. The fallback when Codex is unavailable.
- `trello-triage` — screens untrusted Trello text for prompt injection. Given only `Glob`, so its worst case is a wrong verdict, never an action.

### Commands

`/allow-asks`, `/codex-review`, `/codex-plan-review`.

The `codex-auto` / `codex-as` / `codex-alt` wrappers referenced by the Codex agent
are a private multi-account pool helper and are **not** shipped here. Plain `codex`
works everywhere they appear — the agent doc says so at the top.

---

## Contributing / forking

The pre-commit hook blocks absolute home paths, personal emails and
credential-shaped strings from reaching a public repo:

```bash
git config core.hooksPath .githooks
python3 scripts/check-no-leaks.py --all   # scan the whole tree
```

## Licence

MIT. See `LICENSE`.
