---
name: skilltastic
description: Author a skill that runs on every host and is safe to publish — scaffold SKILL.md with valid front matter, design against the tightest host's limits (20 companion files, 10MB, no local filesystem), install the leak/portability/allowlist guard in the repo, and cut a portable drop-in folder. Use when writing a new skill, reviewing or fixing an existing one, packaging a skill for claude.ai or Cowork, or wiring the publishability guard into a public repo.
---

# skilltastic

A skill for authoring skills, and for keeping them publishable.

It exists because two public repos shipped internal tooling in the same week and
neither had a gate. The gate now travels with the skill.

Four steps. Do them in order — the guard is cheap to run and expensive to
retrofit, so install it before there is anything to hide.

## Step 1 — Scaffold

A skill is a folder. The folder name **is** the address the host loads it by, so
it must equal the `name` in the front matter.

```
<skill-name>/
  SKILL.md              # front matter + the body, loaded when the description matches
  reference/            # opened only when the body points at it (see the table pattern below)
  assets/               # scripts and templates the body tells the agent to run or copy
  portable/
    SKILL.md            # the cut for hosts with no shell — a different document, written by hand
    FILES               # what the portable cut contains
```

Start `SKILL.md` with this and change the two fields:

```markdown
---
name: my-skill
description: What it does, in one clause. Then when to use it — the triggers, the phrases, the situations. This field is the only thing the host matches a request against, so a description that omits *when* is a skill that never fires.
---

# my-skill

One sentence on what this is for.

## Step 1 — …
```

**The front matter rules, all four enforced by the guard:**

| Field | Rule | Why |
|---|---|---|
| `name` | ≤64 chars, lowercase letters, digits and hyphens | The address. Anything else fails to load on at least one host. |
| `name` | never contains `anthropic` or `claude` | Reserved. |
| `name` | equals the folder name | Otherwise it installs at one address and answers to another. |
| `description` | ≤1024 chars, says what **and** when | The only text matched against a request. |

Keep the body under about 5,000 tokens (~20KB). It loads in full every time the
skill fires. Everything longer goes in `reference/` behind a read-this-when
table, so the agent opens one file instead of carrying all of them:

```markdown
| Read this | When |
|---|---|
| [reference/hosts.md](reference/hosts.md) | Deciding which hosts a skill targets, or why one refuses it |
| [reference/publishing.md](reference/publishing.md) | Wiring the guard into a repo, or a guard finding you do not recognise |
```

**Address bundled files relatively — `assets/thing.py`, or `<skill-dir>/assets/thing.py`
resolved from wherever the skill loaded.** A skill that writes out its own
install path works on one machine and is silently broken everywhere else. The
guard blocks this one.

## Step 2 — Decide which hosts it targets

Four hosts read the same `SKILL.md` and none of them syncs to the others. The
format is portable; the machine underneath is not.

| Host | The binding limit |
|---|---|
| Copilot Cowork | One `SKILL.md` (≤1MB) plus **20 companion files**, 10MB per skill, 50 skills. Sees cloud-drive files only, never the local device. |
| claude.ai | Zip upload, per user. Sandbox runs Python and JavaScript. 30MB per file. Network on by default for individual plans, off for team plans. |
| Claude Cowork | A shell in a Linux VM. Egress through an allow-list proxy, so package and browser downloads are unproven at best. |
| Claude Code | The whole machine. Whatever is installed is available. |

**Design against Copilot Cowork.** A skill that fits it fits everywhere. Twenty
companion files is the cap that bites first, and it bites at packaging time,
long after the design is set.

If the skill needs a shell — a renderer, a headless browser, a package install —
say so in its body and ship a **portable cut** for the other three (Step 4),
rather than letting it half-work. Detail and the per-host verdicts:
[reference/hosts.md](reference/hosts.md).

## Step 3 — Make the repo refuse to publish a leak

One guard, four jobs: leaks, portability, the public-skill allowlist, and the
front matter from Step 1. Install it in any repo that pushes to a public remote.

```bash
mkdir -p scripts .githooks
cp <skill-dir>/assets/check-no-leaks.py scripts/
git config core.hooksPath .githooks
python3 scripts/check-no-leaks.py --selftest   # 11 rules, known answers
python3 scripts/check-no-leaks.py --all        # the whole tree, before you trust it
```

Then the two hooks — content on the way in, authorship on the way out, because
an author line is metadata rather than a file and the content check cannot see
it. Copy them from this repo's `.githooks/`.

Two lists make the guard specific to a repo, and neither one is committed:

- **`.leakrc`** — the private literals: domains, surnames, internal command,
  repo, library and infrastructure names. The guard reads the repo's own
  `.leakrc` if it has one, otherwise the shared list in the config directory.
  **Gitignore it.** A guard that spells out what it blocks publishes the
  inventory it exists to protect.
- **`skills/PUBLIC`** — one skill name per line. A skill under `skills/<name>/`
  that this file does not name is refused. Adding a line is a decision, not a
  formality: everything in that folder becomes public on push.

Format, findings and what to do about each one:
[reference/publishing.md](reference/publishing.md).

## Step 4 — Cut the portable version

The portable cut is the flat folder a host with no shell can use. Declare it in
`portable/FILES`, one line per file:

```
portable/SKILL.md -> SKILL.md    # written by hand: a different document for a different reader
assets/template.html             # copied verbatim, so there is no second source to drift
```

Then build it, and make the limits an assertion rather than a hope:

```bash
python3 <skill-dir>/assets/make-portable.py . --self-check
python3 <skill-dir>/assets/make-portable.py . /tmp/out --zip
```

`--self-check` fails on more than 20 companion files, more than 10MB, a
`SKILL.md` over 1MB or without front matter, an empty file, and — the one that
actually catches things — a companion the portable `SKILL.md` never mentions. An
unmentioned file is never opened by the host and still costs one of twenty
slots.

The `--zip` output is what uploads to claude.ai. The folder is what goes in the
Cowork skills directory on the cloud drive.

## When a skill should not be here at all

**A skill that only ever talks to private infrastructure belongs in a private
config repo, not a public one.** Publishing it exposes the shape of that
infrastructure and it is useless to everyone who cannot reach it. The test is
not "does it contain a secret" — the guard covers that — it is "would this do
anything at all in someone else's hands?"

`skills/PUBLIC` is where that decision gets recorded. If a skill is not on the
list, the answer to "can this be published?" is no until somebody writes the
line.

## Reference

| Read this | When |
|---|---|
| [reference/hosts.md](reference/hosts.md) | Choosing target hosts, packaging for one, or explaining why a skill will not run somewhere |
| [reference/publishing.md](reference/publishing.md) | Installing the guard, writing `.leakrc`, or a finding you do not recognise |
