/* The tile controls, starring, the filters, and the lit slide-comment state. */
import { test, expect } from '@playwright/test';
import { openDeck, goToSlide, currentSlide, selectOnSlide, writeComment, shot } from './helpers.mjs';

const tiles = (page) => page.locator('.dcx-ovtile');
const openOverview = (page) => page.locator('.dcx-bar [data-a="overview"]').click();

test('the tile star toggles by click and by the S key, and says so in words', async ({ page }) => {
  await openDeck(page);
  await openOverview(page);
  const tile = tiles(page).nth(1);
  await tile.locator('[data-a="star"]').click();
  await expect(tiles(page).nth(1)).toHaveClass(/starred/);
  await expect(tiles(page).nth(1).locator('.dcx-f-st')).toHaveText('★ STARRED');
  await expect(tiles(page).nth(1)).toHaveAttribute('aria-label', /, starred/);

  await tiles(page).nth(1).focus();
  await page.keyboard.press('s');
  await expect(tiles(page).nth(1)).not.toHaveClass(/starred/);
  await expect(tiles(page).nth(1).locator('.dcx-f-st')).toHaveCount(0);
});

test('the tile hide toggles by click and by the H key', async ({ page }) => {
  await openDeck(page);
  await openOverview(page);
  await tiles(page).nth(2).locator('[data-a="hide"]').click();
  await expect(tiles(page).nth(2)).toHaveClass(/ishidden/);
  await expect(tiles(page).nth(2).locator('.dcx-f-hd')).toHaveText('HIDDEN');
  await tiles(page).nth(2).focus();
  await page.keyboard.press('h');
  await expect(tiles(page).nth(2)).not.toHaveClass(/ishidden/);
});

test('commenting from a tile stays on the overview and returns focus to the tile', async ({ page }) => {
  await openDeck(page);
  await goToSlide(page, 1);
  await openOverview(page);
  await tiles(page).nth(3).locator('[data-a="cmt"]').click();
  await expect(page.locator('.dcx-pop')).toBeVisible();
  await expect(page.locator('.dcx-ov'), 'the comment editor left the overview').toBeVisible();
  expect(await currentSlide(page), 'commenting from a tile navigated the deck').toBe(1);
  // The whole-slide editor takes the keyboard: there is no selection to protect.
  await expect(page.locator('.dcx-pop textarea')).toBeFocused();

  await writeComment(page, 'The base for each figure is missing.');
  await expect(page.locator('.dcx-ov')).toBeVisible();
  await expect.poll(() => page.evaluate(
    () => document.activeElement?.closest?.('.dcx-ovtile')?.dataset?.slide || '',
  ), 'focus did not come back to the tile').toBe('4');
  await expect(tiles(page).nth(3).locator('.dcx-f-cm')).toHaveText('● SLIDE COMMENT');
  await expect(tiles(page).nth(3)).toHaveAttribute('aria-label', /has a slide comment/);
});

test('the C key on a focused tile opens that slide comment', async ({ page }) => {
  await openDeck(page);
  await openOverview(page);
  await tiles(page).nth(5).focus();
  await page.keyboard.press('c');
  await expect(page.locator('.dcx-pop')).toBeVisible();
  await expect(page.locator('.dcx-ov')).toBeVisible();
});

test('the tile note editor edits the note, marks it EDITED, and reverts', async ({ page }) => {
  await openDeck(page);
  await openOverview(page);
  await tiles(page).nth(1).locator('[data-a="note"]').click();
  const box = page.locator('.dcx-noteedit');
  await expect(box).toBeVisible();
  await expect(box.locator('textarea')).toHaveValue('Walk the axes before the cards.');
  await expect(box.locator('.edited')).toBeHidden();

  await box.locator('textarea').fill('Walk the axes, then the cards, then stop.');
  await expect(box.locator('.edited')).toBeVisible();
  await expect(tiles(page).nth(1).locator('[data-a="note"] i')).toHaveText('✓');

  await box.locator('[data-a="revert"]').click();
  await expect(box.locator('.edited')).toBeHidden();
  await expect(tiles(page).nth(1).locator('[data-a="note"] i')).toHaveCount(0);

  await box.locator('textarea').press('Escape');
  await expect(box).toHaveCount(0);
  await expect(page.locator('.dcx-ov'), 'Escape in the note editor closed the overview').toBeVisible();
});

