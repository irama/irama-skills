#!/usr/bin/env python3
"""Self-check for block-broad-pkill.py.

Run: python3 hooks/test_block_broad_pkill.py  (exits non-zero on failure)
"""

import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "block-broad-pkill.py")


def blocked(cmd):
    r = subprocess.run([sys.executable, HOOK], capture_output=True, text=True,
                       input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}))
    return r.returncode == 2


def main():
    assert blocked('cd /x && pkill -f "next dev" -f 2>/dev/null; lsof -ti :4691'), "the incident"
    assert blocked("pkill -f a"), "short pattern"
    assert blocked("sudo pkill node vite"), "two patterns"
    assert not blocked('pkill -f "next dev"'), "one specific pattern"
    assert not blocked('pkill -9 -U irama -f "brief-deliver /tmp/x.html"'), "options with values"
    assert not blocked("lsof -ti :3001 | xargs kill"), "kill by port"
    assert not blocked("echo pkill -f x"), "pkill not the command"
    print("ok")


if __name__ == "__main__":
    main()
