#!/usr/bin/env python3
"""PreToolUse(Write|Edit|MultiEdit): refuse edits to an existing lint, format or CI config.

An agent under pressure to pass a gate can weaken the gate instead of fixing the code:
loosen an ESLint rule, turn off a tsconfig strict flag, drop a CI step. This hook makes
the fix land in the code. Idea adapted from ECC's config-protection hook (MIT).

Creating a config that does not exist yet is allowed (a new project).
Override for one session when the config change is the task:
    export ALLOW_CONFIG_EDIT=1   (set by the human, never by the agent)

Exit 0 = allow. Exit 2 + stderr = block, message goes to the model.
"""

import json
import os
import sys

PROTECTED = {
    ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml", ".eslintrc.yaml",
    "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts",
    "eslint.config.mts", "eslint.config.cts",
    ".prettierrc", ".prettierrc.js", ".prettierrc.cjs", ".prettierrc.json", ".prettierrc.yml",
    ".prettierrc.yaml", "prettier.config.js", "prettier.config.cjs", "prettier.config.mjs",
    "biome.json", "biome.jsonc", ".ruff.toml", "ruff.toml", ".shellcheckrc",
    ".stylelintrc", ".stylelintrc.json", ".stylelintrc.yml",
    ".markdownlint.json", ".markdownlint.yaml", ".markdownlintrc",
    # The two other places a gate is weakened: TypeScript strictness and CI.
    "tsconfig.json",
}


def protected(path: str) -> bool:
    norm = path.replace("\\", "/")
    if "/.github/workflows/" in norm or norm.startswith(".github/workflows/"):
        return True
    return os.path.basename(norm) in PROTECTED


def main() -> int:
    if os.environ.get("ALLOW_CONFIG_EDIT") == "1":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return 0
    path = payload.get("tool_input", {}).get("file_path", "")
    if not path or not protected(path):
        return 0
    full = path if os.path.isabs(path) else os.path.join(payload.get("cwd") or os.getcwd(), path)
    if not os.path.exists(full):
        return 0
    print(
        f"Blocked: {os.path.basename(path)} is a lint, format, type or CI config, and it already exists.\n"
        "Fix the code so the check passes; do not weaken the check.\n"
        "If changing this config IS the task, stop and ask the user to run the session with "
        "ALLOW_CONFIG_EDIT=1.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
