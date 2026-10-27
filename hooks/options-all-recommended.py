#!/usr/bin/env python3
"""Stop hook: every offered next step must be one the assistant recommends.

The rule (check an option's cost, benefit and risk before offering it, and offer
only what passes) already existed in prose and still got broken: the old format
asked for "exactly one (Recommended)" among up to three options, which forced a
non-recommended option onto the screen every time there were two. This checks the
label mechanically.

Blocks when a numbered line inside the *Next steps for us (options)* block lacks
"(Recommended". A DECIDE item that collapses mutually exclusive roads counts as one
option and must carry the recommended road. It cannot check that the analysis was
done, only that each option was individually judged worth doing.
"""

import json
import re
import sys

OPTION_LINE = re.compile(r"^\s*\d+[.)]\s+\S")


def options_block(text):
    """The numbered options section, up to the next heading, or '' if absent."""
    m = re.search(r"Next steps for us[^\n]*\n(.*?)(?=^#{1,6}\s|\Z)", text,
                  re.IGNORECASE | re.MULTILINE | re.DOTALL)
    return m.group(1) if m else ""


def unrecommended(text):
    return [ln.strip() for ln in options_block(text).splitlines()
            if OPTION_LINE.match(ln) and "(recommended" not in ln.lower()]


def last_assistant_text(transcript_path):
    try:
        with open(transcript_path, encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("type") != "assistant":
            continue
        content = (rec.get("message") or {}).get("content") or []
        parts = [c.get("text", "") for c in content
                 if isinstance(c, dict) and c.get("type") == "text"]
        if parts:
            return "\n".join(parts)
    return ""


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    if payload.get("stop_hook_active"):
        return                      # already looping; do not stack another block
    # The hook can fire before the final reply reaches the transcript, so the transcript's last
    # text is then the previous reply. The reply in the hook input wins when there is one.
    last = payload.get("last_assistant_message")
    if not (isinstance(last, str) and last.strip()):
        last = last_assistant_text(payload.get("transcript_path", ""))
    bad = unrecommended(last)
    if bad:
        print(json.dumps({
            "decision": "block",
            "reason": (
                "Next steps for us offers %d option(s) without (Recommended): %s. "
                "Offer only steps you recommend after weighing cost, benefit and "
                "risk. Drop each one that fails, and say in one line what you "
                "checked and why it is not worth doing. Mutually exclusive roads "
                "collapse into one DECIDE item carrying the recommended road."
                % (len(bad), " | ".join(b[:80] for b in bad))
            ),
        }))


if __name__ == "__main__":
    main()