test('starring from a slide, by the bar button and by the S key', async ({ page }) => {
  await openDeck(page);
  await goToSlide(page, 3);
  const star = page.locator('.dcx-bar [data-a="star"]');
  await expect(star).toHaveAttribute('aria-pressed', 'false');
  await expect(star).toHaveText('☆');

  await star.click();
  await expect(star).toHaveAttribute('aria-pressed', 'true');
  await expect(star).toHaveText('★');
  await expect(star).toHaveAttribute('aria-label', /Slide 3 is starred\. Click, or press S, to remove the star\./);

  await page.locator('body').press('s');
  await expect(star).toHaveAttribute('aria-pressed', 'false');
  await expect(star).toHaveText('☆');

  // The state follows the slide, not the button.
  await page.locator('body').press('s');
  await goToSlide(page, 4);
  await expect(star).toHaveAttribute('aria-pressed', 'false');
  await goToSlide(page, 3);
  await expect(star).toHaveAttribute('aria-pressed', 'true');
});

test('a star set on a slide shows on its tile, and the other way round', async ({ page }) => {
  await openDeck(page);
  await goToSlide(page, 2);
  await page.locator('body').press('s');
  await openOverview(page);
  await expect(tiles(page).nth(1)).toHaveClass(/starred/);
  await tiles(page).nth(1).locator('[data-a="star"]').click();
  await page.locator('.dcx-ovhdr [data-a="close"]').click();
  await expect(page.locator('.dcx-bar [data-a="star"]')).toHaveAttribute('aria-pressed', 'false');
});

test('Starred only names its state and reports the filtered count', async ({ page }) => {
  await openDeck(page);
  for (const n of [2, 3, 5]) {
    await goToSlide(page, n);
    await page.locator('body').press('s');
  }
  await goToSlide(page, 1);
  await openOverview(page);
  const fs = page.locator('.dcx-ovhdr [data-a="filterstar"]');
  await expect(fs).toHaveText('☆ Starred only: off');
  await expect(fs).toHaveAttribute('aria-pressed', 'false');

  await fs.click();
  await expect(fs).toHaveText('★ Starred only: on');
  await expect(fs).toHaveAttribute('aria-pressed', 'true');
  // Slide 1 is the origin slide, so the filter keeps it and flags it.
  await expect(page.locator('.dcx-ovhdr .count')).toHaveText('Showing 4 of 8');
  await expect(tiles(page).nth(0).locator('.dcx-f-fo')).toHaveText('FILTERED OUT');
  await expect(tiles(page).nth(0)).toHaveClass(/filtered/);
  await shot(page, 'overview-filter-starred');
});

test('Hidden slides toggle leaves the hidden ones out', async ({ page }) => {
  await openDeck(page);
  await goToSlide(page, 1);
  await openOverview(page);
  const fh = page.locator('.dcx-ovhdr [data-a="filterhidden"]');
  // Slide 7 is data-hidden-src in the fixture.
  await expect(tiles(page)).toHaveCount(8);
  await expect(fh).toHaveText('◉ Hidden slides: shown');
  await fh.click();
  await expect(fh).toHaveText('⊘ Hidden slides: left out');
  await expect(fh).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.dcx-ovhdr .count')).toHaveText('Showing 7 of 8');
});

test('reorder refuses while a filter is on, and says why', async ({ page }) => {
  await openDeck(page);
  await goToSlide(page, 2);
  await page.locator('body').press('s');
  await openOverview(page);
  await page.locator('.dcx-ovhdr [data-a="filterstar"]').click();

  const tile = page.locator('.dcx-ovtile[data-slide="2"]');
  await expect(tile).toHaveAttribute('draggable', 'false');
  await tile.focus();
  await page.keyboard.press('Alt+ArrowRight');
  await expect(page.locator('.dcx-toast')).toHaveText('Turn the filters off to reorder the deck');
  await expect(page.locator('.dcx-ovtile[data-slide="2"] .dcx-f-mv')).toHaveCount(0);
});

