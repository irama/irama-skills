---
name: gen-image
description: Generate images with GPT Image 2 (the default) or another hosted model — Nano Banana 2, Seedream, Qwen Image Edit Plus, Midjourney v7, Z-Image Turbo — and save them straight into the current project. Use when an artefact needs a generated image (slide, hero, illustration, thumbnail, texture, mockup background), when the user says "generate an image", "gen image", "nano banana", "make me a picture/illustration", or invokes /gen-image. Also handles image-to-image via reference URLs.
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

`--model` picks the engine. Default `gpt2`.

| `--model` | Engine | Notes |
|---|---|---|
| `gpt2` | GPT Image 2 (`gpt-image-2`) | **The default.** Strongest prompt adherence, and the one to reach for on a brief with several constraints in it. |
| `nb2` | Nano Banana 2 (`gemini-3.1-flash-image-preview`) | Up to 14 reference images, so it is still the pick for image-to-image and for holding a style across a set. No seed. |
| `seedream` | Seedream 5.0 Lite | Up to 14 refs. Painterly, good at atmosphere. |
| `qwen` | Qwen Image Edit Plus | Up to 3 refs, supports seed + negative prompt. Best for *editing* a supplied image. |
| `mj` | Midjourney v7 | Most stylised. References go inline in the prompt; the script handles that. |
| `zimage` | Z-Image Turbo | Text-to-image only, fastest, cheapest. |

## Options

- `--size` — aspect ratio string, e.g. `16:9` (slides), `1:1`, `4:5`, `9:16`. Not pixels.
- `--ref <url>` — reference image, repeatable. Must be a **public URL** the provider can fetch;
  a local path will not work. For image-to-image on local files, upload the file first.
- `--timeout <seconds>` — default 600.

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
- Nano Banana 2 handles **text in images** better than most; still keep any rendered words short
  and check the output — a misspelt word on a slide is worse than no word.
- For a slide graphic, ask for **negative space on one side** so the deck's copy has somewhere to
  sit: "wide composition, subject on the right third, clean empty space on the left".
- Generating variations: run the script two or three times with the same prompt (neither default
  takes a seed, so each run differs), then pick.
- The skill is `gen-image`, named for what it does rather than for whichever engine is currently
  best. `nano-banana` was the old address and it is gone; the model, not the skill, is the thing
  that changes.

## After generating

- Save into the project that needs it, not a scratch dir, and reference it with a relative path.
- **Australian spelling applies to any text you ask the model to render** (see `~/.claude/CLAUDE.md`).
- Note in the artefact (a comment or a caption) that the image is AI-generated where the audience
  would reasonably want to know — a keynote illustration, yes; a background texture, no.
