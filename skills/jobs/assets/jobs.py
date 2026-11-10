#!/usr/bin/env python3
"""Client for the job board's agent API. The /jobs skill calls this; it never builds curl.

    jobs.py here                                  this repo's target and whether it orchestrates
    jobs.py list [--column C] [--target T|none] [--source board|zero] [--awaiting] [--ship-approved] [--all-pages]
    jobs.py get ID                                one job, runs, last 200 comments
    jobs.py attachments ID                        1-hour signed image URLs
    jobs.py fetch ID [--comment N]                download the attachments on operator comments above
                                                  ack_comment_id (or on comment N) to
                                                  $TMPDIR/jobs/<id>/<comment>/<name>; one path per line
    jobs.py claim ID [--agent LABEL]              claim with this machine's token for the job
    jobs.py patch ID [--column C] [--size S] [--size-reason R] [--targets-picked a,b] [--ack N] [--active on|off]
    jobs.py run ID --target T [--branch B] [--base-sha S] [--head-sha S] [--state claimed|committed|failed]
    jobs.py shipped ID --target T --deployed-sha S
    jobs.py comment ID --kind message|event [--body TEXT | --body-file F | stdin] [--agent LABEL]
                       [--image PATH ...]       up to 6 screenshots, downscaled to 1600px (sips);
                                                needs this machine's claim token for the job
                       [--file PATH ...]        result files (.html/.htm, .pdf, at most 20 MB);
                                                shares the 6 per comment with --image
    jobs.py repos [--root DIR] [--dry-run]        report sibling git repos (PUT /api/jobs/repos);
                                                  outside a repo, --root defaults to $JOBS_REPOS_ROOT
    jobs.py claim-token ID                        print this machine's claim token for one job
    jobs.py preflight ID --target T --repo PATH [--void] [--recheck]   ship preflight; --recheck before the push
    jobs.py data-scope --target T --repo PATH --base S --head S   on the box: paths boxd would refuse
                                                  for a data repo (ADR 0122), from data-repos.json
    jobs.py --selftest

Config: JOBS_BASE_URL, JOBS_AGENT_TOKEN and JOBS_ORCHESTRATORS from ~/.config/jobs/env.
A variable already in the process environment wins over the file (a dry run points
JOBS_BASE_URL at a dev hub that way). Claim tokens live in ~/.config/jobs/claims.json.
JOBS_REPOS_READONLY=1 makes `repos` a dry run always, so this machine never replaces the hub's
repo registry. JOBS_TARGET_MANIFEST=<file> maps targets to paths from that JSON file only
({"owner/repo": "/abs/path"}), never from git config.
Output is JSON on stdout. Exit 0 on success, 1 on an API or preflight refusal, 2 on
a usage or config error.
"""

import argparse
import fcntl
import http.client
import json
import os
import re
import socket
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

HTTP_TIMEOUT = 30  # seconds, per request; the selftest lowers it
TARGET_RE = re.compile(r"^[a-z0-9._-]+/[a-z0-9._-]+$")
TEMPLATE = """# /jobs skill config. Mode 600. Never commit or print this file.
# JOBS_BASE_URL: the job board hub's base URL, no trailing slash.
# JOBS_AGENT_TOKEN: the hub's agent bearer token (the same value as the hub's
#   JOBS_AGENT_TOKEN env var). Paste it; do not generate a new one here.
# JOBS_ORCHESTRATORS: comma-separated targets (owner/repo) where bare /jobs lists every job.
JOBS_BASE_URL=
JOBS_AGENT_TOKEN=
JOBS_ORCHESTRATORS=
"""


def config_dir():
    return Path(os.environ.get("JOBS_CONFIG_DIR") or Path.home() / ".config" / "jobs")


def load_config():
    """Read the env file, writing the empty template only if it is absent."""
    path = config_dir() / "env"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(TEMPLATE)
    cfg = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("JOBS_BASE_URL", "JOBS_AGENT_TOKEN", "JOBS_ORCHESTRATORS"):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    return cfg, path


def die(msg, code=2):
    print(json.dumps({"error": msg}))
    sys.exit(code)


# ── Claim tokens ────────────────────────────────────────────────────────────


def claims_path():
    return config_dir() / "claims.json"


