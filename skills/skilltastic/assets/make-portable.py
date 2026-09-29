#!/usr/bin/env python3
"""Assemble a skill's portable cut, the folder you drop into a host that has
no developer machine, and prove it fits the tightest host's limits.

    python3 make-portable.py <skill-dir> <dest-dir> [--zip] [--md-only] [--single-file]
    python3 make-portable.py <skill-dir> --self-check [--md-only] [--single-file]
    python3 make-portable.py --selftest

Two modes, picked by whether the skill declares `portable/FILES`:

Legacy mode. `<skill-dir>/portable/FILES` lists the cut, one line per file:

    portable/SKILL.md -> SKILL.md      # a different document, so it is written by hand
    assets/template.html               # copied verbatim, so there is no second source

and everything lands flat in `<dest>/<skill-name>/`, for a skill written
before hosts read subfolders.

Folder mode. No `portable/FILES`: the cut is the whole skill folder,
recursively, with relative paths kept (`references/library.md` stays there).

`--md-only` refuses any file that is not `.md`. `--single-file` emits one
`SKILL.md` with each `references/*.md` inlined under `## Reference: <file>`,
links to them rewritten to in-page anchors, and `SOURCES.md` appended under
`## Sources`, for a host that takes one file and nothing else.

Every source must sit inside the skill folder: symlinks, `..`, absolute
paths, hidden files and colliding names are refused. The cut is built in a
fresh temporary folder and renamed into place, and a non-empty destination is
refused, so a stale file can never ride along.

ponytail: a copy loop with a manifest, not a build. Anything a portable cut
needs generating is a sign the cut should be a smaller skill instead.
"""

import argparse
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

# Copilot Cowork, the tightest of the four hosts. A skill inside these fits
# claude.ai, Claude Cowork and Claude Code as well, so this is the only bar.
MAX_COMPANIONS = 20
MAX_BYTES = 10 * 1024 * 1024
MAX_SKILL_MD = 1024 * 1024


class PackError(Exception):
    """A cut that must not ship. main() prints it and exits 1."""


def need(ok, msg):
    # An explicit raise, because `assert` vanishes under `python -O`.
    if not ok:
        raise PackError(msg)


def safe_rel(rel: str, what: str) -> str:
    """A relative POSIX path with no traversal, no hidden part, no absolute root."""
    p = PurePosixPath(rel)
    # A backslash or colon is a plain character to POSIX but a separator, drive
    # (`C:`) or UNC root (`\\host\share`) on Windows, so `sub\..\..\x.md`
    # would pass the parts check below and still traverse once joined there.
    need(rel and not p.is_absolute() and "\\" not in rel and ":" not in rel,
         f"{what} {rel!r} must be a relative path")
    for part in p.parts:
        need(part not in ("..", "."), f"{what} {rel!r} may not use '..' or '.'")
        need(not part.startswith("."), f"{what} {rel!r} is hidden")
    return p.as_posix()


def inside(skill: Path, rel: str) -> Path:
    """Resolve rel under skill, refusing any symlink on the way and any escape."""
    cur = skill
    for part in PurePosixPath(rel).parts:
        cur = cur / part
        need(not cur.is_symlink(), f"{rel} goes through a symlink ({cur.name})")
    root = skill.resolve()
    need(cur.resolve().is_relative_to(root), f"{rel} resolves outside the skill")
    return cur


def plan(skill: Path):
    """The cut as [(source file, relative destination)], legacy or folder mode."""
    need(skill.is_dir(), f"not a skill folder: {skill}")
    f = skill / "portable" / "FILES"
    out = []
    if f.is_file():
        for line in f.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            src, _, dest = (p.strip() for p in line.partition("->"))
            src = safe_rel(src, "source")
            dest = safe_rel(dest or PurePosixPath(src).name, "destination")
            need("/" not in dest, f"destination {dest!r} must be a bare name: "
                 "a legacy cut is flat")
            path = inside(skill, src)
            need(path.is_file(), f"missing: {path}")
            out.append((path, dest))
    else:
        for path in sorted(skill.rglob("*")):
            rel = path.relative_to(skill).as_posix()
            need(not path.is_symlink(), f"{rel} is a symlink")
            safe_rel(rel, "file")
            if path.is_file():
                out.append((path, rel))
    seen = {}
    for _, rel in out:
        key = rel.casefold()  # case-insensitive, as macOS and Windows hosts are
        need(key not in seen, f"two files land on {rel!r}")
        seen[key] = rel
    need(any(rel == "SKILL.md" for _, rel in out),
         "a portable cut with no SKILL.md is not a skill")
    return out


