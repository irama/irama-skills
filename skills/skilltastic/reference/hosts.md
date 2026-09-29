# Hosts, one format

Read this when choosing which hosts a skill targets, packaging it for one of
them, or explaining why a skill will not run somewhere. This is the one host
reference for skilltastic. Do not start a second one.

**At run time, a skill trusts its own tool list over this file.** The tables
below say what vendors document, and the same host differs by plan, by tenant
and from month to month. A skill that needs a tool checks whether it can call
that tool now, and takes the first rung of its ladder that works (see "The
three ladders" below). The canonical wording for that check is
`assets/host-snippet.md` (`host-snippet.md` in a portable cut).

**The `SKILL.md` format is portable and the machine underneath is not.** The
hosts that load a skill folder read the front matter at startup, load the body
when the description matches, and open bundled files only when the body points
at them. What separates them is which runtimes exist, which files the agent can
see, and whether anything can reach the network.

**Custom skills do not sync between hosts.** The same folder has to be installed
in each one. "Portable" means the file works if you copy it, not that copying
happens for you. Support also differs by surface and by plan inside one vendor,
so name the surface, never only the vendor.

## Capabilities by host

Retrieved 29 September 2026 from vendor documentation. Each cell carries its
source key; the keys resolve in "Sources for the capabilities table" below.
**Yes** and **No** are what the vendor states. **Plan or tenant** means the
vendor says it depends on the plan, the licence or an admin setting. **Not
documented** means no vendor page retrieved that day confirms it either way;
it is not a "no".

| Host (surface) | Custom skills | Native image generation | Code execution | File creation and download | HTML or artifact preview | SVG in chat | Mermaid rendering | Web search |
|---|---|---|---|---|---|---|---|---|
| Claude Code | Yes, `~/.claude/skills` or a repo's `.claude/skills` [A7] | Not documented; no image tool listed [A8] | Yes, shell on your machine [A8] | Yes, writes files directly [A8] | Not documented [A8] | Not documented [A8] | Not documented [A8] | Yes, WebSearch tool [A8] |
| claude.ai | Yes on Free, Pro, Max, Team and Enterprise; needs code execution on [A1] | No; builds HTML and SVG visuals instead [A2] | Yes, sandbox, every plan [A5] | Yes, .docx, .xlsx, .pptx, .pdf, 30MB per file [A5] | Yes, artifacts on every plan [A3] | Yes, HTML and SVG visuals, beta on web and desktop [A2] | Not documented [A3] | Plan or tenant: individuals toggle it; a Team or Enterprise owner enables it first [A4] |
| Claude Cowork | Plan or tenant: Pro, Max and Team; Enterprise when an owner enables it [A1] [A6] | Not documented [A6] | Yes, isolated VM or cloud sandbox [A6] | Yes, reads and writes in connected folders [A6] | Yes, live artifacts [A6] | Not documented [A6] | Not documented [A6] | Plan or tenant: no network by default for Enterprise [A6] |
| ChatGPT | Plan or tenant: Business, Enterprise, Healthcare and Edu; off by default in the beta until a workspace owner enables it [O1] [O6] | Plan or tenant: every plan, limits set by plan [O5] | Yes, Python in data analysis [O2] | Yes, downloads from data analysis [O2] | Yes, canvas renders HTML and React [O3] | Not documented | Not documented | Yes, Free to Enterprise, and signed out [O4] |
| Microsoft 365 Copilot Chat | Not documented for plain chat; skills attach to a declarative agent (next row) [M1] [M5] | Plan or tenant: standard access subject to capacity, licence and tenant configuration [M3] [M5] | Not documented for plain chat [M5] | Not documented for plain chat [M5] | Not documented [M5] | Not documented [M5] | Not documented [M5] | Yes, web grounded; off by default in some government clouds [M5] |
| Copilot declarative agents | Plan or tenant: preview for Frontier Preview tenants only, not with Information Barriers; 8 skills per agent, 350 files, scripts with no network [M1] | Plan or tenant: licence and tenant configuration [M3] [M4] | Yes, code interpreter on all three licence models [M2] [M4] | Yes, through code interpreter, kept for the session only [M2] | Not documented [M4] | Not documented | Not documented | Yes, web search knowledge on all three licence models [M4] |
| Copilot Cowork | Yes, 50 skills, 20 companion files, 10MB per skill; not on mobile; admins can turn Cowork off [M6] [M7] | Yes, built-in image skill [M6] [M7] | Yes, scripts run as a background step [M6] | Yes, output folder and OneDrive [M6] | Yes, HTML renders in the preview pane [M6] | Yes, as an image file preview [M6] | Not documented [M6] | Not documented as a search tool; web tasks run in the local Edge browser [M7] |
| Gemini (app) | Plan or tenant: personal accounts aged 18 or over on mobile, Mac and web, `SKILL.md` folder or `.zip` upload; work and school accounts later [G1] [G2] | Yes, with age rules; some models need a Google AI plan [G3] | Not documented for the app [G6] | Not documented for the app [G6] | Yes, Canvas previews HTML and React [G4]; skills do not yet work with Canvas [G2] | Not documented | Not documented | Yes, links to web sources and a Google Search double-check [G5] |

Three readings of the table that matter when you design:

- **Four surfaces load a skill folder today, and each has conditions:**
  Claude Code, claude.ai, Claude Cowork and Copilot Cowork. claude.ai needs
  code execution switched on. Claude Cowork needs a Pro, Max or Team plan, or
  an Enterprise owner who enables it. Copilot Cowork does not run on mobile,
  and an admin can turn it off. On ChatGPT, Copilot
  declarative agents and Gemini, a skill is format-compatible but gated by plan,
  preview or account type. Say so; never claim a skill works on every host.
- **Image generation is the least portable capability.** Claude surfaces do not
  document it, and Microsoft makes it depend on licence and tenant. That is why
  the diagram ladder below never uses it.
- **SVG and Mermaid are mostly undocumented.** Treat both as "try, then fall
  back", which is what the ladders do.

## The three ladders

A skill that makes a diagram, an image or a file picks the first rung its own
tools support, and tells the user in one line which rung it took and why. A
format the user names wins over the ladder.

- **Diagram ladder**, for analytical graphics where labels and arrows must be
  exact: SVG (file or artifact), then a Mermaid block, then a text tree or
  table. Image generation is never used for a diagram.
- **Visual ladder**, for an illustrative metaphor only: the native image tool,
  then SVG, then a written spec plus a ready-to-paste image prompt. For a
  labelled diagram, switch to the diagram ladder.
- **File ladder**: an artifact or preview, then a downloadable file, then one
  code block the user saves.

The text form (tree or table) of any diagram is always produced as well, so the
take-away works in any document.

## Packaging limits of the four folder hosts

| Property | claude.ai chat | Claude Cowork | Copilot Cowork | Claude Code |
|---|---|---|---|---|
| May bundle scripts and resources | Yes | Yes | Yes — ≤20 companion files, 10MB per skill, 50 skills | Yes |
| Runs bundled scripts | Yes, in the code-execution sandbox | Yes, shell in a VM or cloud sandbox | Yes, as a background step | Yes, on your own machine |
| Runtimes | Python and JavaScript, a pre-installed set | Linux VM, package set not published | Not published | Whatever you have installed |
| Files it can see | Uploads and its own sandbox, 30MB per file | Folders you connect on the device | Cloud drive only, **never local files** | The whole filesystem |
| Network from the skill | On by default for individual plans, off by default for team plans | Egress through an allow-list proxy the sandbox cannot bypass | Not published for custom skills | Full, same as any program you run |
| Install path | Zip upload in Settings › Features, per user | Skill folder, uploaded or connected | A folder in the cloud drive's `Documents/Cowork/skills/` | `~/.claude/skills` or the repo's `.claude/skills` |

## Design against Copilot Cowork

It is the tightest of the four folder hosts on every axis that matters, so a
skill that fits it fits the packaging limits of the other three:

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

**A document-authoring skill runs on all four folder hosts, in two grades.**
Full on Claude Code, where its Node renderer inlines the runtime and the
delivered file fetches nothing. Degraded on the other three, where the agent
hand-authors the output from a bundled template and the result links its
runtime from a CDN. The degraded grade is not cosmetic — the reader needs the
network the first time they open the file. Say which grade a host gets, in the
skill's own body.

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

Every packaging limit above is read from vendor documentation retrieved on 4
September 2026, not observed in a run. Two verdicts rest on absence of
documentation rather than a stated limit: whether Node is present in Claude
Cowork's VM, and whether Copilot Cowork's execution step can install packages.
Both are open.

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

### Sources for the capabilities table

All retrieved 29 September 2026. The OpenAI Help Centre refuses automated
fetches, so the five entries marked "search index" were read from the vendor
page's indexed text rather than the live page; re-check them by hand before
relying on a cell.

- [A1] Anthropic. (2026). *Use skills in Claude*. Claude Help Centre. Retrieved September 29, 2026, from https://support.claude.com/en/articles/12512180-use-skills-in-claude
- [A2] Anthropic. (2026). *Can Claude produce images?* Claude Help Centre. Retrieved September 29, 2026, from https://support.claude.com/en/articles/9002504-can-claude-produce-images
- [A3] Anthropic. (2026). *What are artifacts and how do I use them?* Claude Help Centre. Retrieved September 29, 2026, from https://support.claude.com/en/articles/9487310-what-are-artifacts-and-how-do-i-use-them
- [A4] Anthropic. (2026). *Enable and use web search*. Claude Help Centre. Retrieved September 29, 2026, from https://support.claude.com/en/articles/10684626-enable-and-use-web-search
- [A5] Anthropic. (2026). *Create and edit files with Claude*. Claude Help Centre. Retrieved September 29, 2026, from https://support.claude.com/en/articles/12111783-create-and-edit-files-with-claude
- [A6] Anthropic. (2026). *Claude Cowork architecture overview*. Claude Help Centre. Retrieved September 29, 2026, from https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview
- [A7] Anthropic. (2026). *Extend Claude with skills*. Claude Code Docs. Retrieved September 29, 2026, from https://code.claude.com/docs/en/skills
- [A8] Anthropic. (2026). *Tools reference*. Claude Code Docs. Retrieved September 29, 2026, from https://code.claude.com/docs/en/tools-reference
- [G1] Google. (2026). *Create & manage skills for Gemini Apps*. Gemini Apps Help. Retrieved September 29, 2026, from https://support.google.com/gemini/answer/17094296
- [G2] Google. (2026). *About the transition from Gems to skills*. Gemini Apps Help. Retrieved September 29, 2026, from https://support.google.com/gemini/answer/18560919
- [G3] Google. (2026). *Generate & edit images with Gemini Apps*. Gemini Apps Help. Retrieved September 29, 2026, from https://support.google.com/gemini/answer/14286560
- [G4] Google. (2026). *Create docs, apps & more with Canvas*. Gemini Apps Help. Retrieved September 29, 2026, from https://support.google.com/gemini/answer/16047321
- [G5] Google. (2026). *View related sources & double-check responses from Gemini Apps*. Gemini Apps Help. Retrieved September 29, 2026, from https://support.google.com/gemini/answer/14143489
- [G6] Google. (2026). *Upload & analyze files in Gemini Apps*. Gemini Apps Help. Retrieved September 29, 2026, from https://support.google.com/gemini/answer/14903178
- [M1] Microsoft. (2026, September 3). *Custom skills in declarative agents (preview)*. Microsoft Learn. Retrieved September 29, 2026, from https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/declarative-agent-skills
- [M2] Microsoft. (2026, July 6). *Code interpreter capability for declarative agents for Microsoft 365 Copilot*. Microsoft Learn. Retrieved September 29, 2026, from https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/code-interpreter
- [M3] Microsoft. (2026, July 6). *Image generator capability for declarative agents for Microsoft 365 Copilot*. Microsoft Learn. Retrieved September 29, 2026, from https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/image-generator
- [M4] Microsoft. (2026, July 9). *Set up your development environment to extend Microsoft 365 Copilot*. Microsoft Learn. Retrieved September 29, 2026, from https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/prerequisites
- [M5] Microsoft. (2026, September 9). *Overview of Microsoft Copilot Chat*. Microsoft Learn. Retrieved September 29, 2026, from https://learn.microsoft.com/en-us/copilot/overview
- [M6] Microsoft. (2026, September 14). *Use Copilot Cowork*. Microsoft Learn. Retrieved September 29, 2026, from https://learn.microsoft.com/en-us/microsoft-365/copilot/cowork/use-cowork
- [M7] Microsoft. (2026, September 21). *Copilot Cowork common questions*. Microsoft Learn. Retrieved September 29, 2026, from https://learn.microsoft.com/en-us/microsoft-365/copilot/cowork/cowork-faq
- [O1] OpenAI. (2026). *Skills in ChatGPT*. OpenAI Help Centre (search index). Retrieved September 29, 2026, from https://help.openai.com/en/articles/20001066-skills-in-chatgpt
- [O2] OpenAI. (2026). *Data analysis with ChatGPT*. OpenAI Help Centre (search index). Retrieved September 29, 2026, from https://help.openai.com/en/articles/8437071-data-analysis-with-chatgpt
- [O3] OpenAI. (2026). *What is the canvas feature in ChatGPT and how do I use it?* OpenAI Help Centre (search index). Retrieved September 29, 2026, from https://help.openai.com/en/articles/9930697
- [O4] OpenAI. (2026). *Searching the web with ChatGPT*. OpenAI Help Centre (search index). Retrieved September 29, 2026, from https://help.openai.com/en/articles/9237897-searching-the-web-with-chatgpt
- [O5] OpenAI. (2026). *ChatGPT free tier FAQ*. OpenAI Help Centre (search index). Retrieved September 29, 2026, from https://help.openai.com/en/articles/9275245-chatgpt-free-tier-faq
- [O6] OpenAI. (2026). *Skills*. OpenAI Academy. Retrieved September 29, 2026, from https://academy.openai.com/public/clubs/work-users-ynjqu/resources/skills
