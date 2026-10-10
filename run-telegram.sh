#!/usr/bin/env bash
set -euo pipefail
cd /srv/apps/trustedhousesitters-monitor
if [ -f data/config.env ]; then
  set -a
  source data/config.env
  set +a
fi
# Outbound Telegram runs only after a paired dedicated bot exists.
if [ ! -s data/telegram_bot_token ] || [ ! -s data/telegram_chat_id ]; then
  exit 0
fi
if [ -f data/telegram.log ] && [ "$(wc -c < data/telegram.log)" -gt 1000000 ]; then
  tail -c 200000 data/telegram.log > data/telegram.log.tmp
  mv data/telegram.log.tmp data/telegram.log
fi
/usr/bin/flock -n data/dispatch.lock /usr/bin/python3 telegram_upgrade.py --delivery-only >> data/telegram.log 2>&1
