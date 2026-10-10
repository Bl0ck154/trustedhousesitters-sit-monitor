"""Fast callbacks for one-photo Telegram cards. No new messages per tap."""
import json
import sqlite3
import time
import telegram_card as card
import telegram_media_cache as photo_cache
import telegram_photo_api as photo_upload
from setup_telegram import api

# The service keeps the last successfully rendered view per Telegram message.
_VISIBLE={}

def _send_long_action(action,aid,mid,token,chat_id,api_func,db_path):
    """Deliver requested material as new messages, never edit the original card."""
    import telegram_controls as controls
    import telegram_action_send as sender
    import time
    cooldown=30 if action=="d" else 120
    with sqlite3.connect(db_path or controls.DB,timeout=6) as conn:
        controls.init_db(conn)
        canonical=conn.execute("SELECT control_message_id FROM controls WHERE assignment_id=?",(aid,)).fetchone()
        alias=conn.execute("SELECT 1 FROM control_instances WHERE assignment_id=? AND message_id=?",(aid,mid)).fetchone()
        if not ((canonical and canonical[0]==mid) or alias):
            return "stale_card"
        item=controls.load_snapshot(aid,conn)
        if not item:return "missing_details"
        now=time.time()
        row=conn.execute("SELECT sent_at FROM button_sends WHERE assignment_id=? AND message_id=? AND action=?",
                         (aid,mid,action)).fetchone()
        if row and now-row[0]<cooldown:return "already_requested"
        conn.execute("""INSERT INTO button_sends (assignment_id,message_id,action,sent_at,state)
                        VALUES (?,?,?,?,?)
                        ON CONFLICT(assignment_id,message_id,action) DO UPDATE SET
                        sent_at=excluded.sent_at,state=excluded.state,sent_messages=0""",
                     (aid,mid,action,now,"sending"))
        conn.commit()
    try:
        if action=="d":
            message_ids=sender.send_description(token,chat_id,item,reply_to=mid,api_func=api_func)
        else:
            message_ids=sender.send_gallery(token,chat_id,item,reply_to=mid,api_func=api_func)
    except Exception:
        # Ambiguous timeouts must not produce repeat floods. A user can retry
        # after cooldown; no auto-retry is performed.
        with sqlite3.connect(db_path or controls.DB,timeout=6) as conn:
            conn.execute("UPDATE button_sends SET state='uncertain' WHERE assignment_id=? AND message_id=? AND action=?",(aid,mid,action))
            conn.commit()
        raise
    with sqlite3.connect(db_path or controls.DB,timeout=6) as conn:
        conn.execute("UPDATE button_sends SET state='sent', sent_messages=? WHERE assignment_id=? AND message_id=? AND action=?",
                     (len(message_ids),aid,mid,action))
        conn.commit()
    return ("description_sent" if action=="d" else "gallery_sent")+"_"+str(len(message_ids))

def handle(update,token,chat_id,api_func=api,db_path=None):
    # Lazy import avoids telegram_controls -> telegram_card_controller cycle.
    import telegram_controls as controls
    event=update.get("callback_query") or {}
    cid=event.get("id")
    if not cid:return "no_callback"
    raw=event.get("data")
    parsed=card.parse(raw)
    msg=event.get("message") or {}
    chat=msg.get("chat") or {}
    actor=event.get("from") or {}
    if not parsed or not (
        chat.get("type")=="private" and str(chat.get("id"))==str(chat_id)
        and str(actor.get("id"))==str(chat_id)
    ):
        controls.answer_callback(api_func,token,cid,text="Немає доступу")
        return "unauthorized_or_invalid"
    action,aid,pageno,photo=parsed
    # ACK before work, so the Telegram spinner disappears almost instantly.
    controls.answer_callback(api_func,token,cid)
    try:mid=int(msg.get("message_id") or 0)
    except (TypeError,ValueError):return "invalid"
    if action in ("d","g"):
        return _send_long_action(action,aid,mid,token,chat_id,api_func,db_path)
    with sqlite3.connect(db_path or controls.DB,timeout=6) as conn:
        controls.init_db(conn)
        row=conn.execute("SELECT control_message_id FROM controls WHERE assignment_id=?",(aid,)).fetchone()
        alias=conn.execute("SELECT 1 FROM control_instances WHERE assignment_id=? AND message_id=?",(aid,mid)).fetchone()
        if not (row and row[0]==mid) and not alias:return "stale"
        item=controls.load_snapshot(aid,conn)
        if not item:return "missing_details"
        applied=controls.is_applied(aid,conn)
        if action=="n":return "noop"
        if action=="a":
            applied=controls.toggle_application(conn,aid)
            mode="short" if pageno is None else "full"
            cached=controls.card_pages_for(aid,item) if mode=="full" else None
            keyboard=card.controls(item,mode=mode,page=pageno or 0,photo=photo,applied=applied,total=len(cached) if cached else None)
            api_func(token,"editMessageReplyMarkup",{"chat_id":str(chat_id),"message_id":str(mid),
                                                     "reply_markup":keyboard})
            _VISIBLE.pop((str(chat_id),mid),None)
            return "application_marked" if applied else "application_unmarked"
        if action=="c":
            mode="short";pageno=0
        elif action=="p":
            mode="full"
        elif action=="f":
            mode="short" if pageno is None else "full"
        else:return "invalid"
        idx=photo
        pages=controls.card_pages_for(aid,item) if mode=="full" else None
        if pages is not None:pageno=min(max(pageno or 0,0),len(pages)-1)
        else:pageno=0
        view=(mode,pageno,idx,applied)
        if _VISIBLE.get((str(chat_id),mid))==view:
            return "already_visible"
        text=card.caption(item,mode=mode,page=pageno,pages=pages)
        keyboard=card.controls(item,mode=mode,page=pageno,photo=idx,applied=applied,total=len(pages) if pages else None)
        common={"chat_id":str(chat_id),"message_id":str(mid),"reply_markup":keyboard}
        try:
            if action=="f" and card.cover(item,idx):
                source=card.cover(item,idx)
                media={"type":"photo","media":photo_cache.resolve(source),"caption":text,"parse_mode":"HTML"}
                try:
                    fields={**common,"media":json.dumps(media,ensure_ascii=False)}
                    if media["media"]==source and getattr(api_func,"_fast_photo_upload",False):
                        try:
                            response=photo_upload.edit_media(token,source,fields)
                        except ValueError:
                            response=api_func(token,"editMessageMedia",fields)
                    else:
                        response=api_func(token,"editMessageMedia",fields)
                except RuntimeError as media_error:
                    if media["media"]==source or "Telegram HTTP 400" not in str(media_error):
                        raise
                    # Old Telegram file_id can become unusable: fall back to the source URL once.
                    media["media"]=source
                    fields={**common,"media":json.dumps(media,ensure_ascii=False)}
                    if getattr(api_func,"_fast_photo_upload",False):
                        try:
                            response=photo_upload.edit_media(token,source,fields)
                        except ValueError:
                            response=api_func(token,"editMessageMedia",fields)
                    else:
                        response=api_func(token,"editMessageMedia",fields)
                photo_cache.remember(source,response)
                _VISIBLE[(str(chat_id),mid)]=view
                return "photo_changed"
            api_func(token,"editMessageCaption",{**common,"caption":text,"parse_mode":"HTML"})
            _VISIBLE[(str(chat_id),mid)]=view
        except RuntimeError as exc:
            if "Telegram HTTP 400" in str(exc):
                return "unchanged_or_edit_rejected"
            raise
    return "collapsed" if mode=="short" else "expanded"