def anchor(heading: str) -> str:
    # GitHub's heading slug, the one most markdown renderers follow.
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


# Any relative link target, of any file type: not an anchor, a scheme or a root.
REL_LINK = re.compile(r"\]\(<?(?![a-z][a-z0-9+.-]*:|/)([^)\s#<>]+)", re.I)
LINK = re.compile(r"\]\((?!#|[a-z][a-z0-9+.-]*:)([^)\s#]+\.md)(#[^)\s]*)?\)", re.I)


def single_file(files, skill: Path) -> str:
    """Fold SKILL.md, references/*.md and SOURCES.md into one document."""
    by = dict((rel, src) for src, rel in files)

    # A reference is known by its source path: a legacy cut has already
    # flattened `references/x.md` to `x.md` on the destination side.
    def is_ref(src):
        r = src.relative_to(skill).as_posix()
        return r.startswith("references/") and r.count("/") == 1 and r.endswith(".md")

    refs = sorted((r for r in by if r not in ("SKILL.md", "SOURCES.md") and is_ref(by[r])),
                  key=lambda r: by[r].name)
    extra = sorted(set(by) - {"SKILL.md", "SOURCES.md", *refs})
    need(not extra, "--single-file cannot carry " + ", ".join(extra))
    heads = {"SKILL.md": ""}
    heads.update((r, anchor(f"Reference: {PurePosixPath(r).name}")) for r in refs)
    if "SOURCES.md" in by:
        heads["SOURCES.md"] = "sources"

    def text(rel):
        here = posixpath.dirname(rel)

        def fix(m):
            target = posixpath.normpath(posixpath.join(here, m.group(1)))
            if target not in heads:
                return m.group(0)
            return f"](#{heads[target]})" if heads[target] else "](#)"

        return LINK.sub(fix, by[rel].read_text()).rstrip("\n")

    parts = [text("SKILL.md")]
    parts += [f"## Reference: {PurePosixPath(r).name}\n\n{text(r)}" for r in refs]
    if "SOURCES.md" in by:
        parts.append(f"## Sources\n\n{text('SOURCES.md')}")
    doc = "\n\n".join(parts) + "\n"
    need(len(doc.encode()) <= MAX_SKILL_MD, "--single-file SKILL.md is over 1MB")
    return doc


