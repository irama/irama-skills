---
name: html-brief
description: Build interactive HTML briefs/question files the user answers in the browser — tick-off questions, inline locally-persisted answers, selection comments, one-click "Copy responses" / "Download responses" JSON to paste back to Claude. Use whenever delivering an HTML file that asks the user questions or presents reviewable findings/sections — question files, review briefs, AND any plan / proposal / design doc that contains questions or needs sign-off. If the file poses even one question the user is meant to answer, it is a brief.
---

# html-brief — interactive question/review HTML files

## When this applies (read first — the common miss)

**Any HTML file where the user is meant to answer something is a brief** — not
just files literally named "questions". This explicitly includes a **plan,
proposal, or design report that ends with open questions / decisions to make**.
Delivering such a plan as plain HTML with an "Open questions" section and no way
to answer it inline is the exact failure this skill exists to prevent. If your
output has a question in it, it goes through this skill — full stop. (A pure
read-only report with zero questions may stay plain HTML under the "visual HTML
report" rule; the moment it asks anything, it's a brief.)

## One document — never split a plan from its questions

A plan/proposal/design doc and its questions are **the same file**. Do NOT
produce a visual report plus a separate "questions" brief — that's two files the
user has to reconcile, and the report half has no way to answer anything. Build
the whole plan AS one brief: the visual content (cards, tables, diagrams) as
free markup or `section.brief-section` blocks, and each question as an inline
`section.q` in the same document. One file, one `data-brief-id`, one delivered
`file://` URL. Rich custom styling is fine — add a `<style>` block that reuses
brief.css's CSS variables (`--bg --fg --card --line --accent --muted …`) so the
visual extras stay theme-aware (light/dark/system) and cohesive with the brief
chrome, instead of a bespoke dark-only palette.

**House style: no box around a section.** `section.brief-section` and `section.q`
render as a heading with a hairline rule under it, on the page background — no
card, no border, no shadow. A card around every block turns a brief into a stack
of tiles and buries the reading order. Boxes are reserved for things the reader
acts on or reads as data: `details.example`, tables, `pre`, the answer textarea.
Do not add a border, background or radius back onto a section in a custom
`<style>` block. Prose is serif, UI chrome is sans; keep that split in any
extras you add.

## Hard requirements — every brief MUST render all four (verify before delivering)

1. **Numbered questions** — each question is `<section class="q" data-q="Qn">`
   with a visible `<span class="qid">Qn</span>` in its `<h2>`, numbered `Q1, Q2…`
   so the user can answer by number in chat.
2. **A response textarea under every question** — the runtime auto-injects one
   into each `section.q`; your job is to make sure each question is a real
   `section.q` (not a bare `<h2>`), so it gets one.
3. **Selection-comment system** — provided by the runtime; requires `brief.js`
   loaded and `<main>` present. Never omit the script.
4. **Copy + download icon buttons** — one combo control in the runtime top bar;
   require `brief.js` + `data-brief-id` on `<body>`.
5. **A References section with numbered footnotes** — whenever the brief rests on
   sources outside itself (documents, videos, transcripts, papers, web pages, other
   repo files). See the next section; it is not optional and not a nice-to-have.

Self-check before sending: open the file, confirm you can see numbered questions,
a "Your answer" box under each, the comments / width / theme / copy+download icons
top-right, and — if the brief cites anything — footnote markers that jump to a References section carrying
the quoted passages. If any is missing, you didn't build it as a brief — fix it.

## References and footnotes — every sourced claim is traceable

A brief that asserts things the reader can't verify is an opinion piece. If the
brief draws on ANY source outside itself, it carries a References section and
numbered footnotes. Non-negotiable parts:

- **APA 7 entry, with the URL.** Hanging indent is handled by `.apa`. Formats:
  - Video: `Author, A. [Channel Name]. (2026, July 25). *Title of video* [Video]. YouTube. https://…`
  - Web page: `Author, A. (2026, July 25). *Title of page*. Site Name. https://…`
  - No date → `(n.d.)` plus `Retrieved July 25, 2026, from https://…` — never invent
    a publication date to make the entry look complete.
  - Internal/unpublished source (a repo file, a DB row, a transcript with no public
    URL) → cite it as such: `Internal corpus. (2026, July 25). *videos.transcript*
    [Database record]. Row id …` and say so in an `.apa-note`.
- **Quoted passages that prove the claim**, inside the reference entry. Verbatim,
  in `<blockquote class="pull">`, each with its own `id` so a footnote can point at
  the exact quote rather than the whole source. Attribute with a `<span class="qref">`
  carrying the timestamp / page / cell / line. If you cannot quote a passage that
  supports a claim, the claim is your inference — label it as such in the body
  rather than footnoting it.
- **Numbered footnote markers in the body**, at the end of the sentence or table
  cell they support: `…half of Fable 5<sup class="fn"><a href="#ref1-q1">1</a></sup>`.
  Number references `1…n` in first-citation order. A footnote may be cited many
  times; point repeated citations at the most relevant quote in that reference.
- **The runtime handles the jump**: it reveals collapsed `<details>` and ticked-off
  sections before scrolling, highlights the target, and adds a `↩` back-link on each
  reference to its first citation. Don't hand-roll any of that.

Markup:

    <p>Opus 5 is priced at half of Fable 5<sup class="fn"><a href="#ref1-q1">1</a></sup>.</p>

    <section class="brief-section" data-sec="references">
      <div class="sec-head">
        <label class="tick"><input type="checkbox" aria-label="Mark section read"></label>
        <h2>References</h2>
      </div>
      <div class="sec-body">
        <ol class="reflist">
          <li id="ref1">
            <span class="apa">Simmons, P. (n.d.). <i>Opus 5: No-hype full review &amp; testing</i>
              [Video]. YouTube. Retrieved July 25, 2026, from
              <a href="https://www.youtube.com/watch?v=…">https://www.youtube.com/watch?v=…</a></span>
            <blockquote class="pull" id="ref1-q1">"$5 per million input and $25 per million output.
              Whereas Fable 5 is $10 per million input and $50 per million output."
              <span class="qref">Transcript, benchmark walkthrough</span></blockquote>
          </li>
        </ol>
      </div>
    </section>

**Say how many sources the brief rests on, and where the gaps are.** If the user
expected five sources and you found three, state that in the brief — a silently
incomplete evidence base is worse than a stated one.

## How to build one

Any HTML file that asks the user questions (or presents sections to review) MUST
be built from `assets/brief-template.html` in this skill directory. All
interactivity lives in the reusable drop-in runtime — **never regenerate that
logic inline**:

- `cp ~/.claude/skills/html-brief/assets/brief.css ~/.claude/skills/html-brief/assets/brief.js <output-dir>/`
  (copy alongside so the brief folder is portable; overwrite freely — newer
  skill assets are always backwards compatible with stored state).
- Author ONLY content: fill `{{TITLE}}`, `{{BRIEF_ID}}` (stable slug;
  localStorage key — keep identical across regenerations so saved answers
  survive), and **replace the two live SAMPLE sections** in the template's
  `<main>` with your real sections/questions (delete the `<!-- SAMPLE -->`
  markers). The template ships one worked `section.brief-section` + one
  numbered `section.q` so a generated file renders all four requirements
  immediately — never strip them down to an empty `<main>`. The runtime
  self-initializes and injects the top bar / progress / copy + download buttons / answer
  textareas / toast itself.
- Integration into any pre-existing HTML page = the same two tags:
  `<link rel="stylesheet" href="brief.css">` + `<script src="brief.js"></script>`
  plus `data-brief-id` on `<body>`.

Deliver the result per the global rule: full `file:///…` URL in a fenced code
block.

## End-of-phase brief — required section order

A brief closing a work phase (see global CLAUDE.md § How I work) uses these
sections, in this order. Keep it scannable — the user is assessing, not reading
a paper.

1. **Verdict** — one paragraph, plain language, honest answer first. "Partially"
   and "no" are acceptable answers.
2. **Delivered** — what was built, where it lives, what it does. Link
   everything; embed players/previews so it can be assessed without leaving the
   page.
3. **Evidence** — numbers before and after, with the noise floor stated so a
   real gain is distinguishable from variance.
4. **Decisions you made** — every judgement call taken without asking, and why.
   The audit trail; the most closely read section.
5. **What didn't work** — failed attempts, dead ends, things that came out
   worse. A brief with no failures is hiding something.
6. **My config steps** — numbered, exact, each with why you couldn't do it.
   "None" is a good answer.
7. **Open recommendations** — decisions awaiting the user's call.
8. **Review** — one `section.q` per aspect the user would have an opinion on,
   named specifically (not "the UI"), each with its OK / Needs work tick and
   answer box.
9. **Next phase readiness** — what's unblocked, what's still waiting.

## Definitions block — put the vocabulary at the top

**When a brief turns on words the reader and the writer may use differently, open with a Terms
block.** Contested, ambiguous or newly-coined words are the commonest reason a brief gets answered
at cross purposes, and the fix is cheap: say what each word means *here*, before anything rests on
it. Borrowed from the SOURCED definitions block, so a brief and a position paper teach one layout.

**Use it when** the brief coins a term, uses a word two parties define differently, or asks a
question whose answer depends on which sense of a word is meant. **Skip it** for a brief with no
such words — an empty Definitions block is worse than none.

Two halves, in this order, inside one `section.brief-section`:

    <section class="brief-section" data-sec="definitions">
      <div class="sec-head">
        <label class="tick"><input type="checkbox" aria-label="Mark section read"></label>
        <h2>Definitions</h2>
      </div>
      <div class="sec-body">

        <p class="defs-h">Not used here</p>
        <div class="defs-out">
          <div class="term"><s>Decline</s> <span class="to">→</span> <b>depreciation</b> · <b>displacement</b>
            <span class="why">used for two things that move on different clocks</span></div>
        </div>

        <p class="defs-h">Used here</p>
        <div class="defs-in">
          <div class="term">
            <div class="fam">needs</div>
            <h4>Risk</h4>
            <ul>
              <li><span class="k">In this brief</span> the exposure created by something that might go wrong</li>
              <li><span class="k">Needs</span> a <b>likelihood</b> and an <b>impact</b> — neither is a kind of risk</li>
            </ul>
            <div class="foot">Bears on Q3 · Q7</div>
          </div>
        </div>

      </div>
    </section>

- **`defs-out` is what the brief sets aside.** One line each: the word struck through, the word
  used instead in bold, and a short `why`. Never a paragraph — if it needs one, it belongs in
  `defs-in` as a term the brief does use.
- **`defs-in` is what the brief uses.** The `fam` tag names the relation and is optional; the
  SOURCED families are `split`, `needs`, `disambiguate`, `gap`, `rename`, `normative`.
- **`foot` says which questions the term bears on**, so a reader can see why the word was worth
  defining. Drop it rather than leave it vague.
- **Never tell the reader their usage is wrong.** The block says what the words mean *in this
  brief*. A definition good enough to borrow travels; an instruction seeds resistance.

Pure CSS — the runtime does nothing with it, so the block ticks off and collapses like any other
section.

## Question-writing rules (as important as the widgets)

- **Every question is answerable from its own text — never a bare id.** Name the study
  (author, year, what it measured, its n), the number at stake, the person or thing, and what
  changes if the answer is no. "Confirm RT-02" or "E7-007/010/011/018 were struck" is not a
  question, it is a lookup the reader has to do for you. Ids go in small print at the end for
  traceability. Test: could the reader answer it on a phone without opening another file?
  (2026-08-26: a sixteen-question brief phrased as claim ids and red-team ids got two answers
  and the reply "no context, just machine-optimised IDs". Fourteen decisions lost to format.)
- **Lead with the ask in plain English, assumption-first.** The `<h2>` is the
  complete question a non-technical reader can answer at a glance:
  "Confirm: M=No on a purchase row means second-hand purchase, GST claimed
  under Div 66 when sold — and what does X mean?" — never a topic label like
  "GST flag semantics".
- First element of the body is the `.assume` block: **My assumption:** … /
  **If wrong:** what changes. Then 1–2 sentences on the confusion point found.
  Then concrete options (a/b/c) where choices are enumerable.
- Evidence goes under a `<p class="ex-label">Examples</p>` label, each example
  in `<details class="example">`, **collapsed by default**. The `<summary>` is a
  one-line human summary that never collapses: example number, item/name, the
  discriminating values, cell ref — e.g.
  `E1 Digga broom (PSS0100) — M=Yes — X=X  BAS 2026_4!A7:AF10`. Full verbatim
  table inside `.tblwrap`.
- **Table cells wrap; they never truncate.** brief.css wraps every `th`/`td` by
  default — never add `text-overflow: ellipsis`, `overflow: hidden`, or a
  `max-width` that clips a cell in your own `<style>` block. A clipped cell hides
  content the reader has no way to recover, and re-rendering the file to read one
  cell is not an acceptable workaround. Verbatim data tables inside `.tblwrap`
  keep single-line rows (readable via that wrapper's horizontal scroll) — add
  `class="wrap"` to any long-prose cell there to wrap it instead. `class="num"`
  right-aligns numerics, `class="nowrap"` pins a short cell to one line.
- **Large tables: pinned + highlighted.** `.tblwrap` scrolls both axes
  (65vh cap) with the header row AND first column pinned automatically — put
  the identifying value (row no. / code / name) in the FIRST column; add class
  `nopin` to `.tblwrap` only if the first column isn't an identifier. When the
  reader must focus on specific rows/columns/cells, highlight them with
  `hl-focus` (the thing to look at), `hl-warn` (the defect/contradiction),
  `hl-info` (supporting context) on `tr`/`td`/`th` (column = class on each td),
  and put a `.legend` directly above the table naming what each colour means
  in THIS table. A cell-level highlight always overrides its row's highlight
  (e.g. `hl-warn` cell inside an `hl-focus` row renders warn) — rely on it: `<div class="legend"><span class="chip hl-warn"></span>blank
  status cell …</div>`. Never highlight without a legend; never more than
  three colours per table.
- Number every question `Q1…` (`data-q`) and every example `E1…`
  (`<span class="dp">En</span>`) — E-numbers globally unique across the whole
  brief (never restart per question, never bracket-style `[1]`) so the user can
  answer by number in chat as an alternative to the JSON.

## What the template runtime already provides (do not reimplement)

- Tick-off per question AND per non-question section → collapses it (header
  stays, toggle back anytime); progress counter in the sticky top bar.
- Answer `<textarea class="answer">` under each question — **auto-injected by the
  runtime** into every `section.q` that doesn't already have one, so you never have
  to add it (add one manually only to control its exact placement). Persisted to
  localStorage as the user types.
- **Copy icon on every code block** → the runtime injects a top-right copy
  button into every `<pre>` (copies its `<code>`/text content, ✓ + toast on
  success). Just write plain `<pre><code>…</code></pre>` — never hand-roll a
  copy button.
- **Copy + download combo button** → JSON of `{id, question, resolved, answer}`
  pairs plus all selection comments, all drafts and all note fields. The download
  half writes `<brief-id>-responses-<YYYY-MM-DD>.json`, for a brief read offline or
  answers worth keeping as a file. Both are icon-only with hover tooltips.
- **Comments drawer** (speech-bubble icon, or press `C`) → every comment and every
  unsaved draft in one scrollable list, with Show / Edit / Delete per row and
  Resume / Discard per draft. A comment whose highlight could not be restored is
  listed with a **not highlighted** badge rather than disappearing — the drawer is
  what makes a lost highlight cosmetic instead of a lost thought.
- **Draft rescue** — text typed into a comment popup is persisted on every
  keystroke. Clicking away, pressing Escape, or reloading keeps it as a draft in the
  drawer and in the exported JSON under `drafts`. Only the explicit **Discard**
  button throws it away.
- **Keyboard in the comment popup** — `Cmd/Ctrl+Enter` saves, `Escape` closes and
  keeps the draft.
- **Tooltips carry their shortcut.** Every top-bar control renders a CSS tooltip
  from `data-tip` naming what it does and its key (`Copy responses JSON · ⌘C`).
  Never use the `title` attribute — it is slow, unstyleable and hides the shortcut.
- **Comment anchoring survives element boundaries.** Selections flatten to a
  whitespace-normalised string with an index map back into the text nodes, so a quote
  crossing a `<strong>` or spanning two paragraphs anchors as one comment and
  re-anchors on reload. The occurrence index is stored, so a repeated phrase
  re-anchors onto the copy that was actually selected.
- **Per-item note fields** — put `<textarea data-note="unique-key"
  data-note-label="human label">` anywhere (under an audio sample, a mockup, a
  table row) and the runtime persists it to localStorage and exports it under
  `notes: [{id, label, note}]`. Use these when the reader needs to jot against
  many items without one question per item. **Cmd/Ctrl-C with nothing selected (and focus
  outside a field) copies the same JSON.**
- Select any text → popover with a comment textarea; saved comments render as
  `<mark>` highlights, click to edit/delete; re-anchored on reload by
  whitespace-insensitive text match; unanchorable ones still survive in the JSON
  (`{selected_text, near_question, comment}`).
- **Selecting text still copies normally.** The popover deliberately does not
  focus its textarea on a fresh selection (focusing collapses the selection and
  would break Cmd-C), so the user can copy the selection, use the popover's
  "Copy text" button, or click into the box to comment. Never add an autofocus
  or a `removeAllRanges()` to that path. Escape closes the popover.
- Table cells wrap and never truncate (see the question-writing rules above).
- Top-bar icon toggles: theme switcher (system → light → dark, default system)
  and fixed-width vs full-width; both persisted browser-wide (`briefUI` key).
- Progress reads "n/N questions resolved" and **is itself a jump-link to the next
  unresolved question** (advances as each is resolved; becomes plain text once all
  are) — so a long brief never has to be scrolled to find what's outstanding.
  **Resolved = an answer has been typed OR the question has been ticked** — typing
  an answer *is* resolving it, and the counter updates live as you type. The tick
  remains meaningful on its own: it's how a question is resolved by accepting the
  stated assumption without typing anything. Light + dark theme, print-safe,
  `cursor: pointer` affordances, no external network assets.

## Receiving answers back

The user pastes the JSON into chat. Each answer carries `resolved` (answered OR
ticked — matches the on-screen counter), `ticked` (the checkbox alone), and
`answer`. Treat `ticked: true` with an empty `answer` as "assumption confirmed as
stated"; a non-empty `answer` is the reply regardless of `ticked`. Do **not** read
`resolved: false` as "unanswered" when `answer` is non-empty — that combination
can only come from a brief generated before this contract, and the answer still
stands. Comments are keyed by `selected_text` +
`near_question` — locate the passage before acting on the comment. A comment with
`anchored: false` lost its highlight and was recovered from the drawer; treat it
exactly like any other. Entries under `drafts` are text the reader typed but never
saved — read them, but confirm before acting, since they may be abandoned thoughts. After
processing, update whatever register/doc the questions came from and, if
questions remain, regenerate the SAME brief file (same `{{BRIEF_ID}}`, same
path) with resolved questions removed or marked, so their saved state stays
meaningful.

## Template changes

If a brief needs a genuinely new interaction, extend
`assets/brief-template.html` here (keep it dependency-free and backwards
compatible with stored state) — improvements then benefit every future brief.

## Verifying template changes

`assets/smoke-test.mjs` drives a generated test page with Playwright (ticks,
persistence, comment popover, JSON export). Run it after any runtime edit:
build a minimal page from the template into a temp dir **named `test.html`**,
alongside copies of `brief.css`/`brief.js`, then `node smoke-test.mjs <dir>`.
Playwright resolves from the *script's* location, so copy `smoke-test.mjs` into
a repo that has playwright installed and run it from there. All booleans true +
`errors: []` = pass.
