#!/usr/bin/env bash
# Send a Telegram message. Usage: send.sh "message text"
set -euo pipefail

ENV_FILE="${TELEGRAM_ENV:-$HOME/.claude/.telegram.env}"
[ -f "$ENV_FILE" ] || { echo "telegram: not configured — run the setup wizard: bash ~/.claude/skills/telegram/setup.sh" >&2; exit 1; }
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a
: "${TELEGRAM_BOT_TOKEN:?missing TELEGRAM_BOT_TOKEN in $ENV_FILE}"
: "${TELEGRAM_CHAT_ID:?missing TELEGRAM_CHAT_ID in $ENV_FILE}"

TEXT="${1:-}"
[ -n "$TEXT" ] || { echo "telegram: no message text given" >&2; exit 2; }

RESP=$(curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${TEXT}" \
  --data-urlencode "parse_mode=Markdown" \
  --data-urlencode "disable_web_page_preview=true")

if echo "$RESP" | grep -q '"ok":true'; then
  echo "telegram: sent"
else
  # Markdown parse failures are common in agent output — retry as plain text.
  RESP2=$(curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${TEXT}")
  if echo "$RESP2" | grep -q '"ok":true'; then
    echo "telegram: sent (plain text; Markdown was rejected)"
  else
    echo "telegram: FAILED — $RESP2" >&2
    exit 1
  fi
fi
