#!/usr/bin/env python3
"""Direct Telegram media albums + follow-up state notifications for house sits.

Rechecks previously delivered assignments even when they disappear from public search.
Never sends closure for an unverified/missing assignment.
"""
import argparse
import datetime as dt
import html
import json
import pathlib
import sqlite3
import sys
import time
import urllib.error
from zoneinfo import ZoneInfo

import monitor
import telegram_format as fmt
import telegram_controls as controls
import telegram_quality as quality
import telegram_card as card
import housing_preferences as preferences
import telegram_media_cache as photo_cache
import telegram_photo_api as fast_photos
import dispatch_telegram as legacy
from setup_telegram import api, TOKEN_FILE, CHAT_FILE
from setup_telegram import api as ORIGINAL_API

ROOT = pathlib.Path(__file__).resolve().parent / "data"
DB = ROOT / "telegram_delivery.sqlite3"
MIN_RECHECK = dt.timedelta(minutes=4)
HOT_RECHECK = dt.timedelta(minutes=2)
STATUS_CONFIRM_DELAY = dt.timedelta(seconds=65)

def shorten(value, maxchars=190):
    s = " ".join(str(value or "").split())
    return s if len(s) <= maxchars else s[:maxchars - 1].rsplit(" ", 1)[0] + "…"

def label(item):
    title = shorten(item.get("title") or "Оголошення", 110)
    url = html.escape(str(item["url"]), quote=True)
    return '<a href="' + url + '"><b>' + html.escape(title) + '</b></a>'

def caption(item):
    return fmt.caption(item)

def send_open(token, chat_id, item,applied=False,ignored=False):
    # One Telegram message for each sit. A single photo allows inline
    # controls; the other two images are browsed using editMessageMedia.
    first=card.cover(item)
    if first:
        try:
            args={
                "chat_id":chat_id,"photo":photo_cache.resolve(first),
                "caption":card.caption(item),"parse_mode":"HTML",
                "reply_markup":card.controls(item,applied=applied,ignored=ignored)}
            try:
                if api is ORIGINAL_API and args["photo"]==first:
                    response=fast_photos.send_photo(token,first,args)
                else:
                    response=api(token,"sendPhoto",args)
            except ValueError:
                response=api(token,"sendPhoto",args)
            except RuntimeError as photo_error:
                if "Telegram HTTP 400" not in str(photo_error):
                    raise
                response=api(token,"sendPhoto",args)
            if isinstance(response,dict) and isinstance(response.get("message_id"),int):
                photo_cache.remember(first,response)
                return response["message_id"],"photo_card"
            raise RuntimeError("Unexpected Telegram photo result")
        except RuntimeError as ex:
            if "Telegram HTTP 400" not in str(ex):
                raise
    # No media or invalid remote photo: still ONE text message, with buttons.
    response=api(token,"sendMessage",{
        "chat_id":chat_id,"text":fmt.caption(item),"parse_mode":"HTML",
        "reply_markup":controls.keyboard(item),
        "disable_web_page_preview":"true"})
    if not isinstance(response,dict) or not isinstance(response.get("message_id"),int):
        raise RuntimeError("Unexpected Telegram text result")
    return response["message_id"],"text_card"

def status_caption(item, newstate):
    return {"reviewing":"⏸ Прийом заявок призупинено",
            "confirmed":"✅ Сіттера обрано",
            "removed":"⛔ Дати прибрано",
            "open":"🔔 Заявки знову відкриті"}.get(newstate)

def original_card_id(conn, assignment_id):
    """Stable original listing card, not the newest status notification.

    Older companion messages were upgraded in place into standalone photo
    cards; their initial media-group messages may have been deleted.
    Prefer the active control_message_id (now the photo card) and fall back to
    album_message_id. Never infer from watch.message_id, which is updated by
    subsequent status notifications.
    """
    row=conn.execute("""SELECT control_message_id,album_message_id FROM controls
                        WHERE assignment_id=?""",(str(assignment_id),)).fetchone()
    if not row:
        return None
    current_photo_card=row[0] or row[1]
    return int(current_photo_card) if current_photo_card is not None else None


