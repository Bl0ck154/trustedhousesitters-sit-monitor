# TrustedHousesitters Sit Monitor

Unofficial self-hosted personal-use monitor for publicly accessible house-sitting listings. It is not affiliated with, endorsed by or operated by TrustedHousesitters.

## What it does

- Finds house sits within a rolling date window and filters by country, pet type, transport and Wi-Fi.
- Reads embedded JSON in public HTML via HTTPS, without a browser by default. Full scan every 30 minutes plus a quick new-listing lane every 5 minutes.
- Uses SQLite history and a 30-minute detail cache for unchanged open listings.
- Revalidates listings before alerting, independently tracks status changes and deduplicates announcements.
- Only opens detail pages for **Open** sits that already pass pet species, public transport, and Wi-Fi requirements from the search-result metadata; ineligible sits are tracked only by summary state.
- Sends Telegram photo cards, detailed formatted descriptions, native photo albums, and approximate-location links.
- Allows manually marking applications. These markers are not synchronized with a TrustedHousesitters account.

## Running

Requires Python 3.10+, a personal Telegram bot, and network access to the site's public pages. Clone the repository and configure the runtime in its private data directory.

Example environment variables:

    THS_EARLIEST_START=2026-11-01
    THS_FETCH_MODE=http

Create data/config.env with these variables; this file is never committed. To pair Telegram, run setup_telegram.py with Python 3 and follow its instructions. Never share or commit the bot token.

Use run-hourly.sh for full scans, run-quick.sh for incremental new-listing scans, run-telegram.sh for delivery, and telegram_fast_callbacks.py as a persistent restricted service for Telegram button presses. A 30-minute full scan, 5-minute quick scan and 5-minute Telegram delivery interval are suitable moderate configurations. Adapt the host-specific cron/systemd paths to your machine. If you want to diagnose the browser fallback, install Obscura Lite and set THS_FETCH_MODE=browser, adjusting the local path in monitor.py.

Run tests with:

    python3 -m unittest discover -p 'test_*.py'

## Privacy and limits

Collected listings, owner descriptions, photos' source URLs, private application flags, Telegram IDs, bot credentials, and notification history are stored under data/ locally and ignored by Git. Do not publish any collected data, logs, browser sessions or secrets.

The HTML structure and access policies can change. Respect the platform's terms, robots rules, rate limits and access restrictions; do not bypass authentication or anti-abuse controls. A non-200 HTTP response is treated as a failed fetch, not something to evade. This is not a supported or official API, and public search cannot confirm a personal Apply button or personal application status.

No license is included; public visibility is not a grant of reuse rights.
