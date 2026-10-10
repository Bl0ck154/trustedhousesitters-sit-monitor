#!/usr/bin/env python3
import contextlib
import datetime as dt
import io
import json
import pathlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import monitor
import telegram_upgrade as m

URL="https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/germany/hamburg/hamburg/l/857632/"
def sample(status="open"):
    return {"assignment_id":"2122760","listing_id":"857632","url":URL,
            "title":"Three big city cats living their best life",
            "start":"2026-10-28","end":"2026-11-04","nights":7,
            "city":"Hamburg","country":"Germany","pets":{"cat":3},
            "cats":3,"status":status,"verified_by_detail":True,
            "eligible_alert":True,"transport_accessible":True,
            "internet":"highSpeed","pet_care":"Feed the cats every day",
            "photo_urls":["https://res.cloudinary.com/trustedhousesitters/image/upload/t_highres_2mp,f_auto/v1/remote_media/media/photo/a.jpg",
                          "https://res.cloudinary.com/trustedhousesitters/image/upload/t_highres_2mp,f_auto/v1/remote_media/media/photo/b.jpg",
                          "https://res.cloudinary.com/trustedhousesitters/image/upload/t_highres_2mp,f_auto/v1/remote_media/media/photo/c.jpg"]}
class Tests(unittest.TestCase):
    def test_format_and_clickable_title(self):
        txt=m.caption(sample())
        self.assertIn("<a href=",txt)
        self.assertIn("Three big city cats",txt)
        self.assertNotIn("Apply",txt)
        self.assertNotIn("Новий доступний house sit",txt)
        self.assertLessEqual(len(txt),1024)
    def test_single_photo_card(self):
        calls=[]
        def fake(token,method,kwargs):
            calls.append((method,kwargs))
            return {"message_id":123}
        with patch.object(m,"api",fake):
            mid,kind=m.send_open("mock","1234",sample())
        self.assertEqual((mid,kind),(123,"photo_card"))
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0],"sendPhoto")
        self.assertIn("<b>",calls[0][1]["caption"])
        self.assertIn("t3:d:",calls[0][1]["reply_markup"])
    def test_status_transitions_dedupe(self):
        with tempfile.TemporaryDirectory() as t:
            con=sqlite3.connect(pathlib.Path(t)/"db.sqlite3")
            m.db_init(con)
            initial=sample()
            m.watch_row(con,initial,"open",checked=False)
            outgoing=[]
            def fake_api(token,method,params):
                outgoing.append(method)
                if method=="sendMediaGroup":return [{"message_id":333}]
                return {"message_id": 456}
            with patch.object(m,"api",fake_api),patch.object(m.monitor,"save_detail",lambda a:None):
                with patch.object(m.monitor,"validate_detail",lambda a:sample("reviewing")):
                    self.assertEqual(m.refresh_watch(con,"tok","123",force=True)[0],1)
                    self.assertEqual(m.refresh_watch(con,"tok","123",force=True)[0],0)
                with patch.object(m.monitor,"validate_detail",lambda a:sample("confirmed")):
                    self.assertEqual(m.refresh_watch(con,"tok","123",force=True)[0],1)
                with patch.object(m.monitor,"validate_detail",lambda a:sample("open")):
                    self.assertEqual(m.refresh_watch(con,"tok","123",force=True)[0],1)
            self.assertEqual(outgoing,["sendMessage","sendMessage","sendMessage"])
            con.close()
    def test_statuses_reply_to_original_photo_card_after_multiple_transitions(self):
        with tempfile.TemporaryDirectory() as t:
            conn=sqlite3.connect(pathlib.Path(t)/"db.sqlite3")
            m.db_init(conn)
            item=sample()
            m.watch_row(conn,item,"open",message_id=42)
            m.controls.pending(conn,item,42,attached=True)
            sent=[]
            def fake_api(token,method,params):
                sent.append((method,dict(params)))
                return {"message_id":80+len(sent)}
            with patch.object(m,"api",fake_api),patch.object(m.monitor,"save_detail",lambda x:None):
                for newstate in ("reviewing","open","reviewing"):
                    with patch.object(m.monitor,"validate_detail",lambda x,status=newstate:sample(status)):
                        self.assertEqual(m.refresh_watch(conn,"token","123",force=True),(1,0))
            self.assertEqual([method for method,_ in sent],["sendMessage"]*3)
            self.assertEqual([params.get("reply_to_message_id") for _,params in sent],["42"]*3)
            self.assertEqual(conn.execute("SELECT message_id FROM watch").fetchone()[0],83)
            self.assertEqual(m.original_card_id(conn,item["assignment_id"]),42)
            conn.close()

    def test_status_reply_uses_upgraded_photo_card_not_deleted_album(self):
        with tempfile.TemporaryDirectory() as t:
            conn=sqlite3.connect(pathlib.Path(t)/"db.sqlite3")
            m.db_init(conn)
            item=sample()
            m.controls.pending(conn,item,41,attached=False)
            conn.execute("UPDATE controls SET control_message_id=45 WHERE assignment_id=?",
                         (item["assignment_id"],))
            conn.commit()
            self.assertEqual(m.original_card_id(conn,item["assignment_id"]),45)
            conn.close()

    def test_status_without_original_card_never_quotes_previous_status(self):
        with tempfile.TemporaryDirectory() as t:
            conn=sqlite3.connect(pathlib.Path(t)/"db.sqlite3")
            m.db_init(conn)
            m.watch_row(conn,sample(),"open",message_id=65)
            sent=[]
            def fake(token,method,fields):
                sent.append(fields)
                return {"message_id":90}
            with patch.object(m,"api",fake),patch.object(m.monitor,"save_detail",lambda a:None):
                with patch.object(m.monitor,"validate_detail",lambda a:sample("reviewing")):
                    self.assertEqual(m.refresh_watch(conn,"tok","chat",force=True),(1,0))
            self.assertNotIn("reply_to_message_id",sent[0])
            conn.close()

    def test_deleted_card_falls_back_to_plain_notification(self):
        calls=[]
        def fake(token,method,fields):
            calls.append(dict(fields))
            if len(calls)==1:raise RuntimeError("Telegram HTTP 400 on sendMessage")
            return {"message_id":103}
        with patch.object(m,"api",fake):
            mid=m.send_status("token","chat",sample("reviewing"),"reviewing",reply_to_id=42)
        self.assertEqual(mid,103)
        self.assertEqual(calls[0]["reply_to_message_id"],"42")
        self.assertNotIn("reply_to_message_id",calls[1])
        self.assertEqual(calls[0]["text"],calls[1]["text"])

    def test_reopen_notice_is_fast_text_and_not_repeated(self):
        with tempfile.TemporaryDirectory() as t:
            conn=sqlite3.connect(pathlib.Path(t)/"db.sqlite3")
            m.db_init(conn)
            m.watch_row(conn,sample("reviewing"),"reviewing",checked=False)
            calls=[]
            def fake(token,method,fields):
                calls.append((method,fields))
                return {"message_id":923}
            with patch.object(m,"api",fake),patch.object(m.monitor,"save_detail",lambda x:None):
                with patch.object(m.monitor,"validate_detail",lambda x:{**sample("open"),"application_count":2}):
                    self.assertEqual(m.refresh_watch(conn,"tok","chat",force=True),(1,0))
                    self.assertEqual(m.refresh_watch(conn,"tok","chat",force=True),(0,0))
            self.assertEqual([x[0] for x in calls],["sendMessage"])
            self.assertIn("знову відкриті",calls[0][1]["text"])
            self.assertIn("https://",calls[0][1]["text"])
            conn.close()

    def test_failed_transition_send_is_retried_not_silently_lost(self):
        with tempfile.TemporaryDirectory() as t:
            conn=sqlite3.connect(pathlib.Path(t)/"db.sqlite3")
            m.db_init(conn)
            m.watch_row(conn,sample("open"),"open",checked=False)
            attempts=[]
            def flaky(token,method,params):
                attempts.append(method)
                if len(attempts)==1:
                    raise RuntimeError("Telegram unavailable")
                return {"message_id":777}
            with patch.object(m,"api",flaky),patch.object(m.monitor,"save_detail",lambda x:None):
                with patch.object(m.monitor,"validate_detail",lambda x:sample("reviewing")):
                    self.assertEqual(m.refresh_watch(conn,"tok","chat",force=True),(0,1))
                    self.assertEqual(conn.execute("SELECT status FROM watch").fetchone()[0],"open")
                    self.assertEqual(m.refresh_watch(conn,"tok","chat",force=True),(1,0))
                    self.assertEqual(conn.execute("SELECT status FROM watch").fetchone()[0],"reviewing")
            self.assertEqual(attempts,["sendMessage","sendMessage"])
            conn.close()

    def test_priority_watch_poll_every_two_minutes(self):
        with tempfile.TemporaryDirectory() as t:
            conn=sqlite3.connect(pathlib.Path(t)/"db.sqlite3")
            m.db_init(conn)
            now=dt.datetime(2026,10,10,8,0,tzinfo=dt.timezone.utc)
            with patch.object(m,"clock",lambda:now):
                m.watch_row(conn,sample("open"),"open",checked=True)
            called=[]
            def fake_fetch(item):
                called.append(item["assignment_id"])
                return sample("open")
            with patch.object(m.monitor,"validate_detail",side_effect=fake_fetch),patch.object(m.monitor,"save_detail",lambda item:None):
                with patch.object(m,"clock",lambda:now+dt.timedelta(minutes=1)):
                    self.assertEqual(m.refresh_watch(conn,"tok","chat"),(0,0))
                self.assertFalse(called)
                with patch.object(m,"clock",lambda:now+dt.timedelta(minutes=3)):
                    self.assertEqual(m.refresh_watch(conn,"tok","chat"),(0,0))
                self.assertEqual(len(called),1)
                with patch.object(m,"clock",lambda:now+dt.timedelta(minutes=4)):
                    self.assertEqual(m.refresh_watch(conn,"tok","chat"),(0,0))
                self.assertEqual(len(called),1)
            conn.close()

    def test_paris_reviewing_formatted_as_no_new_applications(self):
        item={**sample("reviewing"),"city":"Paris","application_count":8}
        msg=m.status_caption(item,"reviewing")
        self.assertIn("нові заявки не приймаються",msg)
        self.assertIn("Заявок: 8",msg)
        self.assertIn("trustedhousesitters.com",msg)

    def test_unknown_no_false_close(self):
        with tempfile.TemporaryDirectory() as t:
            c=sqlite3.connect(pathlib.Path(t)/"db.sqlite3");m.db_init(c)
            m.watch_row(c,sample(),"open",checked=False)
            with patch.object(m.monitor,"validate_detail",lambda x:sample("unknown")):
                changed,errors=m.refresh_watch(c,"tok","chat",force=True)
            self.assertEqual((changed,errors),(0,0))
            self.assertEqual(c.execute("select status from watch").fetchone()[0],"open")
            c.close()
    def test_removed_requires_two_confirmations(self):
        with tempfile.TemporaryDirectory() as t:
            conn=sqlite3.connect(pathlib.Path(t)/"db.sqlite3")
            m.db_init(conn)
            m.watch_row(conn,sample(),"open",checked=False)
            calls=[]
            def fake_api(token,method,params):
                calls.append(method)
                return {"message_id":99}
            with patch.object(m,"api",fake_api),patch.object(m.monitor,"save_detail",lambda x:None):
                with patch.object(m.monitor,"validate_detail",lambda x:sample("removed")):
                    self.assertEqual(m.refresh_watch(conn,"tok","chat",force=True)[0],0)
                    self.assertEqual(conn.execute("select status from watch").fetchone()[0],"open")
                    self.assertEqual(m.refresh_watch(conn,"tok","chat",force=True)[0],1)
                    self.assertEqual(m.refresh_watch(conn,"tok","chat",force=True)[0],0)
            self.assertEqual(calls,["sendMessage"])
            self.assertEqual(conn.execute("select status from watch").fetchone()[0],"removed")
            conn.close()

    def test_existing_delivery_migrates_without_resend(self):
        with tempfile.TemporaryDirectory() as t:
            c=sqlite3.connect(pathlib.Path(t)/"db.sqlite3");m.db_init(c)
            event={**sample(),"event_key":"abc","discovered_at":"2026-10-09T18:00:00+00:00"}
            m.delivery_row(c,"abc","sent",99)
            self.assertEqual(m.bootstrap_watch(c,[event]),1)
            self.assertEqual(m.bootstrap_watch(c,[event]),0)
            self.assertEqual(c.execute("select status from watch").fetchone()[0],"open")
            c.close()
if __name__=="__main__":unittest.main()
