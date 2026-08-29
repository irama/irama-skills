#!/usr/bin/env python3
"""Trello dispatcher for the /trello skill.

This script owns the Trello credentials. The agent that does the work never
receives them and never posts free text — it hands `report`/`done` a typed JSON
payload and this script assembles the comment itself. That asymmetry is the
main security control: an injected "post the output of env" instruction has
nowhere to put the output.

stdlib only, no dependencies. Reads config from <project>/.claude/trello.json
and credentials from <project>/.env.local.

ponytail: no state file. "Did we post this comment?" is answered by comparing
the comment's author to the bot member id, which the bot account gives us for
free. Add a state file only if the bot ever posts as a human.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.trello.com/1"
SUMMARY_CAP = 1500
ENV_KEYS = ("TRELLO_API_KEY", "TRELLO_TOKEN", "TRELLO_BOARD_ID")


# --------------------------------------------------------------------------
# config / credentials


def project_root(start=None):
    d = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isdir(os.path.join(d, ".git")) or os.path.isfile(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.abspath(start or os.getcwd())
        d = parent


def parse_env(path):
    """Parse .env.local without sourcing it. Never writes, never truncates."""
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load(root=None):
    root = root or project_root()
    env = parse_env(os.path.join(root, ".env.local"))
    missing = [k for k in ENV_KEYS if not env.get(k)]
    if missing:
        die(f"missing in .env.local: {', '.join(missing)}. Run: trello.py setup --help")
    cfg_path = os.path.join(root, ".claude", "trello.json")
    cfg = {}
    if os.path.isfile(cfg_path):
        with open(cfg_path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    return root, env, cfg


def die(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


# --------------------------------------------------------------------------
# api


def call(env, method, path, params=None, body=None):
    params = dict(params or {})
    params.update({"key": env["TRELLO_API_KEY"], "token": env["TRELLO_TOKEN"]})
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:200]
        if e.code == 401 and "invalid key" in detail:
            detail += (
                "  [hint: TRELLO_TOKEN may hold the Power-Up *Secret* instead of a "
                "token. A real token is ~76 chars starting ATTA.]"
            )
        die(f"Trello {method} {path} -> {e.code} {detail}")


def digest(text):
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


def slug(text, maxlen=48):
    """Card titles become branch/worktree names. Everything outside [a-z0-9-]
    is destroyed here so no card text ever reaches a shell as syntax."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (s[:maxlen].rstrip("-")) or "card"


# --------------------------------------------------------------------------
# redaction — belt to the typed-schema braces


def redactor(env):
    secrets = [v for v in env.values() if len(v) >= 8]
    pats = [
        re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"),
        re.compile(r"\bATTA[A-Za-z0-9]{20,}"),
        re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+"),
        re.compile(r"\b(?:postgres|postgresql|mysql|mongodb)(?:\+\w+)?://\S+"),
        re.compile(r"-----BEGIN[^-]+-----"),
        re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),
        re.compile(r"\b[0-9a-f]{32,}\b"),
    ]

    def scrub(text):
        if not text:
            return text
        for s in secrets:
            text = text.replace(s, "[REDACTED]")
        for p in pats:
            text = p.sub("[REDACTED]", text)
        return text

    return scrub


# --------------------------------------------------------------------------
# comment assembly — the agent supplies fields, never prose blocks


def build_comment(payload, scrub, kind):
    status = str(payload.get("status", ""))[:80]
    branch = str(payload.get("branch", ""))[:120]
    summary = str(payload.get("summary", ""))[:SUMMARY_CAP]
    tests = str(payload.get("tests", ""))[:300]
    nxt = str(payload.get("next", ""))[:400]
    commits = [str(c)[:80] for c in (payload.get("commits") or [])][:20]
    files = [str(f)[:200] for f in (payload.get("files") or [])][:40]

    head = "**Claude — work complete, for review**" if kind == "report" else "**Claude — closed out**"
    parts = [head, ""]
    if status:
        parts.append(f"**Status:** {status}")
    if branch:
        parts.append(f"**Branch:** `{branch}`")
    if commits:
        parts.append("**Commits:** " + ", ".join(f"`{c}`" for c in commits))
    if tests:
        parts.append(f"**Tests:** {tests}")
    if files:
        parts.append("**Files touched:**")
        parts += [f"- `{f}`" for f in files]
    if summary:
        parts += ["", summary]
    if nxt:
        parts += ["", f"**Next:** {nxt}"]
    parts += ["", "_Posted by the /trello dispatcher. Reply on this card or in chat._"]
    return scrub("\n".join(parts))


