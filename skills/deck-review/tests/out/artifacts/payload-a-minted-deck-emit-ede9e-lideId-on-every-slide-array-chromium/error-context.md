# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: payload.spec.mjs >> a minted deck emits a valid version 3 payload with slideId on every slide array
- Location: specs/payload.spec.mjs:12:1

# Error details

```
Error: expect(received).toBe(expected) // Object.is equality

Expected: 3
Received: 4
```

# Page snapshot

```yaml
- generic [ref=e1]:
  - generic [ref=e2]:
    - generic:
      - heading "The board" [level=1]
      - paragraph: Supply on one axis and demand on the other, with the cards laid across it.
    - generic:
      - heading "Opening" [level=1]
      - paragraph: The opening line of the deck, which a reader can select and comment on.
    - generic [ref=e3]:
      - heading "The pivot" [level=1] [ref=e4]
      - paragraph [ref=e5]: Where the argument turns, and the reason the rest of the deck follows.
    - generic:
      - heading "Evidence" [level=1]
      - paragraph: Three measurements, each with the date it was taken and the base it counts.
    - generic:
      - heading "The stamp" [level=1]
      - paragraph: The provenance mark, and what a reader can check with it.
    - generic:
      - heading "Risks" [level=1]
      - paragraph: What would have to be true for this to fail, and how we would see it early.
    - generic:
      - heading "Costs" [level=1]
      - paragraph: The build cost and the run cost, kept out of the standard delivery.
    - generic:
      - heading "Close" [level=1]
      - paragraph: The one decision this deck asks for.
  - generic [ref=e6]:
    - button "No slide comment on slide 3. Click to write one." [ref=e7] [cursor=pointer]: 💬 Slide comment
    - button "👁" [ref=e8] [cursor=pointer]
    - button "◆" [pressed] [ref=e9] [cursor=pointer]
    - button "📝 Notes" [ref=e10] [cursor=pointer]
    - button "Slide 3 is starred. Click, or press S, to remove the star." [pressed] [ref=e12] [cursor=pointer]: ★
    - button "🚫" [ref=e13] [cursor=pointer]
    - button "▦ Overview" [ref=e15] [cursor=pointer]
    - button "▶ Present" [ref=e16] [cursor=pointer]
    - button "2 open, 0 addressed" [ref=e18] [cursor=pointer]:
      - generic "2 open, 0 addressed" [ref=e19]: "2"
    - button "📋 Copy" [active] [ref=e20] [cursor=pointer]
  - generic [ref=e21]: HIDDEN
  - generic: Payload copied
```

# Test source