def read_claims():
    try:
        return json.loads(claims_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def claim_token(job_id, create=False):
    """The token for a job. Created and persisted BEFORE the claim call, so a retry
    after a timeout reuses it and the hub answers 200 instead of already_claimed."""
    key = str(job_id)
    claims = read_claims()
    if key in claims:
        return claims[key]
    if not create:
        die(f"no claim token for JOB-{job_id} on this machine; claim it first")
    p = claims_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Two sessions can create tokens at once. The lock serialises the read-modify-write,
    # and the re-read under it means the second writer keeps the first one's token.
    lock_fd = os.open(p.with_suffix(".lock"), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        claims = read_claims()
        if key not in claims:
            claims[key] = str(uuid.uuid4())
            tmp = p.with_name(f"claims.{os.getpid()}.tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(claims, f, indent=1)
            os.replace(tmp, p)
        return claims[key]
    finally:
        os.close(lock_fd)


# ── HTTP ────────────────────────────────────────────────────────────────────


def api(method, path, body=None):
    cfg, cfg_path = load_config()
    base = cfg.get("JOBS_BASE_URL", "").rstrip("/")
    token = cfg.get("JOBS_AGENT_TOKEN", "")
    if not base or not token:
        die(f"JOBS_BASE_URL and JOBS_AGENT_TOKEN must be set in {cfg_path}")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"{}")
        except (ValueError, OSError, http.client.HTTPException):
            payload = {"error": e.reason}
        return e.code, payload
    except urllib.error.URLError as e:
        return 0, {"error": f"hub unreachable: {e.reason}", "code": "UNREACHABLE"}
    except ValueError:  # JSONDecodeError and UnicodeDecodeError are both ValueError
        return 0, {"error": "hub sent a body that is not JSON", "code": "BAD_RESPONSE"}
    except http.client.HTTPException as e:  # IncompleteRead and friends while reading the body
        return 0, {"error": f"hub read failed: {e.__class__.__name__}", "code": "UNREACHABLE"}
    except OSError as e:  # socket.timeout / TimeoutError / reset while reading the body
        return 0, {"error": f"hub read failed: {e.__class__.__name__}: {e}", "code": "UNREACHABLE"}


def emit(status, payload):
    """Print the response. 2xx exits 0; anything else carries its HTTP status and exits 1."""
    if not 200 <= status < 300:
        payload = {**payload, "status": status}
    print(json.dumps(payload, indent=1))
    return 0 if 200 <= status < 300 else 1


def agent_label(given=None):
    if given:
        return given[:100]
    root = repo_root(Path.cwd())
    return f"{socket.gethostname().split('.')[0]}:{root.name if root else 'no-repo'}"[:100]


# ── Repos and targets ──────────────────────────────────────────────────────


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip() if r.returncode == 0 else None


def repo_root(path):
    """The MAIN checkout of the repo holding path (not a worktree), or None."""
    common = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False)
    if not common:
        return None
    common = Path(common)
    return common.parent if common.name == ".git" else common


def target_from_url(url, dirname):
    """owner/repo from an origin URL, lower-cased; else local/<dir> (spec § Targets)."""
    # A path or file:// origin names no owner, so it is local like a missing remote.
    if url and not url.startswith(("/", ".", "file:")):
        m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", url.strip())
        if m:
            t = f"{m.group(1)}/{m.group(2)}".lower()
            if TARGET_RE.match(t):
                return t
    local = re.sub(r"[^a-z0-9._-]", "-", dirname.lower())
    return f"local/{local}"


def target_manifest():
    """{target: path} from $JOBS_TARGET_MANIFEST, or None when it is unset. A git remote can be
    rewritten by insteadOf, so with a manifest set no target ever comes from git config."""
    path = os.environ.get("JOBS_TARGET_MANIFEST")
    if not path:
        return None
    try:
        m = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        die(f"JOBS_TARGET_MANIFEST {path}: {e}")
    if not isinstance(m, dict) or not all(
            isinstance(k, str) and TARGET_RE.match(k) and isinstance(v, str) and v.startswith("/")
            for k, v in m.items()):
        die(f"JOBS_TARGET_MANIFEST {path}: want {{\"owner/repo\": \"/abs/path\"}}")
    return m


def target_of(repo):
    root = repo_root(repo) or Path(repo)
    m = target_manifest()
    if m is not None:
        real = os.path.realpath(root)
        # A manifest entry may name a linked worktree: collapse it as repo_root did for root.
        hits = [t for t, p in m.items() if os.path.realpath(repo_root(p) or p) == real]
        return hits[0] if hits else target_from_url(None, root.name)
    return target_from_url(git(root, "remote", "get-url", "origin", check=False), root.name)


def cmd_here(_a):
    root = repo_root(Path.cwd())
    cfg, _ = load_config()
    orch = {t.strip().lower() for t in cfg.get("JOBS_ORCHESTRATORS", "").split(",") if t.strip()}
    target = target_of(root) if root else None
    print(json.dumps({"repo": str(root) if root else None, "target": target,
                      "orchestrator": bool(target and target in orch)}, indent=1))
    return 0


def sibling_repos(root):
    """Main checkouts under root, plus those one level inside a plain (non-git) folder
    such as tools/travel-app, or inside a checkout that holds child repos (a workspace
    repo that ignores them). A top-level checkout wins over a nested copy of the same
    target. Worktrees (.git is a file) are
    skipped, and so are folders named archive or starting with '_' or '.', which hold
    retired copies. Each entry carries its local path so a target maps to a checkout."""
    out, nested = [], []
    m = target_manifest()
    if m is not None:
        return [{"target": t, "display": Path(p).name[:100], "path": p} for t, p in sorted(m.items())][:200]
    for d in sorted(Path(root).iterdir()):
        if not d.is_dir() or d.name.startswith(("_", ".")) or d.name.lower() == "archive":
            continue
        if (d / ".git").is_dir():
            out.append({"target": target_of(d), "display": d.name[:100], "path": str(d)})
            for s in sorted(p for p in d.iterdir() if p.is_dir() and (p / ".git").is_dir()):
                nested.append({"target": target_of(s), "display": s.name[:100], "path": str(s)})
        elif not (d / ".git").exists():
            for s in sorted(p for p in d.iterdir() if p.is_dir() and (p / ".git").is_dir()):
                out.append({"target": target_of(s), "display": s.name[:100], "path": str(s)})
    seen = {}
    for r in out:
        seen[r["target"]] = r
    for r in nested:
        seen.setdefault(r["target"], r)
    return list(seen.values())[:200]


def cmd_repos(a):
    here = repo_root(Path.cwd())
    # The background poller runs from the home folder, so it names the root in the env.
    fallback = os.environ.get("JOBS_REPOS_ROOT")
    root = Path(a.root) if a.root else (here.parent if here else (Path(fallback) if fallback else None))
    if target_manifest() is None and (not root or not root.is_dir()):
        die("not in a git repo and no --root given")
    repos = sibling_repos(root)
    # Set on a machine that must never replace the hub's registry, whatever the caller asked.
    if a.dry_run or os.environ.get("JOBS_REPOS_READONLY") == "1":
        print(json.dumps({"repos": repos}, indent=1))
        return 0
    # The hub stores target and display only; a local path means nothing to it.
    return emit(*api("PUT", "/api/jobs/repos",
                     {"repos": [{k: r[k] for k in ("target", "display")} for r in repos]}))


# ── API commands ────────────────────────────────────────────────────────────


def cmd_list(a):
    q = {}
    if a.column:
        q["column"] = a.column
    if a.target:
        q["target"] = a.target
    if a.source:
        q["source"] = a.source
    if a.awaiting:
        q["awaiting"] = "1"
    if a.ship_approved:
        q["ship"] = "approved"
    jobs, cursor = [], None
    while True:
        qs = "&".join(f"{k}={urllib.request.quote(v)}" for k, v in {**q, **({"cursor": cursor} if cursor else {})}.items())
        status, payload = api("GET", "/api/jobs" + (f"?{qs}" if qs else ""))
        if status != 200:
            return emit(status, payload)
        jobs += payload["data"]["jobs"]
        cursor = payload["data"].get("next_cursor")
        if not cursor or not a.all_pages:
            break
    print(json.dumps({"jobs": jobs, "next_cursor": cursor}, indent=1))
    return 0


def cmd_get(a):
    return emit(*api("GET", f"/api/jobs/{a.id}"))


def cmd_attachments(a):
    return emit(*api("GET", f"/api/jobs/{a.id}/attachments"))


def safe_name(name, fallback):
    """One path component from an operator-given name: no separators, no .., no control chars."""
    name = re.sub(r"[\x00-\x1f\x7f/\\]", "_", str(name or "")).strip()
    name = name.encode()[:200].decode(errors="ignore")  # filesystems cap a name at 255 bytes
    return fallback if name.strip(".") == "" else name


def cmd_fetch(a):
    """Download reply attachments now: the signed URLs expire an hour after the GET.

    Default scope is operator comments above ack_comment_id, never the whole history: the
    hub's database shares an egress quota with another app. Prints one path per line on
    stdout; each attachment it could not fetch goes to stderr as `not fetched: ...`, exit 1.
    """
    status, payload = api("GET", f"/api/jobs/{a.id}")
    if not 200 <= status < 300:
        return emit(status, payload)
    job = payload.get("data") or {}
    comments = job.get("comments") or []
    if a.comment is not None:
        picked = [c for c in comments if c.get("id") == a.comment]
        if not picked:
            return emit(404, {"error": f"comment {a.comment} is not in the job's last 200 comments",
                              "code": "COMMENT_NOT_FOUND"})
    else:
        ack = job.get("ack_comment_id") or 0
        picked = [c for c in comments if c.get("author") == "you" and (c.get("id") or 0) > ack]
    root = Path(tempfile.gettempdir()) / "jobs" / str(int(a.id))
    failed = 0
    for c in picked:
        folder = (root / str(int(c["id"]))).resolve()
        used, n_img = set(), 0
        for att in c.get("attachments") or []:
            if att.get("kind") == "image":
                n_img += 1
                ext = Path(urllib.parse.urlparse(att.get("url") or "").path).suffix.lower()
                name = f"image-{n_img}{ext if ext in ('.webp', '.jpg', '.jpeg', '.png') else '.img'}"
            else:
                name = safe_name(att.get("name"), f"file-{att.get('id')}")
            if name in used:
                name = f"{att.get('id')}-{name}"
            used.add(name)
            url = att.get("url") or ""
            if not url.startswith(("https://", "http://")):  # null (signing failed) or a hub-login route
                print(f"not fetched: {c['id']}/{name}: no download URL", file=sys.stderr)
                failed += 1
                continue
            dest = folder / name
            if dest.resolve().parent != folder:  # belt and braces after safe_name
                print(f"not fetched: {c['id']}/{name}: unsafe name", file=sys.stderr)
                failed += 1
                continue
            try:  # signed URL: it carries its own token, so no bearer
                with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as r:
                    data = r.read()
            except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
                print(f"not fetched: {c['id']}/{name}: {getattr(e, 'code', '') or e}", file=sys.stderr)
                failed += 1
                continue
            folder.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            print(dest)
    return 1 if failed else 0


def cmd_claim_token(a):
    """This machine's claim token for one job, read under the claims lock; exit 1 if none."""
    p = claims_path()
    # Lock first: a concurrent first claim may be creating claims.json right now.
    p.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(p.with_suffix(".lock"), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_SH)
        token = read_claims().get(str(a.id))
    finally:
        os.close(lock_fd)
    if not token:
        print(json.dumps({"error": f"no claim token for JOB-{a.id} on this machine"}))
        return 1
    print(token)
    return 0


def _owning_dir(log_parent_name, cwds):
    """The folder whose project slug names the directory the session transcript sits in.

    Ported from ~/.claude/bin/brief-deliver (commit 754d22c): a session that ran
    EnterWorktree has several cwds in its transcript, and the thread's own folder is the
    one matching the transcript's project slug, not whichever cwd happens to be current.
    If that folder is gone (worktree pruned), fall back to the main worktree of the repo.
    """
    own = next((c for c in cwds if re.sub(r"[^A-Za-z0-9]", "-", c) == log_parent_name), None)
    if own and os.path.isdir(own):
        return own
    for c in ([own] if own else []) + cwds:
        p = c
        while p and p != "/" and not os.path.isdir(p):
            p = os.path.dirname(p)
        r = subprocess.run(["git", "-C", p, "worktree", "list", "--porcelain"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.startswith("worktree "):
            return r.stdout.splitlines()[0][len("worktree "):]
    return None


def resolved_session_dir(sid):
    """This session's own folder, read fresh from its transcript every call.

    Resolved at send time (claim, and every run/status update) rather than cached once
    at claim time, so a thread that later moves folder (EnterWorktree) still links the
    folder that currently owns it instead of wherever it was when first claimed.
    Returns None if no transcript or no owning directory can be found; callers fall
    back to JOBS_RUN_DIR / the current directory so a transcript-resolved worktree
    always wins over the poller's stale start-up cwd.
    """
    logs = list((Path.home() / ".claude" / "projects").glob(f"*/{sid}.jsonl")) if sid else []
    if not logs:
        return None
    cwds = []
    try:
        with open(logs[0], encoding="utf-8", errors="ignore") as f:
            for line in f:
                if '"cwd"' not in line:
                    continue
                try:
                    c = json.loads(line).get("cwd")
                except (json.JSONDecodeError, ValueError):
                    continue  # truncated/malformed JSONL line; skip it, not fatal
                if c and c not in cwds:
                    cwds.append(c)
    except OSError:
        return None
    return _owning_dir(logs[0].parent.name, cwds)


def cmd_claim(a):
    token = claim_token(a.id, create=True)
    body = {"claim_token": token, "agent": agent_label(a.agent)}
    # The Claude Code thread doing the work, so the card can link back to it in VS Code.
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if sid:
        body["session"] = {"id": sid, "dir": resolved_session_dir(sid) or os.environ.get("JOBS_RUN_DIR") or os.getcwd()}
    if not os.environ.get("JOBS_RUN_DIR"):
        # An interactive thread takes the job over, so the poller stops answering its replies.
        owned = config_dir() / "poller-owned"
        if owned.exists():
            keep = [l for l in owned.read_text().splitlines() if l.strip() != str(a.id)]
            tmp = owned.with_name(f"poller-owned.{os.getpid()}.tmp")
            tmp.write_text("".join(f"{l}\n" for l in keep))
            os.replace(tmp, owned)
    status, payload = api("POST", f"/api/jobs/{a.id}/claim", body)
    if status == 400 and "session" in body:
        # ponytail: a hub from before the session field refuses it; drop this retry once
        # every hub accepts `session`.
        body.pop("session")
        status, payload = api("POST", f"/api/jobs/{a.id}/claim", body)
    return emit(status, payload)


def cmd_patch(a):
    body = {"claim_token": claim_token(a.id)}
    if a.column:
        body["column"] = a.column
    if a.size:
        body["size"] = a.size
    if a.size_reason is not None:
        body["size_reason"] = a.size_reason
    if a.targets_picked:
        body["targets_picked"] = [t.strip().lower() for t in a.targets_picked.split(",") if t.strip()]
    if a.ack is not None:
        body["ack_comment_id"] = a.ack
    if a.active:
        body["active"] = a.active == "on"
    return emit(*api("PATCH", f"/api/jobs/{a.id}", body))


def run_update(job_id, target, **fields):
    body = {"claim_token": claim_token(job_id), "target": target}
    body.update({k: v for k, v in fields.items() if v is not None})
    # Re-resolve the session folder on every status update (not just at claim): a thread
    # that ran EnterWorktree since claiming now has a different owning folder, and the
    # latest one should win on the card.
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if sid:
        body["session"] = {"id": sid, "dir": resolved_session_dir(sid) or os.environ.get("JOBS_RUN_DIR") or os.getcwd()}
    status, payload = api("PUT", f"/api/jobs/{job_id}/runs", body)
    if status == 400 and "session" in body:
        # ponytail: same hub-version guard as cmd_claim; drop once every hub accepts `session`.
        body.pop("session")
        status, payload = api("PUT", f"/api/jobs/{job_id}/runs", body)
    return status, payload


def cmd_run(a):
    return emit(*run_update(a.id, a.target, branch=a.branch, base_sha=a.base_sha,
                            head_sha=a.head_sha, state=a.state))


def cmd_shipped(a):
    return emit(*api("POST", f"/api/jobs/{a.id}/runs/shipped",
                     {"claim_token": claim_token(a.id), "target": a.target, "deployed_sha": a.deployed_sha}))


def cmd_repin(a):
    return emit(*api("POST", f"/api/jobs/{a.id}/runs/repin",
                     {"claim_token": claim_token(a.id), "target": a.target, "head_sha": a.head_sha,
                      "comment_id": a.comment, "note": a.note}))


def post_comment(job_id, kind, body, agent=None, attachment_ids=None):
    payload = {"kind": kind, "body": body, "agent": agent_label(agent)}
    if attachment_ids:
        payload["attachment_ids"] = attachment_ids
    return api("POST", f"/api/jobs/{job_id}/comments", payload)


MAX_IMAGES = 6  # per comment, screenshots and result files together
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024
FILE_MIME = {".html": "text/html", ".htm": "text/html", ".pdf": "application/pdf"}
LONG_EDGE = 1600
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def image_bytes(path, out_dir):
    """The image to upload: downscaled to 1600px on the long edge with macOS sips, or with
    ImageMagick (magick, then convert) where sips is missing; never upscaled. The original when
    neither tool exists or the tool cannot read or write the file."""
    src = Path(path)
    if not src.is_file():
        die(f"image not found: {path}")
    mime = IMAGE_MIME.get(src.suffix.lower())
    if not mime:
        die(f"not a PNG, JPEG or WebP image: {path}")
    out = Path(out_dir) / f"{len(list(Path(out_dir).iterdir()))}{src.suffix.lower()}"
    im = None if shutil.which("sips") else (shutil.which("magick") or shutil.which("convert"))
    try:
        if im:
            dims = subprocess.run([im, str(src), "-format", "%w %h", "info:"],
                                  capture_output=True, text=True, timeout=60, check=True).stdout
            long_edge = max(int(n) for n in dims.split()[:2])
            resize = [im, str(src), "-resize", f"{LONG_EDGE}x{LONG_EDGE}>", str(out)]
        else:
            dims = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(src)],
                                  capture_output=True, text=True, timeout=60, check=True).stdout
            long_edge = max(int(n) for n in re.findall(r"pixel(?:Width|Height): (\d+)", dims))
            resize = ["sips", "-Z", str(LONG_EDGE), str(src), "--out", str(out)]
        if long_edge > LONG_EDGE:
            subprocess.run(resize, capture_output=True, timeout=60, check=True)
            return out.read_bytes(), mime
    except (OSError, ValueError, subprocess.SubprocessError):
        pass  # no tool, or it could not read the file: send the original
    return src.read_bytes(), mime


def sniff_file(head):
    """The result file type from its first bytes, or None. HTML: `<!doctype` or `<html` after a
    UTF-8 byte order mark and whitespace, any case. PDF: `%PDF-`. The hub checks the same."""
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    text = head[3:] if head.startswith(b"\xef\xbb\xbf") else head
    text = text.lstrip(b" \t\r\n\f").lower()
    if text.startswith(b"<!doctype") or text.startswith(b"<html"):
        return "text/html"
    return None


def file_bytes(path):
    """A result file to attach, checked locally before anything is sent: an .html, .htm or .pdf
    file whose first bytes match its extension, at most 20 MB."""
    src = Path(path)
    if not src.is_file():
        die(f"file not found: {path}")
    mime = FILE_MIME.get(src.suffix.lower())
    if not mime:
        die(f"not an HTML or PDF file (.html, .htm, .pdf): {path}")
    if src.stat().st_size > MAX_FILE_BYTES:
        die(f"file over 20 MB: {path}")
    if src.stat().st_size == 0:
        die(f"empty file: {path}")
    data = src.read_bytes()
    if sniff_file(data[:512]) != mime:
        die(f"{path} does not start like {'a PDF (%PDF-)' if mime == 'application/pdf' else 'HTML (<!doctype or <html)'}")
    return data, mime


def put_bytes(url, data, mime):
    """PUT the bytes to a signed upload URL. The URL carries its own token: no bearer."""
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Content-Type", mime)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError, http.client.HTTPException):
        return 0


def upload_images(job_id, paths, files=()):
    """Open a slot per result file and per image, PUT it, return the slot ids (files first).
    Any failure: (None, exit code), and the caller posts nothing, so a comment never goes out
    without the files and screenshots it promised. Files are checked before anything is sent."""
    import tempfile

    prepared = [(path, *file_bytes(path)) for path in files]
    token = claim_token(job_id)
    ids = []
    with tempfile.TemporaryDirectory() as tmp:
        items = prepared + [(path, None, None) for path in paths]
        for path, data, mime in items:
            is_file = data is not None
            what = "result file" if is_file else "screenshot"
            if not is_file:
                data, mime = image_bytes(path, tmp)
                if len(data) > MAX_IMAGE_BYTES:
                    die(f"image over 5 MB after downscaling: {path}")
            body = {"claim_token": token, "mime": mime, "bytes": len(data)}
            if is_file:
                body["filename"] = Path(path).name
            status, payload = api("POST", f"/api/jobs/{job_id}/attachments", body)
            older = status in (400, 404, 405) and payload.get("code") not in ("VALIDATION_ERROR", "NOT_FOUND")
            # A hub from before result files refuses the new type or the filename field as a
            # validation error: say so plainly rather than as a generic refusal.
            if is_file and status == 400 and payload.get("code") == "VALIDATION_ERROR":
                older = True
            if older:
                kind = "result files" if is_file else "agent screenshots"
                print(json.dumps({"error": f"the hub does not accept {kind} yet (the slot route "
                                  f"answered {status}: {payload.get('error', 'error')}); "
                                  "comment not posted", "status": status}, indent=1))
                return None, 1
            if not 200 <= status < 300:
                emit(status, {**payload, "error": f"{what} slot refused for {path}: "
                              f"{payload.get('error', 'error')}; comment not posted"})
                return None, 1
            slot = payload["data"]
            put = put_bytes(slot["upload_url"], data, mime)
            if not 200 <= put < 300:
                print(json.dumps({"error": f"{what} upload failed for {path} (HTTP {put}); "
                                  "comment not posted", "status": put}, indent=1))
                return None, 1
            ids.append(slot["id"])
    return ids, 0


def cmd_comment(a):
    body = a.body if a.body is not None else (Path(a.body_file).read_text() if a.body_file else sys.stdin.read())
    if not body.strip():
        die("empty comment body")
    ids = None
    images, files = a.image or [], getattr(a, "file", None) or []
    if images or files:
        if len(images) + len(files) > MAX_IMAGES:
            die(f"at most {MAX_IMAGES} images and files per comment")
        ids, code = upload_images(a.id, images, files)
        if ids is None:
            return code
    return emit(*post_comment(a.id, a.kind, body, a.agent, ids))


# ── Ship preflight ──────────────────────────────────────────────────────────


def default_branch(repo):
    """origin/HEAD's branch; else main, then master, whichever exists locally."""
    head_ref = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
    if head_ref:
        return head_ref.split("/", 1)[1]
    for b in ("main", "master"):
        if git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{b}", check=False):
            return b
    return "main"


def preflight_check(repo, branch, approved_sha, fetch=True, recheck=False):
    """Return a list of reasons the ship must not start; empty means go.
    Checks: the default branch has nothing unpushed, and the job branch head has the approved tree.
    Trees, not commits: /merge squashes a multi-commit or wip branch (reset --soft + a new commit),
    which changes the head SHA but keeps the tree the operator reviewed.
    recheck=True (just before the push) skips the unpushed check: the merge made it true."""
    reasons = []
    if not recheck:
        reasons += unpushed_reasons(repo, fetch)
    head = git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}", check=False)
    if not head:
        reasons.append(f"branch {branch} not found in {repo}")
    else:
        tree = git(repo, "rev-parse", "--verify", "--quiet", f"{head}^{{tree}}", check=False)
        want = approved_sha and git(repo, "rev-parse", "--verify", "--quiet", f"{approved_sha}^{{tree}}", check=False)
        if not want or tree != want:
            reasons.append(f"{branch} head {head[:12]} does not have the tree of the approved SHA "
                           f"{(approved_sha or 'none')[:12]}")
    return reasons


