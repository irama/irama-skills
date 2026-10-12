#!/usr/bin/env node
// Generate a full PWA icon set + favicon.ico + OpenGraph/Twitter image from a
// single source mark (SVG or raster). Renders with Chromium via Playwright so
// CSS gradients, rounded corners, and real fonts come out pixel-accurate.
//
// Usage (run from the project root):
//   node <skill-dir>/scripts/generate-icons.mjs \
//     --src brand/mark.svg \
//     --bg '#1a1614' --accent '#b89944' --fg '#f0e9dd' --muted '#b8ad9d' \
//     --recolor '#ffffff' \
//     --title 'Example CMS' \
//     --tagline 'Sites that read like books, written with you.' \
//     --name 'Example CMS' --short 'Example'
//
// Flags:
//   --src <path>        Source mark. .svg is inlined (recolourable); raster
//                       (.png/.jpg/.webp) is embedded as-is.               [required]
//   --out <dir>         Icon/manifest output dir.               [default: public]
//   --app <dir>         Where opengraph-image.png goes.        [default: src/app]
//   --bg <hex>          Icon + OG background.                  [default: #111111]
//   --accent <hex>      OG rule / glow accent.                 [default: #b89944]
//   --fg <hex>          OG title colour.                       [default: #f5f5f5]
//   --muted <hex>       OG tagline colour.                     [default: #b8ad9d]
//   --recolor <hex>     Recolour every SVG fill (e.g. #ffffff). SVG src only.
//   --title <str>       OG headline.                    [default: --name value]
//   --tagline <str>     OG subline.                                   [optional]
//   --name <str>        Manifest name.                         [default: 'App']
//   --short <str>       Manifest short_name.            [default: --name value]
//   --trim              Auto-crop the source's dead border so the mark fills the
//                       frame. ON by default for raster; OFF for SVG (already
//                       fills its viewBox). Disable with --no-trim.
//   --trim-tol <0..1>   Trim colour-distance threshold from the corner bg.
//                                                                [default: 0.06]
//   --trim-pad <0..0.2> Fraction of the detected mark re-added as breathing room
//                       after trimming.                          [default: 0]
//   --no-og             Skip the OpenGraph/Twitter image.
//   --no-manifest       Skip the manifest route (src/app/manifest.webmanifest/route.ts).
//   --tile <png>        Finished-art mode: an opaque square app-icon tile a
//                       designer already padded. Standard icons are this tile
//                       resized pro rata (no re-padding); --src must then be the
//                       transparent glyph SVG drawn on the same frame as the tile.
//   --in-place          Rewrite the app's EXISTING icon files under --out (and
//                       --app) at their current pixel sizes, instead of writing
//                       the default file set. Use when an app already has its own
//                       ladder and manifest. Prints nothing to paste.
//   --exclude <str>     With --in-place, skip paths containing this substring
//                       (e.g. an alternative icon set the user can switch to).
//   --fav-dark <hex>    Favicon glyph colour on dark tab bars. [default: --recolor or #ffffff]
//   --fav-light <hex>   Favicon glyph colour on light tab bars.     [default: --bg]
//   --fav-transparent   PNG/ICO favicons with no background (the glyph alone).
//                       Default paints --bg behind SVG marks so Safari, which
//                       ignores SVG favicons, shows the glyph on any tab colour.
//   --theme-dark <hex>  Title-bar colour in dark mode (installed-app title bar).
//                       Use the colour of the app's own top bar.  [default: --bg]
//   --theme-light <hex> Title-bar colour in light mode.  [default: --theme-dark]
//   --maskable-scale <n> Maskable mark size as a multiple of the standard mark
//                       (0.8 = spec: Android crops maskable icons to the central 80%).
//                                                                 [default: 0.8]
//
// After running, paste the metadata block it prints into your root layout.

import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync } from 'node:fs';
import { extname, resolve, join, basename } from 'node:path';
import { createRequire } from 'node:module';

