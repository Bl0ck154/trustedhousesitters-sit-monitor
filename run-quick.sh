#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
mkdir -p data
if [ -f data/config.env ]; then
  set -a
  source data/config.env
  set +a
fi
if [ -f data/quick-scan.log ] && [ "$(wc -c < data/quick-scan.log)" -gt 800000 ]; then
  tail -c 150000 data/quick-scan.log > data/quick-scan.log.tmp
  mv data/quick-scan.log.tmp data/quick-scan.log
fi
/usr/bin/flock -n data/scan.lock /usr/bin/python3 monitor.py --quick --commit >> data/quick-scan.log 2>&1