def unpushed_reasons(repo, fetch):
    reasons = []
    if fetch and git(repo, "fetch", "--quiet", "origin", check=False) is None:
        reasons.append("git fetch failed")
    default = default_branch(repo)
    upstream = git(repo, "rev-parse", "--abbrev-ref", f"{default}@{{u}}", check=False) or f"origin/{default}"
    ahead = git(repo, "log", "--oneline", f"{upstream}..{default}", check=False)
    if ahead is None:
        reasons.append(f"cannot compare {default} with {upstream}")
    elif ahead:
        n = len(ahead.splitlines())
        reasons.append(f"{default} is {n} commit(s) ahead of {upstream}: another thread's work would ship with this job")
    return reasons


def cmd_preflight(a):
    status, payload = api("GET", f"/api/jobs/{a.id}")
    if status != 200:
        return emit(status, payload)
    job = payload["data"]
    run = next((r for r in job.get("runs", []) if r["target"] == a.target), None)
    if not run:
        die(f"JOB-{a.id} has no run for {a.target}", 1)
    reasons = [] if run["state"] == "approved" else [f"run state is {run['state']}, not approved"]
    if not reasons:
        reasons = preflight_check(a.repo, run["branch"], run.get("approved_sha"), recheck=a.recheck)
    result = {"ok": not reasons, "target": a.target, "branch": run["branch"], "reasons": reasons}
    if reasons and a.void:
        body = "Ship preflight refused, nothing was merged or pushed:\n- " + "\n- ".join(reasons) + \
               "\nThe approval is voided. Re-approve once the cause is cleared."
        result["comment"] = post_comment(a.id, "event", body)[0]
        # A state change on an approved run makes job_run_set call void_approval.
        result["void"] = run_update(a.id, a.target, state="committed")[0]
    print(json.dumps(result, indent=1))
    return 0 if not reasons else 1


