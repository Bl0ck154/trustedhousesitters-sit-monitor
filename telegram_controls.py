#!/usr/bin/env python3
"""TrustedHousesitters Telegram callbacks: cached pages, personal applications and map."""
from functools import lru_cache
import json
import pathlib
import re
import sqlite3
import time
from setup_telegram import api
import telegram_format as fmt

DATA=pathlib.Path(__file__).resolve().parent / "data"
DB=DATA/"telegram_delivery.sqlite3"

def init_db(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS controls (
        assignment_id TEXT PRIMARY KEY,album_message_id INTEGER NOT NULL,
        control_message_id INTEGER,updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS control_instances (
        assignment_id TEXT NOT NULL,message_id INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (assignment_id,message_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS button_sends (
        assignment_id TEXT NOT NULL, message_id INTEGER NOT NULL,
        action TEXT NOT NULL, sent_at REAL NOT NULL, state TEXT NOT NULL,
        sent_messages INTEGER DEFAULT 0,
        PRIMARY KEY(assignment_id,message_id,action))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS keyboard_updates(
        assignment_id TEXT NOT NULL,message_id INTEGER NOT NULL,
        requested_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(assignment_id,message_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS applications (
        assignment_id TEXT PRIMARY KEY,applied_at TEXT NOT NULL,
        owner_note TEXT)""")
    conn.commit()

def is_applied(aid,conn=None):
    if conn is not None:
        try:
            row=conn.execute("SELECT stage FROM applications WHERE assignment_id=?",(str(aid),)).fetchone()
            return bool(row and row[0] in ("applied","talking","confirmed"))
        except sqlite3.OperationalError:
            return conn.execute("SELECT 1 FROM applications WHERE assignment_id=?",
                                (str(aid),)).fetchone() is not None
    with sqlite3.connect(DB,timeout=5) as cx:
        init_db(cx)
        return is_applied(aid,cx)

def keyboard(item,page=None,total=1,applied=None):
    aid=str(item["assignment_id"])
    url=item.get("url") or ""
    if applied is None:
        try:applied=is_applied(aid)
        except sqlite3.Error:applied=False
    if page is None:
        rows=[[{"text":"📖 Розгорнути повний опис","callback_data":f"th:p:{aid}:0"}]]
    else:
        nav=[]
        if page>0:nav.append({"text":"◀️ Назад","callback_data":f"th:p:{aid}:{page-1}"})
        if page+1<total:nav.append({"text":"Далі ▶️","callback_data":f"th:p:{aid}:{page+1}"})
        rows=[nav] if nav else []
        rows.append([{"text":"🔼 Згорнути","callback_data":f"th:c:{aid}"}])
    mode="c" if page is None else str(page)
    rows.append([{"text":"✅ Заявку подано · змінити" if applied else "📨 Я подав заявку",
                  "callback_data":f"th:a:{aid}:{mode}"}])
    import housing_preferences as preferences
    hidden=aid in preferences.ignored_ids()
    rows.append([{"text":"↩️ Повернути в моніторинг" if hidden else "🚫 Не цікаво",
                 "callback_data":f"t3:i:{aid}:{0 if hidden else 1}"}])
    # Map and official listing are clickable inside the text; no duplicate URL buttons.
    return json.dumps({"inline_keyboard":rows},ensure_ascii=False)

def pending(conn,item,album_message_id,attached=False):
    init_db(conn)
    # Keep older card keyboards functional when a reopened sit gets a fresh card.
    previous=conn.execute("SELECT control_message_id FROM controls WHERE assignment_id=?",
                          (str(item["assignment_id"]),)).fetchone()
    if previous and previous[0] and previous[0]!=int(album_message_id):
        conn.execute("INSERT OR IGNORE INTO control_instances(assignment_id,message_id) VALUES (?,?)",
                     (str(item["assignment_id"]),int(previous[0])))
    conn.execute("""INSERT INTO controls (assignment_id,album_message_id,control_message_id)
                    VALUES (?,?,?)
                    ON CONFLICT(assignment_id) DO UPDATE SET
                    album_message_id=excluded.album_message_id,
                    control_message_id=excluded.control_message_id,updated_at=CURRENT_TIMESTAMP""",
                 (str(item["assignment_id"]),int(album_message_id),
                  int(album_message_id) if attached else None))
    conn.commit()

def control_send(api_func,token,chat_id,item,album_message_id):
    args={"chat_id":str(chat_id),"text":fmt.control_text(item),
          "parse_mode":"HTML","reply_markup":keyboard(item),
          "disable_web_page_preview":"true",
          "reply_to_message_id":str(album_message_id),
          "allow_sending_without_reply":"true"}
    answer=api_func(token,"sendMessage",args)
    if not isinstance(answer,dict) or not isinstance(answer.get("message_id"),int):
        raise RuntimeError("telegram did not return control message id")
    return answer["message_id"]

def flush_pending(conn,token,chat_id,max_count=5):
    init_db(conn)
    success=errors=0
    sql="""SELECT c.assignment_id,c.album_message_id,w.payload,w.status
             FROM controls c LEFT JOIN watch w ON w.assignment_id=c.assignment_id
             WHERE c.control_message_id IS NULL
             ORDER BY c.updated_at LIMIT ?"""
    for aid,mid,payload,status in conn.execute(sql,(max_count,)).fetchall():
        if not payload or status!="open":continue
        item=json.loads(payload)
        try:
            msg_id=control_send(api,token,chat_id,item,mid)
            conn.execute("UPDATE controls SET control_message_id=?,updated_at=CURRENT_TIMESTAMP WHERE assignment_id=?",(msg_id,aid))
            conn.commit()
            success+=1
        except Exception as ex:
            print("control_delivery_issue",aid,type(ex).__name__)
            errors+=1
    return success,errors

def queue_keyboard_update(conn,aid,message_id):
    init_db(conn)
    conn.execute("""INSERT INTO keyboard_updates(assignment_id,message_id)
                    VALUES (?,?)
                    ON CONFLICT(assignment_id,message_id) DO UPDATE SET
                    requested_at=CURRENT_TIMESTAMP""",(str(aid),int(message_id)))
    conn.commit()

def flush_keyboard_updates(conn,token,chat_id,api_func=api,limit=6,first_aid=None,first_mid=None):
    import telegram_card as card
    import housing_preferences as preferences
    init_db(conn)
    done=0
    for aid,mid in conn.execute("""SELECT assignment_id,message_id FROM keyboard_updates
                                   ORDER BY (assignment_id=? AND message_id=?) DESC,
                                            requested_at LIMIT ?""",
                                (str(first_aid or ""),int(first_mid or 0),limit)).fetchall():
        item=load_snapshot(aid,conn)
        if not item:
            conn.execute("DELETE FROM keyboard_updates WHERE assignment_id=? AND message_id=?",(aid,mid))
            conn.commit()
            continue
        kb=card.controls(item,applied=is_applied(aid,conn),
                         ignored=preferences.is_ignored(conn,aid))
        try:
            api_func(token,"editMessageReplyMarkup",{"chat_id":str(chat_id),
                       "message_id":str(mid),"reply_markup":kb})
        except RuntimeError as exc:
            # Telegram may be temporarily slow/unavailable; never undo the DB
            # state. Cron retries the desired keyboard state later.
            if "Telegram HTTP 400" in str(exc):
                conn.execute("DELETE FROM keyboard_updates WHERE assignment_id=? AND message_id=?",(aid,mid))
                conn.commit()
            else:
                print("keyboard_refresh_retry_pending",aid,type(exc).__name__)
            continue
        conn.execute("DELETE FROM keyboard_updates WHERE assignment_id=? AND message_id=?",(aid,mid))
        conn.commit()
        done+=1
    return done

def safe_assignment_id(data):
    value=str(data or "")
    m=re.fullmatch(r"th:p:([0-9]{1,15}):([0-9]{1,3})",value)
    if m:return (m.group(1),int(m.group(2)))
    m=re.fullmatch(r"th:c:([0-9]{1,15})",value)
    if m:return (m.group(1),None)
    return None

def parse_action(data):
    parsed=safe_assignment_id(data)
    if parsed:return ("page",*parsed,None)
    m=re.fullmatch(r"th:a:([0-9]{1,15}):(c|[0-9]{1,3})",str(data or ""))
    if m:return ("applied",m.group(1),None if m.group(2)=="c" else int(m.group(2)),None)
    m=re.fullmatch(r"th:m:([0-9]{1,15})",str(data or ""))
    if m:return ("map",m.group(1),None,None)
    return None

@lru_cache(maxsize=128)
def _cached_file(aid,mtime):
    return json.loads((DATA/"listings"/(aid+".json")).read_text(encoding="utf8"))

@lru_cache(maxsize=128)
def _cached_pages(aid,mtime):
    return fmt.page_chunks(_cached_file(aid,mtime))

@lru_cache(maxsize=128)
def _cached_card_pages(aid,mtime):
    from telegram_card import detail_pages
    return detail_pages(_cached_file(aid,mtime))

def card_pages_for(aid,item):
    filename=DATA/"listings"/(str(aid)+".json")
    if filename.is_file():
        stamp=filename.stat().st_mtime_ns
        if item==_cached_file(aid,stamp):
            return _cached_card_pages(aid,stamp)
    from telegram_card import detail_pages
    return detail_pages(item)

def load_snapshot(aid,db):
    if not aid.isdecimal():return None
    f=DATA/"listings"/(aid+".json")
    if f.is_file():
        return _cached_file(aid,f.stat().st_mtime_ns)
    row=db.execute("SELECT payload FROM watch WHERE assignment_id=?",(aid,)).fetchone()
    return json.loads(row[0]) if row else None

def pages_for(aid,db,item):
    f=DATA/"listings"/(aid+".json")
    if f.is_file():
        stamp=f.stat().st_mtime_ns
        if item == _cached_file(aid,stamp):
            return _cached_pages(aid,stamp)
    return fmt.page_chunks(item)

def answer_callback(api_func,token,callback_id,**options):
    try:return api_func(token,"answerCallbackQuery",{"callback_query_id":callback_id,**options})
    except RuntimeError as ex:
        if "Telegram HTTP 400" in str(ex):return False
        raise

def toggle_application(conn,aid):
    import housing_state
    current=housing_state.stage(conn,aid)
    if current=="confirmed":
        return True  # a confirmed booking cannot be accidentally unmarked
    now=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
    if current in ("applied","talking"):
        conn.execute("DELETE FROM applications WHERE assignment_id=?",(aid,))
        conn.commit()
        return False
    conn.execute("""INSERT INTO applications(assignment_id,applied_at,stage)
                    VALUES (?,?,'applied')
                    ON CONFLICT(assignment_id) DO UPDATE SET
                    applied_at=excluded.applied_at,stage='applied'""",(aid,now))
    conn.commit()
    return True

def handle_callback(update,token,chat_id,api_func=api,db_path=DB):
    query=update.get("callback_query") or {}
    if str(query.get("data") or "").startswith("t4:"):
        import telegram_housing_confirmation as confirm
        return confirm.reply(update,token,chat_id,api_func=api_func,db_path=db_path)
    import telegram_card as card
    if card.parse(query.get("data")):
        from telegram_card_controller import handle
        return handle(update,token,chat_id,api_func=api_func,db_path=db_path)
    callback_id=query.get("id")
    if not callback_id:return "no_callback"
    actor=query.get("from") or {}
    msg=query.get("message") or {}
    chat=msg.get("chat") or {}
    try:
        authorized=(str(chat.get("id"))==str(chat_id)
                    and chat.get("type")=="private"
                    and str(actor.get("id"))==str(chat_id))
        parsed=parse_action(query.get("data"))
        mid=int(msg.get("message_id") or 0)
    except (ValueError,TypeError):
        authorized=False;parsed=None;mid=0
    if not authorized or parsed is None:
        answer_callback(api_func,token,callback_id,text="Немає доступу")
        return "unauthorized_or_invalid"
    action,aid,page,_=parsed
    # Acknowledge immediately, before any disk, CPU work or message edit.
    answer_callback(api_func,token,callback_id)
    with sqlite3.connect(db_path,timeout=6) as conn:
        init_db(conn)
        row=conn.execute("SELECT control_message_id,album_message_id FROM controls WHERE assignment_id=?",(aid,)).fetchone()
        if not row or row[0]!=mid:return "stale_button"
        item=load_snapshot(aid,conn)
        if not item:return "missing_details"
        if action=="map":
            coords=item.get("coordinates") or {}
            lat,lon=coords.get("lat"),coords.get("lon")
            if not (isinstance(lat,(float,int)) and isinstance(lon,(float,int)) and -90<=lat<=90 and -180<=lon<=180):
                return "missing_map"
            result=api_func(token,"sendVenue",{
                "chat_id":str(chat_id),"latitude":lat,"longitude":lon,
                "title":"Орієнтир: "+str(item.get("city") or "Місцевість"),
                "address":"Орієнтир населеного пункту, не точна адреса будинку",
                "reply_to_message_id":mid,"allow_sending_without_reply":"true"})
            return "map_sent" if isinstance(result,dict) else "map_failed"
        if action=="applied":
            applied=toggle_application(conn,aid)
            total=len(pages_for(aid,conn,item)) if page is not None else 1
            api_func(token,"editMessageReplyMarkup",{
                "chat_id":str(chat_id),"message_id":str(mid),
                "reply_markup":keyboard(item,page,total,applied=applied)})
            return "application_marked" if applied else "application_unmarked"
        if page is None:
            body=fmt.caption(item) if row[0]==row[1] else fmt.control_text(item)
            markup=keyboard(item,applied=is_applied(aid,conn))
        else:
            pages=pages_for(aid,conn,item)
            page=max(0,min(page,len(pages)-1))
            body=pages[page]+f"\n\n<i>Сторінка {page+1}/{len(pages)}</i>"
            markup=keyboard(item,page,len(pages),applied=is_applied(aid,conn))
        try:
            api_func(token,"editMessageText",{
                "chat_id":str(chat_id),"message_id":str(mid),"text":body,
                "parse_mode":"HTML","reply_markup":markup,
                "disable_web_page_preview":"true"})
        except RuntimeError as ex:
            if "Telegram HTTP 400" in str(ex):
                return "unchanged_or_edit_rejected"
            raise
    return "collapsed" if page is None else "expanded"