def send_status(token, chat_id, item, state, reply_to_id=None):
    body = status_caption(item,state)
    if not body:
        raise ValueError("cannot notify unknown status")
    # A reply already quotes the original card. Standalone messages need
    # the listing link, but not dates, counters or instructions.
    args={"chat_id":chat_id,
          "text":body if reply_to_id is not None else body+"\n"+label(item),
          "parse_mode":"HTML","disable_web_page_preview":"true"}
    if reply_to_id is not None:
        args["reply_to_message_id"]=str(reply_to_id)
    try:
        result=api(token,"sendMessage",args)
    except RuntimeError as exc:
        # Original message can be deleted or become unavailable. Do not lose
        # a time-critical status alert just because Telegram rejects a reply.
        # Retry only on definitive HTTP 400: unknown network failures may
        # indicate the first message was actually delivered.
        if reply_to_id is None or "Telegram HTTP 400" not in str(exc):
            raise
        args.pop("reply_to_message_id",None)
        args["text"]=body+"\n"+label(item)
        result=api(token,"sendMessage",args)
    if not isinstance(result,dict) or not isinstance(result.get("message_id"),int):
        raise RuntimeError("Unexpected status message response")
    return result["message_id"]

def db_init(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS delivery (event_key TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at TEXT NOT NULL, message_id INTEGER)")
    conn.execute("CREATE TABLE IF NOT EXISTS watch (assignment_id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL, last_checked TEXT, last_change TEXT, message_id INTEGER)")
    conn.execute("""CREATE TABLE IF NOT EXISTS watch_transitions(
         assignment_id TEXT PRIMARY KEY,
         proposed_status TEXT NOT NULL,
         first_seen TEXT NOT NULL,
         observation_count INTEGER NOT NULL DEFAULT 1
    )""")
    controls.init_db(conn)
    conn.commit()

def clock():
    return dt.datetime.now(dt.timezone.utc)

def watch_row(conn, item, status, checked=True, message_id=None):
    now=clock().isoformat()
    conn.execute("""INSERT INTO watch (assignment_id,status,payload,last_checked,last_change,message_id)
       VALUES (?,?,?,?,?,?)
       ON CONFLICT(assignment_id) DO UPDATE SET
       status=excluded.status,payload=excluded.payload,last_checked=excluded.last_checked,
       last_change=CASE WHEN watch.status!=excluded.status THEN excluded.last_change ELSE watch.last_change END,
       message_id=COALESCE(excluded.message_id,watch.message_id)""",
       (str(item["assignment_id"]),status,json.dumps(item,ensure_ascii=False),
        now if checked else None,now,message_id))
    conn.commit()

def delivery_row(conn,key,state,message_id=None):
    now=clock().isoformat()
    conn.execute("""INSERT INTO delivery (event_key,state,updated_at,message_id) VALUES (?,?,?,?)
       ON CONFLICT(event_key) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at,message_id=excluded.message_id""",
       (key,state,now,message_id))
    conn.commit()

def bootstrap_watch(conn,events):
    # Upgrade from the earlier text-only sender without resending old notifications.
    rows = {e["event_key"]:e for e in events}
    count=0
    for key,state,message_id in conn.execute("SELECT event_key,state,message_id FROM delivery WHERE state='sent'"):
        e=rows.get(key)
        if not e:
            continue
        if conn.execute("SELECT 1 FROM watch WHERE assignment_id=?",(e["assignment_id"],)).fetchone():
            continue
        watch_row(conn,e,"open",checked=False,message_id=message_id)
        count+=1
    return count

def refresh_watch(conn,token,chat_id,force=False,max_items=60):
    changed=0
    errors=0
    now=clock()
    rows=conn.execute("SELECT assignment_id,status,payload,last_checked FROM watch ORDER BY COALESCE(last_checked,'') ASC").fetchall()
    ignored_ids=preferences.ignored_in_connection(conn)
    for aid,old,payload,last_check in rows:
        if str(aid) in ignored_ids:continue
        if max_items<=0:
            break
        item=json.loads(payload)
        try:
            end=dt.date.fromisoformat(item["end"])
            if end < now.date()-dt.timedelta(days=1):
                continue
        except (ValueError,KeyError):
            continue
        if not force and last_check:
            try:
                changed_at=conn.execute("SELECT last_change FROM watch WHERE assignment_id=?",(aid,)).fetchone()[0]
                recent=bool(changed_at and now-dt.datetime.fromisoformat(changed_at)<dt.timedelta(hours=24))
                interval=HOT_RECHECK if (old=="reviewing" or recent) else MIN_RECHECK
                if now-dt.datetime.fromisoformat(last_check)<interval:
                    continue
            except ValueError:
                pass
        max_items-=1
        try:
            actual=monitor.validate_detail(item)
            if actual["status"] not in ("open","reviewing","confirmed","removed"):
                # Missing/unknown never means definitively closed.
                conn.execute("UPDATE watch SET last_checked=? WHERE assignment_id=?",
                             (clock().isoformat(),aid))
                conn.commit()
                continue
            # Save only the verified detail snapshot. Do not let one stale
            # public response generate a Telegram transition.
            monitor.save_detail(actual)
            if actual["status"]==old:
                conn.execute("DELETE FROM watch_transitions WHERE assignment_id=?",(aid,))
                watch_row(conn,actual,old)
                continue

            new=actual["status"]
            pending=conn.execute(
                "SELECT proposed_status,first_seen,observation_count "
                "FROM watch_transitions WHERE assignment_id=?",(aid,)).fetchone()
            if not pending or pending[0]!=new:
                conn.execute("""INSERT INTO watch_transitions
                    (assignment_id,proposed_status,first_seen,observation_count)
                    VALUES (?,?,?,1)
                    ON CONFLICT(assignment_id) DO UPDATE SET
                    proposed_status=excluded.proposed_status,
                    first_seen=excluded.first_seen,observation_count=1""",
                    (aid,new,now.isoformat()))
                conn.execute("UPDATE watch SET last_checked=? WHERE assignment_id=?",
                             (clock().isoformat(),aid))
                conn.commit()
                print("watch_unconfirmed_transition",aid,old,"->",new,flush=True)
                continue
            try:
                first=dt.datetime.fromisoformat(pending[1])
            except (ValueError,TypeError):
                first=now
            elapsed=now-first
            if pending[2]<1 or elapsed<STATUS_CONFIRM_DELAY:
                conn.execute("UPDATE watch_transitions SET observation_count=observation_count+1 "
                             "WHERE assignment_id=?",(aid,))
                conn.execute("UPDATE watch SET last_checked=? WHERE assignment_id=?",
                             (clock().isoformat(),aid))
                conn.commit()
                continue
            # Two independent status observations separated by >=65 seconds
            # confirm a change. Flapping results reset the candidate.
            # Send the important state transition first. A definitive Telegram
            # failure must NOT silently consume the event: leave old status in
            # watch and retry on a later status run. An ambiguous network timeout
            # can occasionally produce a duplicate but not a missing alert.
            mid=send_status(token,chat_id,actual,new,
                            reply_to_id=original_card_id(conn,aid))
            watch_row(conn,actual,new)
            conn.execute("DELETE FROM watch_transitions WHERE assignment_id=?",(aid,))
            conn.execute("UPDATE watch SET message_id=? WHERE assignment_id=?",(mid,aid))
            conn.commit()
            changed+=1
            print("watch_transition",aid,old,"->",new,flush=True)
        except Exception as ex:
            errors+=1
            print("watch_error",aid,type(ex).__name__,file=sys.stderr)
    return changed,errors

def deliver_queue(conn,token,chat_id,events,limit=15):
    sent=skipped=errors=0
    # Show the highest-value city/cat/transit sits first when several arrive together.
    ignored_ids=preferences.ignored_in_connection(conn)
    for e in sorted(events,key=lambda x:quality.priority(x)['score'],reverse=True):
        if str(e['assignment_id']) in ignored_ids:
            delivery_row(conn,e['event_key'],'dismissed')
            skipped+=1
            continue
        row=conn.execute("SELECT state FROM delivery WHERE event_key=?",(e["event_key"],)).fetchone()
        if row and row[0] in ("sent","stale","sending","uncertain"):
            skipped+=1
            continue
        if sent+errors>=limit:
            break
        watch=conn.execute("SELECT status,message_id FROM watch WHERE assignment_id=?",(e["assignment_id"],)).fetchone()
        if watch and watch[0]=="open":
            # Already announced through the lifecycle watcher, or older delivered event.
            delivery_row(conn,e["event_key"],"sent",watch[1])
            skipped+=1
            continue
        try:
            actual=monitor.validate_detail(e)
            if not (actual.get("verified_by_detail") and actual.get("eligible_alert")
                    and actual["status"]=="open" and actual["assignment_id"]==e["assignment_id"]):
                delivery_row(conn,e["event_key"],"stale")
                skipped+=1
                continue
            monitor.save_detail(actual)
            delivery_row(conn,e["event_key"],"sending")
            mid,kind=send_open(token,chat_id,actual,applied=controls.is_applied(e["assignment_id"],conn))
            delivery_row(conn,e["event_key"],"sent",mid)
            watch_row(conn,actual,"open",message_id=mid)
            controls.pending(conn,actual,mid,attached=(kind in ("photo_card","text_card")))
            sent+=1
            print("telegram_sent",e["assignment_id"],kind)
        except Exception as ex:
            # The request may have gone through; don't resend blindly.
            if conn.execute("SELECT state FROM delivery WHERE event_key=?",(e["event_key"],)).fetchone() == ("sending",):
                delivery_row(conn,e["event_key"],"uncertain")
            errors+=1
            print("queue_error",e["assignment_id"],type(ex).__name__,file=sys.stderr)
    return sent,skipped,errors

def main():
    cli=argparse.ArgumentParser()
    cli.add_argument("--dry-run",action="store_true")
    cli.add_argument("--preview-listing",type=str,default=None,
                     help="One manual media album example; does not change delivery/watch state")
    cli.add_argument("--force-watch",action="store_true")
    cli.add_argument("--status-only",action="store_true")
    cli.add_argument("--reset-keyboard",action="store_true")
    cli.add_argument("--delivery-only",action="store_true")
    cli.add_argument("--test-card",type=str,default=None,
                     help="Send one test photo card for a locally cached assignment")
    cli.add_argument("--test-description",action="store_true")
    cli.add_argument("--test-gallery-two",type=str,default=None)
    cli.add_argument("--test-reply",type=int,default=None)
    cli.add_argument("--description-only",type=str,default=None)
    args=cli.parse_args()
    events=legacy.read_events()
    if args.dry_run:
        print(json.dumps({"queue":len(events),"unique_listings":len({e["assignment_id"] for e in events})}))
        return 0
    if not TOKEN_FILE.is_file() or not CHAT_FILE.is_file():
        print("Telegram not paired",file=sys.stderr)
        return 2
    token=TOKEN_FILE.read_text().strip()
    chat_id=CHAT_FILE.read_text().strip()
    if not chat_id.lstrip("-").isdigit():
        return 2
    if args.reset_keyboard:
        result=api(token,"sendMessage",{"chat_id":chat_id,
                    "text":"⌨️ Клавіатуру скинуто.",
                    "reply_markup":json.dumps({"remove_keyboard":True},ensure_ascii=False)})
        if not isinstance(result,dict) or not isinstance(result.get("message_id"),int):
            raise RuntimeError("Keyboard reset not acknowledged")
        print("keyboard_reset_message_id",result["message_id"])
        return 0
    if args.preview_listing:
        matches=[e for e in events if e["listing_id"]==args.preview_listing]
        if not matches:
            print("Not in known delivered queue",file=sys.stderr)
            return 2
        actual=monitor.validate_detail(matches[-1])
        if actual["status"]!="open":
            print("Preview skipped; listing not open",file=sys.stderr)
            return 2
        monitor.save_detail(actual)
        mid,kind=send_open(token,chat_id,actual)
        print(json.dumps({"preview":"sent","type":kind,"message_id":mid}))
        return 0
    if args.description_only:
        import telegram_action_send as detail
        aid=str(args.description_only)
        source=ROOT/"listings"/(aid+".json")
        if not aid.isdecimal() or not source.is_file():return 2
        item=json.loads(source.read_text())
        sent=detail.send_description(token,chat_id,item,reply_to=args.test_reply)
        print(json.dumps({"description_sent":len(sent),"assignment_id":aid}))
        return 0
    if args.test_gallery_two:
        import telegram_action_send as action_sender
        source=ROOT/"listings"/(str(args.test_gallery_two)+".json")
        if not args.test_gallery_two.isdecimal() or not source.is_file():
            return 2
        item=json.loads(source.read_text(encoding="utf8"))
        item["photo_urls"]=(item.get("photo_urls") or [])[:2]
        ids=action_sender.send_gallery(token,chat_id,item,reply_to=args.test_reply)
        print(json.dumps({"test_album_sent":len(ids),"media_count":2}))
        return 0
    if args.test_card:
        import telegram_action_send as action_sender
        source=ROOT/"listings"/(str(args.test_card)+".json")
        if not args.test_card.isdecimal() or not source.is_file():
            print("No such archived assignment",file=sys.stderr)
            return 2
        item=json.loads(source.read_text(encoding="utf8"))
        conn=sqlite3.connect(DB,timeout=15)
        try:
            db_init(conn)
            mid,kind=send_open(token,chat_id,item)
            conn.execute("INSERT OR IGNORE INTO control_instances(assignment_id,message_id) VALUES (?,?)",
                         (str(item["assignment_id"]),mid))
            conn.commit()
            print(json.dumps({"test_card_sent":True,"message_id":mid,
                              "photo_count":len(item.get("photo_urls") or []),"type":kind}))
            if args.test_description:
                mids=action_sender.send_description(token,chat_id,item,reply_to=mid)
                print(json.dumps({"test_description_sent":True,"messages":len(mids)}))
            return 0
        finally:
            conn.close()
    if args.status_only and args.delivery_only:
        print("Choose one service lane",file=sys.stderr)
        return 2
    conn=sqlite3.connect(DB,timeout=20)
    try:
        db_init(conn)
        seeded=bootstrap_watch(conn,events)
        changes,watch_errors=(0,0) if args.delivery_only else refresh_watch(conn,token,chat_id,args.force_watch)
        sent,skipped,errors=(0,0,0) if args.status_only else deliver_queue(conn,token,chat_id,events)
        buttons,button_errors=(0,0) if args.status_only else controls.flush_pending(conn,token,chat_id)
        if not args.status_only:
            buttons+=controls.flush_keyboard_updates(conn,token,chat_id,limit=6)
        print(json.dumps({"known_events":len(events),"new":sent,"changes":changes,"buttons":buttons,
                          "skipped":skipped,"migrated_existing":seeded,
                          "errors":errors+watch_errors+button_errors},ensure_ascii=False))
        return 0 if not (errors or watch_errors or button_errors) else 2
    finally:
        conn.close()

if __name__=="__main__":
    raise SystemExit(main())
