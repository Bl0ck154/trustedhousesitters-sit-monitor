#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
if [ -f data/config.env ]; then
  set -a
  source data/config.env
  set +a
fi
if [ ! -s data/telegram_bot_token ] || [ ! -s data/telegram_chat_id ]; then
  exit 0
fi
if [ -f data/status-watch.log ] && [ "$(wc -c < data/status-watch.log)" -gt 600000 ]; then
  tail -c 120000 data/status-watch.log > data/status-watch.log.tmp
  mv data/status-watch.log.tmp data/status-watch.log
fi
/usr/bin/flock -n data/status.lock /usr/bin/python3 telegram_upgrade.py --status-only >> data/status-watch.log 2>&1
