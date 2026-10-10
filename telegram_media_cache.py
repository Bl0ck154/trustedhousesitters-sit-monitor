"""Persistent Telegram file_id reuse for externally hosted THS listing photos.

When a URL is first uploaded by Telegram, save the bot-scoped file_id from
the returned Message.photo. Later edits can use file_id without re-fetching
that URL from Cloudinary. No photo bytes are persisted.
"""
import os
import pathlib
import sqlite3

DB=pathlib.Path(__file__).resolve().parent/"data"/"telegram_media_cache.sqlite3"

def _connect():
    # Avoid mutating process-global umask in the multi-thread callback worker.
    DB.touch(mode=0o600,exist_ok=True)
    conn=sqlite3.connect(DB,timeout=2)
    conn.execute("""CREATE TABLE IF NOT EXISTS photos (
        source_url TEXT PRIMARY KEY,
        telegram_file_id TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    return conn

def resolve(url):
    if not url:return url
    try:
        with _connect() as conn:
            row=conn.execute("SELECT telegram_file_id FROM photos WHERE source_url=?",(url,)).fetchone()
        if row:return row[0]
    except sqlite3.Error:
        pass
    return url

def remember(url, message):
    if not url or not isinstance(message,dict):return False
    photos=message.get("photo") or []
    if not isinstance(photos,list) or not photos:return False
    last=photos[-1]
    fid=last.get("file_id") if isinstance(last,dict) else None
    if not isinstance(fid,str) or not fid:return False
    try:
        with _connect() as conn:
            conn.execute("""INSERT INTO photos(source_url,telegram_file_id) VALUES (?,?)
               ON CONFLICT(source_url) DO UPDATE SET
               telegram_file_id=excluded.telegram_file_id,updated_at=CURRENT_TIMESTAMP""",(url,fid))
        return True
    except sqlite3.Error:
        return False
