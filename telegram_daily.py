#!/usr/bin/env python3
"""Daily, DST-safe private Telegram housing report; never repeats a local date."""
import argparse
import datetime as dt
import sqlite3
from zoneinfo import ZoneInfo
from pathlib import Path

from setup_telegram import TOKEN_FILE,CHAT_FILE,api
import housing_state as state
import housing_reporting as reporting
import telegram_controls as controls

DB=Path(__file__).resolve().parent/"data"/"telegram_delivery.sqlite3"

def run(dry_run=False,force=False,now=None,api_func=api,db_path=DB):
    now=now or dt.datetime.now(ZoneInfo("Europe/Vilnius"))
    if not force and now.hour!=8:
        return "outside_local_morning_window"
    with sqlite3.connect(db_path,timeout=8) as conn:
        controls.init_db(conn)
        state.ensure(conn)
        content=reporting.daily_text(conn,now.date())
        key="daily_report_"+now.strftime("%Y-%m-%d")
        sent=conn.execute("SELECT value FROM housing_meta WHERE name=?",(key,)).fetchone()
        if sent and not force:return "already_sent"
        if dry_run:
            print(content)
            return "dry_run"
        if not TOKEN_FILE.is_file() or not CHAT_FILE.is_file():
            raise RuntimeError("Telegram pairing is missing")
        token=TOKEN_FILE.read_text().strip()
        chat_id=CHAT_FILE.read_text().strip()
        if not chat_id.lstrip("-").isdigit():
            raise RuntimeError("Invalid private chat ID")
        # Persist before send to prevent a lost network ACK from duplicating
        # the complete daily report.
        with conn:
            conn.execute("INSERT OR REPLACE INTO housing_meta(name,value) VALUES (?,?)",(key,"sending"))
        answer=api_func(token,"sendMessage",{
            "chat_id":chat_id,"text":content,"parse_mode":"HTML",
            "disable_web_page_preview":"true"})
        if not isinstance(answer,dict) or not isinstance(answer.get("message_id"),int):
            raise RuntimeError("Telegram delivery not confirmed; no automatic retry")
        with conn:
            conn.execute("UPDATE housing_meta SET value=? WHERE name=?",
                         ("sent:"+str(answer["message_id"]),key))
        return "sent"

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--dry-run",action="store_true")
    p.add_argument("--force",action="store_true")
    a=p.parse_args()
    print(run(a.dry_run,a.force))
