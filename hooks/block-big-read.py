#!/usr/bin/env python3
"""PreToolUse(Read): refuse an unbounded read of a large text file.

Re-measured 2026-08-03: Read returns 12.15MB of tool-result bytes across 3,799
calls; Bash returns 19.59MB across 25,686. Bash is the larger total but each of
its results is tiny, while Read is the rare-and-enormous tool — median 1,889
chars, p99 34,622, max 131,484 — and every byte it pulls in is re-read by every
later request in the session. That multiplier, not the raw share, is the cost.

So: reads under the threshold pass untouched (the median read never sees this
hook), and an unbounded read of anything bigger is refused with the three
cheaper routes. A read that already declares offset/limit is always allowed —
the point is to stop *whole-file* pulls, not range reads.

Exit 0 = allow. Exit 2 + stderr = block, message goes to the model.
"""

import json
import os
import sys

# ~10,000 chars ≈ 250 lines ≈ 2.5k tokens. Sits between the fleet's p90 (9,276)
# and p99 (34,622) read, so routine work never trips it.
THRESHOLD = 10_000

# Formats a range read can't help with: images are read whole or not at all
# (and are only ~1% of context cost), PDFs page via `pages`, notebooks by cell.
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico", ".avif",
    ".pdf", ".ipynb",
}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # never block on a malformed payload

    if payload.get("tool_name") != "Read":
        return 0

    inp = payload.get("tool_input") or {}
    path = inp.get("file_path")
    if not isinstance(path, str) or not path:
        return 0

    # A range read is exactly what we want — let it through.
    if inp.get("offset") is not None or inp.get("limit") is not None or inp.get("pages"):
        return 0

    if os.path.splitext(path)[1].lower() in BINARY_EXT:
        return 0

    try:
        size = os.path.getsize(path)
    except OSError:
        return 0  # missing/unreadable — let the tool report it properly

    if size <= THRESHOLD:
        return 0

    print(
        f"Unbounded Read refused: {path} is {size:,} bytes (~{size // 40:,} lines) — over the "
        f"{THRESHOLD:,}-byte whole-file limit.\n\n"
        "A single Read result is several KB, and whatever it pulls in is re-read by every\n"
        "later request in this session. Pick the cheapest route that answers\n"
        "your actual question:\n\n"
        "1. KNOW ROUGHLY WHERE IT IS -> range read (always allowed):\n"
        "     Read(file_path=..., offset=<line>, limit=<count>)\n\n"
        "2. LOOKING FOR A PATTERN/SYMBOL -> ast-grep, then range-read the hit:\n"
        "     sg --pattern 'function $NAME($$$) { $$$ }' --lang ts <path>\n\n"
        "3. GENUINELY NEED THE WHOLE FILE -> delegate the read to a subagent and keep only\n"
        "   its conclusion — the subagent's context dies with it. Give it a return budget in\n"
        "   lines as the prompt's LAST line, or the delegation can cost more than the read:\n"
        "   55% of 1,064 agent returns exceeded 3KB, worst 26KB.\n"
        "     Agent(subagent_type='Explore' | 'semble-search', prompt='read <path> and report ...')\n",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