// ---- args ----
function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) continue;
    const key = a.slice(2);
    if (key.startsWith('no-')) { out[key.slice(3)] = false; continue; }
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) { out[key] = true; }
    else { out[key] = next; i++; }
  }
  return out;
}
const args = parseArgs(process.argv.slice(2));
if (!args.src) {
  console.error('Error: --src <path-to-mark> is required.');
  process.exit(1);
}

const cfg = {
  src: resolve(args.src),
  out: resolve(args.out || 'public'),
  app: resolve(args.app || 'src/app'),
  bg: args.bg || '#111111',
  accent: args.accent || '#b89944',
  fg: args.fg || '#f5f5f5',
  muted: args.muted || '#b8ad9d',
  recolor: typeof args.recolor === 'string' ? args.recolor : null,
  name: args.name || 'App',
  short: args.short || args.name || 'App',
  title: args.title || args.name || 'App',
  tagline: typeof args.tagline === 'string' ? args.tagline : '',
  trim: args.trim, // resolved against source type below (default: on for raster)
  trimTol: args['trim-tol'] != null ? Number(args['trim-tol']) : 0.06,
  trimPad: args['trim-pad'] != null ? Number(args['trim-pad']) : 0,
  og: args.og !== false,
  manifest: args.manifest !== false,
  tile: typeof args.tile === 'string' ? resolve(args.tile) : null,
  inPlace: args['in-place'] === true,
  exclude: typeof args.exclude === 'string' ? args.exclude : null,
  favTransparent: args['fav-transparent'] === true,
};
cfg.title = cfg.title === true ? cfg.name : cfg.title;
cfg.favDark = typeof args['fav-dark'] === 'string' ? args['fav-dark'] : cfg.recolor || '#ffffff';
cfg.favLight = typeof args['fav-light'] === 'string' ? args['fav-light'] : cfg.bg;
cfg.themeDark = typeof args['theme-dark'] === 'string' ? args['theme-dark'] : cfg.bg;
cfg.themeLight = typeof args['theme-light'] === 'string' ? args['theme-light'] : cfg.themeDark;

// Standard app icons inset the mark 12% a side. The maskable mark is a fixed
// multiple of the standard mark, never an inset picked by eye (SKILL.md, "Maskable
// icons"). 0.8 follows the spec: Chromium and Android crop maskable icons to their
// central 80%, so 0.8 shows the glyph at the standard size there. 1 makes the
// maskable file equal the standard one, for browsers that use it uncropped.
const STD_PAD = 0.24;
const MASKABLE_SCALE = args['maskable-scale'] != null ? Number(args['maskable-scale']) : 0.8;
const MASK_PAD = 1 - MASKABLE_SCALE * (1 - STD_PAD); // 0.392
if (cfg.tile && !existsSync(cfg.tile)) {
  console.error(`Error: tile not found: ${cfg.tile}`);
  process.exit(1);
}

if (!existsSync(cfg.src)) {
  console.error(`Error: source not found: ${cfg.src}`);
  process.exit(1);
}
mkdirSync(cfg.out, { recursive: true });
mkdirSync(cfg.app, { recursive: true });

// ---- resolve Playwright's chromium from the project ----
const require = createRequire(resolve('package.json'));
let chromium;
try { ({ chromium } = require('@playwright/test')); }
catch {
  try { ({ chromium } = require('playwright')); }
  catch {
    console.error(
      'Error: Playwright not found. Install it once:\n' +
      '  pnpm add -D playwright && pnpm exec playwright install chromium\n' +
      '(or `pnpm add -D @playwright/test`). Then re-run this script.'
    );
    process.exit(1);
  }
}

const stripScheme = (svg) => svg.replace(/<style>[^<]*prefers-color-scheme[^<]*<\/style>/g, '');

