#!/usr/bin/env python3
"""Self-contained Telegram sender for newly OPEN TrustedHousesitters sits.

No ChatGPT process or integration is used. Bot token / chat id are private files.
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import pathlib
import sqlite3
import sys
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

import monitor
from setup_telegram import api, TOKEN_FILE, CHAT_FILE

ROOT = pathlib.Path(__file__).resolve().parent / "data"
QUEUE = ROOT / "pending-notifications.jsonl"
DB = ROOT / "telegram_delivery.sqlite3"

def read_events():
    if not QUEUE.exists():
        return []
    rows = []
    for line in QUEUE.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
            if not (item.get("assignment_id") and item.get("discovered_at")
                    and item.get("eligible_alert") and item.get("verified_by_detail")
                    and item.get("status") == "open"):
                continue
            url = urlparse(str(item.get("url") or ""))
            if url.scheme != "https" or url.netloc != "www.trustedhousesitters.com":
                continue
            if not (url.path.startswith("/house-and-pet-sitting-assignments/")
                    and "/l/" in url.path):
                continue
            item["event_key"] = hashlib.sha256(
                (str(item["assignment_id"]) + "|" + item["discovered_at"]).encode()
            ).hexdigest()
            rows.append(item)
        except (ValueError, TypeError):
            continue
    return rows

def message(item):
    def esc(k):
        return html.escape(str(item.get(k) or "—"))
    checktime = dt.datetime.now(ZoneInfo("Europe/Vilnius")).strftime("%d.%m.%Y %H:%M")
    cats = int(item.get("cats") or 0)
    num_apps = item.get("application_count")
    parts = [
        "🏠 <b>Новий доступний house sit</b>",
        f"📍 <b>{esc('city')}, {esc('country')}</b>",
        f"📅 {esc('start')} — {esc('end')} ({int(item['nights'])} ночей)",
        f"🐈 Коти: {cats}",
        f"🚍 Громадський транспорт: {'так' if item.get('transport_accessible') else 'не підтверджено'}",
        f"📶 Інтернет: {esc('internet')}",
        f"📝 Заявок: {num_apps if isinstance(num_apps,int) else 'невідомо'}",
        f"✅ Відкрито за даними сайту на {checktime} (можливість Apply у твоєму акаунті не гарантована)",
        '<a href="' + html.escape(item["url"], quote=True) + '">Відкрити конкретне оголошення</a>'
    ]
    return "\n".join(parts)

def update(conn, key, state, message_id=None):
    conn.execute("INSERT INTO delivery (event_key,state,updated_at,message_id) VALUES (?,?,?,?) "
                 "ON CONFLICT(event_key) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at,"
                 "message_id=excluded.message_id",
                 (key, state, dt.datetime.now(dt.timezone.utc).isoformat(), message_id))
    conn.commit()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=15)
    args = p.parse_args()
    events = read_events()
    if args.dry_run:
        print(json.dumps({"queue_entries":len(events),"unique_events":len({e['event_key'] for e in events}),
                          "last_three": [{"id":x["assignment_id"],"city":x.get("city")}
                                         for x in events[-3:]]},ensure_ascii=False))
        return 0
    if not (TOKEN_FILE.is_file() and CHAT_FILE.is_file()):
        print("Telegram not paired; run setup_telegram.py interactively.", file=sys.stderr)
        return 0
    token = TOKEN_FILE.read_text().strip()
    chat_id = CHAT_FILE.read_text().strip()
    if not token or not chat_id.lstrip("-").isdigit():
        print("Telegram credentials incomplete; nothing sent.",file=sys.stderr)
        return 2
    conn = sqlite3.connect(DB)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS delivery (event_key TEXT PRIMARY KEY, state TEXT NOT NULL,"
                     "updated_at TEXT NOT NULL, message_id INTEGER)")
        sent, stale, uncertain = 0, 0, 0
        for item in events:
            row = conn.execute("SELECT state FROM delivery WHERE event_key=?", (item["event_key"],)).fetchone()
            # A pre-recorded sending attempt is not resent automatically: avoid duplicates on crash/timeout.
            if row and row[0] in ("sent", "stale", "sending", "uncertain"):
                continue
            if sent + stale + uncertain >= args.limit:
                break
            try:
                actual = monitor.validate_detail(item)
            except Exception:
                # Unverifiable state: do not send, retry on next invocation.
                print("Status verification failed for assignment",item["assignment_id"],file=sys.stderr)
                continue
            if not (actual["status"] == "open" and actual.get("verified_by_detail")
                    and actual.get("eligible_alert")
                    and actual["assignment_id"] == item["assignment_id"]):
                update(conn,item["event_key"],"stale")
                stale += 1
                continue
            update(conn,item["event_key"],"sending")
            try:
                response = api(token, "sendMessage", {
                    "chat_id": chat_id, "text": message(actual),
                    "parse_mode": "HTML", "disable_web_page_preview": "true"
                })
            except Exception as err:
                # Telegram may have accepted a request before a network timeout; no blind duplicate retries.
                update(conn,item["event_key"],"uncertain")
                uncertain += 1
                print("Telegram delivery uncertain for",item["assignment_id"],
                      "(" + type(err).__name__ + ")",file=sys.stderr)
                continue
            if not isinstance(response,dict) or not isinstance(response.get("message_id"),int):
                update(conn,item["event_key"],"uncertain")
                uncertain += 1
                continue
            update(conn,item["event_key"],"sent",response["message_id"])
            sent += 1
        print(json.dumps({"queued_events":len(events),"sent":sent,"stale":stale,
                          "uncertain":uncertain},ensure_ascii=False))
        return 0 if not uncertain else 2
    finally:
        conn.close()

if __name__ == "__main__":
    raise SystemExit(main())
