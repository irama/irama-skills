---
name: gen-image
description: Generate images with GPT Image 2.5 (the default) or another hosted model — Nano Banana 2, Seedream, Qwen Image Edit Plus, Midjourney v7, Z-Image Turbo — and save them straight into the current project. Use when an artefact needs a generated image (slide, hero, illustration, thumbnail, texture, mockup background), when the user says "generate an image", "gen image", "nano banana", "make me a picture/illustration", or invokes /gen-image. Also handles image-to-image via reference URLs.
---

# gen-image — hosted image generation

> **Paths.** `<skill-dir>` means the folder holding this SKILL.md — resolve it from
> wherever the skill was loaded, never a hardcoded home path. This skill installs as a
> plugin, as a project `.claude/skills/` folder, and on Windows, so its location varies.

One script, submit → poll → download:

```
python3 <skill-dir>/generate.py \
  --prompt "<the prompt>" \
  --out ./path/to/image.png \
  --size 16:9
```

Prints the written path on success. Generation runs 20 s – 5 min; the script polls and blocks
(default ceiling 600 s, `--timeout`). Run it in the background for long jobs.

## Models

`--model` picks the engine. Default `gpt25`.

| `--model` | Engine | Notes |
|---|---|---|
| `gpt25` | GPT Image 2.5 Flare (`gpt-image-2.5-flare`) | **The default.** Strongest prompt adherence, and the one to reach for on a brief with several constraints in it. Takes `--quality`, defaulting to `high`. |
| `gpt25max` | GPT Image 2.5 Sunburst (`gpt-image-2.5-sunburst`) | The precise 2.5 variant. Slower for the same prompt, so keep it for work where control matters. |
| `gpt2` | GPT Image 2 (`gpt-image-2`) | The previous default. |
| `nb2` | Nano Banana 2 (`gemini-3.1-flash-image-preview`) | Up to 14 reference images, so it is still the pick for image-to-image and for holding a style across a set. No seed. |
| `seedream` | Seedream 5.0 Lite | Up to 14 refs. Painterly, good at atmosphere. |
| `qwen` | Qwen Image Edit Plus | Up to 3 refs, supports seed + negative prompt. Best for *editing* a supplied image. |
| `mj` | Midjourney v7 | Most stylised. References go inline in the prompt; the script handles that. |
| `zimage` | Z-Image Turbo | Text-to-image only, fastest, cheapest. |

## Options

- `--size` — aspect ratio string, e.g. `16:9` (slides), `1:1`, `4:5`, `9:16`. Not pixels.
- `--ref <url>` — reference image, repeatable. Must be a **public URL** the provider can fetch;
  a local path will not work. For image-to-image on local files, upload the file first.
- `--quality` — `low`, `medium`, `high`, `xhigh` or `max`. GPT Image 2.5 only, and it defaults
  to `high` there. The other engines reject the field, so the script refuses it.
- `--timeout <seconds>` — default 600. A 2.5 generation usually lands in 15–70 s, and the API
  quotes up to 330 s.

## Auth

`EVOLINK_API_KEY`, resolved in this order:

1. the environment variable, if exported;
2. otherwise, only if `GEN_IMAGE_FALLBACK_ENV` points at an env file holding one, read from
   there (read, never copied). Unset by default, because billing your images to another
   app's production key should be opted into rather than inherited.