// ---- build the mark markup (inline SVG, or embedded raster) ----
const isSvg = extname(cfg.src).toLowerCase() === '.svg';
let markPlain; // as-authored colours
let markBold;  // stroked, for tiny favicons (SVG + recolour only)

if (isSvg) {
  let svg = stripScheme(readFileSync(cfg.src, 'utf8'))
    .replace(/<\?xml[\s\S]*?\?>/, '')
    .replace(/<!DOCTYPE[\s\S]*?>/, '')
    .trim();
  if (cfg.recolor) svg = svg.replace(/fill:\s*(?:#[0-9a-fA-F]{3,8}|rgb\([^)]*\))/g, `fill:${cfg.recolor}`);
  markPlain = svg;
  if (cfg.recolor) {
    // Add a matching stroke to every filled shape so thin line-art survives 16px.
    markBold = svg.replace(/style="fill:\s*[^;"]+;?/g, (m) =>
      `${m.endsWith(';') ? m : m + ';'}stroke:${cfg.recolor};stroke-width:9px;`
    );
  } else {
    markBold = svg;
  }
} else {
  const b64 = readFileSync(cfg.src).toString('base64');
  const mime = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' }[extname(cfg.src).toLowerCase()] || 'image/png';
  const img = `<img src="data:${mime};base64,${b64}" alt=""/>`;
  markPlain = img;
  markBold = img;
}

function iconHtml(mark, size, boxW, bg, fit) {
  // NEVER bake a corner radius — every platform (iOS, Android, Windows tiles,
  // macOS dock) masks app-icon corners itself; a baked radius double-rounds and,
  // on a transparent mark, leaves white/blank triangles in the corners.
  // `bg` null → no fill (paired with omitBackground so a transparent source stays
  // transparent). `fit`: contain shows the whole mark; cover fills the frame edge
  // to edge (used for opaque sources that already carry their own background).
  return `<!doctype html><html><head><style>
    html,body{margin:0;padding:0}
    .icon{width:${size}px;height:${size}px;${bg ? `background:${bg};` : ''}
      display:flex;align-items:center;justify-content:center;overflow:hidden}
    .icon svg,.icon img{width:${boxW}px;height:${boxW}px;object-fit:${fit};display:block}
  </style></head><body><div class="icon">${mark}</div></body></html>`;
}

// ---- render ----
const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });
async function shoot(html, size, sel = '.icon', omitBackground = false) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(html, { waitUntil: 'networkidle' });
  return page.locator(sel).screenshot({ omitBackground });
}

// Auto-trim the source's dead border so the mark fills the frame. Raster marks
// routinely ship with baked-in margin; combined with a layout pad that produced
// double padding and a mark lost in whitespace. Default: on for raster, off for
// SVG (an SVG already fills its viewBox).
const doTrim = isSvg ? cfg.trim === true : cfg.trim !== false;

