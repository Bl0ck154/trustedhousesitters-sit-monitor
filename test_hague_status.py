import datetime as dt
import json
import pathlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import monitor
import telegram_upgrade as dispatcher

class HagueStatusRegressionTests(unittest.TestCase):
    def test_flapping_public_cache_never_announces_rejection_or_reopening(self):
        item={"assignment_id":"2124123","listing_id":"31333",
              "title":"Friendly cat looking for house sitter in The Hague!",
              "city":"Scheveningen","country":"Netherlands",
              "url":"https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/netherlands/south-holland/scheveningen/l/31333/",
              "start":"2026-10-25","end":"2026-11-02",
              "pets":{"cat":1},"status":"reviewing","application_count":5}
        with tempfile.TemporaryDirectory() as td:
            con=sqlite3.connect(pathlib.Path(td)/"test.sqlite3")
            dispatcher.db_init(con)
            initial=dt.datetime(2026,10,10,10,30,tzinfo=dt.timezone.utc)
            with patch.object(dispatcher,"clock",lambda:initial):
                dispatcher.watch_row(con,item,"reviewing",checked=False)
            notifications=[]
            def fake(t,m,params):
                notifications.append((m,params))
                return {"message_id":100+len(notifications)}
            observations=[("open",0),("reviewing",5),("open",2),
                          ("reviewing",5),("open",4),("reviewing",5)]
            with patch.object(dispatcher,"api",fake),patch.object(dispatcher.monitor,"save_detail",lambda x:None):
                for offset,(status,count) in enumerate(observations):
                    at=initial+dt.timedelta(minutes=2*(offset+1))
                    with patch.object(dispatcher,"clock",lambda d=at:d):
                        with patch.object(dispatcher.monitor,"validate_detail",
                                          lambda x,s=status,n=count:{**item,"status":s,"application_count":n}):
                            self.assertEqual(dispatcher.refresh_watch(con,"token","chat",force=True),(0,0))
            self.assertEqual(notifications,[])
            self.assertEqual(con.execute("SELECT status FROM watch").fetchone()[0],"reviewing")
            self.assertEqual(con.execute("SELECT count(*) FROM watch_transitions").fetchone()[0],0)
            # Now verify a genuinely sustained reopening, with two separated
            # independent observations. No fluctuating public count is sent.
            with patch.object(dispatcher,"api",fake),patch.object(dispatcher.monitor,"save_detail",lambda x:None):
                for j in range(2):
                    at=initial+dt.timedelta(minutes=14+j*2)
                    with patch.object(dispatcher,"clock",lambda d=at:d):
                        with patch.object(dispatcher.monitor,"validate_detail",
                                          lambda x:{**item,"status":"open","application_count":0}):
                            expected=(0,0) if j==0 else (1,0)
                            self.assertEqual(dispatcher.refresh_watch(con,"token","chat",force=True),expected)
            self.assertEqual(len(notifications),1)
            message=notifications[0][1]["text"]
            self.assertIn("знову відкриті",message)
            self.assertNotIn("Заявок: 0",message)
            self.assertIn("не означає",message)
            self.assertEqual(con.execute("SELECT status FROM watch").fetchone()[0],"open")
            con.close()

    def test_hague_conflicting_assignment_fields_are_unknown(self):
        candidate={"assignment_id":"2124123","listing_id":"31333",
                   "url":"https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/netherlands/south-holland/scheveningen/l/31333/"}
        row={"id":"2124123","startDate":"2026-10-25","endDate":"2026-11-02",
             "isConfirmed":False,"applicationsCount":0}
        item={"id":"31333","title":"Cat sit","location":{"name":"Scheveningen","countryName":"Netherlands"},
              "animals":[],"pets":[],"photos":[],
              "publishedAssignment":[{**row,"isReviewing":False,"canApply":True}],
              "openAssignments":[{**row,"isReviewing":True,"canApply":False}]}
        state={"search":{"listing":{"31333":item}}}
        with patch.object(monitor,"get_state",return_value=state),patch.object(monitor,"get_confirmed",return_value=[]):
            current=monitor.validate_detail(candidate)
        self.assertEqual(current["status"],"unknown")

if __name__=="__main__":unittest.main()
