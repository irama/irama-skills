#!/usr/bin/env python3
"""Self-check for semantic-search-shadow.py.

Run: python3 hooks/test_semantic_search_shadow.py  (exits non-zero on failure)
"""

import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "semantic-search-shadow.py")


def run(cmd, stdout, home, cwd="/tmp"):
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd},
               "tool_response": {"stdout": stdout, "stderr": ""}, "cwd": cwd, "session_id": "t"}
    r = subprocess.run([sys.executable, HOOK], input=json.dumps(payload), text=True,
                       capture_output=True, env={**os.environ, "HOME": home})
    log = os.path.join(home, ".claude/state/semantic-search/shadow.jsonl")
    rows = [json.loads(l) for l in open(log)] if os.path.exists(log) else []
    return r.stdout, rows


def main():
    walk = ("python3 - <<'PY'\nimport os\nROOT=\"docs\"; NEEDLE=\"trusted\"\n"
            "for dp,_,fs in os.walk(\"docs\"):\n    for f in fs:\n        if f.endswith('.md'): pass\nPY")
    with tempfile.TemporaryDirectory() as home:
        out, rows = run("cat docs/wiki/13-measure.md | grep -n -C3 'trusted'", "", home)
        assert out == "" and len(rows) == 1, (out, rows)
        assert rows[0]["route"] == "pipe" and rows[0]["domain"] == "doc" and rows[0]["needle"] == "trusted", rows[0]

        _, rows = run("sg --pattern 'refreshToken($A)' --lang ts src/lib | head -40", "", home)
        assert rows[-1]["route"] == "sg" and rows[-1]["domain"] == "code" and rows[-1]["path"] == "src/lib", rows[-1]

        _, rows = run(walk, "", home)
        assert rows[-1]["route"] == "walk" and rows[-1]["needle"] == "trusted" and rows[-1]["domain"] == "doc", rows[-1]

        _, rows = run("cat src/a.ts | grep -n foo", "12: foo()", home)  # a hit: not logged
        _, rows = run("ls -la", "", home)  # not a search: not logged
        assert len(rows) == 3, rows

        os.makedirs(os.path.join(home, ".claude/state/semantic-search"), exist_ok=True)
        open(os.path.join(home, ".claude/state/semantic-search/live"), "w").close()
        out, rows = run("cat notes/plan.md | grep -n 'cash buffer'", "", home)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        assert "semtools search" in ctx and rows[-1]["live"] is True, ctx
    print("ok")


if __name__ == "__main__":
    main()
