# Installing html-brief

The skill is one `SKILL.md` plus a drop-in runtime (`assets/brief.css`,
`assets/brief.js`). How you install it decides only where those two files come
from — the authoring contract in `SKILL.md` is identical everywhere.

## 1. An agent with a filesystem (Claude Code, Cursor, Gemini CLI, Copilot in VS Code)

Put this folder anywhere the tool discovers skills — a user-level skills
directory, a project's `.claude/skills/`, or a plugin. Nothing inside the skill
assumes a location: it copies its runtime from `<skill-dir>/assets/`, resolved
from wherever the SKILL.md was loaded.

Generated briefs are a folder: `<name>.html` + `brief.css` + `brief.js`. They
work offline and forever, because nothing is fetched.

## 2. Microsoft 365 Copilot CoWork

Drop the folder at `Documents/Cowork/Skills/html-brief/` in OneDrive. CoWork
discovers `SKILL.md` on its own and shows the skill as a chip in the side panel;
there is no install step and no terminal. CoWork allows up to 20 custom skills
and 1 MB per `SKILL.md`, so this one fits with room to spare.

CoWork's handling of a skill's bundled sibling files is not documented, so
**briefs here should use the standalone build** (`assets/brief-standalone.html`)
and depend on nothing but the SKILL.md itself.

## 3. A chat tool with no filesystem (ChatGPT, Copilot chat)

Attach or paste `SKILL.md` and ask for a brief. Because there is nowhere to copy
the runtime to, the answer must be the **standalone build**: a single HTML file
whose two tags point at the version-pinned CDN copies of `brief.css` and
`brief.js`. Save it, open it, and every feature works — tick-off, persisted
answers, selection comments, Copy/Download responses.

Answers live in that browser's own localStorage and the brief's content is never
sent anywhere; only the two static assets are fetched.

## Versioning the CDN build

The standalone template pins a git tag, never `@main`:

    https://cdn.jsdelivr.net/gh/irama/irama-skills@html-brief-v1/skills/html-brief/assets/brief.js

A pinned tag means a brief generated today still renders the same way after the
runtime changes. When the runtime gains something worth publishing, cut the next
tag and bump the template — do not move an existing tag, because briefs already
in someone's hands are pointing at it.

Both tags also carry a Subresource Integrity hash, so the browser refuses a file
that does not match what was published. Recompute both whenever the pinned tag
changes:

    openssl dgst -sha384 -binary brief.css | openssl base64 -A
    openssl dgst -sha384 -binary brief.js  | openssl base64 -A

A stale hash is a hard failure, not a warning — the runtime simply will not run,
and the brief's built-in fallback message tells the reader how to load the assets
locally instead.
