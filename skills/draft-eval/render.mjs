#!/usr/bin/env node
// render.mjs <index.html> <units.json> <outdir>
//
// Screenshots every non-hidden deck unit at 1920x1080 with one browser and one
// page. Loads index.html?_snthumb=1#<hash_index> (the runtime ignores ?slide=;
// it reads a 1-based #N hash, and _snthumb hides the rail), hides the comments
// bar, waits for deck-stage, fonts, images and finite animations, then asserts
// that the active slide's data-slide-id equals the unit id. A mismatch fails
// the whole render; it never falls back. Writes <ordinal>-<id>.png (ordinal
// zero-padded to two digits so the files sort), contact.png (every shot on one
// numbered sheet, for the arc pass) and shots.json of sha256 values plus the
// Playwright and Chromium versions for the run record.
//
// Playwright: resolved normally, else from $PLAYWRIGHT_NODE_MODULES, else from
// ~/LOCAL-DEV/peakstate-deck/tests/node_modules.
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync, unlinkSync, realpathSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

function loadPlaywright() {
  const dirs = [
    process.cwd(),
    process.env.PLAYWRIGHT_NODE_MODULES,
    join(homedir(), 'LOCAL-DEV/peakstate-deck/tests/node_modules'),
  ].filter(Boolean);
  for (const d of dirs) {
    try {
      const req = createRequire(join(d, 'noop.js'));
      return { ...req('playwright'), version: req('playwright/package.json').version };
    } catch (e) { /* next */ }
  }
  throw new Error('playwright not found; set PLAYWRIGHT_NODE_MODULES');
}

const HIDE_BAR = '.dcx, [class^="dcx-"] { display: none !important }';
const ANIM_TIMEOUT_MS = 5000;

async function settle(page) {
  await page.evaluate(async (timeout) => {
    await customElements.whenDefined('deck-stage');
    await document.fonts.ready;
    await Promise.all([...document.images].map((i) => i.decode().catch(() => {})));
    // ponytail: an infinite animation never finishes, so only finite ones are awaited, under a cap.
    const finite = document.getAnimations().filter((a) => {
      const end = a.effect && a.effect.getComputedTiming().endTime;
      return Number.isFinite(end);
    });
    await Promise.race([
      Promise.all(finite.map((a) => a.finished.catch(() => {}))),
      new Promise((r) => setTimeout(r, timeout)),
    ]);
  }, ANIM_TIMEOUT_MS);
}

// ponytail: six thumbnails a row at 320x180, one sheet; split it if a deck outgrows one image.
async function contactSheet(browser, outdir, shots) {
  const cells = shots.map((s, i) => `<figure><img src="${s.file}"><figcaption>${i + 1}</figcaption></figure>`);
  const html = `<!doctype html><style>body{margin:0;background:#fff;display:grid;
    grid-template-columns:repeat(6,320px);gap:8px;padding:8px;font:16px sans-serif}
    figure{margin:0}img{width:320px;height:180px;display:block;border:1px solid #ccc}
    figcaption{text-align:center}</style>${cells.join('')}`;
  const file = join(outdir, 'contact.html');
  writeFileSync(file, html);
  const page = await browser.newPage({ viewport: { width: 6 * 328 + 8, height: 400 } });
  await page.goto(pathToFileURL(resolve(file)).href, { waitUntil: 'load' });
  await page.screenshot({ path: join(outdir, 'contact.png'), fullPage: true });
  await page.close();
  unlinkSync(file);
}

export async function render(indexPath, unitsPath, outdir) {
  const { chromium, version } = loadPlaywright();
  const units = JSON.parse(readFileSync(unitsPath, 'utf8')).units;
  mkdirSync(outdir, { recursive: true });
  const base = pathToFileURL(resolve(indexPath)).href + '?_snthumb=1';
  const browser = await chromium.launch();
  const shots = [];
  let chromiumVersion = null;
  try {
    chromiumVersion = browser.version();
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
    for (const u of units) {
      if (u.hidden) continue;
      // A hash-only change is a same-document navigation and would not reload the deck.
      await page.goto('about:blank');
      await page.goto(`${base}#${u.hash_index}`, { waitUntil: 'load' });
      await page.addStyleTag({ content: HIDE_BAR });
      await settle(page);
      const active = await page.evaluate(() => {
        const all = [...document.querySelectorAll('deck-stage > section')];
        const i = all.findIndex((s) => s.hasAttribute('data-deck-active'));
        if (i < 0) return null;
        // Same fallback as extract.py: a section with no data-slide-id is section-<1-based index>.
        return all[i].getAttribute('data-slide-id') || `section-${i + 1}`;
      });
      if (active !== u.id) {
        throw new Error(`unit ${u.ordinal} ${u.id}: #${u.hash_index} shows ${active}`);
      }
      const file = `${String(u.ordinal).padStart(2, '0')}-${u.id}.png`;
      const png = await page.screenshot({ path: join(outdir, file) });
      shots.push({ id: u.id, ordinal: u.ordinal, hash_index: u.hash_index, file,
                   sha256: createHash('sha256').update(png).digest('hex') });
    }
    await contactSheet(browser, outdir, shots);
  } finally {
    await browser.close();
  }
  writeFileSync(join(outdir, 'shots.json'), JSON.stringify(
    { playwright: version, chromium: chromiumVersion, contact: 'contact.png', shots }, null, 2) + '\n');
  return shots;
}

// Run through a symlinked skill folder, argv[1] is the link path while
// import.meta.url is the real path, so a plain URL compare made the CLI a silent no-op.
// Compare real paths, as peakstate-brief's build-brief.mjs does.
if (process.argv[1] && fileURLToPath(import.meta.url) === realpathSync(process.argv[1])) {
  const [indexPath, unitsPath, outdir] = process.argv.slice(2);
  if (!outdir) {
    console.error('usage: render.mjs <index.html> <units.json> <outdir>');
    process.exit(2);
  }
  render(indexPath, unitsPath, outdir).then(
    (s) => console.log(`${s.length} shots -> ${join(outdir, 'shots.json')}`),
    (e) => { console.error(e.message); process.exit(1); },
  );
}
