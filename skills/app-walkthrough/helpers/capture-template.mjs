/**
 * TEMPLATE — copy into <repo>/walkthroughs/<scene-id>/capture.mjs and edit.
 * Run with: node capture.mjs   (needs `npm i playwright` in the walkthroughs dir
 * or the skill workdir; chromium via `npx playwright install chromium`)
 *
 * Contract it must fulfil:
 *  - screenshot each visual beat into shots/NN_name.png (mobile 390x844 @2x
 *    for phone scenes; 1440x900 @2x for desktop scenes)
 *  - record boundingBox() of every element the cursor will visit or a
 *    highlight will wrap, into shots/boxes.json  { viewport, boxes: {name: box} }
 *  - hide dev chrome before every shot (Next.js badge etc)
 */
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.APP_URL || 'http://localhost:3000';
const OUT = path.resolve('shots');
fs.mkdirSync(OUT, { recursive: true });

const VIEWPORT = { width: 390, height: 844 }; // phone scene; desktop: 1440x900, isMobile:false
const DSF = 2;
const boxes = {};

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: VIEWPORT, deviceScaleFactor: DSF, isMobile: true, hasTouch: true,
});
const page = await context.newPage();

async function hideDevChrome(p) {
  await p.addStyleTag({
    content: `nextjs-portal, [data-nextjs-toast], #__next-build-watcher,
      [data-next-badge-root], [data-nextjs-dev-tools-button] { display: none !important; }`,
  }).catch(() => {});
}
async function snap(name) {
  await hideDevChrome(page);
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
  console.log('shot', name);
}
async function box(name, selector) {
  const el = page.locator(selector).first();
  await el.waitFor({ state: 'visible', timeout: 8000 });
  boxes[name] = await el.boundingBox();
  console.log('box', name, JSON.stringify(boxes[name]));
  return el;
}

// ---- EDIT BELOW: login + walk the flow -------------------------------------
// NB: with Next dev/turbopack use waitUntil:'domcontentloaded' + small waits;
// 'networkidle' never fires (HMR websocket).

await page.goto(`${BASE}/auth/login`, { waitUntil: 'domcontentloaded' });
await page.fill('input[type="email"]', process.env.DEV_LOGIN_EMAIL || 'dev@test.local');
await page.fill('input[type="password"]', process.env.DEV_LOGIN_PASSWORD || 'password123');
await Promise.all([
  page.waitForURL('**/', { timeout: 15000 }).catch(() => {}),
  page.click('button[type="submit"]'),
]);
await page.waitForTimeout(1200);

// Example beat:
// await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
// await page.waitForTimeout(600);
// await box('fab', 'a[href="/capture"]');
// await snap('01_home');

// ---- END EDIT ---------------------------------------------------------------

fs.writeFileSync(path.join(OUT, 'boxes.json'), JSON.stringify({ viewport: VIEWPORT, boxes }, null, 2));
console.log('wrote boxes.json');
await browser.close();
