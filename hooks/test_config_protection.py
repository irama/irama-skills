#!/usr/bin/env python3
"""Self-check for config-protection.py and skill-usage-log.py.

Run: python3 hooks/test_config_protection.py  (exits non-zero on failure)
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "config-protection.py")
LOGGER = os.path.join(HERE, "skill-usage-log.py")


def run(hook, payload, env=None):
    return subprocess.run([sys.executable, hook], capture_output=True, text=True,
                          input=json.dumps(payload), env={**os.environ, **(env or {})})


def blocked(tool, path, env=None):
    return run(GUARD, {"tool_name": tool, "tool_input": {"file_path": path}}, env).returncode == 2


def main():
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, ".github", "workflows"))
        for name in ("eslint.config.mjs", "tsconfig.json", ".github/workflows/ci.yml"):
            open(os.path.join(d, name), "w").close()
        assert blocked("Edit", os.path.join(d, "eslint.config.mjs")), "existing lint config"
        assert blocked("Write", os.path.join(d, "tsconfig.json")), "existing tsconfig"
        assert blocked("MultiEdit", os.path.join(d, ".github/workflows/ci.yml")), "CI workflow"
        assert not blocked("Write", os.path.join(d, "biome.json")), "new config is allowed"
        assert not blocked("Edit", os.path.join(d, "src.ts")), "ordinary file"
        assert not blocked("Edit", os.path.join(d, "tsconfig.json"), {"ALLOW_CONFIG_EDIT": "1"}), "override"

        home = os.path.join(d, "home")
        r = run(LOGGER, {"tool_name": "Skill", "tool_input": {"skill": "commit"}, "cwd": "/x/my-repo"},
                {"HOME": home})
        assert r.returncode == 0
        line = open(os.path.join(home, ".claude/logs/skill-usage.tsv")).read().strip().split("\t")
        assert line[1:] == ["commit", "my-repo"], line
        assert run(LOGGER, {"tool_name": "Bash"}, {"HOME": home}).returncode == 0, "ignores other tools"
    print("ok")


if __name__ == "__main__":
    main()
