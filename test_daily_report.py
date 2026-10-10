import datetime as dt
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import housing_reporting as report
import telegram_daily as daily

def item(aid,pets):
    return {"assignment_id":aid,"title":"Sample stay","status":"open",
            "city":"Berlin","country":"Germany","start":"2026-10-28",
            "end":"2026-11-08","nights":11,"pets":pets,
            "url":"https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/germany/berlin/berlin/l/123/",
            "internet":"highSpeed","transport_accessible":True,
            "verified_by_detail":False}

class DailyReportingTests(unittest.TestCase):
    def test_options_keep_backup_without_farm_work(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td)
            (root/"latest.json").write_text(json.dumps({"results":[
                item("101",{"cat":2}),item("102",{"dog":1}),
                item("103",{"rabbit":1}),item("104",{"horse":2})]}))
            with patch.dict(os.environ,{"THS_EARLIEST_START":"2026-10-25"}),patch.object(report,"DATA",root):
                lines=report.candidates([],dt.date(2026,10,10))
            self.assertEqual(len(lines),3)
            self.assertEqual(sum("dog" in x["pets"] for x in lines),1)
            self.assertTrue(all(x["assignment_id"]!="104" for x in lines))

    def test_daily_once_local_0830(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td)
            token=root/"bot-token"
            chat=root/"chat-id"
            token.write_text("FAKE_TOKEN")
            chat.write_text("123")
            with patch.object(daily,"TOKEN_FILE",token),patch.object(daily,"CHAT_FILE",chat):
                with patch.object(report,"DATA",root):
                    with patch.dict(os.environ,{"THS_EARLIEST_START":"2026-10-25"}):
                        now=dt.datetime(2026,10,11,8,30,tzinfo=ZoneInfo("Europe/Vilnius"))
                        calls=[]
                        def fake(token,method,fields):
                            calls.append((method,fields))
                            return {"message_id":100}
                        result=daily.run(now=now,api_func=fake,db_path=root/"test.sqlite3")
                        again=daily.run(now=now,api_func=fake,db_path=root/"test.sqlite3")
                        too_late=daily.run(now=now.replace(hour=9),api_func=fake,db_path=root/"test.sqlite3")
                        self.assertEqual((result,again,too_late),
                                         ("sent","already_sent","outside_local_morning_window"))
                        self.assertEqual([method for method,_ in calls],["sendMessage"])
                        self.assertIn("2026-10-11",calls[0][1]["text"])

if __name__=="__main__":unittest.main()