```ts
  1   | /* The payload, the two chrome-free modes, and comment re-anchoring. */
  2   | import { test, expect } from '@playwright/test';
  3   | import { openDeck, goToSlide, selectOnSlide, writeComment, copyPayload,
  4   |          MINTED, RELABELLED, LEGACY } from './helpers.mjs';
  5   | 
  6   | test.use({ permissions: ['clipboard-read', 'clipboard-write'] });
  7   | 
  8   | /** Every array in a version 3 payload that names a slide. */
  9   | const SLIDE_ARRAYS = ['comments', 'starredSlides', 'hiddenSlides', 'visibilityChanges',
  10  |                       'noteEdits', 'slideOrder'];
  11  | 
  12  | test('a minted deck emits a valid version 3 payload with slideId on every slide array', async ({ page }) => {
  13  |   await openDeck(page, MINTED);
  14  | 
  15  |   await goToSlide(page, 2);
  16  |   await selectOnSlide(page, 'the cards laid across it');
  17  |   await writeComment(page, 'Say which cards.');
  18  | 
  19  |   await goToSlide(page, 5);
  20  |   await page.locator('.dcx-bar [data-a="slide"]').click();
  21  |   await writeComment(page, 'This slide needs the check a reader can run.');
  22  | 
  23  |   await goToSlide(page, 3);
  24  |   await page.locator('body').press('s');
  25  |   await page.locator('.dcx-bar [data-a="hide"]').click();
  26  | 
  27  |   await page.locator('.dcx-bar [data-a="notes"]').click();
  28  |   await page.locator('.dcx-tray textarea').fill('Turn here, and let it land.');
  29  |   await page.locator('.dcx-tray [data-a="close"]').click();
  30  | 
  31  |   await page.locator('.dcx-bar [data-a="overview"]').click();
  32  |   await page.locator('.dcx-ovtile[data-slide="1"]').focus();
  33  |   await page.keyboard.press('Alt+ArrowRight');
  34  |   await page.locator('.dcx-ovhdr [data-a="close"]').click();
  35  | 
  36  |   const p = await copyPayload(page);
  37  | 
  38  |   expect(p.kind).toBe('deck-comments');
> 39  |   expect(p.version).toBe(3);
      |                     ^ Error: expect(received).toBe(expected) // Object.is equality
  40  |   expect(p.slideCount).toBe(8);
  41  |   expect(p.deck.file).toBe('fixtures/deck-minted.html');
  42  |   expect(p.deck.source).toBe('fixtures/build_minted.py');
  43  |   expect(p.deck.buildHash).toBe('84c3ea6ae5e8');
  44  |   expect(typeof p.instruction).toBe('string');
  45  |   expect(new Date(p.capturedAt).toString()).not.toBe('Invalid Date');
  46  | 
  47  |   expect(p.openCount).toBe(2);
  48  |   expect(p.comments.map((c) => c.target).sort()).toEqual(['selection', 'slide']);
  49  |   expect(p.comments.find((c) => c.target === 'selection').quote).toBe('the cards laid across it');
  50  |   expect(p.orderChanged).toBe(true);
  51  |   expect(p.slideOrder).toHaveLength(8);
  52  |   expect(p.slideOrder[0]).toMatchObject({ position: 1, wasSlide: 2, slideId: 'the-board' });
  53  |   expect(p.slideOrder[1]).toMatchObject({ position: 2, wasSlide: 1, slideId: 'opening' });
  54  |   expect(p.starredSlides.map((s) => s.slideId)).toContain('the-pivot');
  55  |   expect(p.hiddenSlides.map((h) => h.slideId).sort()).toEqual(['costs', 'the-pivot']);
  56  |   expect(p.hiddenSlides.find((h) => h.slideId === 'costs').inSource).toBe(true);
  57  |   expect(p.hiddenSlides.find((h) => h.slideId === 'the-pivot').inSource).toBe(false);
  58  |   expect(p.visibilityChanges).toHaveLength(1);
  59  |   expect(p.visibilityChanges[0]).toMatchObject({ slideId: 'the-pivot', from: 'visible', to: 'hidden' });
  60  |   expect(p.noteEdits.map((n) => n.slideId)).toEqual(['the-pivot']);
  61  |   expect(p.noteEdits[0].note).toBe('Turn here, and let it land.');
  62  | 
  63  |   for (const key of SLIDE_ARRAYS) {
  64  |     for (const [i, row] of (p[key] || []).entries()) {
  65  |       expect(typeof row.slideId, `${key}[${i}] carries no slideId`).toBe('string');
  66  |       expect(row.slideId.length, `${key}[${i}] has an empty slideId`).toBeGreaterThan(0);
  67  |       expect(typeof row.slideLabel, `${key}[${i}] carries no slideLabel`).toBe('string');
  68  |     }
  69  |   }
  70  | });
  71  | 
  72  | test('Copy clears the unsent-changes mark, and only after the payload is on the clipboard', async ({ page }) => {
  73  |   await openDeck(page, MINTED);
  74  |   const badge = page.locator('.dcx-bar .dcx-count');
  75  |   await expect(badge).toHaveText('0');
  76  |   await expect(badge).toHaveClass(/zero/);
  77  | 
  78  |   await goToSlide(page, 2);
  79  |   await page.locator('body').press('s');
  80  |   await expect(badge).toHaveClass(/dirty/);
  81  |   await expect(badge).toHaveText('● 0');
  82  |   await expect(page.locator('.dcx-bar [data-a="list"]'))
  83  |     .toHaveAttribute('aria-label', /Unsent changes: .*star/);
  84  | 
  85  |   await copyPayload(page);
  86  |   await expect(badge).not.toHaveClass(/dirty/);
  87  |   await expect(badge).toHaveText('0');
  88  | });
  89  | 
  90  | test('Copy refuses when nothing has changed', async ({ page }) => {
  91  |   await openDeck(page, MINTED);
  92  |   await page.locator('.dcx-bar [data-a="copy"]').click();
  93  |   await expect(page.locator('.dcx-toast')).toHaveText('Nothing to copy yet');
  94  | });
  95  | 
  96  | test('a legacy deck with no minted ids still emits a valid payload, with slideId absent', async ({ page }) => {
  97  |   await openDeck(page, LEGACY);
  98  | 
  99  |   await goToSlide(page, 2);
  100 |   await selectOnSlide(page, 'the base it was measured against');
  101 |   await writeComment(page, 'Give the base.');
  102 |   await page.locator('body').press('s');
  103 |   await page.locator('.dcx-bar [data-a="hide"]').click();
  104 | 
  105 |   const p = await copyPayload(page);
  106 |   expect(p.kind).toBe('deck-comments');
  107 |   expect(p.version).toBe(3);
  108 |   expect(p.slideCount).toBe(4);
  109 |   expect(p.comments).toHaveLength(1);
  110 |   expect(p.comments[0].slide).toBe(2);
  111 |   expect(p.comments[0].slideLabel).toBe('What we found');
  112 |   expect(p.starredSlides).toHaveLength(1);
  113 |   expect(p.hiddenSlides).toHaveLength(1);
  114 | 
  115 |   for (const key of SLIDE_ARRAYS) {
  116 |     for (const [i, row] of (p[key] || []).entries()) {
  117 |       // The key is simply omitted. Never empty, and never the label wearing an
  118 |       // id's name, which would send the agent to the wrong slide.
  119 |       expect('slideId' in row && row.slideId !== undefined,
  120 |         `${key}[${i}] carries a slideId on an unminted deck`).toBe(false);
  121 |       expect(typeof row.slideLabel, `${key}[${i}] carries no slideLabel to fall back to`).toBe('string');
  122 |     }
  123 |   }
  124 | });
  125 | 
  126 | test('a comment survives the slide it is on being relabelled', async ({ page }) => {
  127 |   await openDeck(page, MINTED);
  128 |   await goToSlide(page, 5);
  129 |   await selectOnSlide(page, 'The provenance mark');
  130 |   await writeComment(page, 'Name the thing it stamps.');
  131 | 
  132 |   // The next build renames slide 5 from "The stamp" to "Confabulation stamp".
  133 |   // Same deck-file, so the same stored review, and the same minted id.
  134 |   await openDeck(page, RELABELLED);
  135 |   await expect(page.locator('.dcx-bar .dcx-count')).toHaveText(/1/);
  136 | 
  137 |   await page.locator('.dcx-bar [data-a="list"]').click();
  138 |   // .item also covers the unsent-changes and orphan rows, so name the comment.
  139 |   const item = page.locator('.dcx-panel .item:not(.dirtyrow):not(.orphanrow)').first();
```