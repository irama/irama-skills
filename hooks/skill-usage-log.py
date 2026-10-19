#!/usr/bin/env python3
"""PostToolUse(Skill): append one line per skill call to a local usage log.

Feeds the quarterly skill stocktake: which skills are called, how often, from which
repo. Without it, retiring a skill is a guess. The log never leaves this machine.

Line format (tab-separated): ISO timestamp, skill name, repo folder name.
Always exits 0: a logging failure must never block the session.
"""

import datetime
import json
import os
import sys

LOG = os.path.expanduser("~/.claude/logs/skill-usage.tsv")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if payload.get("tool_name") != "Skill":
            return 0
        skill = payload.get("tool_input", {}).get("skill", "").strip()
        if not skill:
            return 0
        repo = os.path.basename(payload.get("cwd") or os.getcwd())
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        with open(LOG, "a") as f:
            f.write(f"{stamp}\t{skill}\t{repo}\n")
    except Exception as e:  # fail open, but say so
        print(f"skill-usage-log: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
