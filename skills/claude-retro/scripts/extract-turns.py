#!/usr/bin/env python3
"""Extract real human turns and the assistant text they replied to.

Machine-generated text is the trap. Measured 2026-08-30: background-agent completion
notices, pasted quiz/brief JSON and compaction summaries were 41.8% of everything that
looked like a user turn, and 84% of the long ones, because they are long and full of
framework vocabulary. Every filter below exists because that contamination was found by a
reader agent rather than by the filter.

Usage: extract-turns.py <out.jsonl> [days]
"""
import json, os, sys, re, glob
from datetime import datetime, timezone

ROOT = os.path.expanduser("~/.claude/projects")
CHECK = re.compile(r"\b(pytest|npm (run )?test|vitest|jest|tsc\b|typecheck|eslint|ruff|mypy|"
                   r"npm run build|next build|cargo (test|build)|go test|playwright|curl -|"
                   r"lighthouse|shellcheck|bash -n|validate|gate)\b", re.I)

def text_of(msg):
    c = msg.get("content")
    if isinstance(c, str):
        return c
    return "\n".join(b.get("text", "") for b in c or []
                     if isinstance(b, dict) and b.get("type") == "text")

def is_human(ev):
    if ev.get("type") != "user" or ev.get("isMeta") or ev.get("isSidechain"):
        return False
    if "toolUseResult" in ev or ev.get("attachment"):
        return False
    m = ev.get("message") or {}
    c = m.get("content")
    if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
        return False
    t = text_of(m).strip()
    if not t:
        return False
    if t.startswith(("<command-name>", "<local-command", "Caveat:", "[SYSTEM NOTIFICATION")):
        return False
    if "task-notification" in t or "<system-reminder>" in t[:200]:
        return False
    if t.startswith("{") and any(k in t[:400] for k in ('"kind"', '"brief"', '"answers"')):
        return False
    if t.startswith("<") and t.endswith(">"):
        return False
    if t.startswith("This session is being continued from a previous"):
        return False
    return True

def parse_ts(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None

def main():
    out_path = sys.argv[1]
    cutoff = None
    if len(sys.argv) > 2:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(sys.argv[2]))
    n_sess = n_turn = 0
    with open(out_path, "w") as out:
        for pdir in sorted(os.listdir(ROOT)):
            full = os.path.join(ROOT, pdir)
            if not os.path.isdir(full):
                continue
            for f in glob.glob(os.path.join(full, "*.jsonl")):
                events = []
                try:
                    with open(f, errors="replace") as fh:
                        for line in fh:
                            try:
                                d = json.loads(line)
                            except Exception:
                                continue
                            if d.get("type") in ("user", "assistant"):
                                events.append(d)
                except Exception:
                    continue
                if len(events) < 4:
                    continue
                n_sess += 1
                sid = os.path.basename(f)[:-6]
                hi = 0
                atext, tools, bash = [], [], []
                for ev in events:
                    if is_human(ev):
                        hi += 1
                        ts = parse_ts(ev.get("timestamp", ""))
                        if hi > 1 and atext and (cutoff is None or (ts and ts >= cutoff)):
                            n_turn += 1
                            out.write(json.dumps({
                                "id": f"{sid}:{hi}", "project": pdir, "ts": ev.get("timestamp"),
                                "assistant_said": "\n".join(atext)[-3000:],
                                "human_replied": text_of(ev.get("message") or {}).strip()[:2500],
                                "n_tool_calls": len(tools),
                                "check_ran": bool(CHECK.search(" ".join(bash))),
                            }, ensure_ascii=False) + "\n")
                        atext, tools, bash = [], [], []
                    elif ev.get("type") == "assistant" and not ev.get("isSidechain"):
                        m = ev.get("message") or {}
                        t = text_of(m)
                        if t.strip():
                            atext.append(t)
                        for b in (m.get("content") or []):
                            if isinstance(b, dict) and b.get("type") == "tool_use":
                                tools.append(b.get("name", "?"))
                                if b.get("name") == "Bash":
                                    bash.append(str((b.get("input") or {}).get("command", ""))[:300])
    print(f"sessions {n_sess}, human turns {n_turn}", file=sys.stderr)

if __name__ == "__main__":
    main()
