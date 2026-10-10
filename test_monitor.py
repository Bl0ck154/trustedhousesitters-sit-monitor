import importlib.util
import pathlib
import tempfile
import unittest

PATH = pathlib.Path(__file__).with_name("monitor.py")
spec = importlib.util.spec_from_file_location("monitor", PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def item(assignment=None, features=None):
    a = assignment or {"id": "100", "startDate": "2026-10-28", "endDate": "2026-11-10", "isConfirmed": False, "isReviewing": False}
    return {"id": "55", "title": "Cat apartment", "location": {"name": "Hamburg", "countryName": "Germany"},
            "animals": [{"slug": "cat", "count": 2}], "publishedAssignment": [a],
            "openAssignments": [a], "homeFeatures": features or ["apartment","highSpeed","isAccessibleByPublicTransport"],
            "wifiAvailable": "highSpeed"}

class MonitorTests(unittest.TestCase):
    def test_open_vs_reviewing_and_confirmed(self):
        a = item()["openAssignments"][0]
        self.assertEqual(m.classify(a, item()), "open")
        self.assertEqual(m.classify({**a,"isReviewing":True}, item()), "reviewing")
        self.assertEqual(m.classify({**a,"isConfirmed":True}, item()), "confirmed")

    def test_practical_house_sits(self):
        i = item()
        v = m.fingerprint(i, i["openAssignments"][0], "open")
        self.assertTrue(v["eligible_alert"])
        self.assertTrue(v["transport_accessible"])
        i["homeFeatures"] = ["isNotAccessibleByPublicTransport"]
        v = m.fingerprint(i, i["openAssignments"][0], "open")
        self.assertFalse(v["eligible_alert"])
        self.assertTrue(v["transit_warning"])
        i = item()
        i["animals"].append({"slug":"poultry","count":6})
        self.assertFalse(m.fingerprint(i,i["openAssignments"][0],"open")["eligible_alert"])

    def test_window_and_country(self):
        from unittest.mock import patch
        from datetime import date
        i = item()
        a = i["openAssignments"][0]
        with patch.object(m, "active_window", return_value=(date(2026,10,25),date(2026,11,8))):
            self.assertTrue(m.relevant(i,a))
            self.assertFalse(m.relevant(i,{**a,"startDate":"2026-11-10"}))
            i["location"]["countryName"] = "United Kingdom"
            self.assertFalse(m.relevant(i,a))

    def test_dedup_and_reopening(self):
        i = item()
        a = i["openAssignments"][0]
        open_row = m.fingerprint(i,a,"open")
        open_row["verified_by_detail"] = True
        with tempfile.TemporaryDirectory() as t:
            db = pathlib.Path(t)/"history.sqlite3"
            self.assertEqual(len(m.storage(db,[open_row],True)),1)
            self.assertEqual(len(m.storage(db,[open_row],True)),0)
            self.assertEqual(len(m.storage(db,[{**open_row,"status":"reviewing"}],True)),0)
            self.assertEqual(len(m.storage(db,[open_row],True)),1)

if __name__ == "__main__":
    unittest.main()