// Crop a raster <img> to the bounding box of its content, then square it around
// that box's centre so icons never stretch. Content = any pixel whose alpha is
// meaningful (transparent-background marks) or whose colour is more than
// `trimTol` away from the averaged corner colour (solid/gradient backgrounds).
async function trimRaster(imgTag) {
  const m = imgTag.match(/src="([^"]+)"/);
  if (!m) return imgTag;
  const cropped = await page.evaluate(async ({ src, tol, pad }) => {
    const img = new Image();
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = src; });
    const w = img.naturalWidth, h = img.naturalHeight;
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, w, h).data;
    const idx = (x, y) => (y * w + x) * 4;
    let hasAlpha = false;
    for (let i = 3; i < d.length; i += 4) { if (d[i] < 250) { hasAlpha = true; break; } }
    const corners = [[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1]];
    let br = 0, bgc = 0, bb = 0;
    for (const [x, y] of corners) { const i = idx(x, y); br += d[i]; bgc += d[i + 1]; bb += d[i + 2]; }
    br /= 4; bgc /= 4; bb /= 4;
    const T = tol * 255;
    const isContent = (x, y) => {
      const i = idx(x, y);
      if (hasAlpha) return d[i + 3] > 16;
      const dr = d[i] - br, dg = d[i + 1] - bgc, db = d[i + 2] - bb;
      return Math.sqrt(dr * dr + dg * dg + db * db) > T;
    };
    let minX = w, minY = h, maxX = -1, maxY = -1;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      if (isContent(x, y)) {
        if (x < minX) minX = x; if (x > maxX) maxX = x;
        if (y < minY) minY = y; if (y > maxY) maxY = y;
      }
    }
    if (maxX < minX) return null; // nothing distinct from the border — leave as-is
    let bw = maxX - minX + 1, bh = maxY - minY + 1;
    const padPx = Math.round(Math.max(bw, bh) * pad);
    minX = Math.max(0, minX - padPx); minY = Math.max(0, minY - padPx);
    maxX = Math.min(w - 1, maxX + padPx); maxY = Math.min(h - 1, maxY + padPx);
    bw = maxX - minX + 1; bh = maxY - minY + 1;
    const side = Math.max(bw, bh);
    const cx = minX + bw / 2, cy = minY + bh / 2;
    let sx = Math.round(cx - side / 2), sy = Math.round(cy - side / 2);
    sx = Math.max(0, Math.min(sx, w - side));
    sy = Math.max(0, Math.min(sy, h - side));
    const sq = Math.min(side, w - sx, h - sy);
    const oc = document.createElement('canvas');
    oc.width = sq; oc.height = sq;
    oc.getContext('2d').drawImage(c, sx, sy, sq, sq, 0, 0, sq, sq);
    return oc.toDataURL('image/png');
  }, { src: m[1], tol: cfg.trimTol, pad: cfg.trimPad });
  return cropped ? `<img src="${cropped}" alt=""/>` : imgTag;
}

if (!isSvg && doTrim) {
  markPlain = await trimRaster(markPlain);
  markBold = markPlain;
  console.log('trimmed source to content bounds');
}

// Does the (possibly trimmed) raster mark carry transparency? Transparent marks
// stay transparent (contain, no fill); opaque marks already own a background, so
// they go full-bleed (cover). SVG marks render on --bg so a recoloured mark reads.
let srcHasAlpha = false;
if (!isSvg) {
  const m = markPlain.match(/src="([^"]+)"/);
  srcHasAlpha = m ? await page.evaluate(async (src) => {
    const img = new Image();
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = src; });
    const c = document.createElement('canvas');
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const x = c.getContext('2d');
    x.drawImage(img, 0, 0);
    const d = x.getImageData(0, 0, c.width, c.height).data;
    for (let i = 3; i < d.length; i += 4) { if (d[i] < 250) return true; }
    return false;
  }, m[1]) : false;
}

// Per-source render mode. `iconBg` null → transparent output (omitBackground).
const iconBg = isSvg ? cfg.bg : null;
const iconFit = isSvg || srcHasAlpha ? 'contain' : 'cover';
if (!isSvg) console.log(`source is ${srcHasAlpha ? 'transparent → transparent icons' : 'opaque → full-bleed icons'}`);

// ---- renderers (shared by the default file set and --in-place) ----
const dataUrl = (file, mime) => `data:${mime};base64,${readFileSync(file).toString('base64')}`;
const tileUrl = cfg.tile ? dataUrl(cfg.tile, 'image/png') : null;
// Render from the glyph's base colours: drop any colour-scheme rule a source may
// already carry (an adaptive favicon.svg reused as --src), or headless Chromium's
// light scheme paints the glyph in its light-tab colour.
const glyphUrl = isSvg ? `data:image/svg+xml;base64,${Buffer.from(stripScheme(readFileSync(cfg.src, 'utf8'))).toString('base64')}` : null;

