#!/usr/bin/env python3
"""Hermetic self-check for scripts/heavy-job. Run: python3 scripts/test_heavy_job.py

Every run uses a fresh temp state dir (HEAVY_JOB_STATE_DIR) and a temp config file
(HEAVY_JOB_CONFIG), so the real machine slots are never touched.
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "heavy-job")
FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{detail}]"))
    if not cond:
        FAILS.append(name)


def make_env(tmp, **extra):
    env = {k: v for k, v in os.environ.items() if k not in ("HEAVY_JOB_HELD", "VITEST_MAX_WORKERS", "HEAVY_SLOTS", "HEAVY_WORKERS")}
    env.update(HEAVY_JOB_STATE_DIR=os.path.join(tmp, "state"), HEAVY_JOB_CONFIG=os.path.join(tmp, "heavy-job.env"), HEAVY_SLOTS="2")
    env.update(extra)
    return env


def waits_lines(tmp):
    p = os.path.join(tmp, "state", "waits.ndjson")
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return [json.loads(line) for line in f if line.strip()]


def free_slots(tmp, env):
    """True if a fresh `run` gets a slot at once (a waiting run is killed after 1.5 s)."""
    try:
        r = subprocess.run([TOOL, "run", "--", "true"], env=env, capture_output=True, text=True, timeout=1.5)
    except subprocess.TimeoutExpired:
        return False
    return r.returncode == 0 and "waiting" not in r.stderr


def test_overlap(tmp):
    env = make_env(tmp)
    marks = os.path.join(tmp, "marks")
    job = f"import time,os; s=time.time(); time.sleep(1.5); open({marks!r},'a').write(f'{{s}} {{time.time()}}\\n')"
    procs = [subprocess.Popen([TOOL, "run", "--", sys.executable, "-c", job], env=env, stderr=subprocess.PIPE, text=True) for _ in range(3)]
    errs = [p.communicate(timeout=20)[1] for p in procs]
    codes = [p.returncode for p in procs]
    spans = [tuple(map(float, l.split())) for l in open(marks)]
    peak = max(sum(1 for s, e in spans if s <= t < e) for t, _ in spans)
    check("3 concurrent runs all exit 0", codes == [0, 0, 0], codes)
    check("3 concurrent runs overlap at most 2", len(spans) == 3 and peak <= 2, spans)
    check("the third run said it was waiting", any("waiting" in e for e in errs), errs)
    w = waits_lines(tmp)
    check("a wait line is logged per acquisition", len(w) == 3 and all({"start", "wait_s", "slot", "cwd", "cmd"} <= set(x) for x in w), w)
    check("one logged wait is about the job length", max(x["wait_s"] for x in w) >= 1.0, w)


def test_env_and_exit_code(tmp):
    env = make_env(tmp)
    r = subprocess.run([TOOL, "run", "--", "sh", "-c", 'echo "$VITEST_MAX_WORKERS $HEAVY_JOB_HELD"; exit 3'], env=env, capture_output=True, text=True, timeout=10)
    check("run exports VITEST_MAX_WORKERS=4 and HEAVY_JOB_HELD=1", r.stdout.strip() == "4 1", r.stdout)
    check("run exits with the command's code", r.returncode == 3, r.returncode)
    r = subprocess.run([TOOL, "run", "--", "sh", "-c", 'echo "$VITEST_MAX_WORKERS"'], env=dict(env, VITEST_MAX_WORKERS="2"), capture_output=True, text=True, timeout=10)
    check("caller's own VITEST_MAX_WORKERS is kept", r.stdout.strip() == "2", r.stdout)
    with open(env["HEAVY_JOB_CONFIG"], "w") as f:
        f.write("# comment\nHEAVY_WORKERS=7\nHEAVY_SLOTS=1\n")
    env.pop("HEAVY_SLOTS")
    r = subprocess.run([TOOL, "run", "--", "sh", "-c", 'echo "$VITEST_MAX_WORKERS"'], env=env, capture_output=True, text=True, timeout=10)
    check("settings file sets HEAVY_WORKERS", r.stdout.strip() == "7", r.stdout)
    r = subprocess.run([TOOL, "run", "--", "sh", "-c", 'echo "$VITEST_MAX_WORKERS"'], env=dict(env, HEAVY_WORKERS="5"), capture_output=True, text=True, timeout=10)
    check("env overrides the settings file", r.stdout.strip() == "5", r.stdout)


def test_kill9_frees(tmp):
    env = make_env(tmp, HEAVY_SLOTS="1")
    p = subprocess.Popen([TOOL, "run", "--", "sleep", "30"], env=env, start_new_session=True)
    time.sleep(0.7)
    check("slot is held while the holder runs", not free_slots(tmp, env))
    os.killpg(p.pid, signal.SIGKILL)
    p.wait()
    time.sleep(0.2)
    t = time.time()
    check("kill -9 of the holder frees its slot", free_slots(tmp, env) and time.time() - t < 2)


def test_nested(tmp):
    env = make_env(tmp, HEAVY_SLOTS="1")
    p = subprocess.Popen([TOOL, "run", "--", "sleep", "30"], env=env, start_new_session=True)
    time.sleep(0.7)
    t = time.time()
    r = subprocess.run([TOOL, "run", "--", "sh", "-c", "echo nested"], env=dict(env, HEAVY_JOB_HELD="1"), capture_output=True, text=True, timeout=5)
    check("nested run does not wait", r.stdout.strip() == "nested" and time.time() - t < 2, (r.stdout, time.time() - t))
    r = subprocess.run([TOOL, "acquire", "--for-pid", str(os.getpid())], env=dict(env, HEAVY_JOB_HELD="1"), capture_output=True, text=True, timeout=5)
    check("nested acquire does not wait and prints exports", r.returncode == 0 and "HEAVY_JOB_HELD=1" in r.stdout, r)
    os.killpg(p.pid, signal.SIGKILL)
    p.wait()


def test_waiting_message(tmp):
    env = make_env(tmp, HEAVY_SLOTS="1")
    p = subprocess.Popen([TOOL, "run", "--", "sleep", "2"], env=env, cwd=tmp, start_new_session=True)
    time.sleep(0.7)
    r = subprocess.run([TOOL, "run", "--", "true"], env=env, capture_output=True, text=True, timeout=10)
    p.wait()
    e = r.stderr
    check("waiting job prints holder pid, cwd, command, held time and own wait",
          f"pid {p.pid}" in e and os.path.realpath(tmp) in e and "sleep 2" in e and "held" in e and "waiting" in e, e)


def test_acquire_eval(tmp):
    env = make_env(tmp, HEAVY_SLOTS="1")
    script = f'set -euo pipefail; eval "$({TOOL} acquire --for-pid $$)"; echo "ok $HEAVY_JOB_HELD $VITEST_MAX_WORKERS"'
    t = time.time()
    try:
        r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=5)
        out, code = r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        out, code = "TIMEOUT", -1
    check("eval acquire finishes within 5 s", code == 0 and out == "ok 1 4" and time.time() - t < 5, (code, out))
    deadline = time.time() + 3
    freed = False
    while time.time() < deadline and not freed:
        freed = free_slots(tmp, env)
        time.sleep(0.3)
    check("acquire's slot frees when that bash exits", freed)


def test_max_wait_cap(tmp):
    env = make_env(tmp, HEAVY_SLOTS="1", HEAVY_MAX_WAIT_S="1")
    p = subprocess.Popen([TOOL, "run", "--", "sleep", "5"], env=env, start_new_session=True)
    time.sleep(0.5)
    t = time.time()
    r = subprocess.run([TOOL, "run", "--", "sh", "-c", 'echo "$VITEST_MAX_WORKERS"'], env=env, capture_output=True, text=True, timeout=10)
    elapsed = time.time() - t
    check("past HEAVY_MAX_WAIT_S, run proceeds unslotted instead of waiting for the holder",
          r.returncode == 0 and r.stdout.strip() == "4" and elapsed < 4, (r.returncode, r.stdout, elapsed))
    check("timing out warns on stderr with an unblock hint",
          "timed out" in r.stderr and "HEAVY_MAX_WAIT_S" in r.stderr, r.stderr)
    os.killpg(p.pid, signal.SIGKILL)
    p.wait()


def test_bad_int_setting_falls_back(tmp):
    env = make_env(tmp, HEAVY_SLOTS="not-a-number")
    r = subprocess.run([TOOL, "run", "--", "true"], env=env, capture_output=True, text=True, timeout=5)
    check("an unparseable HEAVY_SLOTS warns and falls back instead of crashing",
          r.returncode == 0 and "Traceback" not in r.stderr and "not-a-number" in r.stderr, r)


def test_waits_report(tmp):
    os.makedirs(os.path.join(tmp, "state"), exist_ok=True)
    rows = [("2026-10-01T09:00:00+10:00", 99.0, "/old")] + [(f"2026-10-2{i}T09:00:00+10:00", float(i), f"/repo{i}") for i in range(1, 8)]
    with open(os.path.join(tmp, "state", "waits.ndjson"), "w") as f:
        for start, w, cwd in rows:
            f.write(json.dumps({"start": start, "wait_s": w, "slot": 0, "cwd": cwd, "cmd": "x"}) + "\n")
    r = subprocess.run([TOOL, "waits", "--since", "2026-10-20"], env=make_env(tmp), capture_output=True, text=True, timeout=10)
    o = r.stdout
    check("waits prints count, median, longest", "count 7" in o and "median 4.0s" in o and "longest 7.0s" in o, o)
    check("waits lists the 5 longest with cwd, excludes before --since",
          all(f"/repo{i}" in o for i in range(3, 8)) and "/repo2" not in o and "/old" not in o, o)


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout.strip()


def make_repo(tmp):
    """A temp repo with one commit. Returns (repo dir, git common dir, base tree sha)."""
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, "docs"))
    git(repo, "init", "-q")
    for path, text in (("src.ts", "x"), ("README.md", "r"), ("docs/a.md", "a"), ("docs/agent-surface.md", "s")):
        with open(os.path.join(repo, path), "w") as f:
            f.write(text)
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "base")
    return repo, git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"), git(repo, "rev-parse", "HEAD^{tree}")


def tree_with(repo, path, text):
    """Tree sha of the base commit plus one written file (staged, not committed)."""
    os.makedirs(os.path.dirname(os.path.join(repo, path)), exist_ok=True)
    with open(os.path.join(repo, path), "w") as f:
        f.write(text)
    git(repo, "add", "-A")
    t = git(repo, "write-tree")
    git(repo, "reset", "-q", "--hard")
    git(repo, "clean", "-qfd")
    return t


def hj(env, *args):
    return subprocess.run([TOOL, *args], env=env, capture_output=True, text=True, timeout=10)


def test_ledger(tmp):
    env = make_env(tmp)
    repo, common, base = make_repo(tmp)
    gate = "ci-gate v9 abc123def456"
    q = lambda tree, g=gate, e=env: hj(e, "passed", "--repo", common, "--tree", tree, "--gate", g)
    check("passed on an empty ledger is no match (exit 1)", q(base).returncode == 1, q(base))
    r = hj(env, "record", "--repo", common, "--tree", base, "--gate", gate)
    check("record exits 0", r.returncode == 0, r)
    r = q(base)
    check("exact tree matches (exit 0, prints exact)", r.returncode == 0 and f"matched {base} exact" in r.stdout, r)
    r = q(base, g="ci-gate v9 000000000000")
    check("a different gate-id does not match", r.returncode == 1, r)
    md = tree_with(repo, "docs/new.md", "n")
    r = q(md)
    check("an inert-only diff matches and names the paths", r.returncode == 0 and f"matched {base} differs only in docs/new.md" in r.stdout, r)
    r = q(tree_with(repo, "NOTES.md", "n"))
    check("a root *.md diff matches", r.returncode == 0, r)
    r = q(tree_with(repo, ".scratch/x/y.json", "{}"))
    check("a .scratch/** diff matches", r.returncode == 0, r)
    r = q(tree_with(repo, "docs/x.ts", "x"))
    check("a docs/x.ts diff does not match", r.returncode == 1, r)
    r = q(tree_with(repo, "docs/agent-surface.md", "changed"))
    check("a docs/agent-surface.md diff does not match", r.returncode == 1, r)
    r = q(tree_with(repo, "sub/README.md", "n"))
    check("a non-root, non-docs *.md diff does not match", r.returncode == 1, r)
    # A rename from code into an inert path must not hide the deleted code path.
    git(repo, "mv", "src.ts", "docs/src.md")
    renamed = git(repo, "write-tree")
    git(repo, "reset", "-q", "--hard")
    check("a rename from src.ts into docs/ does not match", q(renamed).returncode == 1, q(renamed))
    r = q(md, e=dict(env, HEAVY_JOB_INERT="*.txt"))
    check("HEAVY_JOB_INERT overrides the default list", r.returncode == 1, r)
    r = q(tree_with(repo, "notes.txt", "n"), e=dict(env, HEAVY_JOB_INERT="*.txt"))
    check("HEAVY_JOB_INERT pattern matches", r.returncode == 0, r)


def test_ledger_age_gc_and_vitest(tmp):
    env = make_env(tmp)
    repo, common, base = make_repo(tmp)
    gate = "ci-gate v9 abc123def456"
    ledger = os.path.join(tmp, "state", "passed.ndjson")
    os.makedirs(os.path.dirname(ledger), exist_ok=True)
    with open(ledger, "w") as f:
        f.write(json.dumps({"t": time.time() - 8 * 86400, "repo": os.path.realpath(common), "tree": base, "gate": gate}) + "\n")
    r = hj(env, "passed", "--repo", common, "--tree", base, "--gate", gate)
    check("an 8-day-old entry does not match", r.returncode == 1, r)
    gone = "0123456789abcdef0123456789abcdef01234567"
    hj(env, "record", "--repo", common, "--tree", gone, "--gate", gate)
    r = hj(env, "passed", "--repo", common, "--tree", tree_with(repo, "docs/z.md", "z"), "--gate", gate)
    check("a garbage-collected recorded tree is no match, not a crash", r.returncode == 1 and "Traceback" not in r.stderr, r)
    vdir = os.path.join(tmp, "state", "vitest")
    os.makedirs(vdir, exist_ok=True)
    old = os.path.join(vdir, "old-tree.json")
    with open(old, "w") as f:
        f.write("{}")
    os.utime(old, (time.time() - 8 * 86400,) * 2)
    src = os.path.join(tmp, "vitest.json")
    with open(src, "w") as f:
        f.write('{"numFailedTests": 0}')
    r = hj(env, "record", "--repo", common, "--tree", base, "--gate", gate, "--vitest-json", src)
    check("record with --vitest-json exits 0", r.returncode == 0, r)
    check("record deletes stored vitest json older than 7 days", not os.path.exists(old))
    r = hj(env, "passed", "--repo", common, "--tree", tree_with(repo, "docs/q.md", "q"), "--gate", gate)
    lines = [l for l in r.stdout.splitlines() if l.startswith("vitest-json ")]
    stored = lines[0][len("vitest-json "):] if lines else ""
    check("passed prints the stored vitest json path for the matched tree",
          r.returncode == 0 and os.path.isfile(stored) and open(stored).read() == '{"numFailedTests": 0}' and base in stored, r)
    r = hj(env, "record", "--repo", common, "--tree=--oops", "--gate", gate)
    check("record refuses a non-sha tree (exit 64)", r.returncode == 64, r)


if __name__ == "__main__":
    for t in (test_overlap, test_env_and_exit_code, test_kill9_frees, test_nested, test_waiting_message, test_acquire_eval,
              test_max_wait_cap, test_bad_int_setting_falls_back, test_waits_report, test_ledger, test_ledger_age_gc_and_vitest):
        with tempfile.TemporaryDirectory() as tmp:
            t(tmp)
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    sys.exit(1 if FAILS else 0)
