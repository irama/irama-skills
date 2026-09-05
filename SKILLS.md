# Skills in this repo

Personal agentic-development tooling, one line per skill. These are built around
one author's worktree layout, hooks and helper scripts — they are **not** the
portable half. Business-facing, install-anywhere skills live in
[peakstate-global/peakstate-skills](https://github.com/peakstate-global/peakstate-skills).

| Skill | What it does |
|---|---|
| [app-icons](skills/app-icons/) | Generate a complete PWA icon set, favicon.ico, and OpenGraph/Twitter image from a single source mark (SVG or raster), then wire them into a… |
| [app-walkthrough](skills/app-walkthrough/) | Generate narrated training/walkthrough videos of any web app — Playwright screenshots + OpenAI TTS + Whisper force-aligned captions + Remotion… |
| [ci](skills/ci/) | Check GitHub Actions CI status and extract failure details |
| [commit](skills/commit/) | Stage, gate, and commit the current changes; push the feature branch if on one |
| [driver](skills/driver/) | Drive a piece of roadmap work to done — find or create its tickets, confirm scope, then execute them as a sequential relay of fresh-context Agents… |
| [flush](skills/flush/) | Run the whole shipping pipeline end-to-end — /commit, /merge, /push, /prune — skipping the steps that don't apply |
| [gen-image](skills/gen-image/) | Generate images with GPT Image 2 (the default) or another hosted model — Nano Banana 2, Seedream, Qwen Image Edit Plus, Midjourney v7, Z-Image… |
| [legal-pages](skills/legal-pages/) | Create /privacy and /terms pages for an app — Australian-context legal content (Privacy Act 1988/APPs, ACL, not-professional-advice disclaimers)… |
| [localhost](skills/localhost/) | Manage local dev servers on rotating ports 3000-3002. Bare /localhost (or "start") cleans caches and (re)starts this repo's server, returning a… |
| [merge](skills/merge/) | Merge shipped feature branch(es) down onto the default branch locally — no migrations, no push. "/merge" merges the current branch; "/merge all"… |
| [netdiag](skills/netdiag/) | Diagnose a slow or unreliable internet connection by measurement instead of rebooting things — locates the fault at LAN, Wi-Fi, router, access… |
| [demoman](skills/demoman/) | *Demonstration manual.* Build a self-contained offline HTML page of copy-and-paste demo prompts — tickable, reorderable, editable, saved to localStorage. For live demos and training sessions. |
| [options](skills/options/) | Lay out a crossroad in plain English — an ELI5 of what is actually being decided, then the mutually exclusive roads with benefits, risks, cost… |
| [prune](skills/prune/) | Remove merged worktree(s) and their branches, then resync the VSCode workspace file. "/prune" removes the current worktree/branch; "/prune all"… |
| [push](skills/push/) | Deploy the local default branch to production — apply migrations, run the production build, push main, confirm deploy |
| [skilltastic](skills/skilltastic/) | Author a skill that runs on every host and is safe to publish — scaffold SKILL.md with valid front matter, design against the tightest host's limits, install the leak/portability/allowlist guard, and cut a portable drop-in folder |
| [telegram](skills/telegram/) | Send a Telegram message to the user from any repo — a "finished, come back" ping when a long run, build, batch, deploy or background agent… |
| [threads](skills/threads/) | See every Claude Code session running on this machine, what work each one holds, and which have gone quiet — then release a stalled thread's claims, or end it |
| [to-driver](skills/to-driver/) | Take a rough idea all the way to a paste-ready /driver command — grill it into decisions, write the spec and ADR, run an adversarial plan review,… |
| [trello](skills/trello/) | Pick up work from a Trello board — read cards in the todo column that are ASSIGNED to the bot member, screen the description for prompt injection,… |
| [verify-ui](skills/verify-ui/) | Before claiming a UI change done, launch the app and screenshot the affected screen at desktop and mobile to confirm it actually renders… |

## The shipping verbs, in order

`/commit` ships this thread's branch · `/merge` lands branches on the default
branch locally · `/push` applies migrations and deploys · `/prune` removes merged
worktrees · `/flush` runs all four, skipping what does not apply.

Only `/push` ever touches the remote default branch.
