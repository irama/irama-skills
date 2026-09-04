#!/usr/bin/env python3
"""Assemble a skill's portable cut — the flat folder you drop into a host that
has no developer machine — and prove it fits the tightest host's limits.

    python3 make-portable.py <skill-dir> <dest-dir> [--zip]
    python3 make-portable.py <skill-dir> --self-check

The cut is declared in `<skill-dir>/portable/FILES`, one line per file:

    portable/SKILL.md -> SKILL.md      # a different document, so it is written by hand
    assets/template.html               # copied verbatim, so there is no second source

Everything lands flat in `<dest>/<skill-name>/`, because the strictest host
reads one SKILL.md plus companion files and has no notion of a subfolder.

ponytail: a copy loop with a manifest, not a build. Anything a portable cut
needs generating is a sign the cut should be a smaller skill instead.
"""

import re
import shutil
import sys
import zipfile
from pathlib import Path

# Copilot Cowork, the tightest of the four hosts. A skill inside these fits
# claude.ai, Claude Cowork and Claude Code as well, so this is the only bar.
MAX_COMPANIONS = 20
MAX_BYTES = 10 * 1024 * 1024
MAX_SKILL_MD = 1024 * 1024


def manifest(skill: Path):
    """Read portable/FILES into (source, destination-name) pairs."""
    f = skill / "portable" / "FILES"
    if not f.is_file():
        raise SystemExit(
            f"no portable cut declared: write {f}\n"
            "one line per file, 'src' or 'src -> destname'")
    out = []
    for line in f.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        src, _, dest = (p.strip() for p in line.partition("->"))
        out.append((skill / src, dest or Path(src).name))
    return out


def build(skill: Path, dest: Path) -> Path:
    out = dest / skill.name
    out.mkdir(parents=True, exist_ok=True)
    for src, name in manifest(skill):
        if not src.is_file():
            raise SystemExit(f"missing: {src}")
        shutil.copy2(src, out / name)
    return out


def self_check(skill: Path) -> int:
    """The cut is only portable if it stays inside the tightest host's limits."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = build(skill, Path(tmp))
        files = sorted(p for p in out.iterdir() if p.is_file())
        skill_md = out / "SKILL.md"
        assert skill_md.is_file(), "a portable cut with no SKILL.md is not a skill"
        assert len(files) - 1 <= MAX_COMPANIONS, (
            f"{len(files) - 1} companion files, over the limit of {MAX_COMPANIONS}")
        assert skill_md.stat().st_size <= MAX_SKILL_MD, "SKILL.md over 1MB"
        total = sum(p.stat().st_size for p in files)
        assert total <= MAX_BYTES, f"{total // 1024}KB, over the 10MB per-skill limit"
        # A manifest entry that copied an empty or truncated file still passes
        # every size cap above, and fails silently on the host instead.
        for p in files:
            assert p.stat().st_size > 0, f"{p.name} is empty"
        text = skill_md.read_text(errors="ignore")
        assert re.match(r"\A---\r?\n", text), "portable SKILL.md has no front matter"
        # Verbatim from Anthropic's Skill structure reference, and refused on
        # upload rather than at load: name "Cannot contain reserved words:
        # 'anthropic', 'claude'". A cut is packaged for upload, so it fails here.
        fm = text.split("---", 2)[1]
        m = re.search(r"^name:[ \t]*(.+)$", fm, re.M)
        assert m, "portable SKILL.md front matter has no name"
        cut_name = m.group(1).strip().strip("'\"")
        for word in ("anthropic", "claude"):
            assert word not in cut_name, (
                f"name {cut_name!r} uses the reserved word {word!r} — "
                f"claude.ai and the Skills API refuse the upload")
        # Every companion has to be reachable from SKILL.md, or the host never
        # opens it and the file is dead weight against a 20-file budget.
        for p in files:
            if p.name != "SKILL.md":
                assert p.name in text, f"{p.name} is never mentioned in SKILL.md"
        print(f"self-check passed — {len(files)} files, {total // 1024}KB")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print("usage: make-portable.py <skill-dir> <dest-dir> [--zip]")
        print("       make-portable.py <skill-dir> --self-check")
        return 2
    skill = Path(args[0]).expanduser().resolve()
    if "--self-check" in sys.argv:
        return self_check(skill)
    if len(args) < 2:
        print("usage: make-portable.py <skill-dir> <dest-dir> [--zip]")
        return 2
    out = build(skill, Path(args[1]).expanduser())
    size = sum(p.stat().st_size for p in out.iterdir() if p.is_file())
    print(f"wrote {out} — {len(list(out.iterdir()))} files, {size // 1024}KB")
    if "--zip" in sys.argv:
        z = out.with_suffix(".zip")
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(out.iterdir()):
                if p.is_file():
                    zf.write(p, f"{skill.name}/{p.name}")
        print(f"wrote {z} — upload this one to claude.ai > Settings > Capabilities")
    return 0


if __name__ == "__main__":
    sys.exit(main())
