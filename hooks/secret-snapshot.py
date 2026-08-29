#!/usr/bin/env python3
"""PreToolUse(Bash) hook — snapshot gitignored secret/config files before any
Bash command can touch them, so a destructive command (truncation, bad sed,
rm) is always recoverable.

Design: for every Bash call, look at the sensitive files that exist in the
tool's cwd. If the command text references one by name, or uses a destructive
operator, copy each such file to a timestamped backup — but only when its
content differs from the newest existing backup (sha dedup), so constant reads
(e.g. `grep X .env.local`) don't spam backups. Never blocks; any error → exit 0.

Backups: ~/.claude/secret-backups/<cwd-slug>/<basename>/<ISO>.bak  (keep 60).
Restore: ~/.claude/scripts/restore-secret.sh
"""
import sys, os, json, glob, hashlib, shutil, re, time

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if data.get("tool_name") != "Bash":
        return
    cmd = (data.get("tool_input") or {}).get("command", "") or ""
    cwd = data.get("cwd") or os.getcwd()

    # sensitive filename globs (repo-root + one level deep)
    patterns = [
        ".env", ".env.*", "*.env", "*.pem", "*.key", "id_rsa*", "id_ed25519*",
        "*.p12", "*.pfx", "credentials.json", "credentials", ".npmrc",
        ".secrets*", "service-account*.json", "*.keystore", ".env.local",
    ]
    candidates = set()
    for base in (cwd, *[d for d in glob.glob(os.path.join(cwd, "*")) if os.path.isdir(d)][:40]):
        for pat in patterns:
            for f in glob.glob(os.path.join(base, pat)):
                if os.path.isfile(f) and os.path.getsize(f) >= 0:
                    candidates.add(f)
    if not candidates:
        return

    destructive = bool(re.search(
        r'(^|[^>])>[^>&]|>\||\bopen\([^)]*[\'"]w[\'"]|\bsed\b[^\n]*\s-i\b|\btruncate\b|\btee\b|\brm\b|\bdd\b|\bmv\b|\bcp\b',
        cmd))

    slug = re.sub(r'[^A-Za-z0-9]+', '-', cwd).strip('-')[:120]
    root = os.path.expanduser(f"~/.claude/secret-backups/{slug}")
    touched = 0
    for f in candidates:
        name = os.path.basename(f)
        # snapshot when the command names this file, or when it's destructive at all
        if not destructive and name not in cmd and f not in cmd:
            continue
        try:
            with open(f, "rb") as fh:
                content = fh.read()
        except Exception:
            continue
        # never snapshot an empty file — a truncation must not shadow the good
        # backup as the "newest" copy the restore tool picks
        if len(content) == 0:
            continue
        sha = hashlib.sha256(content).hexdigest()
        bdir = os.path.join(root, name)
        os.makedirs(bdir, exist_ok=True)
        backups = sorted(glob.glob(os.path.join(bdir, "*.bak")))
        # dedup against newest existing backup
        if backups:
            try:
                with open(backups[-1], "rb") as fh:
                    if hashlib.sha256(fh.read()).hexdigest() == sha:
                        continue
            except Exception:
                pass
        # skip snapshotting an already-empty file over a non-empty last backup
        # (don't let a truncation overwrite the good copy — but here we snapshot
        #  the CURRENT good state BEFORE the command runs, so just save it)
        stamp = time.strftime("%Y%m%dT%H%M%S")
        dst = os.path.join(bdir, f"{stamp}.bak")
        try:
            shutil.copy2(f, dst)
            touched += 1
        except Exception:
            continue
        # prune to newest 60
        allb = sorted(glob.glob(os.path.join(bdir, "*.bak")))
        for old in allb[:-60]:
            try:
                os.remove(old)
            except Exception:
                pass

    if touched and destructive:
        sys.stderr.write(
            f"[secret-snapshot] backed up {touched} sensitive file(s) before this command "
            f"→ ~/.claude/secret-backups/{slug}/ (restore: ~/.claude/scripts/restore-secret.sh)\n")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
