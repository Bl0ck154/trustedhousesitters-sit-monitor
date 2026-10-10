#!/usr/bin/env python3
"""One-time, interactive pairing of a dedicated Telegram bot for this monitor.

Run inside an interactive SSH terminal; never place the token in shell arguments.
"""
import getpass
import json
import os
import pathlib
import secrets
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

DATA = pathlib.Path(__file__).resolve().parent / "data"
TOKEN_FILE = DATA / "telegram_bot_token"
CHAT_FILE = DATA / "telegram_chat_id"

def private_write(path, data):
    os.umask(0o077)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data.strip() + "\n")
    except Exception:
        os.close(fd)
        raise

def api(token, method, fields=None):
    raw = urllib.parse.urlencode(fields or {}).encode()
    req = urllib.request.Request("https://api.telegram.org/bot" + token + "/" + method, data=raw, method="POST")
    try:
        # Never leave incoming Telegram buttons stuck on a 20-second long-poll.
        # The client timeout is slightly longer than getUpdates server wait.
        poll_timeout=(min(12,max(6,int((fields or {}).get("timeout",5))+3))
                      if method=="getUpdates" else
                      5 if method in ("answerCallbackQuery","editMessageReplyMarkup")
                      else 20)
        with urllib.request.urlopen(req, timeout=poll_timeout) as stream:
            data = json.load(stream)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Telegram HTTP {error.code} on {method}") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError(f"Telegram unreachable on {method}") from None
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API rejected {method} (error {data.get('error_code','unknown')})")
    return data.get("result")

def main():
    os.umask(0o077)
    DATA.mkdir(mode=0o700, exist_ok=True)
    if not sys.stdin.isatty():
        print("Run this setup interactively from your server terminal.")
        return 2
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
        print("Using existing private Telegram credential file.")
    else:
        token = getpass.getpass("Enter Telegram bot token (hidden): ").strip()
        if not token or ":" not in token:
            print("Invalid token shape.")
            return 2
    try:
        me = api(token, "getMe")
        webhook = api(token, "getWebhookInfo")
    except RuntimeError as e:
        print(e)
        return 2
    if webhook.get("url"):
        # Owner explicitly authorized disconnecting this bot from its old webhook.
        # Keep pending updates so unrelated messages are not silently discarded.
        try:
            api(token, "deleteWebhook", {"drop_pending_updates": "false"})
        except RuntimeError as e:
            print("Could not disconnect old webhook:", e)
            return 2
        print("Old webhook disconnected; continuing Telegram pairing.")
    if not TOKEN_FILE.exists():
        private_write(TOKEN_FILE, token)
    print("Validated bot:", "@" + str(me.get("username", "unknown")))
    code = "ths_" + secrets.token_urlsafe(8)
    print("Open your bot in Telegram and send EXACTLY:")
    print("/start " + code)
    print("Watching for that pairing message (up to 2 minutes)...")
    deadline = time.monotonic() + 120
    offset = None
    while time.monotonic() < deadline:
        fields = {"timeout": 8, "limit": 100}
        if offset is not None:
            fields["offset"] = offset
        try:
            updates = api(token, "getUpdates", fields)
        except RuntimeError as e:
            print("Pairing read error:", e)
            return 2
        for event in updates:
            offset = max(offset or 0, int(event["update_id"]) + 1)
            message = event.get("message") or {}
            chat = message.get("chat") or {}
            actor = message.get("from") or {}
            if chat.get("type") == "private" and not actor.get("is_bot") and (message.get("text") or "").strip() == "/start " + code:
                chat_id = chat.get("id")
                if not isinstance(chat_id, int):
                    continue
                private_write(CHAT_FILE, str(chat_id))
                try:
                    api(token, "sendMessage", {"chat_id": chat_id,
                        "text": "✅ TrustedHousesitters: Telegram підключено. Нові перевірені варіанти надходитимуть сюди."})
                except RuntimeError as e:
                    print("Paired, but test message failed:", e)
                    return 2
                print("Paired successfully. Test Telegram message delivered.")
                return 0
    print("No matching /start code received. Token saved; run setup again to pair.")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
