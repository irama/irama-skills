---
name: app-icons
description: Generate or replace a web app's whole icon set (PWA icons, maskable icons, apple-touch, favicons, adaptive SVG favicon, OpenGraph/Twitter image, title-bar colour) and wire it into a Next.js App Router app so it works signed-out. Takes either one source mark or designer-finished art (an opaque tile plus a transparent glyph), and can rewrite an app's existing icon files in place at their current sizes. Use for any "add a favicon / app icon / PWA icons / touch icon / OG image / social preview" task, rebranding icons across one or many apps, icons that look a different size in different browsers, a title bar that does not match the app, or a missing/blurry favicon.
---

# App icons

One skill, one script: `scripts/generate-icons.mjs`. It renders with Chromium via
Playwright, so gradients, masks and fonts come out pixel-accurate. This is the only
copy: do not vendor it into an app's `.claude/skills/`, because vendored copies drift.

## Pick the mode

| You have | Mode | Flags |
|---|---|---|
| One mark (SVG or raster), no finished icons | **Generate** the default file set | `--src` |
| A designer's finished art: an opaque square tile already padded, plus the transparent glyph SVG on the same frame | **Finished art**: the tile is resized pro rata, never re-padded | `--tile <png> --src <glyph.svg>` |
| An app that already ships its own icon ladder and manifest | **In place**: every existing icon file is rewritten at its current pixel size; URLs, manifest and layout stay as they are | add `--in-place` (and `--exclude <str>` for an alternative icon set to leave alone) |

Keep the source art in the repo (for example `brand/`). A download folder is not a
source: on 2026-10-11 the 1200px fleet tiles were deleted from `~/Downloads` a day
after the rollout, and only 512px derivatives survived.

## Run it

From the app's root (Playwright must resolve from its `package.json`). `<skill-dir>` is
the folder this skill loaded from:

    node <skill-dir>/scripts/generate-icons.mjs \
      --src brand/glyph.svg --tile brand/tile-1200.png \
      --bg '#1A1614' --fav-transparent --fav-light '#1A1614' \
      --theme-dark '#121c30' --theme-light '#fbfaf5' \
      --in-place

Without Playwright: `pnpm add -D playwright && pnpm exec playwright install chromium`.
The full flag list is in the script header. Generate mode prints the `metadata` and
`viewport` block to paste into `src/app/layout.tsx`.

## What each platform reads

| Surface | File it uses | What it does to it |
|---|---|---|
| Browser tab, Chrome/Firefox/Edge | `icon.svg` / `favicon.svg` when linked | Honours `prefers-color-scheme` inside the SVG |
| Browser tab, Safari | PNG / ICO favicon | Ignores SVG favicons |
| Installed app, Chromium on macOS | The `maskable` manifest icon if listed, else the standard one (the route lists none for desktop) | Crops a maskable icon to the central 80% (a 61% glyph showed at 75%); uses a standard icon as is |
| Installed app, Android | The `maskable` manifest icon | Crops to the safe zone and applies its own mask shape |
| Safari "Add to Dock" (macOS) | The **maskable** manifest icon if listed, even when an `any` icon and an apple-touch icon exist (verified 2026-10-12: baked glyph 0.541; maskable art 0.54, standard 0.68), else the standard one | Does not crop; places it in a squircle as is |
| iOS "Add to Home Screen" | `apple-touch-icon` | Rounds the corners |
| Installed-app title bar | `viewport.themeColor` (per scheme), else manifest `theme_color` | Paints the title bar |

## Rules

- **Maskable icons: write them, list them for Android only.** Chromium and Safari both
  read a listed maskable icon and only Chromium crops it, so listing one makes the same
  app a different size in each. With none listed, both use the standard icon uncropped
  and match (verified 2026-10-12: glyph 0.677 of the tile in Safari, 0.676 in
  Chromium). Android launchers need the maskable icon to fill their shapes. So the
  manifest is a route, not a file: `templates/manifest-route.ts` lists the maskable
  icons only when `Sec-CH-UA-Platform` (or, failing that, the user agent) says
  Android, and sends `Vary` so a CDN never mixes the two. Generate mode writes it to
  `src/app/manifest.webmanifest/route.ts` with its test; delete any static
  `public/manifest.webmanifest` or `app/manifest.ts`, which would shadow it. In place,
  copy the template by hand and point its icon paths at the app's own files.
  The template's test runs in the Node environment: a browser-like test environment
  drops `Sec-*` request headers.
- **Never pick a maskable inset by eye.** When used, it is a fixed multiple of the standard mark.
- **Standard icons: pad 12% a side on an opaque background.** The OS masks the
  corners. A finished-art tile is already padded: resize it, do not pad it again.
- **Never bake a corner radius.** Every platform rounds app icons itself.
- **Favicons fill the frame.** `--fav-transparent` gives the glyph alone with no tile.
  A light glyph alone disappears on a light tab bar, so always ship the adaptive SVG
  favicon (light glyph on dark tabs, `--fav-light` on light tabs) and link it first.
  Safari still uses the PNG, so a transparent light PNG is faint in Safari's light mode.
- **Title bar = the bar directly below it.** Set `--theme-dark` / `--theme-light` to
  the colour of the app's own top bar (often the header or context bar, not the page).
- **Signed-out access.** Every icon URL must return 200 with no session. Check the auth
  gate's matcher or public-path list includes each file, including a newly added
  `favicon.svg`. A 307 to the login page means a broken icon.

## Verify (do every step)

- Render check: open the outputs and compare glyph sizes across apps.
- Live check per app, signed-out: `curl -s -o /dev/null -w '%{http_code} %{content_type}' <url>`
  for each icon. Then compare the live bytes with the committed file (`curl -s <url> | md5`
  against `md5 -q <file>`). A deploy can "succeed" and still serve the old file.
- Vercel's bot checkpoint can answer scripts with a 403 page; check the deployment
  status instead.

## Installed apps do not refresh icons

Chromium on desktop does not update an installed app's icon from the site. Safari Dock
apps keep the icon they were created with. To see new icons:

- Chromium: uninstall the app (app menu > Uninstall, or right-click it in
  `chrome://apps`), hard-reload the site, install it again.
- Safari: delete the app from `~/Applications` (the folder in the home folder, not
  `/Applications`), then File > Add to Dock again. The app loses its cookies.
- Chromium apps live in `~/Applications/<Browser> Apps.localized/`.
- If the Dock still shows the old icon, run `killall Dock`.

## Rolling out across many apps

- Push one app at a time. Several CI gates running at once on one machine caused
  timing-test failures that do not occur when run alone.
- Check who else holds a repo's shipping verb before pushing (the conductor).
- Apps not hosted on Vercel need their own deploy step after the push.