test('Alt+Arrow reorders when no filter is on, and moves the deck with it', async ({ page }) => {
  await openDeck(page);
  await openOverview(page);
  const tile = page.locator('.dcx-ovtile[data-slide="1"]');
  await expect(tile).toHaveAttribute('draggable', 'true');
  await tile.focus();
  await page.keyboard.press('Alt+ArrowRight');
  await expect(page.locator('.dcx-ovtile').first().locator('.dcx-ovlabel'))
    .toHaveText('Slide 1 · The board');
  // The section really moved in the light DOM, not just the grid.
  const order = await page.evaluate(() => [...document.querySelectorAll('deck-stage > section')]
    .map((s) => s.dataset.slideId));
  expect(order.slice(0, 2)).toEqual(['the-board', 'opening']);
});

test('the lit Slide comment state goes on and off with no reload, and the tile agrees', async ({ page }) => {
  await openDeck(page);
  await goToSlide(page, 5);
  const btn = page.locator('.dcx-bar [data-a="slide"]');
  await expect(btn).toHaveText('💬 Slide comment');
  await expect(btn).toHaveAttribute('aria-label', /No slide comment on slide 5/);

  await btn.click();
  await writeComment(page, 'Say what the stamp lets a reader check.');
  await expect(btn).toHaveText('● 💬 Slide comment');
  await expect(btn).toHaveClass(/on/);
  await expect(btn).toHaveAttribute('aria-label', /Slide 5 has a slide comment/);

  await openOverview(page);
  await expect(page.locator('.dcx-ovtile[data-slide="5"] .dcx-f-cm')).toHaveText('● SLIDE COMMENT');
  await expect(page.locator('.dcx-ovtile[data-slide="5"] [data-a="cmt"] i')).toHaveText('●');
  await page.locator('.dcx-ovhdr [data-a="close"]').click();

  // Delete it from the list: two clicks, and the light must go out at once.
  await page.locator('.dcx-bar [data-a="list"]').click();
  const item = page.locator('.dcx-panel .item').filter({ hasText: 'Slide 5' });
  await item.locator('[data-a="del"]').click();
  await item.locator('[data-a="del"]').click();
  await expect(btn).toHaveText('💬 Slide comment');
  await expect(btn).not.toHaveClass(/on/);

  await openOverview(page);
  await expect(page.locator('.dcx-ovtile[data-slide="5"] .dcx-f-cm')).toHaveCount(0);
});

test('a second Slide comment click edits the first, it does not stack a duplicate', async ({ page }) => {
  await openDeck(page);
  await goToSlide(page, 6);
  await page.locator('.dcx-bar [data-a="slide"]').click();
  await writeComment(page, 'First take.');
  await page.locator('.dcx-bar [data-a="slide"]').click();
  await expect(page.locator('.dcx-pop textarea')).toHaveValue('First take.');
  await writeComment(page, 'Second take.', { withKey: true });
  await expect(page.locator('.dcx-bar .dcx-count')).toHaveText('● 1');
});

test('a selection comment anchors to the quote and never lights the slide-comment button', async ({ page }) => {
  await openDeck(page);
  await goToSlide(page, 2);
  await selectOnSlide(page, 'Supply on one axis');
  await expect(page.locator('.dcx-pop .q')).toHaveText('Supply on one axis');
  await writeComment(page, 'Name the axes in the heading.');
  await expect(page.locator('.dcx-bar [data-a="slide"]')).not.toHaveClass(/on/);
  await openOverview(page);
  await expect(page.locator('.dcx-ovtile[data-slide="2"] .dcx-f-cm')).toHaveText('1 COMMENT');
});
