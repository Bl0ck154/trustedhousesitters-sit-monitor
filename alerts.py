#!/usr/bin/env python3
"""Read and acknowledge only server-confirmed sitter alerts."""
import argparse
import datetime
import json
import pathlib
import sqlite3
ROOT = pathlib.Path(__file__).resolve().parent / "data"

def queued():
    fp = ROOT / "pending-notifications.jsonl"
    rows = {}
    if fp.exists():
        for line in fp.read_text().splitlines():
            try:
                item = json.loads(line)
                if item.get("assignment_id") and item.get("verified_by_detail") and item.get("status") == "open" and item.get("eligible_alert"):
                    rows[item["assignment_id"]] = item
            except (json.JSONDecodeError, KeyError):
                continue
    return rows

def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["peek","ack"])
    p.add_argument("ids", nargs="*")
    args = p.parse_args()
    rows = queued()
    conn = sqlite3.connect(str(ROOT / "alert_delivery.sqlite3"))
    conn.execute("CREATE TABLE IF NOT EXISTS delivered (assignment_id TEXT PRIMARY KEY, delivered_at TEXT NOT NULL)")
    try:
        if args.command == "peek":
            done = {a[0] for a in conn.execute("SELECT assignment_id FROM delivered")}
            pending = [r for k,r in rows.items() if k not in done]
            print(json.dumps({"pending":pending[:10],"pending_count":len(pending)},ensure_ascii=False))
        else:
            chosen = [k for k in args.ids if k in rows]
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            for key in chosen:
                conn.execute("INSERT OR IGNORE INTO delivered VALUES (?,?)",(key,now))
            conn.commit()
            print(json.dumps({"acknowledged":chosen},ensure_ascii=False))
    finally:
        conn.close()

if __name__ == "__main__":
    main()
