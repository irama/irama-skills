"""render.mjs runs as a CLI through a symlink too. Needs node, never a browser."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("node"), "node not installed")
class RenderCliTest(unittest.TestCase):
    def run_cli(self, path):
        return subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=30)

    def test_usage_from_the_real_path(self):
        r = self.run_cli(HERE / "render.mjs")
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage: render.mjs", r.stderr)

    def test_usage_through_a_symlinked_skill_dir(self):
        # the skill is installed as a symlinked directory; the CLI must not no-op there
        with tempfile.TemporaryDirectory() as d:
            link = Path(d) / "draft-eval"
            os.symlink(HERE, link)
            r = self.run_cli(link / "render.mjs")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("usage: render.mjs", r.stderr)


if __name__ == "__main__":
    unittest.main()
