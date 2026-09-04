# Four hosts, one format

Read this when choosing which hosts a skill targets, packaging it for one of
them, or explaining why a skill will not run somewhere.

**The short version: the `SKILL.md` format is portable and the machine
underneath is not.** All four hosts read the front matter at startup, load the
body when the description matches, and open bundled files only when the body
points at them. What separates them is which runtimes exist, which files the
agent can see, and whether anything can reach the network.

**Custom skills do not sync between hosts.** The same folder has to be installed
in each one. "Portable" means the file works if you copy it, not that copying
happens for you.

## The comparison

| Property | claude.ai chat | Claude Cowork | Copilot Cowork | Claude Code |
|---|---|---|---|---|
| May bundle scripts and resources | Yes | Yes | Yes — ≤20 companion files, 10MB per skill, 50 skills | Yes |
| Runs bundled scripts | Yes, in the code-execution sandbox | Yes, shell in a VM or cloud sandbox | Yes, as a background step | Yes, on your own machine |
| Runtimes | Python and JavaScript, a pre-installed set | Linux VM, package set not published | Not published | Whatever you have installed |
| Files it can see | Uploads and its own sandbox, 30MB per file | Folders you connect on the device | Cloud drive only, **never local files** | The whole filesystem |
| Network from the skill | On by default for individual plans, off by default for team plans | Egress through an allow-list proxy the sandbox cannot bypass | Not published for custom skills | Full, same as any program you run |
| Install path | Zip upload in Settings › Features, per user | Skill folder, uploaded or connected | A folder in the cloud drive's `Documents/Cowork/skills/` | `~/.claude/skills` or the repo's `.claude/skills` |

## Design against Copilot Cowork

It is the tightest host on every axis that matters, so a skill that fits it fits
everywhere:

- **20 companion files.** This is the cap that bites first, and it bites at
  packaging time — long after the design is set. A skill with a test suite, a
  fixture folder and three generators is already over.
- **10MB per skill, 1MB per file.** Generous until a skill bundles a font, a
  browser, or an inlined runtime.
- **No local device access.** Anything the skill needs must travel with it or
  live on the cloud drive. A skill that reads the user's home directory is not
  packageable here at all.
- **The vendor does not validate custom skills.** There is no gate but yours,
  which is the argument for Step 3 of the parent skill.

## The two verdicts worth copying

Measured on two real skills, September 2026:

**A document-authoring skill runs on all four, in two grades.** Full on Claude
Code, where its Node renderer inlines the runtime and the delivered file fetches
nothing. Degraded on the other three, where the agent hand-authors the output
from a bundled template and the result links its runtime from a CDN. The
degraded grade is not cosmetic — the reader needs the network the first time
they open the file. Say which grade a host gets, in the skill's own body.

**A skill with a real toolchain runs on one host.** A deck exporter shelling out
to python-pptx, Playwright and headless Chrome is a developer machine, not a
document sandbox. Two separate things must be true for a sandbox to run it — the
packages must install, and a browser binary must download — and an egress
allow-list clearly blocks the second. Packaged for Copilot Cowork it lands at 21
files against a cap of 21. Fitting exactly is a warning, not a pass.

**The dependency list is a choice, not a law.** A lighter exporter, or an export
to PDF, moves a skill into more hosts. That is a design decision available at
Step 2 and expensive after Step 4.

## What is claimed here, and how

Every limit above is read from vendor documentation retrieved on 4 September
2026, not observed in a run. Two verdicts rest on absence of documentation
rather than a stated limit: whether Node is present in Claude Cowork's VM, and
whether Copilot Cowork's execution step can install packages. Both are open.

- Anthropic. (2026). *Agent Skills*. Claude Platform Docs.
  https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
- Anthropic. (2026). *Claude Cowork architecture overview*. Anthropic Help Centre.
  https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview
- Anthropic. (2026). *Create and edit files with Claude*. Anthropic Help Centre.
  https://support.claude.com/en/articles/12111783-create-and-edit-files-with-claude
- GitHub. (2026). *Agent Skills*. awesome-copilot documentation.
  https://github.com/github/awesome-copilot/blob/main/docs/README.skills.md
- Microsoft. (2026, August 27). *Use Copilot Cowork*. Microsoft Learn.
  https://learn.microsoft.com/en-us/microsoft-365/copilot/cowork/use-cowork
- Microsoft. (2026). *Copilot Cowork common questions*. Microsoft Learn.
  https://learn.microsoft.com/en-us/microsoft-365/copilot/cowork/cowork-faq
