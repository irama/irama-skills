---
name: demoman
description: Build a self-contained offline HTML page of copy-and-paste demo prompts — each with a title, target app, markdown instructions and a copyable prompt block, tickable, reorderable and editable in the browser with edits saved to localStorage. Use when the user is preparing a live demo, training session or workshop where they paste prompts into other apps, or says "demoman", "demo prompts", "prompt runsheet", "prompt cards", or invokes /demoman.
argument-hint: "The demo or session the prompts are for"
---

# Demoman — a demonstration manual

One HTML file, no build step, no network. The user opens it beside the app they
are demoing, works down the list, copies each prompt, and it ticks itself off.

## Build one

i) Copy `template.html` to the target path. Name it for the session
   (`tools/demo-prompts/<session>.html` or wherever the user asks).
ii) Replace the two placeholders:
    - `{{FILE_PATH}}` — the path, repo-relative, that the JSON export tells the agent to edit.
    - `{{DOC_KEY}}` — `demo-prompts:<title-slug>-<8 hex chars>`. **Generate fresh every
      time.** Two pages sharing a key overwrite each other's saved edits.
iii) Fill the `SEED` constant with the real prompts. Nothing else in the file changes.
iv) Hand back the full `file://` URL in a fenced code block.

```bash
python3 -c "import hashlib,time;print('demo-prompts:my-session-'+hashlib.sha1(str(time.time()).encode()).hexdigest()[:8])"
```

## The SEED shape

`items` is one flat ordered list. A `section` is an editable, draggable heading;
a `prompt` is a card. Ids must be unique and stable — the JSON export matches on them.

```js
const SEED = {
  title: "Demo prompts",
  items: [
    { type: "section", id: "sec-1", title: "First section" },
    { type: "prompt", id: "p-1",
      title: "What it does",          // shown as the card heading
      app: "Copilot",                 // badge; colour is hashed from this string
      instructions: "1. Step one\n2. Step two",   // markdown
      prompt: "The text to copy." }
  ]
};
```

`instructions` supports headings, ordered and unordered lists, tables, `**bold**`,
`*italic*`, `` `code` ``, links, quotes and rules. One blank line separates blocks;
every extra blank line renders as real space.

## What the page does

- Copy icon on a prompt copies it and ticks the card off. **Tick all** / **Untick all** resets.
- Prompts clamp to ~10 lines with a Show more / Show less pill, and only fade when truly cut off.
- Everything is editable inline; instructions open as raw markdown in a textarea.
- Drag the ⠿ grip to reorder sections and prompts.
- Theme cycles system → light → dark, remembered separately from the content.
- Renaming the page offers to **re-key** it, so a copied page stops sharing a
  storage slot with its original. The modal shows both keys with copy buttons.

## Reading edits back

The **⧉ JSON** button lights up as soon as the page holds edits the file doesn't, with a
tooltip saying to paste them into Claude Code — or into any modern chat tool (Copilot,
ChatGPT) with the HTML file attached, since the payload names the file and carries its own
instructions. The user clicks it and pastes the result back. It carries
only what differs from `SEED`: `title`, `changed` (matched by id, changed fields only),
`added`, `deleted`, `order`, and `docKey`.

Apply it to the `SEED` constant in the file named by `file`. If `docKey` differs from
`DOC_KEY` in the file, update `DOC_KEY` too. **Never rewrite the page's HTML, CSS or JS
from an edits payload** — only the data.
