#!/usr/bin/env python3
"""Self-check for heavy-job-gate.py.

Run: python3 hooks/test_heavy_job_gate.py  (exits non-zero on failure)

Hermetic: HOME points at a temp dir that holds a stand-in heavy-job, and the
command runs in a temp project whose package.json copies a real app's scripts.
"""

import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "heavy-job-gate.py")

SCRIPTS = {
    "build": "next build",
    "test": "vitest",
    "test:run": "vitest run",
    "typecheck": "tsc --noEmit",
    "lint": "eslint src --fix",
    "dev": "next dev",
    "check": "pnpm run typecheck && pnpm run lint && pnpm run test:run && pnpm run build",
    "conformance": "vitest run --reporter=json --outputFile=x.json; node report.mjs --strict",
}

# (command, should it be denied?)
TABLE = [
    # full suites
    ("vitest", True),
    ("vitest run", True),
    ("vitest --run", True),
    ("npx vitest run", True),
    ("rtk vitest", True),                       # RTK's own rewrite of `vitest run`
    ("rtk vitest run", True),
    ("vitest run src", True),                   # a directory is a full suite
    ("vitest run --project db", True),          # option value is not a filter
    ("CI=1 vitest run", True),
    ("timeout 600 vitest run", True),
    ("nice -n 10 env FOO=1 time vitest run", True),
    ("cd sub && pnpm test:run", True),          # resolves the parent package.json
    ("pnpm test:run", True),
    ("pnpm test", True),
    ("pnpm run test:run", True),
    ("npm test", True),
    ("npm run test:run 2>&1 | tail -20", True),
    ("yarn test:run", True),
    ("pnpm exec vitest run", True),
    ("pnpm vitest run", True),                  # pnpm runs a bin when no script matches
    ("pnpm run conformance", True),
    ("bash -c 'pnpm test:run'", True),
    ("sh -lc \"cd sub; vitest run\"", True),
    ("(cd sub && pnpm test:run)", True),
    ("git status && pnpm test:run; echo done", True),
    # builds
    ("next build", True),
    ("rtk next build", True),
    ("vite build", True),
    ("pnpm build", True),
    ("npm run build", True),
    ("pnpm check", True),                       # check runs next build
    ("pnpm -r build", True),
    ("pnpm --filter app build", True),
    # always denied
    ("~/.claude/scripts/heavy-job record --repo r --tree t --gate g", True),
    ("HEAVY_JOB_HELD=1 pnpm test:run", True),
    ("export HEAVY_JOB_HELD=1", True),
    ("env HEAVY_JOB_HELD=1 vitest run", True),
    ("~/.claude/scripts/heavy-job run -- ~/.claude/scripts/heavy-job record --repo r", True),
    ("~/.claude/scripts/heavy-job run -- HEAVY_JOB_HELD=1 pnpm test:run", True),
    ("~/.claude/scripts/heavy-job run -- bash -c 'heavy-job record --repo r'", True),
    ("pnpm exec heavy-job record --repo r", True),
    ("xargs /x/heavy-job record --repo r", True),
    # a here-string is not a here-doc: the next line still runs
    ("cat <<< \"x\"\nvitest run", True),
    # allowed: named files, name filters, slotted, unrelated
    ("vitest run src/lib/x.test.ts", False),
    ("vitest run -t 'parses headers'", False),
    ("vitest run --testNamePattern=parses", False),
    ("vitest run reply-recipients", False),     # a filename filter, not a directory
    ("pnpm test -- src/lib/x.test.ts", False),
    ("pnpm test:run src/lib/x.spec.tsx", False),
    ("npx vitest run src/lib/x.test.ts", False),
    ("rtk vitest run src/a.test.ts src/b.test.ts", False),
    ("~/.claude/scripts/heavy-job run -- rtk vitest run", False),
    ("~/.claude/scripts/heavy-job run -- pnpm build", False),
    ("cd sub && ~/.claude/scripts/heavy-job run -- pnpm test:run", False),
    ("~/.claude/scripts/heavy-job waits --since 2026-10-01", False),
    ("~/.claude/scripts/heavy-job passed --repo r --tree t --gate g", False),
    ("git push origin main", False),
    ("bash scripts/ci-gate.sh --attest", False),
    ("pnpm typecheck", False),
    ("pnpm lint", False),
    ("pnpm dev", False),
    ("pnpm install", False),
    ("next dev", False),
    ("echo vitest run", False),
    ("git commit -m 'run vitest run and next build under HEAVY_JOB_HELD=1'", False),
    ("cat <<'EOF' > notes.txt\nvitest run\nit's fine\nEOF", False),
    ("ls 'unbalanced", False),                  # unparseable: fail open
]


