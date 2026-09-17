#!/usr/bin/env python3
"""Self-check for require-git-hooks-before-push.sh.

Builds two throwaway repos: GATED has its core.hooksPath directory, UNGATED does not.
Each case feeds the hook a Bash tool call and checks allow (exit 0) or deny (exit 2).

Run: python3 hooks/test_require_git_hooks_before_push.py  (exits non-zero on failure)
"""

import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "require-git-hooks-before-push.sh")


def make_repo(root, name, with_hooks):
    path = os.path.join(root, name)
    os.makedirs(path)
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "config", "core.hooksPath", ".husky/_"], check=True)
    if with_hooks:
        os.makedirs(os.path.join(path, ".husky", "_"))
    return path


def run(cwd, cmd):
    payload = json.dumps({"cwd": cwd, "tool_input": {"command": cmd}})
    return subprocess.run(["bash", HOOK], input=payload, capture_output=True, text=True).returncode


def main():
    with tempfile.TemporaryDirectory() as root:
        gated = make_repo(root, "gated", True)
        ungated = make_repo(root, "ungated", False)
        cases = [
            ("plain push from a gated repo", gated, "git push", 0),
            ("plain push from an ungated repo", ungated, "git push origin main", 2),
            ("git -C into an ungated repo from a gated cwd", gated, f"git -C {ungated} push origin main", 2),
            ("git -C into a gated repo from an ungated cwd", ungated, f"git -C {gated} push", 0),
            ("cd into an ungated repo, then push", gated, f"cd {ungated} && git push", 2),
            ("relative git -C", root, "git -C ungated push", 2),
            ("loop with the path in a variable", gated,
             'for W in a b; do git -C "$W" push origin HEAD:main; done', 2),
            ("cd into a variable path, then push", gated, 'cd "$dir" && git push', 2),
            ("--no-verify", gated, "git push --no-verify", 2),
            ("--no-verify with the explicit escape", gated, "ALLOW_UNGATED_PUSH=1 git push --no-verify", 0),
            ("deletion-only push into an ungated repo", gated, f"git -C {ungated} push origin --delete old", 0),
            ("dry run into an ungated repo", gated, f"git -C {ungated} push --dry-run", 0),
            ("rtk-prefixed push into an ungated repo", gated, f"rtk git -C {ungated} push", 2),
            # Review findings: pushes that used to slip through.
            ("push inside a subshell", gated, f"(cd {ungated} && git push)", 2),
            ("push inside bash -c", gated, f"bash -c 'cd {ungated} && git push'", 2),
            ("push behind sudo", gated, f"sudo git -C {ungated} push", 2),
            ("push behind timeout", gated, f"timeout 60 git -C {ungated} push", 2),
            ("push fed by xargs", gated, "echo a | xargs -I{} git -C {} push", 2),
            ("push after a background job", ungated, "true & git push", 2),
            ("hooksPath switched off with -c", gated, "git -c core.hooksPath=/dev/null push", 2),
            ("hooksPath switched off, any case", gated, "git -c core.hookspath=x push", 2),
            ("--work-tree= form", gated, f"git --work-tree={ungated} --git-dir={ungated}/.git push", 2),
            ("escape inside an echo does not count", gated,
             'echo ALLOW_UNGATED_PUSH=1; git push --no-verify', 2),
            ("cd inside a subshell does not leak", ungated, f"(cd {gated}) && git push", 2),
            ("cd - is unresolved", gated, "cd - && git push", 2),
            # Review findings: ordinary commands that used to be refused.
            ("push text inside a commit message", ungated, "git commit -m 'fix; git push later'", 0),
            ("--no-verify text inside a commit message", gated,
             'git commit -m "note; git push --no-verify is refused"', 0),
            ("push lines inside a heredoc", ungated,
             "cat > /tmp/x.sh <<'EOF'\ngit -C $W push\nEOF\necho done", 0),
            ("cd $HOME expands instead of being refused", gated, "cd $HOME && git push", 0),
            ("cd to the toplevel substitution", gated,
             "cd $(git rev-parse --show-toplevel) && git push", 0),
            ("cd to an unrelated substitution is unresolved", gated, "cd $(mktemp -d) && git push", 2),
            ("not a push", ungated, "git status", 0),
            ("push only inside a string", ungated, 'echo "git push" && git commit -m "fix push"', 0),
        ]
        failed = 0
        for name, cwd, cmd, want in cases:
            got = run(cwd, cmd)
            ok = got == want
            failed += not ok
            print(f"{'ok  ' if ok else 'FAIL'} {name}: want {want}, got {got}")
    if failed:
        print(f"{failed} case(s) failed")
        sys.exit(1)
    print("all cases passed")


if __name__ == "__main__":
    main()
