#!/usr/bin/env python3
"""Tests for the box-side switches in jobs.py: the read-only repo registry, the target
manifest, claim-token, and the ImageMagick fallback. Stdlib only; the hub is a local fixture.

    python3 skills/jobs/assets/test_jobs_box.py
"""

import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOBS = HERE / "jobs.py"
sys.path.insert(0, str(HERE))
import jobs  # noqa: E402


class FakeHub:
    """Counts every request and answers 200 {}."""

    def __init__(self):
        self.requests = []
        hub = self

        class H(http.server.BaseHTTPRequestHandler):
            def _answer(self):
                n = int(self.headers.get("Content-Length") or 0)
                hub.requests.append((self.command, self.path, self.rfile.read(n)))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            do_GET = do_PUT = do_POST = do_PATCH = _answer

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def make_repo(path, origin=None):
    path.mkdir(parents=True)
    sh(path, "git", "init", "-q")
    if origin:
        sh(path, "git", "remote", "add", "origin", origin)
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.hub = FakeHub()
        self.cfg = self.tmp / "cfg"
        self.cfg.mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("JOBS_REPOS_READONLY", "JOBS_TARGET_MANIFEST", "JOBS_REPOS_ROOT")}
        self.env.update(JOBS_CONFIG_DIR=str(self.cfg), JOBS_BASE_URL=self.hub.url,
                        JOBS_AGENT_TOKEN="fixture-token")

    def tearDown(self):
        self.hub.close()
        subprocess.run(["rm", "-rf", str(self.tmp)])

    def jobs(self, *args, cwd=None, **env):
        return subprocess.run([sys.executable, str(JOBS), *args], cwd=cwd or self.tmp,
                              env={**self.env, **env}, capture_output=True, text=True)


class ReposReadonly(Base):
    def setUp(self):
        super().setUp()
        self.root = self.tmp / "repos"
        make_repo(self.root / "widget", "https://github.com/Acme/Widget.git")

    def test_control_without_switch_puts_once(self):
        r = self.jobs("repos", "--root", str(self.root))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([q[:2] for q in self.hub.requests], [("PUT", "/api/jobs/repos")])

    def test_readonly_bare_repos_makes_no_http_call(self):
        r = self.jobs("repos", "--root", str(self.root), JOBS_REPOS_READONLY="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.hub.requests, [])
        self.assertEqual([x["target"] for x in json.loads(r.stdout)["repos"]], ["acme/widget"])

    def test_readonly_from_inside_a_repo_makes_no_http_call(self):
        r = self.jobs("repos", cwd=self.root / "widget", JOBS_REPOS_READONLY="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.hub.requests, [])


class Manifest(Base):
    def setUp(self):
        super().setUp()
        # A box clone: origin is a file path to a mirror, which git config alone maps to local/.
        mirror = self.tmp / "mirrors" / "acme" / "widget.git"
        mirror.mkdir(parents=True)
        sh(mirror, "git", "init", "-q", "--bare")
        self.clone = make_repo(self.tmp / "clones" / "acme" / "widget", str(mirror))
        # A sibling whose origin claims another target: the manifest must win over it.
        self.other = make_repo(self.tmp / "clones" / "acme" / "gadget",
                               "https://github.com/Evil/Elsewhere.git")
        self.manifest = self.tmp / "targets.json"
        self.manifest.write_text(json.dumps({"acme/widget": str(self.clone),
                                             "acme/gadget": str(self.other)}))

    def test_without_manifest_file_origin_is_local(self):
        r = self.jobs("here", cwd=self.clone)
        self.assertEqual(json.loads(r.stdout)["target"], "local/widget")

    def test_manifest_maps_file_origin_to_its_target(self):
        r = self.jobs("here", cwd=self.clone, JOBS_TARGET_MANIFEST=str(self.manifest))
        self.assertEqual(json.loads(r.stdout)["target"], "acme/widget", r.stderr)

    def test_manifest_wins_over_git_remote(self):
        r = self.jobs("here", cwd=self.other, JOBS_TARGET_MANIFEST=str(self.manifest))
        self.assertEqual(json.loads(r.stdout)["target"], "acme/gadget")

    def test_repos_lists_manifest_only(self):
        stray = make_repo(self.tmp / "clones" / "acme" / "stray", "https://github.com/Acme/Stray.git")
        r = self.jobs("repos", "--dry-run", cwd=stray, JOBS_TARGET_MANIFEST=str(self.manifest))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        got = {x["target"]: x["path"] for x in json.loads(r.stdout)["repos"]}
        self.assertEqual(got, {"acme/widget": str(self.clone), "acme/gadget": str(self.other)})

    def test_repos_needs_no_root_with_manifest(self):
        r = self.jobs("repos", "--dry-run", JOBS_TARGET_MANIFEST=str(self.manifest))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_bad_manifest_is_a_config_error(self):
        self.manifest.write_text(json.dumps({"acme/widget": "relative/path"}))
        r = self.jobs("here", cwd=self.clone, JOBS_TARGET_MANIFEST=str(self.manifest))
        self.assertEqual(r.returncode, 2)


class ClaimToken(Base):
    def test_prints_token_for_claimed_job_and_exits_1_otherwise(self):
        r = self.jobs("claim-token", "7")
        self.assertEqual(r.returncode, 1, "no claims file yet")
        self.assertEqual(self.jobs("claim", "7").returncode, 0)
        token = json.loads((self.cfg / "claims.json").read_text())["7"]
        r = self.jobs("claim-token", "7")
        self.assertEqual((r.returncode, r.stdout), (0, token + "\n"))
        r = self.jobs("claim-token", "8")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn(token, r.stdout)
        self.assertEqual(len(self.hub.requests), 1, "claim-token itself makes no HTTP call")


class ImageMagickFallback(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.calls = self.tmp / "calls"
        self.old_path = os.environ["PATH"]
        os.environ["PATH"] = str(self.bin)  # no sips here
        self.img = self.tmp / "shot.png"
        self.img.write_bytes(b"original")
        self.out = self.tmp / "out"
        self.out.mkdir()

    def tearDown(self):
        os.environ["PATH"] = self.old_path
        subprocess.run(["rm", "-rf", str(self.tmp)])

    def stub(self, name, w=3000, h=2000):
        p = self.bin / name
        p.write_text(f"""#!/bin/sh
echo "$@" >> "{self.calls}"
for last; do :; done
if [ "$last" = "info:" ]; then printf '{w} {h}'; else printf small > "$last"; fi
""")
        p.chmod(0o755)

    def test_magick_downsizes_when_sips_absent(self):
        self.stub("magick")
        self.assertEqual(jobs.image_bytes(self.img, self.out), (b"small", "image/png"))
        self.assertIn("-resize 1600x1600>", self.calls.read_text())

    def test_convert_used_when_no_magick(self):
        self.stub("convert")
        self.assertEqual(jobs.image_bytes(self.img, self.out)[0], b"small")

    def test_small_image_is_sent_as_is(self):
        self.stub("magick", 800, 600)
        self.assertEqual(jobs.image_bytes(self.img, self.out)[0], b"original")
        self.assertNotIn("-resize", self.calls.read_text())

    def test_no_tool_keeps_original(self):
        self.assertEqual(jobs.image_bytes(self.img, self.out)[0], b"original")


if __name__ == "__main__":
    unittest.main()