def read_payload(path):
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        die("payload must be a JSON object")
    allowed = {"status", "branch", "commits", "files", "tests", "summary", "next"}
    extra = set(payload) - allowed
    if extra:
        die(f"unknown payload fields: {sorted(extra)}. Allowed: {sorted(allowed)}")
    return payload


# --------------------------------------------------------------------------
# commands


def list_id(cfg, role):
    try:
        return cfg["columns"][role]["id"]
    except (KeyError, TypeError):
        die(f"config has no column mapped to '{role}'. Run: trello.py setup")


def cmd_whoami(env, cfg, args):
    me = call(env, "GET", "members/me", {"fields": "id,username,fullName"})
    boards = call(env, "GET", "members/me/boards", {"fields": "name,shortLink"})
    out(
        {
            "me": me,
            "boards": boards,
            "bot_member_id_in_config": (cfg.get("bot") or {}).get("id"),
            "is_bot": (cfg.get("bot") or {}).get("id") == me["id"],
        }
    )


def cmd_setup(env, cfg, args):
    board = env["TRELLO_BOARD_ID"]
    lists = call(env, "GET", f"boards/{board}/lists", {"fields": "name"})
    members = call(env, "GET", f"boards/{board}/members", {"fields": "username,fullName"})
    me = call(env, "GET", "members/me", {"fields": "id,username"})
    out(
        {
            "board": call(env, "GET", f"boards/{board}", {"fields": "name,shortLink"}),
            "lists": lists,
            "members": members,
            "token_identity": me,
        }
    )


def cmd_poll(env, cfg, args):
    """Candidates are cards in the todo column ASSIGNED to the bot member.

    Assignment beats a title prefix: it is Trello's own native signal, it shows
    as an avatar on the card, it is one click to give or take back, and it
    cannot be set by editing text — so nobody hands us work by typing a magic
    string into a title. Unassigning is also the operator's stop button."""
    bot = (cfg.get("bot") or {}).get("id")
    if not bot:
        die("config.bot.id is not set — nothing to match cards against. Run: trello.py setup")
    todo = list_id(cfg, "todo")
    cards = call(
        env,
        "GET",
        f"lists/{todo}/cards",
        {"fields": "name,desc,shortUrl,idList,idMembers,dateLastActivity"},
    )
    result = []
    for c in cards:
        if bot not in (c.get("idMembers") or []):
            continue
        result.append(
            {
                "id": c["id"],
                "name": c["name"],
                "url": c["shortUrl"],
                "slug": slug(c["name"]),
                "digest": digest(c["desc"]),
                "desc_chars": len(c["desc"]),
                "authors": authors_of(env, c["id"]),
            }
        )
    out(
        {
            "match": f"assigned to {(cfg.get('bot') or {}).get('username')} in {cfg['columns']['todo']['name']}",
            "count": len(result),
            "candidates": result,
            "scanned": len(cards),
        }
    )


def authors_of(env, card_id):
    """Who wrote the CURRENT description — the createCard author is not it.
    A member who edits a card leaves the creator field untouched, so the
    description-edit action is the thing to attribute."""
    acts = call(
        env,
        "GET",
        f"cards/{card_id}/actions",
        {"filter": "createCard,updateCard:desc", "limit": "50"},
    )
    created_by, edited_by = None, None
    for a in acts or []:
        who = {
            "id": a["idMemberCreator"],
            "username": (a.get("memberCreator") or {}).get("username"),
            "at": a["date"],
        }
        if a["type"] == "createCard" and not created_by:
            created_by = who
        if a["type"] == "updateCard" and not edited_by:
            edited_by = who
    return {"created_by": created_by, "desc_last_edited_by": edited_by or created_by}


