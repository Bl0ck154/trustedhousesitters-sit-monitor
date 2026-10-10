#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
mkdir -p data
if [ -f data/config.env ]; then
  set -a
  source data/config.env
  set +a
fi
/usr/bin/flock -n data/daily.lock /usr/bin/python3 telegram_daily.py >> data/daily.log 2>&1
