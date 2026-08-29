/* Shared helpers. Every path here is relative to this folder, on purpose:
   nothing in this repo may carry a home directory. */
import { expect } from '@playwright/test';

export const MINTED = '/deck-minted.html';
export const RELABELLED = '/deck-minted-relabelled.html';
export const LEGACY = '/deck-legacy.html';

/** Load a fixture deck and wait for the review bar to exist. */
export async function openDeck(page, url = MINTED) {
  await page.goto(url);
  await page.waitForSelector('.dcx-bar');
  return page;
}

/** Which slide number is live, 1-based. */
export function currentSlide(page) {
  return page.evaluate(() => {
    const all = [...document.querySelectorAll('deck-stage > section')];
    return all.indexOf(document.querySelector('deck-stage > section[data-deck-active]')) + 1;
  });
}

export async function goToSlide(page, n) {
  await page.evaluate((i) => document.querySelector('deck-stage').goTo(i), n - 1);
  await expect.poll(() => currentSlide(page)).toBe(n);
}

/**
 * Select a phrase on the live slide and raise the mouseup the runtime listens
 * for. A real mouse drag is not usable here: the runtime deliberately refuses
 * to steal the selection, so the assertion has to be about the selection the
 * browser really holds.
 */
export async function selectOnSlide(page, needle) {
  const ok = await page.evaluate((text) => {
    const sec = document.querySelector('deck-stage > section[data-deck-active]');
    const walk = document.createTreeWalker(sec, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walk.nextNode())) {
      const i = node.nodeValue.indexOf(text);
      if (i === -1) continue;
      const r = document.createRange();
      r.setStart(node, i);
      r.setEnd(node, i + text.length);
      const sel = getSelection();
      sel.removeAllRanges();
      sel.addRange(r);
      const b = r.getBoundingClientRect();
      sec.dispatchEvent(new MouseEvent('mouseup', {
        bubbles: true, clientX: b.left + 4, clientY: b.bottom + 4,
      }));
      return true;
    }
    return false;
  }, needle);
  expect(ok, `phrase not on the live slide: ${needle}`).toBe(true);
  await page.waitForSelector('.dcx-pop');
}

/** Write a comment in whatever popover is open, and save it. */
export async function writeComment(page, body, { withKey = false } = {}) {
  const ta = page.locator('.dcx-pop textarea');
  await ta.fill(body);
  if (withKey) await ta.press('ControlOrMeta+Enter');
  else await page.locator('.dcx-pop [data-a="save"]').click();
  await expect(page.locator('.dcx-pop')).toHaveCount(0);
}

/** Click Copy and read the payload back off the clipboard. */
export async function copyPayload(page) {
  await page.locator('.dcx-bar [data-a="copy"]').click();
  await expect(page.locator('.dcx-toast')).toHaveText('Payload copied');
  const raw = await page.evaluate(() => navigator.clipboard.readText());
  return JSON.parse(raw);
}

/** A screenshot for a human or an agent to look at. See README.md. */
export async function shot(page, name) {
  await page.screenshot({ path: `out/screens/${name}.png` });
}

/** Every box is inside the viewport, which is what a header that will not wrap breaks. */
export async function expectOnScreen(page, locator, what) {
  const box = await locator.boundingBox();
  const vp = page.viewportSize();
  expect(box, `${what} has no box`).not.toBeNull();
  expect(box.x, `${what} runs off the left`).toBeGreaterThanOrEqual(0);
  expect(box.y, `${what} runs off the top`).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width, `${what} runs off the right`).toBeLessThanOrEqual(vp.width + 1);
}
