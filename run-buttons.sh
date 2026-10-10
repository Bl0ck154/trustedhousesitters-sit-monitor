#!/usr/bin/env bash
set -euo pipefail
cd /srv/apps/trustedhousesitters-monitor
if [ ! -s data/telegram_bot_token ] || [ ! -s data/telegram_chat_id ]; then exit 0; fi
if [ -f data/buttons.log ] && [ "$(wc -c < data/buttons.log)" -gt 300000 ]; then
  tail -c 50000 data/buttons.log > data/buttons.log.tmp
  mv data/buttons.log.tmp data/buttons.log
fi
/usr/bin/flock -n data/buttons.lock /usr/bin/timeout 56s /usr/bin/python3 telegram_callbacks.py >> data/buttons.log 2>&1