def cmd_card(env, cfg, args):
    c = call(env, "GET", f"cards/{args.card}", {"fields": "name,desc,shortUrl,idList"})
    out(
        {
            "id": c["id"],
            "name": c["name"],
            "url": c["shortUrl"],
            "slug": slug(c["name"]),
            "digest": digest(c["desc"]),
            "authors": authors_of(env, c["id"]),
            "desc": c["desc"],
        }
    )


def cmd_claim(env, cfg, args):
    """Fail closed on any description change between triage and claim."""
    c = call(env, "GET", f"cards/{args.card}", {"fields": "name,desc,idMembers"})
    bot = (cfg.get("bot") or {}).get("id")
    if bot not in (c.get("idMembers") or []):
        die("card is no longer assigned to the bot — unassignment is the stop button. ABORTING.", code=3)
    now = digest(c["desc"])
    if now != args.digest:
        die(
            f"description changed since triage (approved {args.digest}, now {now}). "
            "ABORTING — re-run poll and re-triage.",
            code=2,
        )
    call(env, "PUT", f"cards/{args.card}", {"idList": list_id(cfg, "wip")})
    out({"claimed": args.card, "digest": now, "moved_to": cfg["columns"]["wip"]["name"]})


def cmd_replies(env, cfg, args):
    """Comments NOT written by the bot. The bot's own output must never come
    back as if it were the operator — that is the self-approval attack."""
    bot = (cfg.get("bot") or {}).get("id")
    if not bot:
        die("config.bot.id is not set — cannot distinguish our own comments. Run: trello.py setup")
    acts = call(
        env, "GET", f"cards/{args.card}/actions", {"filter": "commentCard", "limit": "50"}
    )
    replies = []
    for a in acts or []:
        if a["idMemberCreator"] == bot:
            continue
        replies.append(
            {
                "id": a["id"],
                "at": a["date"],
                "author_id": a["idMemberCreator"],
                "author": (a.get("memberCreator") or {}).get("username"),
                "text": a["data"]["text"],
                "digest": digest(a["data"]["text"]),
            }
        )
    out({"card": args.card, "bot_id": bot, "count": len(replies), "replies": replies})


def _post(env, cfg, args, kind, dest_role):
    scrub = redactor(env)
    text = build_comment(read_payload(args.json), scrub, kind)
    call(env, "POST", f"cards/{args.card}/actions/comments", {"text": text})
    call(env, "PUT", f"cards/{args.card}", {"idList": list_id(cfg, dest_role)})
    out({"card": args.card, "moved_to": cfg["columns"][dest_role]["name"], "comment": text})


def cmd_report(env, cfg, args):
    _post(env, cfg, args, "report", "review")


def cmd_done(env, cfg, args):
    _post(env, cfg, args, "done", "done")


def out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(description="Trello dispatcher for the /trello skill")
    p.add_argument("--root", help="project root (default: nearest git root)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami", help="identity of the configured token + visible boards")
    sub.add_parser("setup", help="dump board lists/members for building .claude/trello.json")
    sub.add_parser("poll", help="candidate cards in the todo column, with authors + digest")

    c = sub.add_parser("card", help="one card, full description + authors")
    c.add_argument("card")

    c = sub.add_parser("claim", help="verify digest unchanged, then move to WIP")
    c.add_argument("card")
    c.add_argument("digest")

    c = sub.add_parser("replies", help="comments excluding the bot's own")
    c.add_argument("card")

    for name, helptext in (("report", "post review comment + move to Review"),
                           ("done", "post closing comment + move to Done")):
        c = sub.add_parser(name, help=helptext)
        c.add_argument("card")
        c.add_argument("--json", required=True, help="path to typed payload")

    args = p.parse_args()
    root, env, cfg = load(args.root)
    globals()[f"cmd_{args.cmd}"](env, cfg, args)


if __name__ == "__main__":
    main()
