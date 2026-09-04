#!/usr/bin/env python3
"""SessionStart: give this thread an identity in the cross-thread work register.

Twenty sessions run at once and none can see the others. `register.py` is the
shared store they claim work in, but a thread cannot claim anything until the
register knows it exists, knows its process, and knows which transcript to read
its quiet time from. This hook is that one write, and nothing else.

The thread name is the working directory plus six characters of the session id:
short enough to type at `/threads show`, unique enough that two threads in the
same repo are still tellable apart.

Fails open, always. A SessionStart hook that raises makes every thread unusable,
and the register is a convenience, not a safety system.
"""

import json
import sys
from pathlib import Path

# hooks/ and skills/ are siblings in the repo, and ~/.claude/hooks and
# ~/.claude/skills both symlink into it, so resolving this file gets there from
# either side.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "threads" / "assets"))


def thread_name(cwd, session_id):
    return f"{Path(cwd).name}-{(session_id or '?')[:6]}"


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    try:
        import register
        cwd = payload.get("cwd") or str(Path.cwd())
        session_id = payload.get("session_id") or ""
        register.register_session(
            session_id,
            thread_name(cwd, session_id),
            payload.get("transcript_path") or "",
            cwd,
        )
    except Exception:
        return                      # fail open: never block a session start


if __name__ == "__main__":
    main()
