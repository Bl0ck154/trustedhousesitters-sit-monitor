#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
mkdir -p data
if [ -f data/config.env ]; then
  set -a
  source data/config.env
  set +a
fi
# Rolling 30-day discovery window. Keep running for future sits until owner disables monitoring.
if [ -f data/scan.log ] && [ "$(wc -c < data/scan.log)" -gt 1500000 ]; then
  tail -c 250000 data/scan.log > data/scan.log.tmp
  mv data/scan.log.tmp data/scan.log
fi
/usr/bin/flock -n data/scan.lock /usr/bin/python3 monitor.py --commit >> data/scan.log 2>&1
