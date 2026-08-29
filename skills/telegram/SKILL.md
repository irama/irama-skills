---
name: telegram
description: Send a Telegram message to the user from any repo — a "finished, come back" ping when a long run, build, batch, deploy or background agent completes, or any note they asked to be told about. Use when the user says "telegram me", "ping me on Telegram", "message me when this is done", "notify me when it finishes", or invokes /telegram. Also runs the one-time bot setup wizard when Telegram is not configured yet.
---

# Telegram

Send the user a Telegram message. One script, one `curl`, no dependencies.

```bash
bash ~/.claude/skills/telegram/send.sh "Your message text"
```

Prints `telegram: sent` on success. Markdown is tried first and falls back to
plain text if Telegram rejects the formatting, so odd characters never lose a
message.

## When to send

Send only when the user asked for a ping, or when they set up a standing rule
("always telegram me when a driver leg ends"). Do not ping on ordinary turns —
they are already reading the chat.

Good triggers:

- A long run finishes: build, test sweep, batch, deploy, `/driver` leg, background agent.
- A run fails and they walked away.
- Something they explicitly asked to be told about at a certain point.

Write the message for a phone screen, away from the terminal:

- Name the app or repo first — the ping arrives with no context.
- Say the outcome in one line, with the number that matters.
- Say what waits for them, if anything.

```
Study repo — question bank audit done. 412 questions, 7 gaps closed, gate green.
Nothing waiting; branch is committed.
```

## Configuration

Credentials live in `~/.claude/.telegram.env` (mode 600, outside every repo):

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

`send.sh` exits with `telegram: not configured` when that file is missing.

## First-time setup

Only the user can create a Telegram bot, so this is a wizard, not a step you
run for them:

```bash
bash ~/.claude/skills/telegram/setup.sh
```

Three stages: create the bot with BotFather and paste the token, message the
bot once so the wizard can read the chat id back automatically, then send a
test message. It is idempotent — re-run it to rotate the token, and press
Enter to keep any value it already has.

Tell the user to run it in their own terminal. Never run it yourself; it opens
a browser and blocks on typed input.

## Notes

- The bot can only message a person who has messaged it first. That is Telegram's rule, not a bug — if sends start failing with `chat not found`, the user deleted the chat and has to press Start again.
- To ping a group instead, add the bot to the group and re-run the wizard; the chat id it finds will be negative.
- Sending is fire-and-forget. If it fails, say so in the chat reply too, so a failed ping never silently swallows the news.
