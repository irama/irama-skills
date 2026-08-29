#!/usr/bin/env python3
"""Statusline segment: this thread's turn count + estimated API-equivalent cost.

Passive readout only — no prompt, no nudge, no auto-compact. Cost per turn grows
with conversation length (97% of spend is cache reads), so the point of this is
simply to make session length visible while it is still cheap to act on.

Reads the statusline JSON on stdin, streams the session transcript, and prints
e.g.  ⟳84 $18.30  — the count is API requests, not human turns; amber from 150, red from 300.

Incremental: per-session state in /tmp keeps a byte offset so each render only
parses the bytes appended since the last one.
"""

import glob
import json
import os
import sys

# Per-Mtok rates. Cache reads bill at 0.1x input, cache writes at 1.25x.
# This table will go stale — it lives here, in one place, for that reason.
RATES = {
    "opus": (5.30, 26.50),
    "fable": (10.90, 54.70),
    "sonnet-4-6": (3.20, 16.10),
    "sonnet": (2.10, 10.40),
    "haiku": (1.00, 5.10),
}
DEFAULT_RATE = RATES["opus"]

# `turns` counts API requests (assistant messages carrying usage), NOT human
# turns — which is the metric that actually tracks cost. Thresholds track
# CLAUDE.md § Session length is the cost driver: nudge around 150, and a session
# well past that is a defect, not a long session.
AMBER, RED = 150, 300
STATE_DIR = "/tmp/cc-statusline-cost"


def rate_for(model: str):
    m = (model or "").lower()
    if "sonnet-4-6" in m or "sonnet-4.6" in m:
        return RATES["sonnet-4-6"]
    for key in ("opus", "fable", "sonnet", "haiku"):
        if key in m:
            return RATES[key]
    return DEFAULT_RATE


def cost_of(usage: dict, model: str) -> float:
    rin, rout = rate_for(model)
    billed_in = (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0) * 0.1
        + usage.get("cache_creation_input_tokens", 0) * 1.25
    )
    return (billed_in * rin + usage.get("output_tokens", 0) * rout) / 1_000_000


def fresh() -> dict:
    return {"offsets": {}, "turns": 0, "cost": 0.0, "subcost": 0.0, "seen": set()}


def load_state(path: str) -> dict:
    try:
        with open(path) as f:
            s = json.load(f)
        # "offsets" is a dict keyed by file — a session spans the main transcript
        # plus one file per subagent. Older single-offset state is discarded.
        return {"offsets": dict(s["offsets"]), "turns": s["turns"], "cost": s["cost"],
                "subcost": s.get("subcost", 0.0), "seen": set(s["seen"])}
    except Exception:
        return fresh()


def save_state(path: str, st: dict) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({**st, "seen": list(st["seen"])}, f)
        os.replace(tmp, path)
    except Exception:
        pass


def scan(path: str, st: dict, is_sub: bool) -> None:
    """Read the bytes appended to one transcript since the last render.

    Subagent turns live in their own files, never in the main transcript, so they
    can't inflate the turn count — but their spend is real and caused by this
    thread, so it is charged to the session while being kept out of `turns`
    (which is a proxy for how long *this* context has grown).
    """
    with open(path, "r", errors="ignore") as f:
        f.seek(st["offsets"].get(path, 0))
        pos = st["offsets"].get(path, 0)
        for line in f:
            if not line.endswith("\n"):
                break  # partial trailing write — leave it for the next render
            pos += len(line.encode("utf-8", "ignore"))
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("type") != "assistant":
                continue
            msg = rec.get("message") or {}
            usage = msg.get("usage")
            if not usage:
                continue
            # One assistant turn can emit several records sharing a message id;
            # without this dedupe both the count and the cost inflate.
            key = f"{msg.get('id')}|{rec.get('requestId')}"
            if key in st["seen"]:
                continue
            st["seen"].add(key)
            c = cost_of(usage, msg.get("model", ""))
            if is_sub:
                st["subcost"] += c
            else:
                st["turns"] += 1
                st["cost"] += c
        st["offsets"][path] = pos


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    transcript = payload.get("transcript_path")
    session_id = payload.get("session_id") or "unknown"
    if not transcript or not os.path.isfile(transcript):
        return 0  # fresh session, first render — print nothing

    state_path = os.path.join(STATE_DIR, session_id.replace("/", "_") + ".json")
    st = load_state(state_path)

    try:
        if os.path.getsize(transcript) < st["offsets"].get(transcript, 0):
            # Transcript shrank (compaction/rewrite) — every offset is meaningless.
            st = fresh()
        scan(transcript, st, False)
        # Subagent transcripts sit beside the main one, under
        # <project>/<session_id>/subagents/agent-*.jsonl. Measured 2026-07-25:
        # they add 10.7% of fleet spend overall and up to 427% within a single
        # session, so leaving them out understates a delegation-heavy thread badly.
        for sub in glob.glob(os.path.join(os.path.dirname(transcript), session_id,
                                          "subagents", "agent-*.jsonl")):
            try:
                scan(sub, st, True)
            except OSError:
                continue
    except OSError:
        return 0

    save_state(state_path, st)

    if st["turns"] == 0:
        return 0

    total = st["cost"] + st["subcost"]
    colour = 244 if st["turns"] < AMBER else (214 if st["turns"] < RED else 196)
    sys.stdout.write(f"\033[38;5;{colour}m⟳{st['turns']} ${total:.2f}\033[0m")
    # Break out the delegated share once it is material — it is spend this thread
    # caused but did not carry in its own context, so it reads differently.
    if st["subcost"] >= 0.5:
        sys.stdout.write(f"\033[38;5;244m (+${st['subcost']:.2f} sub)\033[0m")

    # Weekly rate-limit burn, straight from the payload — free to show, and the
    # number that actually decides whether a long session matters today.
    pct = ((payload.get("rate_limits") or {}).get("seven_day") or {}).get("used_percentage")
    if isinstance(pct, (int, float)):
        c = 244 if pct < 70 else (214 if pct < 90 else 196)
        sys.stdout.write(f" \033[38;5;{c}m7d {pct:.0f}%\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
