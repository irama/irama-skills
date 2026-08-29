#!/usr/bin/env python3
"""Generate an image with Nano Banana 2 (or another hosted model) and save it locally.

    python3 generate.py --prompt "a lone lighthouse in fog" --out ~/Desktop/lighthouse.png
    python3 generate.py --model seedream --size 1:1 --ref https://... --prompt "..." --out out.png

Submit → poll → download, against the same image API host a companion app uses. Key
resolution order: $EVOLINK_API_KEY, then the key in that app's gitignored .env.local
(never copied, only read).
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

API = "https://api.evolink.ai/v1"
UA = "nano-banana-skill/1.0"
# Optional fallback: a path to another app's env file holding an EVOLINK_API_KEY.
# Unset by default, because the path names somebody's private project and because
# billing your images to another app's production key should be opted into, not
# inherited. Set GEN_IMAGE_FALLBACK_ENV to use it.
FALLBACK_ENV = os.path.expanduser(os.environ.get("GEN_IMAGE_FALLBACK_ENV", ""))

# Internal name → host model string. Matches the companion app's generate route.
MODELS = {
    "gpt2": "gpt-image-2",                     # the default: strongest prompt adherence
    "nb2": "gemini-3.1-flash-image-preview",   # Nano Banana 2 — up to 14 refs, no seed
    "seedream": "doubao-seedream-5.0-lite",    # up to 14 refs, quality param
    "qwen": "qwen-image-edit-plus",            # up to 3 refs, seed + negative prompt
    "zimage": "z-image-turbo",                 # text-to-image only
    "mj": "mj-v7",                             # Midjourney syntax; refs go in the prompt
}


PLACEHOLDER = "PASTE_CLAUDE_SKILLS_EVOLINK_KEY_HERE"


def api_key() -> str:
    key = (os.environ.get("EVOLINK_API_KEY") or "").strip()
    if key and key != PLACEHOLDER:
        return key
    # Fallback: another app's PRODUCTION key. It works, but every image generated this
    # way bills to that app and lands on its spend tile. Attribution by API key cannot
    # tell these images from that app's users'. Loud, not silent.
    if not FALLBACK_ENV:
        sys.exit("No API key. Set EVOLINK_API_KEY in your shell profile.")
    try:
        with open(FALLBACK_ENV, encoding="utf-8") as fh:
            m = re.search(r"^EVOLINK_API_KEY=(.+)$", fh.read(), re.M)
        if m:
            print(
                "WARNING: no dedicated EVOLINK_API_KEY set — falling back to the "
                "companion app's production key, so this image bills to that app. Fix: create a "
                "'claude-skills' key at https://evolink.ai/dashboard/keys and paste it "
                "into the EVOLINK_API_KEY export in ~/.zshrc.",
                file=sys.stderr,
            )
            return m.group(1).strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    sys.exit("No API key. Set EVOLINK_API_KEY in your shell profile, or point "
             "GEN_IMAGE_FALLBACK_ENV at an env file that holds one.")


def call(path: str, key: str, body=None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body is not None else None,
        # The host 403s the default urllib User-Agent, so send a real one.
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "User-Agent": UA},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True, help="where to write the image")
    ap.add_argument("--model", default="gpt2", choices=sorted(MODELS))
    ap.add_argument("--size", default="16:9", help="aspect ratio, e.g. 16:9, 1:1, 4:5")
    ap.add_argument("--ref", action="append", default=[], help="reference image URL (repeatable)")
    ap.add_argument("--timeout", type=int, default=600, help="seconds to wait before giving up")
    a = ap.parse_args()

    key = api_key()
    body = {"model": MODELS[a.model], "prompt": a.prompt, "size": a.size}
    if a.ref:
        # mj takes references inline in the prompt; everything else takes image_urls.
        if a.model == "mj":
            body["prompt"] = " ".join(a.ref) + " " + a.prompt + f" --ar {a.size}"
        else:
            body["image_urls"] = a.ref[:14]

    task = call("/images/generations", key, body)
    task_id = task.get("id")
    if not task_id:
        sys.exit("No task id in submit response: " + json.dumps(task)[:400])
    print("task", task_id, "submitted", file=sys.stderr)

    deadline = time.time() + a.timeout
    while time.time() < deadline:
        time.sleep(3)
        st = call("/tasks/" + task_id, key)
        status = st.get("status")
        if status in ("pending", "processing"):
            continue
        if status == "failed":
            sys.exit("Generation failed: " + json.dumps(st.get("error"))[:400])
        urls = st.get("results") or []
        if not urls:
            sys.exit("Completed with no results: " + json.dumps(st)[:400])
        out = os.path.expanduser(a.out)
        dl = urllib.request.Request(urls[0], headers={"User-Agent": UA})
        with urllib.request.urlopen(dl, timeout=120) as res, open(out, "wb") as fh:
            fh.write(res.read())
        print(out)
        for extra in urls[1:]:
            print("also:", extra, file=sys.stderr)
        return
    sys.exit("Timed out after %ds — task %s may still finish; poll %s/tasks/%s"
             % (a.timeout, task_id, API, task_id))


if __name__ == "__main__":
    main()
