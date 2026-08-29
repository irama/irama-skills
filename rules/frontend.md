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

**Every clickable element shows `cursor: pointer` on hover** — buttons,
`[role="button"]`, links, labels tied to a control, `summary`, custom clickable
divs. Disabled controls keep the default arrow (`cursor: not-allowed` where it
clarifies). Tailwind preflight resets `button` to the arrow, so this is NOT
automatic. Add one global base rule per project (fall back to per-element
`cursor-pointer` only if a global rule is impossible):

    @layer base {
      button:not(:disabled):not([aria-disabled='true']),
      [role='button']:not([aria-disabled='true']),
      a[href], label[for], summary,
      [tabindex]:not([tabindex='-1']):not([aria-disabled='true']) {
        cursor: pointer;
      }
    }

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
