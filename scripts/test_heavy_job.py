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


if __name__ == "__main__":
    for t in (test_overlap, test_env_and_exit_code, test_kill9_frees, test_nested, test_waiting_message, test_acquire_eval,
              test_max_wait_cap, test_bad_int_setting_falls_back, test_waits_report):
        with tempfile.TemporaryDirectory() as tmp:
            t(tmp)
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    sys.exit(1 if FAILS else 0)