// Finished-art mode: draw on a canvas in the page so the tile keeps its own
// background. The maskable background is one glyph-free column of the tile (3% in
// from the left edge) stretched across, so a vertical gradient carries over exactly.
async function canvasPng(size, kind) {
  const url = await page.evaluate(async ({ tile, glyph, size, kind, scale }) => {
    const load = (src) => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = src; });
    const c = document.createElement('canvas'); c.width = size; c.height = size;
    const x = c.getContext('2d'); x.imageSmoothingQuality = 'high';
    const t = await load(tile);
    if (kind === 'standard') { x.drawImage(t, 0, 0, size, size); return c.toDataURL('image/png'); }
    x.drawImage(t, Math.round(t.naturalWidth * 0.03), 0, 1, t.naturalHeight, 0, 0, size, size);
    const g = await load(glyph); const gs = size * scale;
    x.drawImage(g, (size - gs) / 2, (size - gs) / 2, gs, gs);
    return c.toDataURL('image/png');
  }, { tile: tileUrl, glyph: glyphUrl, size, kind, scale: MASKABLE_SCALE });
  return Buffer.from(url.split(',')[1], 'base64');
}

const favBg = cfg.favTransparent ? null : iconBg;
const renderStandard = (size) => cfg.tile ? canvasPng(size, 'standard')
  : shoot(iconHtml(markPlain, size, size * (1 - STD_PAD), cfg.bg, 'contain'), size);
const renderMaskable = (size) => cfg.tile ? canvasPng(size, 'maskable')
  : shoot(iconHtml(markPlain, size, size * (1 - MASK_PAD), cfg.bg, 'contain'), size);
const renderFavicon = (size) => shoot(iconHtml(markBold, size, size, favBg, iconFit), size, '.icon', favBg == null);

// Scalable favicon: the glyph alone, no tile, recoloured per colour scheme so it
// reads on dark AND light tab bars. A gradient-filled glyph swaps its stop colours;
// a flat one swaps its fills (never inside <mask>, which would break the cut-outs).
function adaptiveSvg() {
  let svg = stripScheme(readFileSync(cfg.src, 'utf8')).replace(/<\?xml[\s\S]*?\?>/, '').replace(/<!DOCTYPE[\s\S]*?>/, '').trim();
  const shapes = ':is(path,circle,rect,polygon,ellipse,polyline,text):not(mask *)';
  const css = /<(linear|radial)Gradient/.test(svg)
    ? `@media (prefers-color-scheme: light){stop{stop-color:${cfg.favLight} !important}}`
    : `${shapes}{fill:${cfg.favDark} !important}@media (prefers-color-scheme: light){${shapes}{fill:${cfg.favLight} !important}}`;
  return svg.replace(/(<svg\b[^>]*>)/, `$1<style>${css}</style>`);
}

// favicon.ico (PNG-in-ICO, 16/32/48 — supported by all modern browsers)
function buildIco(frames) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0); header.writeUInt16LE(1, 2); header.writeUInt16LE(frames.length, 4);
  const dir = Buffer.alloc(16 * frames.length);
  let offset = 6 + 16 * frames.length; const body = [];
  frames.forEach((f, i) => {
    const b = 16 * i;
    dir.writeUInt8(f.size >= 256 ? 0 : f.size, b); dir.writeUInt8(f.size >= 256 ? 0 : f.size, b + 1);
    dir.writeUInt16LE(1, b + 4); dir.writeUInt16LE(32, b + 6);
    dir.writeUInt32LE(f.data.length, b + 8); dir.writeUInt32LE(offset, b + 12);
    offset += f.data.length; body.push(f.data);
  });
  return Buffer.concat([header, dir, ...body]);
}
// One page renders everything, so frames must render one after another: parallel
// renders race on the viewport and mislabel the frames (a 48 entry holding 32px).
async function buildFaviconIco() {
  const frames = [];
  for (const size of [16, 32, 48]) frames.push({ size, data: await renderFavicon(size) });
  return buildIco(frames);
}

