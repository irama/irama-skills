#!/usr/bin/env python3
"""Stop hook: refuse to end a turn while this thread still holds open work.

A claim in the cross-thread work register stays open until its thread says what
happened to it. Nothing else can say: another thread cannot know whether the job
finished, stalled or was abandoned, and a claim nobody closes locks the key for
every other thread forever. So the thread that took the work is made to sign off
before it stops talking.

`blocked` and `waiting-on-user` count as signed off, and deliberately keep the
claim held. That is the point: the thread has said what state the work is in, and
until it says otherwise nobody else may take it.

Block-and-reason shape copied from handoff-ends-next-steps.py, including its
`stop_hook_active` guard — without which the hook stacks blocks on itself.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "threads" / "assets"))


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    if payload.get("stop_hook_active"):
        return                      # already looping; do not stack another block

    try:
        import register
        session_id = payload.get("session_id") or ""
        os.environ["CLAUDE_SESSION_ID"] = session_id      # how register.py finds us
        _, _, _, by_thread = register.picture()
        open_here = [c for c in by_thread.get(session_id, [])
                     if c.get("state") in register.OPEN]
    except Exception:
        return                      # fail open: the register is not a safety system

    if not open_here:
        return

    keys = ", ".join(c["key"] for c in open_here)
    statuses = " ".join(sorted(register.STATUSES - register.OPEN))
    print(json.dumps({
        "decision": "block",
        "reason": (
            "This thread still holds open work in the register: %s. Say what "
            "happened to each one before ending the turn:\n"
            "  CLAUDE_SESSION_ID=%s python3 ~/.claude/skills/threads/assets/"
            "register.py sign-off <key> --status <status> --note '<one line>'\n"
            "Statuses: %s. `blocked` and `waiting-on-user` keep the claim held, "
            "which is correct when the work is real but stopped — nobody else may "
            "take it. `incomplete` and `abandoned` hand it back. Then re-send."
            % (keys, session_id, statuses)
        ),
    }))


if __name__ == "__main__":
    main()