If neither exists, the script exits saying so. To use it outside that machine, get a key at
[evolink.ai](https://evolink.ai) → account → API keys, then `export EVOLINK_API_KEY=...` in
`~/.zshrc`. Spend is per generation on the host's own billing — treat a batch of more than ~10
images as a spend the user should approve first, with an estimate.

## Prompting notes

- Say the **medium and the light** first ("editorial photograph, low winter sun, shallow depth of
  field"), then subject, then composition, then what to exclude.
- **Say where a face is looking.** Any person or animal in frame needs a named point to look at —
  out across the water, down at the work in their hands, along the path ahead. Left unsaid, the
  model puts the subject in direct eye contact with the lens, which reads as posed and unnerving.
  Ask for eye contact only when it is the point of the image, and then say so in those words.
- Nano Banana 2 handles **text in images** better than most; still keep any rendered words short
  and check the output — a misspelt word on a slide is worse than no word.
- For a slide graphic, ask for **negative space on one side** so the deck's copy has somewhere to
  sit: "wide composition, subject on the right third, clean empty space on the left".
- Generating variations: run the script two or three times with the same prompt (neither default
  takes a seed, so each run differs), then pick.
- The skill is `gen-image`, named for what it does rather than for whichever engine is currently
  best. `nano-banana` was the old address and it is gone; the model, not the skill, is the thing
  that changes.

## Icons: render a sheet, then slice

Never render icons one at a time. One render of a 4 by 4 sheet gives 16 icons that share a
style, for the price of one image. Tested 2026-10 on `nb2`, `gpt2` and `gpt25`: all three kept
a 4 by 4 grid with nothing overlapping, at 1:1.

**Prompt shape.** Two blocks, the sheet first, then the style:

- *Sheet:* "A sheet of 16 icons arranged in a strict 4 by 4 grid on a plain flat <colour>
  background. Every cell is the same size, evenly spaced with generous empty margin, each icon
  centred in its own cell, no icon touches or overlaps another. No grid lines, no borders, no
  labels, no numbers, no text of any kind." Then the 16 subjects, numbered in reading order.
  End with "All 16 icons share exactly the same style, line weight and scale."
- *Style:* the line (tool, weight, wobble, ends), the detail budget ("the outline plus at
  most three interior lines"), what is banned (hatching, shading, gradients), and the palette
  as hex codes, ending "Only those colours on the background."
- Ask for a line weight that "still reads at 48 pixels". Fine sketchy pencil styles look
  good on the sheet and fall apart at 64 px.
- Name a character literally when you need it: "a cartoon monkey, not an astronaut or robot".
  The GPT models turned a "robot monkey head" into an antenna robot.

**Slice.** `<skill-dir>/slice_sheet.py` cuts the sheet into one transparent PNG per icon:

```
python3 <skill-dir>/slice_sheet.py sheet.png icons/ --grid 4x4 --names pipe,seesaw,...
```

It keys out the background, trims each icon to its ink, pads it to a square (`--size`,
default 512) and writes `<name>-dark.png` too, with neutral ink swapped for a light colour
(`--dark-ink`) so the set works on dark slides while coloured accents keep their colour. Grid
lines snap to the emptiest gutter near their nominal position, because models drift a little
off a perfect grid; a cut that still crosses ink is printed, so check those cells by eye.
`--dark-drop-wash` leaves a pale wash out of the `-dark` copy (see House look). `--selftest` runs its built-in check. Needs Pillow and numpy.

**House look.** A fine hand-drawn ink line: two or three light overlapping passes, little
interior detail, no hatching or shading. On light backgrounds a flat light gold shape
(#E9D4A0) sits under the line: a copy of the icon's main silhouette, offset down and right by
one fixed share of the icon box, like a print whose colour plate is slightly out of register.
On dark backgrounds the line turns cream and has no wash.

- Render the sheet line only, then add the wash by script, free and deterministic:

  ```
  python3 <skill-dir>/shape_wash.py icons/hammer.png icons/scale.png -o washed/
  python3 <skill-dir>/shape_wash.py --strip strip.png icons/*.png   # 120 px test strip, two tints
  ```

  It closes small gaps in the line, fills enclosed holes, then erodes and dilates so thin
  strokes drop out and the shape follows the main body. A separate thin part (a dash, an
  arrow shaft) takes a modest thickening of its own stroke instead. The shape is flat and
  opaque with an anti-aliased edge, offset 4.2 % of the box (`--offset`), tint by `--tint`.
  Apply it to the light copies only; the `-dark` copies stay line only.
- For a drawing assembled from several icons, wash each piece at its own offset and lay every
  shape under every line. One shift for the whole drawing doubles thin dashed lines.
- Tested 2026-10: a wash rendered by the model (watercolour) and a noise-wobbled blob were
  both rejected; the shape-matched flat offset is the method.
- `--dark-drop-wash` remains for a sheet that was rendered with a wash: the `-dark` copy
  clears the pale wash and keeps the line, recoloured cream.
- A reference sheet's subjects win over the prompt's list: `nb2` redrew the reference's 16
  subjects and ignored swapped-in ones. Pass a reference whose subjects match the new sheet.

**Keep a set consistent across sheets.**

- Same style block, word for word, saved as a `.txt` beside the icons.
- Same model for the whole set. The models do not match each other's line.
- For sheet two onwards, use `nb2` and pass sheet one back as a reference. The script prints
  each result's public URL (`url:` on stderr); keep it in a log, then `--ref <that url>` and
  open the prompt with "The attached image is the style reference for this set. Match it
  exactly: the same line weight, wobble, accent and icon scale." The host's result URLs are
  temporary, so re-upload the saved sheet if the link has expired.

## After generating

- Save into the project that needs it, not a scratch dir, and reference it with a relative path.
- **Australian spelling applies to any text you ask the model to render** (see `~/.claude/CLAUDE.md`).
- Note in the artefact (a comment or a caption) that the image is AI-generated where the audience
  would reasonably want to know — a keynote illustration, yes; a background texture, no.
