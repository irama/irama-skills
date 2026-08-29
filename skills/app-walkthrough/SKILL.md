---
name: app-walkthrough
description: Generate narrated training/walkthrough videos of any web app — Playwright screenshots + OpenAI TTS + Whisper force-aligned captions + Remotion cursor/highlight compositing. Exports .mp4 + .srt + .md manifest bundles and guides each app to publish them on a /help route organised job-by-job (JTBD). Use when the user wants a training video, walkthrough video, demo video of an app flow, a help/tutorial video library, or mentions "app-walkthrough".
---

# App Walkthrough — narrated training videos for any app

Turns a scripted app flow into a polished portrait/landscape MP4: real screenshots,
an oversized animated cursor that "clicks" real elements, gold highlight boxes,
word-synced captions, and a calm AU narrator. Ships every video as a
**bundle**: `<id>.mp4` + `<id>.srt` + `<id>.md` manifest.

Proven pipeline (first shipped for a publishing app, 2026-07). All local, ~$0.01/video
in API costs. No SaaS.

## Hard rules (non-negotiable)

1. **Every output is 16:9 — 1920×1080.** Whatever the capture aspect. Portrait (phone)
   captures are centred and **letterboxed with pure-black (`#000`) side-bars**; landscape
   (desktop) captures fill the width with black top/bottom bars. Never stretch to fill,
   never white bars. The Remotion template enforces this automatically (aspect inferred
   from `boxes.json` viewport) — do not override the composition dimensions.
2. **Foreman's-voice narration.** The narration is deliberately terse and plain — this is
   a feature, not a limitation. One idea per line. No marketing, no filler, no "in this
   video we'll…". Say what the user does and why, in *their* vocabulary, the way a foreman
   explains a job to an offsider: "Bought an auger off a private seller. Tap the plus.
   Dictate it." Sentence fragments are good. If a line reads like a SaaS tour, cut it back.
   **Delivery is a NORMAL speaking pace — the natural speed of everyday talk, never slowed,
   dragged, or over-enunciated.** The calm comes from the real silence BETWEEN phrases
   (`<break>` tags → generated silence), NOT from slow words. Keep the pauses; keep the pace
   normal. A "calm, slow narrator voice" is the wrong instinct here and reads as sluggish.
3. **Captions are verbatim the script**, never Whisper's raw transcript (use the
   force-aligner). See step 3.
4. **Verify by looking** — extract frames and check the cursor lands on its target and
   captions match, before showing the user. See step 7.
5. **No real PII on screen — use dummy data.** Never capture a user's real email addresses,
   names, message contents, or other personal data. Seed a dummy account / stub the data,
   or replace the on-screen values with plausible dummies (`you@gmail.com`, `work@company.com`)
   in the capture before every shot. Redact by substitution, not blur.
6. **Plain, calm capture background.** Turn OFF busy/animated app backdrops (matrix rain,
   scenes, video walls) for the capture — force a plain solid background so the UI, cursor,
   and highlights read clearly. Respect the app's theme choice (dark vs light) but strip
   decorative motion behind the content.

## What lives where

- **This skill (reusable, app-agnostic):** helpers/ (TTS, force-align, bundle export,
  capture template), remotion-template/ (config-driven composition). Node deps install
  into a per-session workdir — never into the consuming repo.
- **The consuming repo (per app):** `walkthroughs/` dir containing one folder per scene
  (`<scene-id>/narration.txt`, `capture.mjs`, `scene.json`, `meta.json`) plus
  `walkthroughs/curriculum.md` (the JTBD storyboard). Output bundles go to
  `public/help/videos/` so the app can serve them.
- **Requirements on the machine:** node ≥ 20, ffmpeg/ffprobe, chromium via
  `npx playwright install chromium` (first use). Key: `OPENAI_API_KEY` (env or `.env` beside narration) — used for BOTH TTS
  (gpt-4o-mini-tts) and the Whisper caption aligner.

## Pipeline (per scene)

Work in a scratch/session workdir; only the final bundle lands in the repo.