# ── Data repos on the box (MARIPOSA ADR 0122) ─────────────────────────────

DATA_REPOS_FILE = "/etc/box-agent/data-repos.json"  # root 0644; absent off the box
BOXD_FILE = "/opt/box-agent/boxd.py"                 # root 0755; its sensitive() is the broker's own


def data_scope(repo, target, base, head, cfg=DATA_REPOS_FILE, boxd=BOXD_FILE):
    """Whether boxd would refuse to ship base...head of target for leaving its data-repo prefixes.
    Loads boxd itself and calls its data_repos(), named_in_data_repos() and sensitive(), so the
    answer is the broker's own, then mirrors outside_prefixes: renames off, a symlink or submodule
    counts anywhere, and a sensitive path counts inside a prefix too. "error" means boxd would
    refuse too (a malformed file naming the target) or the answer is unknown: treat it as outside."""
    if not Path(cfg).exists():
        return {"data_repo": False}
    t = target.lower()
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("boxd", boxd)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.CFG["etc"] = str(Path(cfg).parent)
        repos = mod.data_repos()
        if repos is None:
            return {"data_repo": True, "error": f"{cfg} is malformed"} if mod.named_in_data_repos(t) \
                else {"data_repo": False}
        if t not in repos:
            return {"data_repo": False}
        r = subprocess.run(["git", "-C", str(repo), "diff", "--raw", "-z", "--no-renames", "--no-ext-diff",
                            "--no-abbrev", f"{base}...{head}", "--"], capture_output=True, text=True, check=True)
    except Exception as e:  # no boxd, a bad SHA: unknown, so never offer an Approve boxd may refuse
        return {"data_repo": True, "error": f"data-scope check failed: {e}"}
    out = r.stdout.split("\0")
    outside = [path for meta, path in zip(out[0::2], out[1::2])
               if not path.startswith(repos[t]) or mod.sensitive(path)
               or {"120000", "160000"} & set(meta.lstrip(":").split(" ")[:2])]
    return {"data_repo": True, "prefixes": list(repos[t]), "outside": outside}


