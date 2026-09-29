---
name: skilltastic
description: Author a portable skill — scaffold SKILL.md with valid front matter, keep the body small, and design against the tightest host's limits of 20 companion files and 10MB with no local filesystem. Use when writing a new skill, reviewing an existing one, or working out whether a skill can run where you need it.
---

# skilltastic

A skill for authoring skills. This is the portable cut: the authoring rules,
with no scripts. The publishability guard and the portable-cut packer need git
and a shell, so they stay on the full version.

## 1. The folder

The folder name **is** the address the host loads the skill by, so it must equal
the `name` in the front matter.

```
<skill-name>/
  SKILL.md              # front matter + body, loaded when the description matches
  reference/            # opened only when the body points at it
  assets/               # scripts and templates the body names
```

## 2. The front matter

```markdown
---
name: my-skill
description: What it does, in one clause. Then when to use it — the triggers, the phrases, the situations. This field is the only thing the host matches a request against, so a description that omits *when* is a skill that never fires.
---
```

| Field | Rule | Why |
|---|---|---|
| `name` | ≤64 chars, lowercase letters, digits and hyphens | The address. Anything else fails to load on at least one host. |
| `name` | never contains `anthropic` or `claude` | Reserved. |
| `name` | equals the folder name, under `skills/` | There the folder name is the install address, so a mismatch installs at one address and answers to another. A skill kept elsewhere in a source tree is installed by a symlink or a copy that renames it, and the check does not apply. |
| `description` | ≤1024 chars, says what **and** when | The only text matched against a request. |

## 3. The body

Keep it under about 5,000 tokens (~20KB). It loads in full every time the skill
fires. Everything longer goes in `reference/` behind a read-this-when table, so
the agent opens one file instead of carrying all of them:

```markdown
| Read this | When |
|---|---|
| [reference/hosts.md](hosts.md) | Deciding which hosts a skill targets |
```

Address bundled files relatively. A skill that writes out its own install path
works on one machine and is silently broken everywhere else.

## 4. The host

Design against the tightest host — one `SKILL.md` under 1MB plus **20 companion
files**, 10MB per skill, and no access to local device files. A skill that fits
that fits the packaging limits of the four hosts that load a skill folder.
ChatGPT, Copilot declarative agents and Gemini read the same format but gate
it by plan, preview or account type. The limits, the capabilities table for all
eight surfaces, the three ladders and the per-host verdicts are in
[hosts.md](hosts.md). At run time a skill trusts its own tool list over that
table: it checks which tools it can call now and takes the first rung that
works. The wording for that check is in [host-snippet.md](host-snippet.md):
paste it into any skill that makes a diagram, an image or a file.

If a skill needs a real shell — a renderer, a headless browser, a package
install — say so in its own body and ship a smaller cut for the hosts that have
none, rather than letting it half-work.

The full version's packer builds that cut. With no `portable/FILES` it takes
the whole folder and keeps subfolders such as `references/`. With one, it
copies the listed files flat. `--md-only` refuses any file that is not `.md`,
and `--single-file` folds the references and `SOURCES.md` into one `SKILL.md`
for a host that takes a single file.

## 5. Before it goes anywhere public

A skill that only ever talks to private infrastructure belongs in a private
repo. The test is not "does it contain a secret" — it is "would this do anything
at all in someone else's hands?"

The full version of this skill carries a guard that enforces that, plus absolute
home paths, credentials, private domains and dead links, as a pre-commit hook.
Run it from a developer machine before publishing.
