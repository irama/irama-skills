#!/usr/bin/env python3
"""PreToolUse(Write) guard: if an .html file being written poses questions the
user is meant to answer but is NOT built on the html-brief runtime, block and
point at the skill. Stops plain-HTML plans/proposals/question-files from
shipping with no way to answer them inline.

Blocks (exit 2) only when the signal is strong (an explicit "open questions"/
"sign-off" phrase, or 2+ question-headings) AND the brief runtime is absent.
Anything already wired to the runtime (data-brief-id / brief.js) passes.
"""
import json
import re
import sys

try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)  # can't parse → don't interfere

tool = payload.get("tool_name", "")
ti = payload.get("tool_input", {}) or {}
path = ti.get("file_path", "") or ""

# Only guard full-file Writes of .html (Edits are partial — no reliable context).
if tool != "Write" or not path.lower().endswith((".html", ".htm")):
    sys.exit(0)

content = ti.get("content", "") or ""
if not content:
    sys.exit(0)

# Already a brief? Pass.
if "data-brief-id" in content or "brief.js" in content:
    sys.exit(0)

# Strong question signal.
q_headings = len(re.findall(r"(?is)<h[1-6][^>]*>[^<]{0,200}\?\s*</h[1-6]>", content))
phrase = re.search(
    r"(?i)open questions|questions? for (you|us|review)|needs? sign-?off|"
    r"decisions? (to make|needed)|please answer|awaiting your (answer|input)",
    content,
)

if q_headings < 2 and not phrase:
    sys.exit(0)  # not question-shaped enough → pass

msg = (
    "html-brief-guard: this .html poses questions/decisions for the user but is "
    "NOT built on the html-brief runtime — so there's no answer box, no "
    "select-to-comment, no 'Copy responses' button, and questions aren't wired "
    "for inline answers.\n\n"
    "Build it with the html-brief skill instead:\n"
    "  • Skill(html-brief) — read ~/.claude/skills/html-brief/SKILL.md\n"
    "  • Base the file on assets/brief-template.html; copy brief.css + brief.js "
    "next to it; give <body> a data-brief-id; make each question a "
    "<section class=\"q\" data-q=\"Qn\">.\n\n"
    "If this file genuinely has no questions to answer (a pure read-only "
    "report), the signal misfired — reword the question-shaped headings or wire "
    "in the brief runtime, then re-write."
)
print(msg, file=sys.stderr)
sys.exit(2)
