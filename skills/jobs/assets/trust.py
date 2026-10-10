#!/usr/bin/env python3
"""Mark folders as trusted in ~/.claude.json, so a headless `claude -p` run there keeps the
folder's permission allow rules. Claude Code walks up to the git root and no further, so each
repo needs its own entry: a trusted parent folder does not cover the repos inside it.

    trust.py DIR [DIR ...]   trust these folders
    trust.py --all           trust every main checkout that `jobs.py repos --dry-run` finds

Writes a temp file, then renames it over ~/.claude.json, so a crash never truncates it.
"""
import json
import os
import subprocess
import sys
import tempfile

CONF = os.path.expanduser("~/.claude.json")


def trust(dirs):
    with open(CONF) as f:
        conf = json.load(f)
    projects = conf.setdefault("projects", {})
    added = []
    for d in dirs:
        key = os.path.realpath(d)
        entry = projects.setdefault(key, {})
        if entry.get("hasTrustDialogAccepted") is not True:
            entry["hasTrustDialogAccepted"] = True
            added.append(key)
    if added:
        # ponytail: a running Claude session can still rewrite the file from its own copy;
        # the poller calls this before every run, so a lost entry comes back next run.
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CONF), prefix=".claude.json.")
        with os.fdopen(fd, "w") as f:
            json.dump(conf, f, indent=2)
        os.chmod(tmp, os.stat(CONF).st_mode & 0o777)
        os.replace(tmp, CONF)
    return added


def all_checkouts():
    here = os.path.dirname(os.path.abspath(__file__))
    out = subprocess.run([sys.executable, os.path.join(here, "jobs.py"), "repos", "--dry-run"],
                         capture_output=True, text=True, check=True).stdout
    return [r["path"] for r in json.loads(out)["repos"]]


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    dirs = all_checkouts() if args == ["--all"] else args
    for d in trust([d for d in dirs if os.path.isdir(d)]):
        print("trusted", d)
