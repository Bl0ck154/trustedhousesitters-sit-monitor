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
            self.assertEqual(outgoing,["sendMessage","sendMessage","sendPhoto"])
            con.close()
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
