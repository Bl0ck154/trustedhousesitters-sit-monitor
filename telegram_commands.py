"""Private Telegram commands for house sit applications and monitoring."""
import html
import sqlite3
from pathlib import Path
from setup_telegram import api
import telegram_controls as controls

DB=Path(__file__).resolve().parent/"data"/"telegram_delivery.sqlite3"

def app_list(conn):
    controls.init_db(conn)
    rows=conn.execute("""SELECT a.assignment_id,a.applied_at,COALESCE(w.payload,''),COALESCE(w.status,'unknown')
                          FROM applications a LEFT JOIN watch w USING(assignment_id)
                          ORDER BY a.applied_at DESC LIMIT 30""").fetchall()
    if not rows:return "📋 <b>Мої заявки</b>\nПоки немає позначених заявок. Натисни «📨 Я подав заявку» під потрібним оголошенням."
    import json
    parts=["📋 <b>Мої заявки</b> — позначені вручну, не синхронізовані з TrustedHousesitters"]
    for aid,applied_at,payload,status in rows:
        item=json.loads(payload) if payload else {}
        name=html.escape(str(item.get("title") or aid))
        link=str(item.get("url") or "")
        if link.startswith("https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/"):
            name=f'<a href="{html.escape(link,quote=True)}">{name}</a>'
        parts.append("• "+name+"\n  "+html.escape(str(item.get("city") or ""))+" · "+html.escape(str(item.get("start") or ""))+" → "+html.escape(str(item.get("end") or ""))+"\n  Стан оголошення: "+html.escape(status))
    return "\n\n".join(parts)[:3900]

def handle_message(update,token,chat_id,api_func=api,db_path=DB):
    msg=update.get("message") or {}
    chat=msg.get("chat") or {}
    sender=msg.get("from") or {}
    if chat.get("type")!="private" or str(chat.get("id"))!=str(chat_id) or str(sender.get("id"))!=str(chat_id):
        return "ignored"
    cmd=str(msg.get("text") or "").split(maxsplit=1)[0].split("@")[0].lower()
    if cmd not in ("/applications","/zayavki","/help","/start"):
        return "ignored"
    if cmd in ("/applications","/zayavki"):
        with sqlite3.connect(db_path,timeout=8) as cx:
            body=app_list(cx)
    else:
        body=("🏠 <b>TrustedHousesitters Monitor</b>\n"
              "📖 Опис — кнопка під оголошенням.\n"
              "📨 Я подав заявку — зберегти заявку в локальному журналі.\n"
              "📍 Локація — орієнтир міста на мапі.\n"
              "/applications — список позначених заявок.")
    api_func(token,"sendMessage",{"chat_id":str(chat_id),"text":body,"parse_mode":"HTML",
                                  "disable_web_page_preview":"true",
                                  "reply_to_message_id":str(msg.get("message_id") or ""),
                                  "allow_sending_without_reply":"true"})
    return "command"
