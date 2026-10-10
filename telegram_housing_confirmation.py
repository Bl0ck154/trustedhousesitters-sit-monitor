"""Two-step, owner-authorized confirmation of a personal house sit."""
import html
import re
import sqlite3
import time
import housing_state as state
import housing_reporting as reporting
import telegram_controls as controls
from setup_telegram import api

def prompt(aid,mid,token,chat_id,db_path,api_func=api):
    aid=str(aid)
    with sqlite3.connect(db_path,timeout=6) as conn:
        controls.init_db(conn)
        state.ensure(conn)
        canon=conn.execute("SELECT control_message_id FROM controls WHERE assignment_id=?",(aid,)).fetchone()
        alias=conn.execute("SELECT 1 FROM control_instances WHERE assignment_id=? AND message_id=?",(aid,mid)).fetchone()
        if not ((canon and canon[0]==mid) or alias):return "stale"
        item=state.snapshot(conn,aid,controls.DATA/"listings")
        if not item:return "not_found"
        current=state.stage(conn,aid)
        if current=="confirmed":return "already_confirmed"
        place=str(item.get("city") or "")+", "+str(item.get("country") or "")
        period=str(item.get("start") or "?")+"–"+str(item.get("end") or "?")
        body=("🏠 <b>Підтвердити власне проживання?</b>\n"
              +html.escape(place)+"\n📅 "+html.escape(period)
              +"\n\nЛише якщо власник справді обрав тебе. Це перенесе пошук на незайняті дати.")
        markup={"inline_keyboard":[[
            {"text":"✅ Так, мене підтвердили","callback_data":f"t4:y:{aid}"},
            {"text":"Скасувати","callback_data":f"t4:n:{aid}"}
        ]]}
        # Use a fresh message, never edit the image or original caption.
        answer=api_func(token,"sendMessage",{
            "chat_id":str(chat_id),"text":body,"parse_mode":"HTML",
            "reply_markup":__import__("json").dumps(markup,ensure_ascii=False),
            "reply_to_message_id":str(mid),"allow_sending_without_reply":"true"})
        if not isinstance(answer,dict) or not isinstance(answer.get("message_id"),int):
            raise RuntimeError("Confirmation prompt not acknowledged by Telegram")
        with conn:
            conn.execute("INSERT OR REPLACE INTO pending_confirmations(prompt_message_id,assignment_id,created_at) VALUES (?,?,?)",
                         (answer["message_id"],aid,time.time()))
    return "confirmation_requested"

def reply(update,token,chat_id,api_func=api,db_path=controls.DB):
    cb=update.get("callback_query") or {}
    match=re.fullmatch(r"t4:(y|n):([0-9]{1,15})",str(cb.get("data") or ""))
    chat=(cb.get("message") or {}).get("chat") or {}
    actor=cb.get("from") or {}
    if not match or chat.get("type")!="private" or str(chat.get("id"))!=str(chat_id) or str(actor.get("id"))!=str(chat_id):
        controls.answer_callback(api_func,token,cb.get("id"),text="Немає доступу")
        return "unauthorized"
    controls.answer_callback(api_func,token,cb.get("id"))
    flag,aid=match.groups()
    mid=(cb.get("message") or {}).get("message_id")
    with sqlite3.connect(db_path,timeout=6) as conn:
        state.ensure(conn)
        row=conn.execute("SELECT created_at FROM pending_confirmations WHERE prompt_message_id=? AND assignment_id=?",(mid,aid)).fetchone()
        if not row or time.time()-row[0]>600:
            return "expired"
        with conn:
            conn.execute("DELETE FROM pending_confirmations WHERE prompt_message_id=?",(mid,))
        if flag=="n":
            body="Скасовано. Дати не змінені."
        else:
            try:
                state.update(conn,aid,"confirmed",controls.DATA/"listings")
                body="✅ <b>Проживання підтверджено вручну.</b>\n\n"+reporting.plan_text(conn)
            except ValueError as ex:
                body="⚠️ "+html.escape(str(ex))
    api_func(token,"sendMessage",{"chat_id":str(chat_id),"text":body,"parse_mode":"HTML",
             "reply_to_message_id":str(mid),"allow_sending_without_reply":"true"})
    return "confirmed" if flag=="y" and body.startswith("✅") else "cancelled_or_rejected"