if (cfg.inPlace) {
  // Rewrite every existing icon file at its own pixel size; the manifest and
  // layout keep pointing at the same URLs, so nothing else changes.
  const pngWidth = (f) => readFileSync(f).readUInt32BE(16); // IHDR width
  const files = [];
  const walk = (dir) => { if (!existsSync(dir)) return; for (const e of readdirSync(dir, { withFileTypes: true })) {
    const f = join(dir, e.name);
    if (e.isDirectory()) { if (e.name !== 'node_modules') walk(f); continue; }
    if (/(icon|favicon|apple)[^/]*\.(png|ico|svg)$/i.test(e.name) && !(cfg.exclude && f.includes(cfg.exclude))) files.push(f);
  } };
  walk(cfg.out); walk(cfg.app);
  for (const f of files) {
    const n = basename(f).toLowerCase();
    let buf, kind;
    // Only the favicon SVGs: other SVGs whose names contain "icon" are unrelated art.
    if (n.endsWith('.svg')) { if (!isSvg || !/^(icon|favicon)\.svg$/.test(n)) continue; buf = adaptiveSvg(); kind = 'adaptive svg'; }
    else if (n.endsWith('.ico')) { buf = await buildFaviconIco(); kind = 'ico'; }
    else {
      const w = pngWidth(f);
      if (n.includes('maskable')) { buf = await renderMaskable(w); kind = 'maskable'; }
      else if (n.includes('favicon') || w <= 48) { buf = await renderFavicon(w); kind = 'favicon'; }
      else { buf = await renderStandard(w); kind = 'standard'; }
      kind += ` ${w}px`;
    }
    writeFileSync(f, buf);
    console.log(`rewrote ${f} (${kind})`);
  }
  await browser.close();
  console.log(`\nDone: ${files.length} files. Check the layout links an SVG favicon and the auth gate serves every icon signed-out.`);
  console.log('Serve the manifest from templates/manifest-route.ts so maskable icons are listed for Android only (SKILL.md, "Maskable icons").');
  process.exit(0);
}

const pngs = {};
for (const [name, size] of [['icon-192.png', 192], ['icon-512.png', 512], ['apple-touch-icon.png', 180]]) {
  writeFileSync(`${cfg.out}/${name}`, await renderStandard(size));
  console.log('wrote', name);
}
for (const [name, size] of [['icon-maskable-192.png', 192], ['icon-maskable-512.png', 512]]) {
  writeFileSync(`${cfg.out}/${name}`, await renderMaskable(size));
  console.log('wrote', name);
}
for (const [name, size] of [['favicon-16x16.png', 16], ['favicon-32x32.png', 32], ['favicon-48x48.png', 48]]) {
  pngs[size] = await renderFavicon(size);
  writeFileSync(`${cfg.out}/${name}`, pngs[size]);
  console.log('wrote', name);
}
if (isSvg) {
  writeFileSync(`${cfg.out}/icon.svg`, adaptiveSvg());
  console.log('wrote icon.svg (adapts to light/dark tab bars)');
}
writeFileSync(`${cfg.out}/favicon.ico`, buildIco([16, 32, 48].map((size) => ({ size, data: pngs[size] }))));
console.log('wrote favicon.ico');

// Manifest as a route: maskable icons are listed for Android only, so desktop Safari
// and Chromium both use the standard icon at the same size (SKILL.md, "Maskable icons").
if (cfg.manifest) {
  const base = {
    name: cfg.name,
    short_name: cfg.short,
    ...(cfg.tagline ? { description: cfg.tagline } : {}),
    start_url: '/',
    display: 'standalone',
    background_color: cfg.bg,
    theme_color: cfg.themeDark,
  };
  const tpl = (f) => readFileSync(new URL(`../templates/${f}`, import.meta.url), 'utf8');
  const dir = `${cfg.app}/manifest.webmanifest`;
  mkdirSync(dir, { recursive: true });
  writeFileSync(`${dir}/route.ts`, tpl('manifest-route.ts').replace('__BASE__', JSON.stringify(base, null, 2)));
  writeFileSync(`${dir}/route.test.ts`, tpl('manifest-route.test.ts'));
  console.log('wrote manifest.webmanifest/route.ts + route.test.ts');
  if (existsSync(`${cfg.out}/manifest.webmanifest`)) console.log(`DELETE ${cfg.out}/manifest.webmanifest: a static file shadows the route.`);
}

