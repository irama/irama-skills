"""Tests for land's mutation-check guard. Run: python3 skills/driver/test_mutation_guard.py"""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location(
    "driver_state", os.path.join(os.path.dirname(os.path.abspath(__file__)), "driver_state.py"))
ds = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ds)


def git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True)


class MutationGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "books")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "base")
        git(self.repo, "switch", "-q", "-c", "t-1")
        self.log = os.path.join(self.tmp.name, "pilot-log.ndjson")
        os.environ["MUTATE_DIFF_LOG"] = self.log

    def tearDown(self):
        os.environ.pop("MUTATE_DIFF_LOG", None)
        self.tmp.cleanup()

    def commit(self, name):
        open(os.path.join(self.repo, name), "w").write("x\n")
        git(self.repo, "add", name)
        git(self.repo, "commit", "-q", "-m", name)
        return subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()

    def row(self, head, **extra):
        with open(self.log, "a") as fh:
            fh.write(json.dumps({"repo": "books", "branch": "t-1", "head": head, **extra}) + "\n")

    def test_branch_outside_the_pilot_passes(self):
        self.commit("a.ts")
        self.assertTrue(ds._mutation_on_record(self.repo, "main", "t-1"))

    def test_pilot_branch_with_no_run_row_is_refused(self):
        head = self.commit("stryker.config.mjs")
        base = subprocess.run(["git", "-C", self.repo, "rev-parse", "main"], check=True,
                              capture_output=True, text=True).stdout.strip()
        self.row(base, exit=0)  # an old run on the target: another incarnation of the name
        self.row(head, kind="outcome")  # an outcome row runs nothing
        self.assertFalse(ds._mutation_on_record(self.repo, "main", "t-1"))

    def test_pilot_branch_with_a_run_row_at_its_own_commit_passes(self):
        first = self.commit("stryker.config.mjs")
        self.commit("b.ts")  # fixes committed after the run
        self.row(first, exit=1)  # a failed run still counts
        self.assertTrue(ds._mutation_on_record(self.repo, "main", "t-1"))

if __name__ == "__main__":
    unittest.main()
