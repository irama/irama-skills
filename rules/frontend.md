---
paths:
  - "**/*.tsx"
  - "**/*.jsx"
  - "**/*.vue"
  - "**/*.svelte"
  - "**/*.css"
  - "**/*.scss"
  - "**/*.astro"
  - "**/components/**/*.{ts,js}"
  - "**/tailwind.config.{ts,js,mjs,cjs}"
---

# Frontend core rules

These are core rules, not suggestions. They load whenever a frontend file is
read, and are absent from context otherwise — see `~/.claude/CLAUDE.md`
§ Frontend rules. **If you are authoring a new UI surface without having read an
existing one, read this file first**: a rule that never loaded is not a rule you
were exempt from.

## Cursor affordance

**The cursor says what a click will do.** Pick from this table, and nothing else:

| Cursor | Where |
|---|---|
| `pointer` (finger) | Anything you click: buttons, `[role="button"]`, links, labels tied to a control, `summary`, `select`, custom clickable elements |
| `text` (I-beam) | Anywhere you type: text inputs, `textarea`, rich-text editors (`[contenteditable]`) |
| `help` (question mark) | Text that shows a hint or definition on hover: `abbr[title]`, `[data-hint]` |
| `not-allowed` | A disabled control, only where the reason is not obvious |
| `default` (arrow) | Everything else, including disabled controls, plain text and boxes |

Tailwind preflight resets `button` to the arrow, so none of this is automatic. Add one global base
rule per project, and fall back to per-element classes only if a global rule is impossible. Wrap
each group in `:where()`: it keeps the rules at zero specificity, so the text rule (written after)
wins on an element that matches both. A focusable rich-text editor carries `tabindex`, so without
`:where()` the pointer rule beats the text rule and the editor shows a finger.

    @layer base {
      :where(button:not(:disabled):not([aria-disabled='true']),
        [role='button']:not([aria-disabled='true']),
        a[href], label[for], summary, select:not(:disabled),
        [tabindex]:not([tabindex='-1']):not([aria-disabled='true'])) {
        cursor: pointer;
      }
      :where(input:not([type='checkbox'], [type='radio'], [type='button'], [type='submit'],
          [type='reset'], [type='range'], [type='color'], [type='file'], [type='hidden']):not(:disabled),
        textarea:not(:disabled), [contenteditable='true'], [contenteditable='']) {
        cursor: text;
      }
      :where(abbr[title], [data-hint]) {
        cursor: help;
      }
    }

**Check it in the browser before calling a UI change done:** hover each new field, button and
hint. A field that shows a finger is a defect.

## Tooltips

**Never the `title` attribute** — always a real element via the project's shared
tooltip primitive (if the project has the `tooltip` skill, use it; otherwise
build/reuse one primitive, don't sprinkle `title=`). Every tooltip must:

- Show on hover AND keyboard focus; `aria-hidden` on the bubble, trigger keeps
  its own `aria-label` (no double-read).
- Fit its text — `nowrap` for short labels, sensible `max-width` + wrap for
  long. Never truncate or clip mid-word.
- Never clip — not by viewport, not by an `overflow:hidden`/scroll ancestor. Use
  collision-aware placement (flip/shift to the open side) or portal to `body`.
  Manual per-instance placement is a last resort — it's fragile (caused the
  Labels-button clipped-tip bug).

## Admin-visible error detail

**When building app error handling: generic message for normal users, full
detail for admins.** If the signed-in user is an admin (the app's own admin
flag, e.g. `is_platform_admin`), every user-facing error surface additionally
renders an expandable section (`<details>` or equivalent) containing the full
underlying error as pretty-printed JSON (message, code, hint, stack where
available, plus request context), with a **copy button** that copies that JSON —
so the admin can paste it straight back to Claude for troubleshooting. Never
show internals to non-admins; never swallow the detail before it reaches the
admin path (thread the raw error through, don't pre-flatten to "Unexpected
error").

## Designing a new look and feel

**Before inventing a visual language for a new app, surface or redesign, pull a
reference and pick a tool. Do not freehand it.**

- **Reference library: [Refero Styles](https://styles.refero.design/).** Design
  systems extracted from 2,000+ real product sites (colour, type, spacing,
  components), published as `DESIGN.md` files built to be read by an AI coding
  tool. Browse for a style close to the target feel, take the `DESIGN.md`, and
  adapt it into the project's own tokens. Real products beat a palette invented
  on the spot, which is the usual reason generated UI looks generic.
- **`/impeccable`** is the design and critique skill: use it for the whole loop,
  from information architecture and visual hierarchy through to polish, motion
  and accessibility. It is the default for any non-trivial UI surface.
- **Claude Design** (the `claude-design` MCP server) is the other half: it holds
  named design systems (`list_design_systems`, `read_design_skill`), renders a
  live preview (`render_preview`) and carries review comments. Use it when the
  work is a new look and feel, a multi-screen layout, or anything a person will
  comment on before it is built.
- **`/frontend-design:frontend-design`** is the plugin skill for general frontend
  design work, and it is a versioned plugin cache, so it cannot be patched with
  project rules. Bring the references above to it, rather than expecting it to
  know them.

Both `/impeccable` and Claude Design are installed and available. Complex UI, a
new look and feel, or a new layout means using one of the two, never neither.

## Axis and ruler labels adapt to the space

A timeline, ruler or chart axis picks its tick step from the width it actually has, never a fixed
interval. Measure the element (a ResizeObserver), then take the first "nice" step (1, 2, 5, 10, 15,
30, 60 … seconds, or the unit's equivalent) that leaves at least about 56 px between labels.
Format time as m:ss. A fixed two-second ruler on a three-minute film printed labels on top of each
other, and a "0:" prefix turned 100 s into "0:100".
