/* The overview: getting in, getting out, the keyboard, and the header.
   Every case here is a fault that was found by driving a real browser. */
import { test, expect } from '@playwright/test';
import { openDeck, goToSlide, currentSlide, expectOnScreen, shot } from './helpers.mjs';

const tiles = (page) => page.locator('.dcx-ovtile');

test('the Overview button opens the grid, one tile per slide, thumbnails drawn', async ({ page }) => {
  await openDeck(page);
  await page.locator('.dcx-bar [data-a="overview"]').click();
  await expect(page.locator('.dcx-ov')).toBeVisible();
  await expect(tiles(page)).toHaveCount(8);
  await expect(page.locator('.dcx-ovhdr .count')).toHaveText('All 8 slides');
  // The tile is the real slide, deep-cloned. A blank frame is the fault to
  // catch: the clone is there but nothing in it is visible.
  const thumb = page.locator('.dcx-ovthumb').first();
  await expect(thumb.locator('h1'), 'the first thumbnail materialised no clone').toHaveCount(1);
  await expect(thumb.locator('h1')).toHaveText('Opening');
  const shown = await thumb.locator('h1').evaluate((n) => {
    const r = n.getBoundingClientRect();
    return { opacity: +getComputedStyle(n).opacity, w: r.width, h: r.height };
  });
  expect(shown.opacity, 'the thumbnail clone is drawn transparent').toBeGreaterThan(0);
  expect(shown.w * shown.h, 'the thumbnail clone has no size').toBeGreaterThan(0);
  await expect(page.locator('.dcx-ovlabel').first()).toHaveText('Slide 1 · Opening');
});

test('going left off slide 1 opens the overview', async ({ page }) => {
  await openDeck(page);
  expect(await currentSlide(page)).toBe(1);
  await page.locator('body').press('ArrowLeft');
  await expect(page.locator('.dcx-ov')).toBeVisible();
});

test('left arrow on slide 2 pages the deck, it does not open the overview', async ({ page }) => {
  await openDeck(page);
  await goToSlide(page, 2);
  await page.locator('body').press('ArrowLeft');
  await expect(page.locator('.dcx-ov')).toBeHidden();
  expect(await currentSlide(page)).toBe(1);
});

test('Escape returns to the slide it was opened from, and leaves focus on Overview', async ({ page }) => {
  await openDeck(page);
  await goToSlide(page, 4);
  await page.locator('.dcx-bar [data-a="overview"]').click();
  await expect(page.locator('.dcx-ov')).toBeVisible();
  await page.locator('.dcx-ovtile').first().press('Escape');
  await expect(page.locator('.dcx-ov')).toBeHidden();
  expect(await currentSlide(page), 'Escape did not return to the origin slide').toBe(4);
  const focused = await page.evaluate(() => document.activeElement?.dataset?.a || '');
  expect(focused, 'focus did not land back on the Overview button').toBe('overview');
});

test('Escape in a tile comment editor closes the editor only, not the overview', async ({ page }) => {
  await openDeck(page);
  await page.locator('.dcx-bar [data-a="overview"]').click();
  await tiles(page).nth(2).locator('[data-a="cmt"]').click();
  await expect(page.locator('.dcx-pop')).toBeVisible();
  await page.locator('.dcx-pop textarea').press('Escape');
  await expect(page.locator('.dcx-pop')).toHaveCount(0);
  await expect(page.locator('.dcx-ov'), 'Escape closed the whole overview').toBeVisible();
});

test('opening focuses the slide it came from', async ({ page }) => {
  await openDeck(page);
  await goToSlide(page, 6);
  await page.locator('.dcx-bar [data-a="overview"]').click();
  await expect.poll(() => page.evaluate(
    () => document.activeElement?.closest?.('.dcx-ovtile')?.dataset?.slide || '',
  )).toBe('6');
});

test('everything outside the overview goes inert, and Tab cannot leave it', async ({ page }) => {
  await openDeck(page);
  await page.locator('.dcx-bar [data-a="overview"]').click();
  const barInert = await page.evaluate(() => document.querySelector('.dcx-bar').inert);
  expect(barInert, 'the bar behind the overview is still reachable').toBe(true);
  const stageInert = await page.evaluate(() => document.querySelector('deck-stage').inert);
  expect(stageInert, 'the deck behind the overview is still reachable').toBe(true);

  await page.locator('.dcx-ovhdr [data-a="filterstar"]').focus();
  for (let i = 0; i < 14; i++) {
    await page.keyboard.press('Tab');
    const inside = await page.evaluate(() => !!document.activeElement?.closest?.('.dcx-ov'));
    expect(inside, `Tab left the overview after ${i + 1} presses`).toBe(true);
  }
});

test('left and right move one tile, up and down move a whole row', async ({ page }) => {
  await openDeck(page);
  await page.locator('.dcx-bar [data-a="overview"]').click();
  const box = async (n) => tiles(page).nth(n).boundingBox();
  const focusedSlide = () => page.evaluate(
    () => +(document.activeElement?.closest?.('.dcx-ovtile')?.dataset?.slide || 0),
  );

  await tiles(page).first().focus();
  await page.keyboard.press('ArrowRight');
  expect(await focusedSlide(), 'right did not step one tile').toBe(2);
  await page.keyboard.press('ArrowLeft');
  expect(await focusedSlide(), 'left did not step back one tile').toBe(1);

  // A whole row, measured from the laid-out grid: same column, next row down.
  const first = await box(0);
  await page.keyboard.press('ArrowDown');
  const down = await focusedSlide();
  expect(down, 'ArrowDown moved one tile, not a row').toBeGreaterThan(2);
  const landed = await box(down - 1);
  expect(Math.abs(landed.x - first.x), 'ArrowDown changed column').toBeLessThan(2);
  expect(landed.y, 'ArrowDown did not move down a row').toBeGreaterThan(first.y);

  await page.keyboard.press('ArrowUp');
  expect(await focusedSlide(), 'ArrowUp did not come back to the first tile').toBe(1);

  await page.keyboard.press('End');
  expect(await focusedSlide()).toBe(8);
  await page.keyboard.press('Home');
  expect(await focusedSlide()).toBe(1);
});

test('arrow keys in the overview never page the deck behind', async ({ page }) => {
  await openDeck(page);
  await goToSlide(page, 3);
  await page.locator('.dcx-bar [data-a="overview"]').click();
  await tiles(page).first().focus();
  for (const k of ['ArrowRight', 'ArrowRight', 'ArrowDown', 'ArrowLeft']) {
    await page.keyboard.press(k);
  }
  expect(await currentSlide(page), 'the deck moved under the overview').toBe(3);
});

test('clicking a tile jumps to that slide and closes the overview', async ({ page }) => {
  await openDeck(page);
  await page.locator('.dcx-bar [data-a="overview"]').click();
  await tiles(page).nth(4).locator('.dcx-ovthumb').click();
  await expect(page.locator('.dcx-ov')).toBeHidden();
  expect(await currentSlide(page)).toBe(5);
});

test('the overview header keeps every control on screen, at 1440 and at 1024', async ({ page }) => {
  await openDeck(page);
  await page.locator('.dcx-bar [data-a="overview"]').click();
  for (const width of [1440, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(120);
    for (const a of ['filterstar', 'filterhidden', 'resetorder', 'close']) {
      await expectOnScreen(page, page.locator(`.dcx-ovhdr [data-a="${a}"]`), `${a} at ${width}px`);
    }
    await shot(page, `overview-header-${width}`);
  }
});
