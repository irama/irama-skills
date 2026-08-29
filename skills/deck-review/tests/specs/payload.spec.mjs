/* The payload, the two chrome-free modes, and comment re-anchoring. */
import { test, expect } from '@playwright/test';
import { openDeck, goToSlide, selectOnSlide, writeComment, copyPayload,
         MINTED, RELABELLED, LEGACY } from './helpers.mjs';

test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

/** Every array in a version 3 payload that names a slide. */
const SLIDE_ARRAYS = ['comments', 'starredSlides', 'hiddenSlides', 'visibilityChanges',
                      'noteEdits', 'slideOrder'];

test('a minted deck emits a valid version 3 payload with slideId on every slide array', async ({ page }) => {
  await openDeck(page, MINTED);

  await goToSlide(page, 2);
  await selectOnSlide(page, 'the cards laid across it');
  await writeComment(page, 'Say which cards.');

  await goToSlide(page, 5);
  await page.locator('.dcx-bar [data-a="slide"]').click();
  await writeComment(page, 'This slide needs the check a reader can run.');

  await goToSlide(page, 3);
  await page.locator('body').press('s');
  await page.locator('.dcx-bar [data-a="hide"]').click();

  await page.locator('.dcx-bar [data-a="notes"]').click();
  await page.locator('.dcx-tray textarea').fill('Turn here, and let it land.');
  await page.locator('.dcx-tray [data-a="close"]').click();

  await page.locator('.dcx-bar [data-a="overview"]').click();
  await page.locator('.dcx-ovtile[data-slide="1"]').focus();
  await page.keyboard.press('Alt+ArrowRight');
  await page.locator('.dcx-ovhdr [data-a="close"]').click();

  const p = await copyPayload(page);

  expect(p.kind).toBe('deck-comments');
  expect(p.version).toBe(3);
  expect(p.slideCount).toBe(8);
  expect(p.deck.file).toBe('fixtures/deck-minted.html');
  expect(p.deck.source).toBe('fixtures/build_minted.py');
  expect(p.deck.buildHash).toBe('84c3ea6ae5e8');
  expect(typeof p.instruction).toBe('string');
  expect(new Date(p.capturedAt).toString()).not.toBe('Invalid Date');

  expect(p.openCount).toBe(2);
  expect(p.comments.map((c) => c.target).sort()).toEqual(['selection', 'slide']);
  expect(p.comments.find((c) => c.target === 'selection').quote).toBe('the cards laid across it');
  expect(p.orderChanged).toBe(true);
  expect(p.slideOrder).toHaveLength(8);
  expect(p.slideOrder[0]).toMatchObject({ position: 1, wasSlide: 2, slideId: 'the-board' });
  expect(p.slideOrder[1]).toMatchObject({ position: 2, wasSlide: 1, slideId: 'opening' });
  expect(p.starredSlides.map((s) => s.slideId)).toContain('the-pivot');
  expect(p.hiddenSlides.map((h) => h.slideId).sort()).toEqual(['costs', 'the-pivot']);
  expect(p.hiddenSlides.find((h) => h.slideId === 'costs').inSource).toBe(true);
  expect(p.hiddenSlides.find((h) => h.slideId === 'the-pivot').inSource).toBe(false);
  expect(p.visibilityChanges).toHaveLength(1);
  expect(p.visibilityChanges[0]).toMatchObject({ slideId: 'the-pivot', from: 'visible', to: 'hidden' });
  expect(p.noteEdits.map((n) => n.slideId)).toEqual(['the-pivot']);
  expect(p.noteEdits[0].note).toBe('Turn here, and let it land.');

  for (const key of SLIDE_ARRAYS) {
    for (const [i, row] of (p[key] || []).entries()) {
      expect(typeof row.slideId, `${key}[${i}] carries no slideId`).toBe('string');
      expect(row.slideId.length, `${key}[${i}] has an empty slideId`).toBeGreaterThan(0);
      expect(typeof row.slideLabel, `${key}[${i}] carries no slideLabel`).toBe('string');
    }
  }
});

test('Copy clears the unsent-changes mark, and only after the payload is on the clipboard', async ({ page }) => {
  await openDeck(page, MINTED);
  const badge = page.locator('.dcx-bar .dcx-count');
  await expect(badge).toHaveText('0');
  await expect(badge).toHaveClass(/zero/);

  await goToSlide(page, 2);
  await page.locator('body').press('s');
  await expect(badge).toHaveClass(/dirty/);
  await expect(badge).toHaveText('● 0');
  await expect(page.locator('.dcx-bar [data-a="list"]'))
    .toHaveAttribute('aria-label', /Unsent changes: .*star/);

  await copyPayload(page);
  await expect(badge).not.toHaveClass(/dirty/);
  await expect(badge).toHaveText('0');
});