// OpenGraph + Twitter image (1200x630)
if (cfg.og) {
  const og = `<!doctype html><html><head><style>
    html,body{margin:0;padding:0}
    .card{width:1200px;height:630px;background:${cfg.bg};position:relative;overflow:hidden;
      display:flex;flex-direction:column;align-items:center;justify-content:center;
      font-family:Georgia,'Times New Roman',serif;color:${cfg.fg}}
    .card::after{content:"";position:absolute;inset:0;
      background:radial-gradient(120% 90% at 50% 8%, ${cfg.accent}28, transparent 60%)}
    .mark{width:300px;height:auto;position:relative;z-index:1}
    .mark svg,.mark img{width:100%;height:auto;display:block}
    h1{position:relative;z-index:1;margin:14px 0 0;font-size:76px;font-weight:600;letter-spacing:.5px;text-align:center;padding:0 40px}
    .rule{position:relative;z-index:1;width:64px;height:3px;background:${cfg.accent};margin:26px 0 0;border-radius:2px}
    .tag{position:relative;z-index:1;margin:18px 0 0;font-family:Inter,Helvetica,Arial,sans-serif;
      font-size:27px;color:${cfg.muted};max-width:820px;text-align:center;line-height:1.4;padding:0 40px}
  </style></head><body>
    <div class="card">
      <div class="mark">${markPlain}</div>
      <h1>${cfg.title}</h1>
      ${cfg.tagline ? '<div class="rule"></div>' : ''}
      ${cfg.tagline ? `<div class="tag">${cfg.tagline}</div>` : ''}
    </div></body></html>`;
  await page.setViewportSize({ width: 1200, height: 630 });
  await page.setContent(og, { waitUntil: 'networkidle' });
  const ogBuf = await page.locator('.card').screenshot();
  writeFileSync(`${cfg.app}/opengraph-image.png`, ogBuf);
  writeFileSync(`${cfg.app}/twitter-image.png`, ogBuf);
  console.log('wrote opengraph-image.png + twitter-image.png');
}

await browser.close();

// ---- print the metadata block to wire up ----
const svgIconLine = isSvg ? "\n      { url: '/icon.svg', type: 'image/svg+xml' }," : '';
console.log(`
Done. Add this to your root layout (src/app/layout.tsx):

export const metadata: Metadata = {
  // ...existing title/description...
  manifest: '/manifest.webmanifest',
  icons: {
    icon: [
      { url: '/favicon.ico', sizes: 'any' },${svgIconLine}
      { url: '/favicon-16x16.png', sizes: '16x16', type: 'image/png' },
      { url: '/favicon-32x32.png', sizes: '32x32', type: 'image/png' },
      { url: '/icon-192.png', sizes: '192x192', type: 'image/png' },
      { url: '/icon-512.png', sizes: '512x512', type: 'image/png' },
    ],
    apple: [{ url: '/apple-touch-icon.png', sizes: '180x180' }],
  },
};

// Title bar of the installed app: match the app's own top bar, per scheme.
export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: dark)', color: '${cfg.themeDark}' },
    { media: '(prefers-color-scheme: light)', color: '${cfg.themeLight}' },
  ],
};

// opengraph-image.png / twitter-image.png in src/app/ are auto-wired by Next.
// Ensure your auth middleware matcher excludes static assets, e.g.:
//   '/((?!_next/static|_next/image|favicon.ico|manifest.webmanifest|.*\\\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)'
`);