def build(skill: Path, dest: Path, md_only=False, one_file=False) -> Path:
    files = plan(skill)
    if md_only:
        bad = [rel for _, rel in files if not rel.lower().endswith(".md")]
        need(not bad, "--md-only refuses " + ", ".join(bad))
    out = dest / skill.name
    need(not out.is_symlink(), f"{out} is a symlink")
    need(not out.exists() or (out.is_dir() and not any(out.iterdir())),
         f"{out} is not empty: remove it, or pick another destination")
    dest.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{skill.name}.", dir=dest))
    mask = os.umask(0)
    os.umask(mask)
    os.chmod(tmp, 0o777 & ~mask)  # mkdtemp makes 0700; a cut folder is shared
    try:
        if one_file:
            (tmp / "SKILL.md").write_text(single_file(files, skill))
        else:
            for src, rel in files:
                (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, tmp / rel)
        if out.exists():
            out.rmdir()
        os.rename(tmp, out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return out


def walk(out: Path):
    return sorted(p for p in out.rglob("*") if p.is_file())


def self_check(skill: Path, md_only=False, one_file=False) -> int:
    """The cut is only portable if it stays inside the tightest host's limits."""
    with tempfile.TemporaryDirectory() as tmp:
        out = build(skill, Path(tmp), md_only, one_file)
        files = walk(out)
        skill_md = out / "SKILL.md"
        need(skill_md.is_file(), "a portable cut with no SKILL.md is not a skill")
        need(len(files) - 1 <= MAX_COMPANIONS,
             f"{len(files) - 1} companion files, over the limit of {MAX_COMPANIONS}")
        need(skill_md.stat().st_size <= MAX_SKILL_MD, "SKILL.md over 1MB")
        total = sum(p.stat().st_size for p in files)
        need(total <= MAX_BYTES, f"{total // 1024}KB, over the 10MB per-skill limit")
        # A manifest entry that copied an empty or truncated file still passes
        # every size cap above, and fails silently on the host instead.
        for p in files:
            need(p.stat().st_size > 0, f"{p.relative_to(out)} is empty")
        text = skill_md.read_text(errors="ignore")
        need(re.match(r"\A---\r?\n", text), "portable SKILL.md has no front matter")
        # Verbatim from Anthropic's Skill structure reference, and refused on
        # upload rather than at load: name "Cannot contain reserved words:
        # 'anthropic', 'claude'". A cut is packaged for upload, so it fails here.
        fm = text.split("---", 2)[1]
        m = re.search(r"^name:[ \t]*(.+)$", fm, re.M)
        need(m, "portable SKILL.md front matter has no name")
        cut_name = m.group(1).strip().strip("'\"")
        for word in ("anthropic", "claude"):
            need(word not in cut_name,
                 f"name {cut_name!r} uses the reserved word {word!r}: "
                 f"claude.ai and the Skills API refuse the upload")
        # Every companion has to be reachable from SKILL.md, or the host never
        # opens it and the file is dead weight against a 20-file budget.
        for p in files:
            rel = p.relative_to(out).as_posix()
            if rel != "SKILL.md":
                need(rel in text, f"{rel} is never mentioned in SKILL.md")
        # A mention is not a working link: a legacy cut flattens references/x.md
        # to x.md, so a link written against the source tree breaks in the cut.
        # Every relative link in every packed .md must land on a packed file.
        packed = {p.relative_to(out).as_posix() for p in files}
        for p in files:
            rel = p.relative_to(out).as_posix()
            if not rel.lower().endswith(".md"):
                continue
            for m in REL_LINK.finditer(p.read_text(errors="ignore")):
                target = posixpath.normpath(posixpath.join(posixpath.dirname(rel),
                                                           unquote(m.group(1))))
                need(target in packed,
                     f"{rel} links to {m.group(1)!r}, which is not in the cut")
        print(f"self-check passed — {len(files)} files, {total // 1024}KB")
    return 0


def write_zip(out: Path, name: str) -> Path:
    z = out.with_suffix(".zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in walk(out):
            zf.write(p, f"{name}/{p.relative_to(out).as_posix()}")
    return z


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    """Both modes, both flags, and every rejection, on throwaway fixtures."""
    ran = 0

    def skill(root: Path, files: dict, name="demo") -> Path:
        s = root / name
        for rel, body in files.items():
            (s / rel).parent.mkdir(parents=True, exist_ok=True)
            (s / rel).write_text(body)
        return s

    def refuses(fn, fragment):
        nonlocal ran
        try:
            fn()
        except PackError as e:
            if fragment not in str(e):
                raise AssertionError(f"wanted {fragment!r}, got {e!r}")
            ran += 1
            return
        raise AssertionError(f"expected a refusal containing {fragment!r}")

    def check(cond, msg):
        nonlocal ran
        if not cond:
            raise AssertionError(msg)
        ran += 1

    fm = "---\nname: demo\ndescription: d\n---\n"
    with tempfile.TemporaryDirectory() as t:
        T = Path(t)

        # Legacy mode: flat, renamed, bytes and mtimes kept, zip flat too.
        s = skill(T / "a", {
            "SKILL.md": "full\n", "assets/t.html": "<p>t</p>\n",
            "portable/SKILL.md": fm + "see t.html\n",
            "portable/FILES": "# note\n\nportable/SKILL.md -> SKILL.md\nassets/t.html\n"})
        out = build(s, T / "a-out")
        check(sorted(p.relative_to(out).as_posix() for p in walk(out))
              == ["SKILL.md", "t.html"], "legacy cut is flat")
        check((out / "SKILL.md").read_bytes() == (s / "portable/SKILL.md").read_bytes()
              and (out / "t.html").read_bytes() == (s / "assets/t.html").read_bytes(),
              "legacy copies bytes verbatim")
        check((out / "t.html").stat().st_mtime == (s / "assets/t.html").stat().st_mtime,
              "legacy keeps mtimes, so the zip is reproducible")
        with zipfile.ZipFile(write_zip(out, s.name)) as zf:
            check(zf.namelist() == ["demo/SKILL.md", "demo/t.html"], "legacy zip")
        self_check(s)
        refuses(lambda: build(s, T / "a-out"), "is not empty")
        (T / "empty" / "demo").mkdir(parents=True)
        build(s, T / "empty")  # an empty destination folder is fine
        ran += 1
        refuses(lambda: build(s, T / "a-out2", md_only=True), "--md-only refuses t.html")
        # A link written against the source tree breaks once the cut is flat.
        s = skill(T / "bl", {
            "SKILL.md": "full\n", "references/x.md": "# X\n",
            "portable/SKILL.md": fm + "Read [x](references/x.md), then x.md.\n",
            "portable/FILES": "portable/SKILL.md -> SKILL.md\nreferences/x.md\n"})
        refuses(lambda: self_check(s), "links to 'references/x.md', which is not in the cut")
        (s / "portable/SKILL.md").write_text(fm + "Read [x](x.md) and [w](https://example.org/a.md).\n")
        self_check(s)
        ran += 1

        # Folder mode: recursive, relative paths kept, checks and zip recurse.
        body = fm + "Read [lib](references/lib.md) and [src](SOURCES.md).\n"
        s = skill(T / "f", {"SKILL.md": body,
                            "references/lib.md": "# Lib\nSee [x](../SOURCES.md#s1).\n",
                            "SOURCES.md": "[S1] Someone (2026).\n"})
        out = build(s, T / "f-out", md_only=True)
        check([p.relative_to(out).as_posix() for p in walk(out)]
              == ["SKILL.md", "SOURCES.md", "references/lib.md"], "folder keeps paths")
        with zipfile.ZipFile(write_zip(out, s.name)) as zf:
            check("demo/references/lib.md" in zf.namelist(), "folder zip recurses")
        self_check(s, md_only=True)
        (s / "references" / "orphan.md").write_text("x\n")
        refuses(lambda: self_check(s), "references/orphan.md is never mentioned")
        (s / "references" / "orphan.md").write_text("")
        refuses(lambda: self_check(s), "is empty")
        (s / "references" / "orphan.md").unlink()
        for i in range(MAX_COMPANIONS):
            (s / f"c{i}.md").write_text("x\n")
        refuses(lambda: self_check(s), "companion files, over the limit")
        for i in range(MAX_COMPANIONS):
            (s / f"c{i}.md").unlink()

        # --single-file: one SKILL.md, references inlined, links to anchors.
        out = build(s, T / "one", one_file=True)
        doc = (out / "SKILL.md").read_text()
        check([p.name for p in walk(out)] == ["SKILL.md"], "single file is one file")
        check("## Reference: lib.md\n\n# Lib" in doc, "reference inlined under heading")
        check("[lib](#reference-libmd)" in doc and "[src](#sources)" in doc
              and "[x](#sources)" in doc, "links rewritten to anchors")
        check(doc.rstrip().endswith("## Sources\n\n[S1] Someone (2026)."),
              "SOURCES.md appended last under ## Sources")
        self_check(s, one_file=True)
        (s / "assets").mkdir()
        (s / "assets" / "x.md").write_text("x\n")
        refuses(lambda: build(s, T / "one2", one_file=True), "cannot carry assets/x.md")
        (s / "assets" / "x.md").unlink()
        (s / "assets").rmdir()
        # A legacy cut flattens references/lib.md to lib.md; still inlined.
        s2 = skill(T / "lf", {"SKILL.md": "full\n", "portable/SKILL.md": fm + "Read [l](lib.md).\n",
                              "references/lib.md": "# Lib\n",
                              "portable/FILES": "portable/SKILL.md -> SKILL.md\n"
                                                "references/lib.md\n"})
        doc = (build(s2, T / "lf-out", one_file=True) / "SKILL.md").read_text()
        check("## Reference: lib.md\n\n# Lib" in doc and "[l](#reference-libmd)" in doc,
              "legacy --single-file inlines references by source path")
        (s / "references" / "big.md").write_text("x" * MAX_SKILL_MD)
        refuses(lambda: build(s, T / "one3", one_file=True), "over 1MB")
        (s / "references" / "big.md").unlink()

        # Rejections: symlinks, traversal, absolute, hidden, collisions, missing.
        outside = T / "secret.md"
        outside.write_text("secret\n")
        s = skill(T / "r1", {"SKILL.md": fm})
        (s / "leak.md").symlink_to(outside)
        refuses(lambda: build(s, T / "r1-out"), "leak.md is a symlink")
        s = skill(T / "r2", {"SKILL.md": fm, "portable/FILES": "SKILL.md\nlink/x.md\n"})
        (s / "link").symlink_to(T)
        refuses(lambda: build(s, T / "r2-out"), "goes through a symlink")
        s = skill(T / "r5", {"SKILL.md": fm, "a\\..\\b.md": "x\n"})
        refuses(lambda: build(s, T / "r5-out"), "must be a relative path")
        s = skill(T / "r3", {"SKILL.md": fm, ".DS_Store": "x"})
        refuses(lambda: build(s, T / "r3-out"), "is hidden")
        for i, (files, frag) in enumerate([
                ("SKILL.md\n../secret.md\n", "may not use '..'"),
                ("SKILL.md\n/etc/hosts\n", "must be a relative path"),
                ("SKILL.md\nsub\\..\\..\\victim.md\n", "must be a relative path"),
                ("SKILL.md\nSKILL.md -> ..\\..\\victim.md\n", "must be a relative path"),
                ("SKILL.md\nC:/Windows/x.md\n", "must be a relative path"),
                ("SKILL.md\nSKILL.md -> c:x.md\n", "must be a relative path"),
                ("SKILL.md\n\\\\host\\share\\x.md\n", "must be a relative path"),
                ("SKILL.md\nSKILL.md -> \\x.md\n", "must be a relative path"),
                ("SKILL.md\n//host/share/x.md\n", "must be a relative path"),
                ("SKILL.md\nSKILL.md -> /tmp/x.md\n", "must be a relative path"),
                ("SKILL.md\nSKILL.md -> sub/x.md\n", "must be a bare name"),
                ("SKILL.md\nSKILL.md -> ../x.md\n", "may not use '..'"),
                ("SKILL.md\n.env\n", "is hidden"),
                ("SKILL.md\nSKILL.md -> .x.md\n", "is hidden"),
                ("SKILL.md\na.md -> skill.md\n", "two files land on"),
                ("SKILL.md\nnope.md\n", "missing:"),
                ("a.md\n", "no SKILL.md")]):
            s = skill(T / f"m{i}", {"SKILL.md": fm, "a.md": "a\n", ".env": "k",
                                    "portable/FILES": files})
            refuses(lambda: build(s, T / f"m{i}-out"), frag)
        s = skill(T / "r4", {"README.md": "x\n"})
        refuses(lambda: build(s, T / "r4-out"), "no SKILL.md")
        check(not any(T.rglob(".demo.*")),
              "a failed build leaves no temp folder behind")

    # The command line: unknown flags and missing arguments exit non-zero.
    me = [sys.executable, str(Path(__file__).resolve())]
    for argv in (["x", "y", "--bogus"], [], ["x", "--self-check", "--zip"]):
        r = subprocess.run(me + argv, capture_output=True)
        check(r.returncode != 0, f"{argv} should exit non-zero")
    print(f"selftest passed: {ran} checks")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Build a skill's portable cut and check it against host limits.")
    ap.add_argument("skill", nargs="?", help="the skill folder")
    ap.add_argument("dest", nargs="?", help="where <dest>/<skill-name>/ is written")
    ap.add_argument("--zip", action="store_true", help="also write <dest>/<name>.zip")
    ap.add_argument("--self-check", action="store_true",
                    help="build into a temp folder and check the host limits")
    ap.add_argument("--md-only", action="store_true", help="refuse any non-.md file")
    ap.add_argument("--single-file", action="store_true",
                    help="emit one SKILL.md with references and sources inlined")
    ap.add_argument("--selftest", action="store_true", help="test this script")
    a = ap.parse_args(argv)
    try:
        if a.selftest:
            return selftest()
        if not a.skill:
            ap.error("give a skill folder")
        skill = Path(a.skill).expanduser().resolve()
        if a.self_check:
            if a.dest or a.zip:
                ap.error("--self-check takes no destination and no --zip")
            return self_check(skill, a.md_only, a.single_file)
        if not a.dest:
            ap.error("give a destination folder, or --self-check")
        out = build(skill, Path(a.dest).expanduser(), a.md_only, a.single_file)
        files = walk(out)
        size = sum(p.stat().st_size for p in files)
        print(f"wrote {out} — {len(files)} files, {size // 1024}KB")
        if a.zip:
            z = write_zip(out, skill.name)
            print(f"wrote {z} — upload this one to claude.ai > Settings > Capabilities")
        return 0
    except PackError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