def run_hook(cmd, home, cwd):
    env = dict(os.environ, HOME=home)
    env.pop("HEAVY_JOB_HELD", None)
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd}
    r = subprocess.run([sys.executable, HOOK], capture_output=True, text=True,
                       input=json.dumps(payload), env=env)
    assert r.returncode == 0, f"hook exit {r.returncode} for {cmd!r}: {r.stderr}"
    if not r.stdout.strip():
        return None
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny", out
    return out["permissionDecisionReason"]


def main():
    fails = 0
    with tempfile.TemporaryDirectory() as tmp:
        home = os.path.join(tmp, "home")
        proj = os.path.join(tmp, "proj")
        os.makedirs(os.path.join(home, ".claude", "scripts"))
        os.makedirs(os.path.join(proj, "src", "lib"))
        os.makedirs(os.path.join(proj, "sub"))
        hj = os.path.join(home, ".claude", "scripts", "heavy-job")
        with open(hj, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(hj, 0o755)
        with open(os.path.join(proj, "package.json"), "w") as f:
            json.dump({"scripts": SCRIPTS}, f)

        for cmd, want in TABLE:
            got = run_hook(cmd, home, proj) is not None
            if got != want:
                fails += 1
                print(f"FAIL {'deny' if want else 'allow'} expected: {cmd!r}")

        # The reason carries the exact slotted command.
        why = run_hook("pnpm test:run", home, proj) or ""
        if "~/.claude/scripts/heavy-job run -- rtk vitest run" not in why:
            fails += 1
            print(f"FAIL vitest reason lacks the rtk form: {why!r}")
        why = run_hook("pnpm build", home, proj) or ""
        if "~/.claude/scripts/heavy-job run -- pnpm build" not in why:
            fails += 1
            print(f"FAIL build reason lacks the slotted command: {why!r}")
        why = run_hook("cd sub && pnpm check", home, proj) or ""
        if "heavy-job run -- bash -c 'cd sub && pnpm check'" not in why:
            fails += 1
            print(f"FAIL chain reason does not wrap the whole command: {why!r}")

        # Run the suggestion: a stand-in heavy-job execs the words after `--` (no shell,
        # like the real one) and a stub pnpm prints its args and $CI.
        with open(hj, "w") as f:
            f.write('#!/bin/sh\n[ "$1" = run ] && shift\n[ "$1" = -- ] && shift\nexec "$@"\n')
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir)
        with open(os.path.join(bindir, "pnpm"), "w") as f:
            f.write('#!/bin/sh\necho "pnpm $* CI=$CI"\n')
        os.chmod(os.path.join(bindir, "pnpm"), 0o755)
        env = dict(os.environ, HOME=home, PATH=bindir + os.pathsep + os.environ["PATH"])
        for cmd, log, want in [
            ("CI=1 pnpm build", None, "pnpm build CI=1"),
            ("pnpm build > b.log 2>&1", "b.log", "pnpm build CI="),
            ("pnpm build > c.log 2>&1 &", "c.log", "pnpm build CI="),
            ("pnpm build &", None, "pnpm build CI="),
        ]:
            why = run_hook(cmd, home, proj) or ""
            sug = next((ln for ln in why.splitlines() if ln.startswith("~/")), "")
            r = subprocess.run(["bash", "-c", sug + '\nrc=$?\n[ -n "$!" ] && { wait $!; rc=$?; }\nexit $rc'], cwd=proj, env=env,
                               capture_output=True, text=True)
            path = os.path.join(proj, log) if log else ""
            out = (open(path).read() if os.path.exists(path) else "") if log else r.stdout
            if r.returncode != 0 or want not in out:
                fails += 1
                print(f"FAIL suggestion for {cmd!r} did not run: {sug!r} rc={r.returncode} "
                      f"out={out!r} err={r.stderr!r}")

        # Fail open: no heavy-job installed, and a payload that is not JSON.
        os.remove(hj)
        if run_hook("pnpm test:run", home, proj) is not None:
            fails += 1
            print("FAIL denied with heavy-job missing")
        r = subprocess.run([sys.executable, HOOK], input="not json", capture_output=True,
                           text=True, env=dict(os.environ, HOME=home))
        if r.returncode != 0 or r.stdout.strip():
            fails += 1
            print("FAIL bad payload did not fail open")

    if fails:
        print(f"{fails} failed")
        sys.exit(1)
    print(f"ok ({len(TABLE)} commands + 9 checks)")


if __name__ == "__main__":
    main()
