# TrustedHousesitters Cloudflare Workers port (experimental)

The existing Python runtime remains unchanged. This port is **not** a production cutover and is not guaranteed parity until verified with migrated data and independent tests. No credentials or private data belong in Git.

## Staging defaults (fail-closed)

- \`LIVE_MODE=false\`, \`SCAN_ENABLED=false\`, \`WEBHOOK_ENABLED=false\`.
- Staging has **no Cron Triggers**, no bot token, no Telegram chat ID, and cannot call TrustedHousesitters or send Telegram messages.
- \`GET /health\` is a public readiness response. \`POST /telegram/webhook\` returns 409 in staging.
- Do **not** register a webhook for the production Telegram bot while old polling is running.
- Do **not** activate staging schedules just to test. Use a test bot for genuine Telegram end-to-end testing.
- No R2, KV, browser or paid Cloudflare products are used.

## Architecture

- ES module Worker with D1 persistence and a minute-based scheduler.
- Quick search every 2 minutes (3 pages sorted newest), rolling full search across the next 30-minute cycle (up to 90 pages per Open/Reviewing stream, seven pages per minute). Full-search *completion is not currently guaranteed on a Free account under large result volumes*.
- Status lifecycle check every 2 minutes. Reviewing/hot items at 2-minute frequency, other items at 4 minutes. Two observations separated by 65+ seconds (reopenings require an extra verification). Failed access is unknown, never a removal.
- Public HTML structured data via HTTPS; 429 -> 1h shared cooldown, 403/challenge -> 6h. **No bypass, proxy fallback or browser fallback**.
- D1 snapshots, applications, confirmed stays, ignored listings, status transitions, delivery state and deduplication.
- Telegram photo card, two native galleries on demand, full description, manual /plan /options /applications /report, manual stage changes and two-step confirmation.
- D1 leases prevent competing minute jobs. Delivery claimed as "sending" before calling Telegram; network-ambiguous sends remain "uncertain" and need manual reconciliation, not automatic retry.

## Important differences / incomplete parity

1. Original Python has richer formatting, legacy t2 cards and controls tables, photo upload optimization and queued retry of keyboard redraws. These are **not fully ported**; do not switch production until tested.
2. Cloudflare Free has 10ms CPU and 50 subrequests per invocation. Search HTML parsing and D1 writes per candidate can hit either limit. The port is NOT yet proven capable of delivering exhaustive 90-page full scans under these limits. No automatic omission of these constraints is acceptable.
3. Workers can reach only public unauthenticated pages. No private THS login, application status sync or bypass of access blocks exists. Source site's robots and ToS still apply.
4. Staging health passing does not prove search, Telegram albums, status transitions or full-scan parity.
5. Browser fallback and local proxy broker are deliberately absent (Workers has neither); their absence affects recovery from network failures, never permits bypass of HTTP 403/429.
6. The rolling full-scanner's detail budget and cache behavior must be load-tested against real data before cutover.
7. Old on-disk album, HTTP and Telegram media caches are not directly reusable; D1 stores relevant public URLs/snapshots only.
8. Date-based report runs in Europe/Vilnius at local 08:30 via minute cron, including DST changes, but **cron must be enabled only at cutover**.

## Local verification

\`\`\`sh
cd cloudflare
npm install
npm test
npx wrangler dev --env staging --local
\`\`\`

Schema bootstrapping after creating an *empty staging D1*:

\`\`\`sh
npx wrangler d1 create ths-sit-monitor-staging
# Set new ID in env.staging.d1_databases in wrangler.toml
npx wrangler d1 execute ths-sit-monitor-staging --env staging --remote --file schema.sql
npx wrangler deploy --env staging
curl https://<actual-workers-subdomain>/health
\`\`\`

No automatic GitHub Actions deployment or Workers Builds: avoid unplanned GitHub minutes and production changes.

## Read-only Netcup snapshot migration (no SSH from staging)

1. On Netcup **after access is restored**, stop all writes briefly or take a consistent SQLite backup using \`sqlite3.Connection.backup()\`; keep the original running until the final cutover; export can be delayed if the server remains unreachable.
2. Copy \`data/history.sqlite3\`, \`data/telegram_delivery.sqlite3\`, \`data/latest.json\` and \`data/listings/\` to a private temporary directory. **Do not commit those files or config.env, bot tokens, or chat IDs.**
3. On a secured machine: \`python3 cloudflare/export_sqlite.py --data <path-to-private-data> --output <private-migration.sql> --earliest-start YYYY-MM-DD\`.
4. Create an entirely separate D1 staging database, apply \`schema.sql\`, then import private migration SQL through a secured Wrangler session: \`npx wrangler d1 execute ths-sit-monitor-staging --remote --file <private-migration.sql>\`. Keep the import file outside the repo; delete it securely after validation.
5. Verify counts of applications, confirmed_stays, records, watch and ignored_assignments in both copies. Review the next gap in /plan using a separate test bot or offline logic tests. Imported pending notifications remain \`imported_hold\` (must never be sent on staging).
6. Cutover only after a dry run and explicit approval: stop Netcup polling and outgoing cron lanes, freeze and re-export any changes, import production D1, set secrets using Wrangler (do not store in Git), register production webhook once, turn on Workers cron \`* * * * *\`, enable \`LIVE_MODE, SCAN_ENABLED, WEBHOOK_ENABLED\` for the production Worker, and verify one owner-only /plan. Keep Netcup backup for rollback; webhook rollback first, then re-enable old poller.

### Production rollback

Disable Workers Cron and send gates first, restore Telegram to polling via \`deleteWebhook\` (do not drop pending updates), restore old Netcup bot, check owner-only status, and reconcile any messages marked \`uncertain\` before resending anything. D1 remains a backup; do not delete the SQLite snapshot.

## Emergency Netcup-free start (2026-10-17)

Second EU D1 database and independent production-target Worker 'ths-sit-monitor-live' have been created.

Current flags: SCAN_ENABLED=true, SCAN_PROFILE=quick, LIVE_MODE=false and WEBHOOK_ENABLED=false. One search-results page is scheduled every 2 minutes; the full search is NOT running (Free-tier CPU needs verification first). Initial earliest start is 2026-11-14; past private confirmations and applications are not yet migrated.

### Secure Telegram activation

1. Open https://dash.cloudflare.com > Bl0ck account > Workers & Pages > ths-sit-monitor-live > Settings > Variables and Secrets.
2. In @BotFather regenerate the existing TrustedHousesitters bot's token. This revokes the Netcup token so an unexpectedly recovered server cannot send duplicate messages.
3. Save the replacement value as a SECRET named TELEGRAM_BOT_TOKEN. Do not commit or paste the token publicly.
4. Save the owner's numeric private Telegram user ID as TELEGRAM_CHAT_ID. Use @userinfobot to retrieve the personal user ID; not the bot's username/ID.
5. Verify both bindings, then explicitly set LIVE_MODE=true and WEBHOOK_ENABLED=true while retaining SCAN_ENABLED=true.
6. The next cron run calls Telegram setWebhook automatically at PUBLIC_WORKER_URL + /telegram/webhook, with drop_pending_updates=false, max_connections=1 and an HMAC-like deterministic token-derived webhook secret header (SHA-256; original bot token is never placed in URL).
7. Use /start and /plan with the existing bot and check Workers logs, D1 settings and getWebhookInfo. Full scans, historical applications and legacy Telegram cards still need migration/testing before treating functionality as equivalent.

### Explicit limitations
- Quick-only mode observes ONLY first sorted page; listings on pages 2-90 can be missed.
- Existing SQLite manual statuses, old card identifiers and ignores are absent until Netcup history is imported.
- Staging remains separate and disabled. Cron propagation takes up to 15 minutes.
- Do not add API secrets to source, logs, tickets, or GitHub.

## Alternative listing feed: Sittify (2026-10-17)

**Never claim the original THS live scraper works on Cloudflare.** THS responds to the Worker with HTTP 202 and a JavaScript robot-verification page. SCAN_ENABLED remains false.

Sittify (https://sittify.com/ ; Android app https://play.google.com/store/apps/details?id=com.sittify.app) currently advertises THS sit aggregation, personalized filters and prompt email/push alerts. It is an independent third party and its service status and alert speed are not guaranteed. The fastest currently usable option is installing the mobile app and configuring its filters directly. No public Sittify API or outgoing webhook contract has been confirmed, so do not attempt unsupported scraping.

Optional email-to-Telegram adapter has been implemented, but NOT activated. It handles Cloudflare Email Routing's 'email' event, checks Sittify sender domain, deduplicates Message-ID-derived hashes in inbound_alerts, and sends the subject plus allowlisted HTTPS sit links to the same Telegram owner. It does not poll either platform, does not import old data, and does not reconstruct full THS cards. It ignores other sender domains.

Activation prerequisites:
1. Register for Sittify, create THS-specific alert filters and enable email alerts.
2. Choose an email delivery path to the Worker. A dedicated address on an existing Cloudflare-managed domain can route incoming mail to the Worker via Cloudflare Email Routing; alternatively, manually set up a Gmail forward from the account receiving Sittify emails. Check Cloudflare DNS MX conflicts before enabling routing, and verify any forwarding address manually. Neither Cloudflare Email Routing nor Gmail forwarding rules have been configured automatically.
3. Enable EMAIL_ALERTS_ENABLED=true in live Worker settings only after the email route has been configured.
4. Send one legitimate Sittify test alert and verify bot delivery and dedup. The adapter currently has no real production Sittify email sample, and compatibility with its exact MIME format remains unverified.
5. Leave SCAN_ENABLED=false. Do not confuse email-generated notifications with native every-two-minute site scans.

The adapter's passive D1 table can be installed in the live D1 without affecting the original Telegram webhook or the scanner.