test('Copy refuses when nothing has changed', async ({ page }) => {
  await openDeck(page, MINTED);
  await page.locator('.dcx-bar [data-a="copy"]').click();
  await expect(page.locator('.dcx-toast')).toHaveText('Nothing to copy yet');
});

test('a legacy deck with no minted ids still emits a valid payload, with slideId absent', async ({ page }) => {
  await openDeck(page, LEGACY);

  await goToSlide(page, 2);
  await selectOnSlide(page, 'the base it was measured against');
  await writeComment(page, 'Give the base.');
  await page.locator('body').press('s');
  await page.locator('.dcx-bar [data-a="hide"]').click();

  const p = await copyPayload(page);
  expect(p.kind).toBe('deck-comments');
  expect(p.version).toBe(3);
  expect(p.slideCount).toBe(4);
  expect(p.comments).toHaveLength(1);
  expect(p.comments[0].slide).toBe(2);
  expect(p.comments[0].slideLabel).toBe('What we found');
  expect(p.starredSlides).toHaveLength(1);
  expect(p.hiddenSlides).toHaveLength(1);

  for (const key of SLIDE_ARRAYS) {
    for (const [i, row] of (p[key] || []).entries()) {
      // The key is simply omitted. Never empty, and never the label wearing an
      // id's name, which would send the agent to the wrong slide.
      expect('slideId' in row && row.slideId !== undefined,
        `${key}[${i}] carries a slideId on an unminted deck`).toBe(false);
      expect(typeof row.slideLabel, `${key}[${i}] carries no slideLabel to fall back to`).toBe('string');
    }
  }
});

test('a comment survives the slide it is on being relabelled', async ({ page }) => {
  await openDeck(page, MINTED);
  await goToSlide(page, 5);
  await selectOnSlide(page, 'The provenance mark');
  await writeComment(page, 'Name the thing it stamps.');

  // The next build renames slide 5 from "The stamp" to "Confabulation stamp".
  // Same deck-file, so the same stored review, and the same minted id.
  await openDeck(page, RELABELLED);
  await expect(page.locator('.dcx-bar .dcx-count')).toHaveText(/1/);

  await page.locator('.dcx-bar [data-a="list"]').click();
  // .item also covers the unsent-changes and orphan rows, so name the comment.
  const item = page.locator('.dcx-panel .item:not(.dirtyrow):not(.orphanrow)').first();
  await expect(item, 'the comment orphaned when the heading was rewritten')
    .not.toContainText('ORPHANED');
  await expect(page.locator('.dcx-panel .orphanrow')).toHaveCount(0);
  // The record keeps the label it was WRITTEN about. The deck now says
  // "Confabulation stamp"; the comment still says what the reader saw.
  await expect(item.locator('.slide')).toHaveText('Slide 5 · The stamp');

  const p = await copyPayload(page);
  expect(p.comments).toHaveLength(1);
  expect(p.comments[0].slideId).toBe('the-stamp');
  expect(p.comments[0].slide).toBe(5);
  expect(p.orphanedComments || []).toHaveLength(0);
});

test('?export renders no review chrome at all', async ({ page }) => {
  await page.goto(`${MINTED}?export`);
  await page.waitForSelector('deck-stage > section[data-deck-active]');
  await expect(page.locator('.dcx')).toHaveCount(0);
  await expect(page.locator('.dcx-bar')).toHaveCount(0);
});

test('?audit renders no review chrome at all', async ({ page }) => {
  await page.goto(`${MINTED}?audit`);
  await page.waitForSelector('deck-stage > section[data-deck-active]');
  await expect(page.locator('.dcx')).toHaveCount(0);
});

test('presentation mode hides the bar, and Escape brings it back', async ({ page }) => {
  await openDeck(page, MINTED);
  await expect(page.locator('.dcx-bar')).toBeVisible();
  await page.locator('.dcx-bar [data-a="perform"]').click();
  await expect(page.locator('body')).toHaveClass(/dcx-performing/);
  await expect(page.locator('.dcx-bar')).toBeHidden();
  await expect(page.locator('.dcx-count')).toBeHidden();

  await page.locator('body').press('Escape');
  await expect(page.locator('body')).not.toHaveClass(/dcx-performing/);
  await expect(page.locator('.dcx-bar')).toBeVisible();
});

test('S does nothing while presenting', async ({ page }) => {
  await openDeck(page, MINTED);
  await page.locator('.dcx-bar [data-a="perform"]').click();
  await page.locator('body').press('s');
  await page.locator('body').press('Escape');
  await expect(page.locator('.dcx-bar [data-a="star"]')).toHaveAttribute('aria-pressed', 'false');
});
