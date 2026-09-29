import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import run  # noqa: E402

VERSIONS = {"codex_cli": "codex-cli 0.0", "chrome": "Chrome 0"}


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        sh(self.repo, "git", "init", "-q")
        sh(self.repo, "git", "config", "user.email", "t@example.com")
        sh(self.repo, "git", "config", "user.name", "t")
        self.deck = self.repo / "deck"
        self.deck.mkdir()
        (self.deck / "_gen.py").write_text("x = 1\n")
        (self.repo / "other.txt").write_text("a\n")
        sh(self.repo, "git", "add", ".")
        sh(self.repo, "git", "commit", "-qm", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def test_second_start_is_refused_until_release(self):
        r = run.start(self.deck, "t", "s1", versions=VERSIONS)
        self.assertTrue((self.deck / run.LOCK).exists())
        self.assertEqual(sh(self.repo, "git", "status", "--porcelain"), "")  # record and lock are excluded
        with self.assertRaises(SystemExit) as e:
            run.start(self.deck, "t", "s2", versions=VERSIONS)
        self.assertIn("refused", str(e.exception.code))
        self.assertEqual(run.main(["start", str(self.deck), "--target", "t", "--session", "s2"]), 2)
        self.assertEqual(run.release(self.deck, "failed: test"), r)
        self.assertFalse((self.deck / run.LOCK).exists())
        self.assertEqual(json.loads((r / "run.json").read_text())["end_reason"], "failed: test")

    def test_dirty_folder_is_refused(self):
        (self.deck / "_gen.py").write_text("x = 2\n")
        with self.assertRaises(SystemExit):
            run.start(self.deck, "t", "s", versions=VERSIONS)
        self.assertFalse((self.deck / run.LOCK).exists())

    def test_commit_takes_only_the_given_paths(self):
        r = run.start(self.deck, "a4", "s", versions=VERSIONS)
        (r / "rounds" / "r1").mkdir(parents=True)
        (self.deck / "_gen.py").write_text("x = 2\n")
        (self.repo / "other.txt").write_text("b\n")
        sh(self.repo, "git", "add", "other.txt")  # another thread's staged work
        sha = run.commit(r, 1, [str(self.deck / "_gen.py")])
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%s"), "draft-eval(a4): round 1")
        self.assertEqual(sh(self.repo, "git", "show", "--name-only", "--format=", sha), "deck/_gen.py")
        self.assertIn("M  other.txt", sh(self.repo, "git", "status", "--porcelain"))
        self.assertEqual(json.loads((r / "rounds" / "r1" / "record.json").read_text())["rewrite_commit"], sha)
        with self.assertRaises(SystemExit):
            run.commit(r, 1, [str(self.repo / "other.txt")])

    def test_check_names_missing_fields(self):
        r = run.start(self.deck, "t", "s", versions=VERSIONS)
        rd = r / "rounds" / "r1"
        (rd / "grading").mkdir(parents=True)
        (rd / "units.json").write_text(json.dumps({"kind": "article", "units": []}))
        missing = run.check(r)
        self.assertIn("r1/score.json", missing)
        self.assertIn("r1/record.json models", missing)
        (rd / "grading" / "claude.jsonl").write_text(json.dumps({"model": "m"}) + "\n")
        (rd / "grading" / "batch-01.claude.json").write_text("{}")
        (rd / "score.json").write_text("{}")
        (rd / "rewrites.json").write_text(json.dumps({"rewrites": []}))
        run.record(r, 1)
        self.assertEqual(run.check(r), [])


if __name__ == "__main__":
    unittest.main()
