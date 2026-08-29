#!/usr/bin/env python3
# PreToolUse hook (Write|Edit): lint SQL migrations for the #1 cross-project bug class —
# SECURITY DEFINER functions losing auth guards / staying callable by PUBLIC.
# Escape hatch: `-- lint: allow <auth-uid|revoke|rls|all>` skips only those checks.
# Exit 2 blocks the write and feeds stderr back to Claude.
import json, re, sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

ti = data.get("tool_input", {})
path = ti.get("file_path") or ""
content = ti.get("content") or ti.get("new_string") or ""

if "/migrations/" not in path or not path.endswith(".sql"):
    sys.exit(0)

# Escape hatch, SCOPED. `-- lint: allow <check>[,<check>]` skips only the named
# checks: auth-uid | revoke | rls. `-- lint: allow all` skips everything.
#
# It used to be blanket: ANY `lint: allow` disabled every check. That is how an
# anon-callable SECURITY DEFINER function shipped (2026-07-17) — the comment was
# justifying an auth.uid() exemption (legitimate: the app uses Clerk, so
# auth.uid() is always NULL) and silently switched off the REVOKE check too. An
# exemption you argued for must never disable a check you didn't.
CHECKS = {"auth-uid", "revoke", "rls", "all"}
_allow = re.search(r"lint:\s*allow\b(.*)$", content, re.M | re.I)
allowed = set()
if _allow:
    # The justification follows an em/en dash; only the tokens before it are
    # check names. Split on the dash FIRST — a lazy character-class match stops
    # inside "auth-uid" at the hyphen and silently captures "auth", which then
    # matches no check and re-enables the very thing you exempted.
    tokens_part = re.split(r"[—–]", _allow.group(1), maxsplit=1)[0]
    toks = {t.strip().lower() for t in tokens_part.split(",") if t.strip()}
    # Bare `-- lint: allow — reason...` = the legacy blanket form. Treat it as
    # auth-uid only: that is what every real use of it has meant, and it is the
    # one check that genuinely cannot be satisfied on a Clerk-auth project.
    allowed = (toks & CHECKS) or {"auth-uid"}
    unknown = toks - CHECKS
    if unknown:
        print(
            f"migration-lint: ignoring unknown `lint: allow` token(s): {', '.join(sorted(unknown))}. "
            f"Known: {', '.join(sorted(CHECKS))}.",
            file=sys.stderr,
        )

def skipped(check):
    return "all" in allowed or check in allowed

problems = []
lower = content.lower()

# Each CREATE [OR REPLACE] FUNCTION ... SECURITY DEFINER must guard auth.uid()
# and be revoked from PUBLIC — CREATE OR REPLACE wipes prior guards.
funcs = re.split(r"(?i)(?=create\s+(?:or\s+replace\s+)?function)", content)
for f in funcs[1:]:
    if "security definer" not in f.lower():
        continue
    name = re.search(r"(?i)function\s+([\w.\"]+)", f)
    fname = name.group(1) if name else "<unknown>"
    if "auth.uid()" not in f.lower() and not skipped("auth-uid"):
        problems.append(
            f"SECURITY DEFINER function {fname} has no auth.uid() guard — it runs with owner "
            f"privileges and bypasses RLS. Re-state the guard (CREATE OR REPLACE wipes prior ones)."
        )
    # Supabase grants EXECUTE on public functions to `anon` and `authenticated`
    # EXPLICITLY (default privileges) — NOT via the PUBLIC pseudo-role. So
    # `REVOKE ... FROM PUBLIC` alone leaves this ACL intact:
    #   postgres=X | anon=X | authenticated=X | service_role=X
    # i.e. still fully callable with the publishable/anon key that ships in the
    # browser bundle. This check used to accept FROM PUBLIC and say the function
    # was safe — false assurance that shipped an anon-callable SECURITY DEFINER
    # function taking workspace_id as an argument (2026-07-17). Require each role.
    missing = [
        role
        for role in ("public", "anon", "authenticated")
        if not re.search(rf"(?i)revoke\s+(all|execute)\b.*\bfrom\s+{role}\b", lower)
    ]
    if missing and not skipped("revoke"):
        problems.append(
            f"SECURITY DEFINER function {fname}: missing "
            + ", ".join(f"`REVOKE EXECUTE ... FROM {r}`" for r in missing)
            + " in this file. REVOKE FROM PUBLIC is NOT enough — Supabase grants EXECUTE to "
            f"anon/authenticated explicitly, so the function stays callable with the anon key. "
            f"Revoke all three, then GRANT only to the role that should call it (usually "
            f"service_role). Verify after applying: "
            f"SELECT proacl FROM pg_proc WHERE proname='{fname.split('.')[-1]}';"
        )

# New tables must enable RLS in the same file.
for m in re.finditer(r"(?i)create\s+table\s+(?:if\s+not\s+exists\s+)?([\w.\"]+)", content):
    tname = m.group(1).split(".")[-1].strip('"')
    if not re.search(
        rf"(?i)alter\s+table\s+[\w.\"]*{re.escape(tname)}\"?\s+enable\s+row\s+level\s+security",
        content,
    ):
        if not skipped("rls"):
            problems.append(
                f"CREATE TABLE {tname} without ENABLE ROW LEVEL SECURITY in the same migration."
            )

if problems:
    print(
        "migration-lint BLOCKED " + path + ":\n- " + "\n- ".join(problems) +
        "\nFix the SQL, or add `-- lint: allow <check>` (auth-uid|revoke|rls) with a "
        "justification comment if intentional. It is scoped on purpose — do not use "
        "`allow all` to silence a check you have not actually reasoned about.",
        file=sys.stderr,
    )
    sys.exit(2)
