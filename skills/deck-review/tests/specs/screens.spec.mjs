/* Screenshots, plus the few visual faults that can be asserted.

   Three of the faults found by driving this runtime were only visible in a
   picture: an emoji rendering as a brown blob, the deck ghosting through the
   overview, and tiles scrolling into a dead gap. Assertions did not catch any
   of them. So this file captures the states where that class of fault lives,
   into out/screens/, and README.md says what to look for. */
import { test, expect } from '@playwright/test';
import { openDeck, goToSlide, selectOnSlide, shot } from './helpers.mjs';

const openOverview = (page) => page.locator('.dcx-bar [data-a="overview"]').click();

test('the bar, plain and lit', async ({ page }) => {
  await openDeck(page);
  await shot(page, 'bar-plain');
  await goToSlide(page, 2);
  await page.locator('body').press('s');
  await page.locator('.dcx-bar [data-a="slide"]').click();
  await page.locator('.dcx-pop textarea').fill('A slide comment, so the button lights.');
  await page.locator('.dcx-pop [data-a="save"]').click();
  await expect(page.locator('.dcx-bar [data-a="slide"]')).toHaveClass(/on/);
  await shot(page, 'bar-lit');
});

test('the selection popover', async ({ page }) => {
  await openDeck(page);
  await goToSlide(page, 3);
  await selectOnSlide(page, 'Where the argument turns');
  await shot(page, 'popover-selection');
});

test('the overview covers the deck, and the grid scrolls to its end', async ({ page }) => {
  await openDeck(page);
  await openOverview(page);
  await expect(page.locator('.dcx-ov')).toBeVisible();

  // The deck must not ghost through the overlay. Colour alone is not asserted,
  // but a transparent backdrop is, because that is what ghosting looks like.
  const alpha = await page.locator('.dcx-ov').evaluate((n) => {
    const bg = getComputedStyle(n).backgroundColor;
    const m = bg.match(/rgba?\(([^)]+)\)/);
    const parts = m ? m[1].split(',').map(Number) : [];
    return parts.length === 4 ? parts[3] : 1;
  });
  expect(alpha, 'the deck can ghost through the overview backdrop').toBeGreaterThanOrEqual(0.95);
  await shot(page, 'overview-grid-top');

  // Scroll to the end. The last tile must land fully on screen, not in a dead
  // gap under the fold.
  await page.locator('.dcx-ov').evaluate((n) => { n.scrollTop = n.scrollHeight; });
  await page.waitForTimeout(200);
  const last = page.locator('.dcx-ovtile').last();
  const box = await last.boundingBox();
  const vp = page.viewportSize();
  expect(box.y + box.height, 'the last tile is cut off at the bottom of the scroll')
    .toBeLessThanOrEqual(vp.height + 1);
  expect(box.y + box.height, 'the grid scrolls past the last tile into a dead gap')
    .toBeGreaterThan(vp.height * 0.35);
  await shot(page, 'overview-grid-bottom');
});

test('the tile controls, close up', async ({ page }) => {
  await openDeck(page);
  await goToSlide(page, 2);
  await page.locator('body').press('s');
  await page.locator('.dcx-bar [data-a="slide"]').click();
  await page.locator('.dcx-pop textarea').fill('Lights the comment icon on the tile.');
  await page.locator('.dcx-pop [data-a="save"]').click();
  await openOverview(page);
  await page.locator('.dcx-ovtile[data-slide="2"]').screenshot({ path: 'out/screens/tile-controls.png' });
  await page.locator('.dcx-ovtile[data-slide="2"] [data-a="note"]').click();
  await shot(page, 'overview-note-editor');
});

test('presentation mode, with no chrome on it', async ({ page }) => {
  await openDeck(page);
  await goToSlide(page, 4);
  await page.locator('.dcx-bar [data-a="perform"]').click();
  await expect(page.locator('.dcx-bar')).toBeHidden();
  await shot(page, 'presenting');
});

test('the comment list', async ({ page }) => {
  await openDeck(page);
  await goToSlide(page, 2);
  await selectOnSlide(page, 'Supply on one axis');
  await page.locator('.dcx-pop textarea').fill('Name the axes.');
  await page.locator('.dcx-pop [data-a="save"]').click();
  await page.locator('.dcx-bar [data-a="list"]').click();
  await shot(page, 'comment-list');
});