def cmd_data_scope(a):
    print(json.dumps(data_scope(a.repo, a.target, a.base, a.head), indent=1))
    return 0


# ── Self-test ───────────────────────────────────────────────────────────────


def selftest():
    import tempfile

    assert target_from_url("git@github.com:Owner/Repo.git", "x") == "owner/repo"
    assert target_from_url("https://github.com/owner/my.repo.git", "x") == "owner/my.repo"
    assert target_from_url("https://github.com/owner/repo/", "x") == "owner/repo"
    assert target_from_url("ssh://git@github.com/o/r", "x") == "o/r"
    assert target_from_url(None, "My Dir") == "local/my-dir"
    assert target_from_url("", "WIDGET") == "local/widget"

    # _owning_dir: a transcript's cwd matching the slug wins while it still exists; a
    # pruned worktree (its cwd deleted) falls back to the main worktree, found via
    # `git worktree list` from whichever other surviving cwd the session visited.
    with tempfile.TemporaryDirectory() as root:
        root = Path(root).resolve()  # macOS /tmp is a symlink; match git's own realpath output
        main_repo = root / "main"
        main_repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=main_repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=main_repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=main_repo, check=True)
        (main_repo / "f").write_text("x")
        subprocess.run(["git", "add", "f"], cwd=main_repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=main_repo, check=True)
        wt_dir = root / "main-wt" / "task"
        wt_dir.parent.mkdir()
        subprocess.run(["git", "worktree", "add", str(wt_dir), "-b", "task"], cwd=main_repo, check=True)

        slug = re.sub(r"[^A-Za-z0-9]", "-", str(wt_dir))
        assert _owning_dir(slug, [str(main_repo), str(wt_dir)]) == str(wt_dir), \
            "slug-matched cwd that still exists wins directly"

        subprocess.run(["rm", "-rf", str(wt_dir)], check=True)
        assert _owning_dir(slug, [str(main_repo), str(wt_dir)]) == str(main_repo), \
            "slug-matched cwd now gone falls back to the main worktree"

    # resolved_session_dir: a transcript that resolves to a worktree wins over
    # JOBS_RUN_DIR (the poller's start-up cwd, which goes stale after EnterWorktree);
    # a truncated/malformed "cwd" line in the transcript is skipped, not fatal.
    import unittest.mock
    with tempfile.TemporaryDirectory() as root2:
        root2 = Path(root2).resolve()
        repo2 = root2 / "repo"
        repo2.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo2, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo2, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=repo2, check=True)
        (repo2 / "f").write_text("x")
        subprocess.run(["git", "add", "f"], cwd=repo2, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=repo2, check=True)
        wt2 = root2 / "repo-wt" / "task"
        wt2.parent.mkdir()
        subprocess.run(["git", "worktree", "add", str(wt2), "-b", "task2"], cwd=repo2, check=True)

        fake_home = root2 / "home"
        slug2 = re.sub(r"[^A-Za-z0-9]", "-", str(wt2))
        proj_dir = fake_home / ".claude" / "projects" / slug2
        proj_dir.mkdir(parents=True)
        sid = "testsid"
        transcript = proj_dir / f"{sid}.jsonl"
        # First line truncated mid-object (still contains the "cwd" substring that
        # gates the json.loads call); second line is the real, well-formed entry.
        transcript.write_text(
            '{"cwd": "/tmp/truncated-not-json\n'
            + json.dumps({"cwd": str(wt2)}) + "\n"
        )

        with unittest.mock.patch.object(Path, "home", return_value=fake_home):
            os.environ["JOBS_RUN_DIR"] = "/tmp/stale-poller-startup-dir"
            try:
                assert resolved_session_dir(sid) == str(wt2), \
                    "malformed cwd line must be skipped, not fatal, and the worktree must win"
            finally:
                del os.environ["JOBS_RUN_DIR"]

            # A transcript with no usable "cwd" line at all resolves to None, so the
            # caller (cmd_claim / run_update) is the one that falls back to JOBS_RUN_DIR.
            transcript.write_text('{"cwd": "/tmp/still-not-json\n')
            assert resolved_session_dir(sid) is None, \
                "no owning directory found must return None, not raise or guess the cwd"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        os.environ["JOBS_CONFIG_DIR"] = str(tmp / "cfg")
        for k in ("JOBS_BASE_URL", "JOBS_AGENT_TOKEN", "JOBS_ORCHESTRATORS"):
            os.environ.pop(k, None)
        cfg, path = load_config()
        assert path.read_text() == TEMPLATE and oct(path.stat().st_mode & 0o777) == "0o600"
        assert cfg["JOBS_AGENT_TOKEN"] == ""
        path.write_text("JOBS_BASE_URL=http://x\nJOBS_AGENT_TOKEN=\"abc\"\n")
        load_config()
        assert path.read_text().startswith("JOBS_BASE_URL=http://x"), "template must not overwrite"
        os.environ["JOBS_BASE_URL"] = "http://override"
        assert load_config()[0] == {"JOBS_BASE_URL": "http://override", "JOBS_AGENT_TOKEN": "abc"}
        del os.environ["JOBS_BASE_URL"]

        t1 = claim_token(7, create=True)
        assert claim_token(7, create=True) == t1 and claim_token(7) == t1, "retries reuse the token"
        assert claim_token(8, create=True) != t1
        assert oct(claims_path().stat().st_mode & 0o777) == "0o600"
        # Concurrent creators: every job keeps one token, and no job's token is lost.
        pids = []
        for i in range(8):
            pid = os.fork()
            if pid == 0:
                claim_token(100 + i % 4, create=True)
                os._exit(0)
            pids.append(pid)
        assert all(os.waitpid(p, 0)[1] == 0 for p in pids)
        c = read_claims()
        assert {"7", "8", "100", "101", "102", "103"} <= set(c) and c["7"] == t1, c

        # A body read that times out is a JSON refusal, not a traceback.
        import http.server
        import threading
        import time

        class Stall(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.flush()
                time.sleep(2)

            def log_message(self, *_):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Stall)
        threading.Thread(target=srv.handle_request, daemon=True).start()
        global HTTP_TIMEOUT
        HTTP_TIMEOUT, saved = 0.5, HTTP_TIMEOUT
        os.environ["JOBS_BASE_URL"] = f"http://127.0.0.1:{srv.server_port}"
        os.environ["JOBS_AGENT_TOKEN"] = "t"
        status, payload = api("GET", "/api/jobs")
        assert status == 0 and payload["code"] == "UNREACHABLE", payload
        HTTP_TIMEOUT = saved
        srv.server_close()
        # A short body (IncompleteRead) and a non-UTF-8 body are JSON refusals too.
        class Bad(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"a"' if self.path == "/short" else b"\xff\xfe"
                self.send_response(200)
                self.send_header("Content-Length", "100" if self.path == "/short" else "2")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Bad)
        threading.Thread(target=lambda: [srv.handle_request() for _ in range(2)], daemon=True).start()
        os.environ["JOBS_BASE_URL"] = f"http://127.0.0.1:{srv.server_port}"
        assert api("GET", "/short") == (0, {"error": "hub read failed: IncompleteRead", "code": "UNREACHABLE"})
        assert api("GET", "/bytes")[1]["code"] == "BAD_RESPONSE"
        srv.server_close()
        # list --source reaches the hub as ?source=, beside the other filters.
        seen = []

        class Echo(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                body = b'{"data":{"jobs":[],"next_cursor":null}}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Echo)
        threading.Thread(target=srv.handle_request, daemon=True).start()
        os.environ["JOBS_BASE_URL"] = f"http://127.0.0.1:{srv.server_port}"
        ns = argparse.Namespace(column="backlog", target=None, source="zero", awaiting=False,
                                ship_approved=False, all_pages=False)
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            assert cmd_list(ns) == 0
        assert seen == ["/api/jobs?column=backlog&source=zero"], seen
        srv.server_close()

        # comment --image: slot, PUT, then one comment naming the slots. Offline fake hub.
        hits = []

        class Hub(http.server.BaseHTTPRequestHandler):
            deployed = True

            def reply(self, status, obj):
                body = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                sent = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                hits.append(("POST", self.path, sent))
                if self.path.endswith("/attachments"):
                    if not Hub.deployed:
                        return self.reply(405, {})
                    n = sum(1 for h in hits if h[1].endswith("/attachments"))
                    url = f"http://127.0.0.1:{self.server.server_port}/upload/{n}?token=t"
                    return self.reply(201, {"data": {"id": 40 + n, "upload_url": url, "method": "PUT",
                                                     "headers": {"content-type": sent["mime"]}}})
                self.reply(201, {"data": {"id": 99}})

            def do_GET(self):
                hits.append(("GET", self.path, self.headers.get("Authorization")))
                if self.path.startswith("/api/jobs/"):
                    return self.reply(200, {"data": Hub.job})
                if self.path.startswith("/gone/"):
                    return self.reply(400, {"error": "expired"})
                body = self.path.encode()  # a stored object: its bytes are its own path
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_PUT(self):
                data = self.rfile.read(int(self.headers["Content-Length"]))
                hits.append(("PUT", self.path, (self.headers["Content-Type"], data,
                                                self.headers.get("Authorization"))))
                self.reply(200, {})

            def log_message(self, *_):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Hub)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        os.environ["JOBS_BASE_URL"] = f"http://127.0.0.1:{srv.server_port}"
        shots = [tmp / "a.png", tmp / "b.jpg"]
        for i, f in enumerate(shots):
            f.write_bytes(b"not-really-an-image-%d" % i)  # sips cannot read it: the original goes
        tok = claim_token(5, create=True)
        ns = argparse.Namespace(id=5, kind="message", body="done", body_file=None, agent="t",
                                image=[str(f) for f in shots])
        with contextlib.redirect_stdout(io.StringIO()):
            assert cmd_comment(ns) == 0
        assert [h[:2] for h in hits] == [("POST", "/api/jobs/5/attachments"), ("PUT", "/upload/1?token=t"),
                                         ("POST", "/api/jobs/5/attachments"), ("PUT", "/upload/2?token=t"),
                                         ("POST", "/api/jobs/5/comments")], hits
        assert hits[0][2] == {"claim_token": tok, "mime": "image/png", "bytes": 21}
        assert hits[1][2] == ("image/png", b"not-really-an-image-0", None), "PUT carries no bearer"
        assert hits[3][2][0] == "image/jpeg"
        assert hits[4][2] == {"kind": "message", "body": "done", "agent": "t", "attachment_ids": [41, 42]}
        # Before the hub deploys the route: a clear failure, and no text-only comment.
        hits.clear()
        Hub.deployed = False
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert cmd_comment(ns) == 1
        assert "does not accept agent screenshots yet" in out.getvalue(), out.getvalue()
        assert [h[1] for h in hits] == ["/api/jobs/5/attachments"], hits
        # comment --file: checked locally, then slot (with filename), PUT, one comment.
        Hub.deployed = True
        hits.clear()
        rep = tmp / "2026-10-10 triage report.html"
        rep.write_bytes(b"\xef\xbb\xbf\n  <!DOCTYPE html><html><body>r</body></html>")
        pdf = tmp / "brief.pdf"
        pdf.write_bytes(b"%PDF-1.7\n%fake\n")
        nf = argparse.Namespace(id=5, kind="message", body="result", body_file=None, agent="t",
                                image=[str(shots[0])], file=[str(rep), str(pdf)])
        with contextlib.redirect_stdout(io.StringIO()):
            assert cmd_comment(nf) == 0
        assert [h[:2] for h in hits] == [("POST", "/api/jobs/5/attachments"), ("PUT", "/upload/1?token=t"),
                                         ("POST", "/api/jobs/5/attachments"), ("PUT", "/upload/2?token=t"),
                                         ("POST", "/api/jobs/5/attachments"), ("PUT", "/upload/3?token=t"),
                                         ("POST", "/api/jobs/5/comments")], hits
        assert hits[0][2] == {"claim_token": tok, "mime": "text/html", "bytes": rep.stat().st_size,
                              "filename": "2026-10-10 triage report.html"}, hits[0]
        assert hits[1][2][0] == "text/html" and hits[1][2][2] is None
        assert hits[2][2]["mime"] == "application/pdf" and hits[2][2]["filename"] == "brief.pdf"
        assert hits[4][2] == {"claim_token": tok, "mime": "image/png", "bytes": 21}
        assert hits[6][2]["attachment_ids"] == [41, 42, 43]
        # Wrong magic bytes, another type, or too many: refused locally, nothing sent.
        hits.clear()
        bad = tmp / "fake.pdf"
        bad.write_bytes(b"<html>not a pdf")
        txt = tmp / "notes.txt"
        txt.write_text("x")
        for files, extra in (([str(bad)], []), ([str(txt)], []), ([str(rep)] * 4, [str(shots[0])] * 3)):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                try:
                    cmd_comment(argparse.Namespace(id=5, kind="message", body="x", body_file=None,
                                                   agent="t", image=extra, file=files))
                    raise AssertionError("expected a refusal")
                except SystemExit as e:
                    assert e.code == 2, e.code
        assert hits == [], hits
        # An older hub refuses the file type as a validation error: clear failure, nothing posted.
        class OldHub(Hub):
            def do_POST(self):
                sent = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                hits.append(("POST", self.path, sent))
                if self.path.endswith("/attachments") and sent["mime"] not in IMAGE_MIME.values():
                    return self.reply(400, {"error": "Invalid option", "code": "VALIDATION_ERROR"})
                return self.reply(201, {"data": {"id": 99}})
        old = http.server.HTTPServer(("127.0.0.1", 0), OldHub)
        threading.Thread(target=old.serve_forever, daemon=True).start()
        os.environ["JOBS_BASE_URL"] = f"http://127.0.0.1:{old.server_port}"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert cmd_comment(argparse.Namespace(id=5, kind="message", body="x", body_file=None,
                                                  agent="t", image=None, file=[str(rep)])) == 1
        assert "does not accept result files yet" in out.getvalue(), out.getvalue()
        assert [h[1] for h in hits] == ["/api/jobs/5/attachments"], hits
        old.shutdown()
        old.server_close()
        os.environ["JOBS_BASE_URL"] = f"http://127.0.0.1:{srv.server_port}"
        # Without --image the payload is unchanged.
        hits.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            assert cmd_comment(argparse.Namespace(id=5, kind="event", body="x", body_file=None,
                                                  agent="t", image=None)) == 0
        assert hits == [("POST", "/api/jobs/5/comments", {"kind": "event", "body": "x", "agent": "t"})]

        # fetch: operator comments above the cursor only, into $TMPDIR/jobs/<id>/<comment>/<name>.
        u = f"http://127.0.0.1:{srv.server_port}"
        Hub.job = {"id": 5, "ack_comment_id": 20, "comments": [
            {"id": 10, "author": "you", "attachments": [{"id": 1, "kind": "image", "url": f"{u}/s/old.webp?t"}]},
            {"id": 21, "author": "agent", "attachments": [{"id": 2, "kind": "image", "url": f"{u}/s/ag.png?t"},
                                                          {"id": 3, "kind": "result", "url": "/jobs/files/3"}]},
            {"id": 22, "author": "you", "body": "no files"},
            {"id": 23, "author": "you", "attachments": [
                {"id": 4, "kind": "image", "url": f"{u}/s/a.webp?t", "expires_in": 3600},
                {"id": 5, "kind": "file", "url": f"{u}/s/b.bin?t", "name": "brief.pdf",
                 "mime": "application/octet-stream", "bytes": 9},
                {"id": 6, "kind": "image", "url": f"{u}/s/c.jpg?t"},
                {"id": 7, "kind": "file", "url": f"{u}/s/d.bin?t", "name": "../../../etc/passwd"},
                {"id": 8, "kind": "file", "url": f"{u}/s/e.bin?t", "name": "/abs\\..\\x\nname"},
                {"id": 9, "kind": "file", "url": f"{u}/s/f.bin?t", "name": ".."},
                {"id": 11, "kind": "file", "url": f"{u}/s/g.bin?t", "name": "brief.pdf"},
                {"id": 12, "kind": "file", "url": None, "name": "unsigned.txt"},
                {"id": 13, "kind": "file", "url": f"{u}/gone/h.bin?t", "name": "late.zip"}]}]}
        tempfile.tempdir = str(tmp / "T")
        jroot = tmp / "T" / "jobs" / "5"

        def fetch(comment=None):
            hits.clear()
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = cmd_fetch(argparse.Namespace(id=5, comment=comment))
            return rc, out.getvalue().splitlines(), err.getvalue()

        rc, paths, err = fetch()
        assert rc == 1, "two attachments could not be fetched"
        d = (jroot / "23").resolve()
        names = ["image-1.webp", "brief.pdf", "image-2.jpg", ".._.._.._etc_passwd", "_abs_.._x_name",
                 "file-9", "11-brief.pdf"]
        assert paths == [str(d / n) for n in names], paths
        assert all(Path(x).resolve().parent == d for x in paths), "no name escapes its folder"
        assert (d / "brief.pdf").read_bytes() == b"/s/b.bin?t" and (d / "11-brief.pdf").read_bytes() == b"/s/g.bin?t"
        assert "not fetched: 23/unsigned.txt: no download URL" in err and "23/late.zip: 400" in err, err
        assert not (jroot / "10").exists() and not (jroot / "21").exists(), "below the cursor or agent: skipped"
        assert hits[0] == ("GET", "/api/jobs/5", "Bearer t"), hits[0]
        assert all(h[2] is None for h in hits[1:]), "signed URLs carry no bearer"
        assert sorted(os.listdir(tmp / "T")) == ["jobs"] and sorted(os.listdir(tmp / "T" / "jobs")) == ["5"]
        # --comment N: that comment only, cursor or not.
        rc, paths, _ = fetch(10)
        assert rc == 0 and paths == [str((jroot / "10").resolve() / "image-1.webp")], paths
        assert [h[1] for h in hits] == ["/api/jobs/5", "/s/old.webp?t"], hits
        rc, paths, _ = fetch(999)
        assert rc == 1 and paths[0] == "{" and [h[1] for h in hits] == ["/api/jobs/5"]
        # Nothing new above the cursor: no downloads, no output.
        Hub.job = {**Hub.job, "ack_comment_id": 23}
        assert fetch()[:2] == (0, []) and len(hits) == 1
        tempfile.tempdir = None
        assert len(safe_name("\u00e9" * 300, "f").encode()) <= 200 and safe_name(" . ", "f") == "f"
        srv.shutdown()
        srv.server_close()
        for k in ("JOBS_BASE_URL", "JOBS_AGENT_TOKEN"):
            del os.environ[k]

        # Preflight against a local bare origin: no network.
        def sh(cwd, *args):
            subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)
        origin, repo = tmp / "origin.git", tmp / "repo"
        sh(tmp, "init", "--quiet", "--bare", "-b", "main", str(origin))
        sh(tmp, "clone", "--quiet", str(origin), str(repo))
        for c in (("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
            sh(repo, *c)
        sh(repo, "commit", "--quiet", "--allow-empty", "-m", "base")
        sh(repo, "push", "--quiet", "-u", "origin", "main")
        sh(repo, "remote", "set-head", "origin", "main")
        sh(repo, "checkout", "--quiet", "-b", "job/1-x")
        sh(repo, "commit", "--quiet", "--allow-empty", "-m", "work")
        approved = git(repo, "rev-parse", "HEAD")
        sh(repo, "checkout", "--quiet", "main")
        assert preflight_check(repo, "job/1-x", approved) == []
        assert preflight_check(repo, "job/1-x", approved[:7]) == []
        r = preflight_check(repo, "job/1-x", "0" * 40)
        assert len(r) == 1 and "tree of the approved SHA" in r[0]
        assert "not found" in preflight_check(repo, "job/9-nope", approved)[0]
        sh(repo, "commit", "--quiet", "--allow-empty", "-m", "someone else's work")
        r = preflight_check(repo, "job/1-x", approved)
        assert len(r) == 1 and "1 commit(s) ahead" in r[0], r
        assert preflight_check(repo, "job/1-x", approved, recheck=True) == [], "recheck skips unpushed"
        assert "tree of the approved SHA" in preflight_check(repo, "job/1-x", "0" * 40, recheck=True)[0]
        # /merge's squash: new head, same tree, still passes. A changed tree refuses.
        sh(repo, "checkout", "--quiet", "job/1-x")
        (repo / "f.txt").write_text("a")
        sh(repo, "add", "f.txt")
        sh(repo, "commit", "--quiet", "-m", "wip auto-commit")
        approved = git(repo, "rev-parse", "HEAD")
        sh(repo, "reset", "--quiet", "--soft", "main~1")
        sh(repo, "commit", "--quiet", "-m", "feat: squashed")
        assert git(repo, "rev-parse", "HEAD") != approved
        assert preflight_check(repo, "job/1-x", approved, recheck=True) == [], "squash keeps the tree"
        (repo / "f.txt").write_text("b")
        sh(repo, "commit", "--quiet", "-am", "edit after approval")
        assert "tree of the approved SHA" in preflight_check(repo, "job/1-x", approved, recheck=True)[0]
        sh(repo, "checkout", "--quiet", "main")

        # Default branch: origin/HEAD wins, else main, else master.
        assert default_branch(repo) == "main"
        sh(repo, "remote", "set-head", "origin", "-d")
        assert default_branch(repo) == "main"
        m = tmp / "m"
        sh(tmp, "init", "--quiet", "-b", "master", str(m))
        sh(m, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "--quiet", "--allow-empty", "-m", "x")
        assert default_branch(m) == "master"
        sh(tmp, "init", "--quiet", "-b", "trunk", str(tmp / "t"))
        assert default_branch(tmp / "t") == "main"
        sh(repo, "remote", "set-head", "origin", "main")
        import shutil
        shutil.rmtree(m)
        shutil.rmtree(tmp / "t")

        assert target_of(repo) == "local/repo"
        sh(repo, "remote", "set-url", "origin", "https://github.com/Acme/Widget.git")
        assert target_of(repo) == "acme/widget"
        sh(repo, "worktree", "add", "--quiet", str(tmp / "repo-wt"), "job/1-x")
        assert repo_root(tmp / "repo-wt") == repo.resolve() or repo_root(tmp / "repo-wt") == repo
        assert [r["display"] for r in sibling_repos(tmp)] == ["repo"], "bare and worktree dirs skipped"
        for parent in ("group", "Archive", "_old"):
            sh(tmp, "init", "--quiet", str(tmp / parent / "inner"))
        found = sibling_repos(tmp)
        assert [r["display"] for r in found] == ["inner", "repo"], "nested found, retired skipped"
        assert found[0]["path"] == str(tmp / "group" / "inner")
        sh(tmp, "init", "--quiet", str(tmp / "repo" / "child"))
        found = sibling_repos(tmp)
        assert [r["display"] for r in found] == ["inner", "repo", "child"], "child repo inside a checkout found"
    # data_scope: what boxd would refuse for a data repo, read from data-repos.json.
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        repo, cfg, fake = d / "r", d / "data-repos.json", d / "boxd.py"
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)

        def commit(path):
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text(path)
            for c in (("add", "-A"), ("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", path)):
                subprocess.run(["git", "-C", str(repo), *c], check=True, capture_output=True)
            return git(repo, "rev-parse", "HEAD")
        base = commit("README")
        inside = commit("network/a/index.md")
        cfg.write_text(json.dumps({"version": 1, "repos": {"owner/Data": ["exec-news/", "network/"]}}))
        fake.write_text(  # boxd's three calls, cut down: the real ones live in MARIPOSA box/agent/boxd.py
            "import json, pathlib\nCFG = {'etc': '/nowhere'}\n"
            "def data_repos():\n"
            "    try:\n        m = json.loads((pathlib.Path(CFG['etc']) / 'data-repos.json').read_text())\n"
            "    except ValueError:\n        return None\n"
            "    return {k.lower(): tuple(v) for k, v in m['repos'].items()}\n"
            "def named_in_data_repos(t):\n"
            "    return t in (pathlib.Path(CFG['etc']) / 'data-repos.json').read_text().lower()\n"
            "def sensitive(p):\n    return p.lower().endswith('claude.md')\n")
        scope = lambda head, t="owner/data", c=cfg: data_scope(repo, t, base, head, cfg=c, boxd=fake)  # noqa: E731
        assert scope(inside) == {"data_repo": True, "prefixes": ["exec-news/", "network/"], "outside": []}
        out = commit(".claude/settings.json")
        assert scope(out)["outside"] == [".claude/settings.json"], scope(out)
        nested = commit("network/CLAUDE.md")
        assert "network/CLAUDE.md" in scope(nested)["outside"], "boxd's sensitive() counts inside a prefix"
        assert scope(inside, t="owner/other") == {"data_repo": False}
        assert scope(inside, c=d / "missing.json") == {"data_repo": False}
        assert "error" in scope("0" * 40), "a bad SHA is unknown, never a clean pass"
        assert "error" in data_scope(repo, "owner/data", base, inside, cfg=cfg, boxd=d / "nope.py")
        cfg.write_text('{not json "owner/data"')
        assert "error" in scope(inside), "malformed and naming the target: boxd refuses it too"
        assert scope(inside, t="owner/other") == {"data_repo": False}
    print("jobs.py selftest: ok")
    return 0


def main():
    if "--selftest" in sys.argv[1:]:
        return selftest()
    p = argparse.ArgumentParser(prog="jobs.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("here").set_defaults(fn=cmd_here)
    s = sub.add_parser("list")
    s.add_argument("--column", choices=["backlog", "in_progress", "in_review", "done"])
    s.add_argument("--target")
    s.add_argument("--source", choices=["board", "zero"])
    s.add_argument("--awaiting", action="store_true")
    s.add_argument("--ship-approved", action="store_true")
    s.add_argument("--all-pages", action="store_true")
    s.set_defaults(fn=cmd_list)
    for name, fn in (("get", cmd_get), ("attachments", cmd_attachments)):
        s = sub.add_parser(name)
        s.add_argument("id", type=int)
        s.set_defaults(fn=fn)
    s = sub.add_parser("fetch")
    s.add_argument("id", type=int)
    s.add_argument("--comment", type=int)
    s.set_defaults(fn=cmd_fetch)
    s = sub.add_parser("claim-token")
    s.add_argument("id", type=int)
    s.set_defaults(fn=cmd_claim_token)
    s = sub.add_parser("claim")
    s.add_argument("id", type=int)
    s.add_argument("--agent")
    s.set_defaults(fn=cmd_claim)
    s = sub.add_parser("patch")
    s.add_argument("id", type=int)
    s.add_argument("--column", choices=["in_progress", "in_review", "done"])
    s.add_argument("--size", choices=["quick", "build", "grill", "prototype", "to_driver", "wayfinder"])
    s.add_argument("--size-reason")
    s.add_argument("--targets-picked")
    s.add_argument("--ack", type=int)
    s.add_argument("--active", choices=["on", "off"], help="heartbeat: an agent is working now")
    s.set_defaults(fn=cmd_patch)
    s = sub.add_parser("run")
    s.add_argument("id", type=int)
    s.add_argument("--target", required=True)
    s.add_argument("--branch")
    s.add_argument("--base-sha")
    s.add_argument("--head-sha")
    s.add_argument("--state", choices=["claimed", "committed", "failed"])
    s.set_defaults(fn=cmd_run)
    s = sub.add_parser("shipped")
    s.add_argument("id", type=int)
    s.add_argument("--target", required=True)
    s.add_argument("--deployed-sha", required=True)
    s.set_defaults(fn=cmd_shipped)
    s = sub.add_parser("repin", help="move a run's approval to a fixed head, on operator consent")
    s.add_argument("id", type=int)
    s.add_argument("--target", required=True)
    s.add_argument("--head-sha", required=True)
    s.add_argument("--comment", type=int, required=True,
                   help="the newest operator comment: the approve event or a reply asking to ship")
    s.add_argument("--note", required=True, help="one line: what the fix was")
    s.set_defaults(fn=cmd_repin)
    s = sub.add_parser("comment")
    s.add_argument("id", type=int)
    s.add_argument("--kind", choices=["message", "event"], default="message")
    s.add_argument("--body")
    s.add_argument("--body-file")
    s.add_argument("--agent")
    s.add_argument("--image", action="append", metavar="PATH",
                   help="a screenshot to attach (repeatable, at most 6)")
    s.add_argument("--file", action="append", metavar="PATH",
                   help="an HTML or PDF result file to attach (repeatable; shares the 6 with --image)")
    s.set_defaults(fn=cmd_comment)
    s = sub.add_parser("repos")
    s.add_argument("--root")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_repos)
    s = sub.add_parser("preflight")
    s.add_argument("id", type=int)
    s.add_argument("--target", required=True)
    s.add_argument("--repo", required=True)
    s.add_argument("--void", action="store_true")
    s.add_argument("--recheck", action="store_true",
                   help="just before the push: approval and SHA only, skip the unpushed check")
    s.set_defaults(fn=cmd_preflight)
    s = sub.add_parser("data-scope", help="on the box: paths boxd would refuse for a data repo")
    s.add_argument("--target", required=True)
    s.add_argument("--repo", required=True)
    s.add_argument("--base", required=True)
    s.add_argument("--head", required=True)
    s.set_defaults(fn=cmd_data_scope)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