1. **Script** — write `narration.txt` in the Foreman's voice (Hard Rule 2): terse, one
   idea per line, the user's vocabulary, no marketing. Insert `<break time="0.9s" />`
   between lines — pauses are what make it digestible. Default voice `ash`
   (OpenAI, AU accent + pace shaped by the helper's instructions prompt);
   override per app with `--voice`.
2. **TTS** — `python3 helpers/elevenlabs_tts.py narration.txt narration.mp3` (mandated
   voice: ElevenLabs Charlie @ speed 0.95; needs `ELEVENLABS_API_KEY`). Fallback only if no
   ElevenLabs key: `helpers/tts_generate.py` (OpenAI `ash`).
3. **Align** — `python3 helpers/align_captions.py narration.mp3 narration.txt timing.json`
   Force-aligns the KNOWN script onto Whisper word timings (difflib match +
   interpolation for gaps) so captions/SRT are verbatim, never Whisper's mishearing.
4. **Capture** — copy `helpers/capture-template.mjs`, edit to walk the flow. It must
   emit `shots/*.png` AND `shots/boxes.json` (element bounding boxes). Rules learned
   the hard way: `domcontentloaded` not `networkidle` (HMR); hide Next dev badge via
   injected CSS before every shot; phone scenes 390x844@2x, desktop 1440x900@2x;
   seed the DB so data looks real — never lorem ipsum.
5. **Scene spec** — write `scene.json` (see remotion-template/src/Scene.tsx header for
   schema). Every beat is anchored to a narration WORD (`atWord: "plus"`), never to
   seconds — re-pacing narration re-times everything automatically. Targets reference
   box names from boxes.json.
6. **Render** — copy remotion-template to workdir, `npm i` (once per session), drop
   assets into `public/` (shots, boxes.json, timing.json, scene.json, narration.mp3),
   `npx remotion render Scene out/<id>.mp4`.
7. **Verify (mandatory)** — extract 3-4 frames with ffmpeg at beat times; check cursor
   sits ON its target, highlight wraps the right element, captions match narration,
   no dev chrome. Fix and re-render before showing the user.
8. **Bundle** — `python3 helpers/export_bundle.py out/<id>.mp4 timing.json meta.json`
   → `<id>.mp4` + `<id>.srt` + `<id>.md` side by side. meta.json carries the narrative
   (title/summary/context/teaches/steps/routes/reference_urls); the generator adds
   technical frontmatter (duration, dims, fps, codec, audio, bytes) via ffprobe.

## The .md manifest (contract)

YAML frontmatter: title, app, feature, kind, register, narrator_voice,
duration_seconds/hms, video{width,height,fps,codec}, audio{codec,sample_rate,channels},
file_bytes, sidecars, routes_shown, reference_urls, pipeline, generated.
Body: summary → What this teaches → Context → Step-by-step (matches on-screen beats)
→ Narration (verbatim) → Reference URLs. The manifest is both human help-page copy
AND machine-readable index data for the /help route.

## The /help route (per app)

Each consuming app publishes its videos on a `/help` page. Principles:

- **Organise by job-to-be-done, not by feature.** Sections follow the user's life
  with the app: "Getting set up" → "Daily work" → "Weekly/periodic" → "Advanced /
  when you're ready". Within a section, order by dependency (what you must do first).
- **Foundational first.** The top of the page is the onboarding path a brand-new
  user follows linearly; advanced material is clearly separated and safe to ignore.
- Each video card: title, one-line summary (from manifest), duration, routes shown;
  expandable step-by-step text (from manifest body) for people who prefer reading;
  the SRT/VTT wired as `<track>` captions — but NOT `default` (the burned-in captions already cover it; double captions look broken).
- Source the index from the `.md` manifests at build time — no separate copy of
  titles/durations that can drift.
- Keep a `walkthroughs/curriculum.md` storyboard in the repo: the full JTBD map of
  planned/shipped videos with status. The /help page is its rendered, user-facing form.
- **Video storage — R2, not git.** Commit only the `.md` manifest + `.srt`/`.vtt`
  captions to `public/help/videos/`; keep the `.mp4` OUT of git (`.gitignore` it) and
  upload it to object storage. In a repo that already has R2/S3 wired, store
  under a fixed prefix like `help/videos/<id>.mp4` and serve via a
  **long-TTL signed GET URL** (12h — training content is non-sensitive but watched
  slowly; a short attachment-grade TTL expires mid-watch). Mint the signed URL in the
  server page (`dynamic = 'force-dynamic'`) and pass it to the player; captions stay
  same-origin so `<track>` works without CORS. Ship a small `scripts/upload-help-videos.mjs`
  so new videos are one command. If the repo has no object storage, fall back to serving
  the `.mp4` from `public/` directly (simpler, but bloats the repo).

## Voice defaults

**MANDATED narrator: ElevenLabs "Charlie" (AU male), speed 0.95.** This is the
house voice for every walkthrough — use it unless the audience is
genuinely different. Generate with `helpers/elevenlabs_tts.py` (voice_id
`IKne3meq5aSn9XLyUdCD`, `--speed 0.95`), which needs **`ELEVENLABS_API_KEY`**.
Pipeline step 2 becomes:

    python3 helpers/elevenlabs_tts.py narration.txt narration.mp3   # speed 0.95, Charlie

`<break>` tags render as real generated silence (each chunk synthesised
separately and joined with silence). Delivery pace is set by ElevenLabs
`voice_settings.speed` — 0.95 is natural talk (never slow; the calm is the
pauses, Hard Rule 2). `align_captions.py` still uses `OPENAI_API_KEY` (Whisper),
so both keys are needed.

Legacy/fallback: `helpers/tts_generate.py` (OpenAI `gpt-4o-mini-tts`, voice
`ash`) remains for when no ElevenLabs key is available — same interface, lesser
voice. Do not use it by default.

## Gotchas (hard-won)

- `<break>` tags become literal silence between separately-synthesised chunks;
  keep the total pause budget reasonable — force-align absorbs boundary noise.
- Open captions render as STATIC sentence blocks: the sentence appears whole,
  exactly ONE current word highlights in place (never two at once), then the
  block swaps. Never a rolling word window — words must not move once on
  screen. (Template `buildCaptionBlocks` + `activeIdx`.)
- Cursor pacing lives in the template (`TRAVEL_S`): a quick ~0.55s flick between
  stops, then a dwell on target until just before the next anchor. Never make the
  cursor glide continuously across a whole narration gap — it reads painfully slow.
- Whisper drops/mishears quiet words — that's why align_captions.py exists; never
  build SRT straight from Whisper output.
- Remotion versions move fast; template pins ^4.0.486, run `npm view remotion version`
  if install fails.
- Local dev servers die when their spawning shell ends — start them detached and
  health-check with curl before capture.
- deviceScaleFactor must match between capture (Playwright) and scene math
  (scene.json `deviceScaleFactor`) or overlays land off-target.
