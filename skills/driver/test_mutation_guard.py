"""Tests for land's mutation-check guard. Run: python3 skills/driver/test_mutation_guard.py"""
import importlib.util
import json
import os
import subprocess
import tempfile
import time
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

    def row(self, branch, ran_at):
        with open(self.log, "a") as fh:
            fh.write(json.dumps({"ran_at": ran_at, "repo": "books", "branch": branch}) + "\n")

    def test_branch_outside_the_pilot_passes(self):
        self.commit("a.ts")
        self.assertTrue(ds._mutation_on_record(self.repo, "main", "t-1"))

    def test_pilot_branch_with_no_row_is_refused(self):
        self.commit("stryker.config.mjs")
        self.row("t-1", "2000-01-01T00:00:00Z")  # an older run on a reused branch name
        self.row("t-2", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 60)))
        self.assertFalse(ds._mutation_on_record(self.repo, "main", "t-1"))

    def test_pilot_branch_with_a_row_since_its_first_commit_passes(self):
        self.commit("stryker.config.mjs")
        self.row("t-1", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 60)))
        self.assertTrue(ds._mutation_on_record(self.repo, "main", "t-1"))


if __name__ == "__main__":
    unittest.main()
