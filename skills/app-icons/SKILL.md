---
name: app-icons
description: Generate a complete PWA icon set, favicon.ico, and OpenGraph/Twitter image from a single source mark (SVG or raster), then wire them into a Next.js App Router app so they work signed-out. Use for any "add a favicon / app icon / PWA icons / touch icon / OG image / social preview" task, rebranding an app's icons, or fixing a missing/blurry favicon or broken social card.
---

# App icons — one mark → full icon + social set

Feed one source mark, get every icon a modern web app needs, rendered
pixel-accurate (rounded corners, gradients, real fonts) and wired into Next.js
metadata. No design tools, no online generators, no per-size hand-export.

**Default action:** run the bundled script against the project's mark, drop the
output into `public/` + `src/app/`, paste the printed metadata block into the
root layout, confirm the auth middleware lets static assets through.

## What it produces

Into `public/` (or `--out`):

- `favicon.ico` — PNG-in-ICO, 16/32/48 frames; tiny sizes get a **stroked/bold**
  treatment so thin line-art still reads at 16px.
- `favicon-16x16.png`, `favicon-32x32.png`, `favicon-48x48.png`
- `icon.svg` — scalable favicon (SVG sources only)
- `apple-touch-icon.png` (180)
- `icon-192.png`, `icon-512.png`
- `icon-maskable-192.png`, `icon-maskable-512.png` — 30% safe-zone padding for
  Android adaptive masks
- `manifest.webmanifest`

Into `src/app/` (or `--app`):

- `opengraph-image.png` + `twitter-image.png` (1200×630) — Next auto-wires the
  `og:image` / `twitter:card` tags from these filenames.

## Prerequisite

The script renders with Chromium via Playwright. If the project already runs
Playwright E2E, there's nothing to install. Otherwise, once:

    npm i -D playwright && npx playwright install chromium

## Run it

From the project root:

    node .claude/skills/app-icons/scripts/generate-icons.mjs \
      --src brand/mark.svg \
      --bg '#1a1614' --accent '#b89944' --fg '#f0e9dd' --muted '#b8ad9d' \
      --recolor '#ffffff' \
      --title 'App Name' \
      --tagline 'One-line pitch.' \
      --name 'App Name' --short 'App'

Key flags (full list in the script header):

- `--src` **(required)** — SVG (inlined, recolourable) or raster (`.png/.jpg/.webp`).
- `--bg` — background for the maskable safe zone, the OG card, and SVG marks.
  Pick a solid brand colour; a dark ink reads well on both light and dark tabs.
  Not painted behind a transparent raster mark (that stays transparent).
- `--recolor` — recolour every SVG fill (e.g. `#ffffff` for a white mark on a dark
  `--bg`). SVG sources only; also enables the bold small-favicon stroke.
- `--accent` / `--fg` / `--muted` — OG glow-rule / title / tagline colours.
- `--title` / `--tagline` — OG text. Omit `--tagline` to drop the subline + rule.
- `--name` / `--short` — manifest `name` / `short_name`.
- `--trim` / `--no-trim` — auto-crop the source's dead border so the mark fills
  the frame. **On by default for raster** (marks routinely ship baked-in margin),
  off for SVG. `--trim-tol <0..1>` sets the colour-distance threshold from the
  corner background (default `0.06`; raise it to shave a soft glow/shadow, lower
  it to keep faint edges). `--trim-pad` re-adds breathing room (default `0`).
- `--no-og`, `--no-manifest` — skip those outputs.

The script prints the exact `metadata` + `viewport` block to paste into
`src/app/layout.tsx`.

## Wire-up (after running)

1.  Paste the printed `metadata.icons` + `metadata.manifest` + `viewport.themeColor`
    into the root layout. Import `Viewport` from `next` alongside `Metadata`.
2.  `opengraph-image.png` / `twitter-image.png` in `src/app/` need no wiring —
    Next detects them.
3.  **Signed-out access** — icons must serve without auth. Confirm the auth
    middleware `matcher` excludes static assets and the manifest:

        '/((?!_next/static|_next/image|favicon.ico|manifest.webmanifest|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)'

    Files in `public/` and the `src/app` image conventions are static, so this is
    the only gate that can block them.

## Design guidance

- **Pad every app icon; fill the frame only for favicons.** Favicons (16/32/48 +
  `favicon.ico`) fill edge to edge — they're tiny and have no pixels to waste on
  whitespace. Every **app icon** (apple-touch, `icon-192`/`icon-512`, the whole
  64→512 ladder) gets ~12% padding each side on an opaque background: iOS/macOS
  mask the corners themselves, and a full-bleed mark loses its corners to that
  mask. Trim the source's baked-in margin first (`--trim`), then pad
  deliberately — that way the inset is a known 12%, not whatever the artboard
  happened to have. Bump `--trim-tol` if a soft glow/shadow left the crop loose.
- **Padding needs an opaque background.** Pad a transparent mark and iOS
  composites the gap on black anyway — pick the brand `--bg` so the inset reads
  as intentional rather than as a hole.
- **Never bake a corner radius.** Every platform (iOS, Android, Windows tiles,
  macOS dock) masks app-icon corners itself. A baked radius double-rounds, and on
  a transparent mark it leaves blank/white triangles in the corners — the exact
  bug this rule prevents. Ship square; the OS rounds.
- **Transparency in → transparency out.** A transparent-background source (PNG/SVG
  alpha) produces transparent icons — no `--bg` is painted behind it, so it sits
  cleanly on any surface. An **opaque** source already carries its own background,
  so it goes full-bleed (`cover`) — scaled to fill the frame, no letterbox, no
  added fill. `--bg` then only backs the maskable safe zone and the OG card.
  (Caveat: iOS composites transparent apple-touch icons on black; supply an opaque
  mark if that matters.)
- **Contrast the mark against `--bg`.** White/light mark on a dark ink background
  is the safe default — legible on any tab colour, no theme flicker.
- **Wordmarks squash.** A wide logo shrinks to nothing in a square. Prefer a
  compact glyph/monogram; if only a wordmark exists, expect faint 16px favicons —
  the bold stroke helps but can't fully rescue fine detail.
- **Maskable ≠ standard.** The maskable variants pad to the Android safe zone on
  purpose; that inset is spec, not decoration — don't "fix" it, and don't confuse
  it with the fill-the-frame rule above.
- Keep the source mark in the repo (e.g. `brand/`) so a rebrand is one re-run.

## Verify

- Hard-refresh (Cmd+Shift+R) → browser-tab favicon.
- DevTools → Application → Manifest → icons load, no errors.
- Paste the deployed URL into a social-card debugger to confirm the OG image.
- iOS: Share → Add to Home Screen → apple-touch-icon shows.
