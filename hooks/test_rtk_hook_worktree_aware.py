#!/usr/bin/env python3
"""Self-check for rtk-hook-worktree-aware.py. Needs `rtk` on PATH.

Run: python3 hooks/test_rtk_hook_worktree_aware.py  (exits non-zero on failure)
"""

import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rtk-hook-worktree-aware.py")
WT = "/repo/.claude/worktrees/feature"


def rewrite(cwd, cmd):
    out = subprocess.run([sys.executable, HOOK], capture_output=True, text=True,
                         input=json.dumps({"tool_name": "Bash", "cwd": cwd,
                                           "tool_input": {"command": cmd}})).stdout
    return json.loads(out)["hookSpecificOutput"]["updatedInput"]["command"] if out.strip() else None


def main():
    assert rewrite(WT, "git status") is None, "git in a worktree runs plain"
    assert rewrite(WT, "git add -A && npx vitest run") is None, "any git in the command"
    assert rewrite(WT + "/src", "cd .. && git log") is None, "subdirectory of a worktree"
    assert rewrite(WT, "npx vitest run") == "rtk vitest", "non-git still rewritten"
    assert rewrite("/repo", "git status") == "rtk git status", "main checkout keeps RTK"
    print("ok")


if __name__ == "__main__":
    main()
