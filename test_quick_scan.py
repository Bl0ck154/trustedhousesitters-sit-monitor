import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import monitor

class QuickLaneTests(unittest.TestCase):
    def test_quick_lane_only_open_and_no_false_incomplete_alert(self):
        calls=[]
        def state(url):
            calls.append(url)
            return {"search":{"listings":{"search-listings-results":{
                "total":500,"results":["100"]
            }},"listing":{"100":{
                "id":100,"title":"Cats in Berlin",
                "location":{"countryName":"Germany","name":"Berlin"},
                "openAssignments":[{"id":555,"startDate":"2026-11-01","endDate":"2026-11-12"}],
                "animals":[{"slug":"cat","count":1}],
                "homeFeatures":["isAccessibleByPublicTransport"],
                "wifiAvailable":"highSpeed"
            }}}}
        with patch.object(monitor,"get_state",side_effect=state),patch.object(monitor,"active_window",return_value=(dt.date(2026,10,25),dt.date(2026,11,10))):
            found,totals,pages,errors=monitor.collect(
                end_date="2026-12-30",max_pages=2,delay=0,
                include_reviewing=False,require_complete=False)
        self.assertEqual(len(calls),2)
        self.assertEqual(pages,2)
        self.assertEqual(totals,{"open":500})
        self.assertFalse(errors)
        self.assertIn("555",found)

    def test_partial_fast_scan_never_marks_unseen_sits_closed(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"scan.sqlite3"
            previous={
                "assignment_id":"999","status":"open",
                "eligible_alert":True,"verified_by_detail":True
            }
            monitor.storage(db,[previous],True)
            monitor.storage(db,[],True)
            with sqlite3.connect(db) as c:
                state=c.execute("SELECT status FROM records WHERE assignment_id='999'").fetchone()
            self.assertEqual(state,("open",))
if __name__=="__main__":
    unittest.main()
