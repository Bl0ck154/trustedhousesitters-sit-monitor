import datetime as dt
import json
import os
import pathlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import housing_plan as plan
import housing_state as state
import housing_reporting as report
import telegram_controls as controls
import telegram_housing_confirmation as conf
import telegram_commands as commands

NOW=dt.date(2026,10,10)
def example(aid="901",start="2026-10-27",end="2026-11-14",pets=None):
    return {"assignment_id":aid,"listing_id":"123","status":"open",
            "start":start,"end":end,"city":"Vienna","country":"Austria",
            "title":"Quiet friendly pets","url":"https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/austria/vienna/vienna/l/123/",
            "pets":pets or {"cat":2},"nights":(dt.date.fromisoformat(end)-dt.date.fromisoformat(start)).days,
            "internet":"highSpeed","transport_accessible":True,"transit_warning":False}

class HousingPlanTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{"THS_EARLIEST_START":"2026-10-25"})
        self.env.start()
    def tearDown(self):self.env.stop()
    def test_cat_small_pets_and_dog_backup(self):
        self.assertEqual(plan.pet_tier(example(pets={"cat":2})),"A")
        self.assertEqual(plan.pet_tier(example(pets={"rabbit":1,"hamster":1})),"A")
        self.assertEqual(plan.pet_tier(example(pets={"small pet":2})),"A")
        self.assertEqual(plan.pet_tier(example(pets={"dog":1})),"B")
        self.assertEqual(plan.pet_tier(example(pets={"cat":1,"dog":1})),"B")
        self.assertEqual(plan.pet_tier(example(pets={"dog":3})),"C")
        self.assertEqual(plan.pet_tier(example(pets={"cat":2,"horse":1})),"C")
        self.assertTrue(plan.should_alert(example(),[],NOW))
        self.assertTrue(plan.should_alert(example(pets={"hamster":1}),[],NOW))
        self.assertFalse(plan.should_alert(example(pets={"dog":1}),[],NOW))
        self.assertTrue(plan.should_alert(example(pets={"dog":1}),[],dt.date(2026,10,16)))

    def test_confirmed_stay_moves_window_and_no_overlap(self):
        stay=example()
        window=plan.journey_window([stay],NOW)
        self.assertEqual(window["focus"][0],dt.date(2026,11,14))
        self.assertIn((dt.date(2026,10,25),dt.date(2026,10,27)),window["bridge_gaps"])
        self.assertEqual(plan.search_window([stay],NOW)[0],dt.date(2026,11,14))
        self.assertFalse(plan.candidate_fit(example("902","2026-10-29","2026-11-05"),[stay],NOW))
        self.assertTrue(plan.candidate_fit(example("903","2026-11-14","2026-11-25"),[stay],NOW))

    def test_future_booking_still_requires_gap_before_it(self):
        future=example("999","2026-11-05","2026-11-16")
        window=plan.journey_window([future],NOW)
        self.assertEqual(window["focus"][0],dt.date(2026,10,25))
        self.assertTrue(plan.candidate_fit(example("990","2026-10-26","2026-11-04"),[future],NOW))
        self.assertTrue(plan.candidate_fit(example("991","2026-11-16","2026-11-27"),[future],NOW))
        self.assertFalse(plan.candidate_fit(example("992","2026-11-01","2026-11-10"),[future],NOW))

class HousingDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{"THS_EARLIEST_START":"2026-10-25"})
        self.env.start()
        self.tmp=tempfile.TemporaryDirectory()
        self.db=pathlib.Path(self.tmp.name)/"a.sqlite3"
        self.conn=sqlite3.connect(self.db)
        controls.init_db(self.conn)
        self.conn.execute("""CREATE TABLE watch (
            assignment_id TEXT PRIMARY KEY,status TEXT,payload TEXT,
            last_checked TEXT,last_change TEXT,message_id INTEGER)""")
        for item in (example(),example("902","2026-11-01","2026-11-11")):
            self.conn.execute("INSERT INTO watch(assignment_id,status,payload) VALUES (?,?,?)",
                              (item["assignment_id"],"open",json.dumps(item)))
        # The four historical application rows must survive migration unchanged.
        self.conn.execute("INSERT INTO applications(assignment_id,applied_at) VALUES (?,?)",
                          ("901","2026-10-09T12:00:00Z"))
        self.conn.commit()
    def tearDown(self):
        self.conn.close();self.tmp.cleanup();self.env.stop()
    def test_migration_status_confirm_and_conflicting_second_booking(self):
        self.assertEqual(state.stage(self.conn,"901"),"applied")
        self.assertEqual(state.update(self.conn,"901","confirmed"),"confirmed")
        stays=state.confirmed(self.conn)
        self.assertEqual(len(stays),1)
        with self.assertRaises(ValueError):
            state.update(self.conn,"902","confirmed")
        self.assertEqual(len(state.confirmed(self.conn)),1)
        self.assertTrue(controls.toggle_application(self.conn,"901"))
        self.assertEqual(state.stage(self.conn,"901"),"confirmed")
        state.update(self.conn,"901","rejected")
        self.assertEqual(state.confirmed(self.conn),[])
    def test_commands_are_private_and_confirm_updates_plan(self):
        calls=[]
        def fake(t,m,args):
            calls.append((m,args))
            return {"message_id":100}
        msg={"message":{"chat":{"type":"private","id":123},
                         "from":{"id":123},"message_id":10,
                         "text":"/confirm 901"}}
        self.assertEqual(commands.handle_message(msg,"secret","123",api_func=fake,db_path=self.db),"command")
        self.assertEqual(state.stage(self.conn,"901"),"confirmed")
        self.assertIn("Підтверджено для мене",calls[-1][1]["text"])
        self.assertNotIn("План житла",calls[-1][1]["text"])
        bad={**msg,"message":{**msg["message"],"from":{"id":456}}}
        self.assertEqual(commands.handle_message(bad,"secret","123",api_func=fake,db_path=self.db),"ignored")
    def test_two_step_button_not_confirmed_until_explicit_yes(self):
        from unittest.mock import patch
        self.conn.execute("""INSERT INTO controls (assignment_id,album_message_id,control_message_id)
                             VALUES ('901',80,80)""")
        self.conn.commit()
        sent=[]
        def fake(t,method,args):
            sent.append(method)
            if method=="sendMessage":return {"message_id":81+sent.count("sendMessage")-1}
            return True
        with patch.object(controls,"DATA",pathlib.Path(self.tmp.name)):
            result=conf.prompt("901",80,"secret","123",self.db,api_func=fake)
            self.assertEqual(result,"confirmation_requested")
            self.assertIsNone(state.stage(self.conn,"902"))
            self.assertEqual(state.stage(self.conn,"901"),"applied")
            callback={"callback_query":{"id":"c1","data":"t4:y:901",
                       "from":{"id":123},
                       "message":{"chat":{"type":"private","id":123},"message_id":81}}}
            self.assertEqual(conf.reply(callback,"secret","123",api_func=fake,db_path=self.db),"confirmed")
            self.assertEqual(state.stage(self.conn,"901"),"confirmed")
    def test_report_mentions_bridges_and_backup(self):
        state.update(self.conn,"901","confirmed")
        with patch.object(report,"DATA",pathlib.Path(self.tmp.name)):
            body=report.plan_text(self.conn,NOW)
        self.assertIn("2 ночей",body)
        self.assertIn("2026-11-14",body)

if __name__=="__main__":unittest.main()
