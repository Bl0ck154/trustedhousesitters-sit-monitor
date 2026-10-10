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
        self.assertEqual(v["pet_tier"],"A")
        self.assertFalse(v["eligible_alert"]) # summary alone is not verified
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

    def test_unknown_transit_wifi_must_not_exclude_cats(self):
        # The search page often omits these fields even for valid cat sits.
        cats={"assignment_id":"201","status":"open","pets":{"cat":2},
              "internet":None,"transport_accessible":False,
              "transit_warning":False,"eligible_alert":False}
        cats.update({"start":"2026-10-28","end":"2026-11-08"})
        self.assertTrue(m.prefilter_detail(cats))
        self.assertEqual(m.detail_candidates([cats],10),[cats])
        self.assertTrue(m.prefilter_detail({**cats,"pets":{"cat":2,"dog":1}})) # reserve tier B
        self.assertFalse(m.prefilter_detail({**cats,"pets":{"cat":1,"horse":1}}))
        self.assertFalse(m.prefilter_detail({**cats,"transit_warning":True}))
        self.assertFalse(m.prefilter_detail({**cats,"status":"reviewing"}))

    def test_only_matching_open_sits_get_detail_fetch(self):
        from unittest.mock import patch
        import sys, json
        eligible={"assignment_id":"101","listing_id":"21","status":"open",
                  "eligible_alert":True,"start":"2026-10-28","end":"2026-11-06",
                  "score":30,"country":"Germany","city":"Hamburg","pets":{"cat":2},"url":"https://example.test/21"}
        dog={"assignment_id":"102","listing_id":"22","status":"open",
             "eligible_alert":False,"start":"2026-10-28","end":"2026-11-06",
             "score":1,"country":"Germany","city":"Berlin","pets":{"dog":1},"url":"https://example.test/22"}
        mixed={"assignment_id":"103","listing_id":"23","status":"open",
               "eligible_alert":False,"start":"2026-10-29","end":"2026-11-07",
               "score":2,"country":"France","city":"Lyon","pets":{"cat":1,"dog":1},"url":"https://example.test/23"}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(m,"OUT",pathlib.Path(tmp)),patch.object(m,"collect",return_value=(
                {row["assignment_id"]:row for row in (eligible,dog,mixed)},
                {"open":3},1,[])),patch.object(m,"validate_detail",side_effect=lambda row:{
                    **row,"verified_by_detail":True,"photo_urls":[]}),patch.object(sys,"argv",["monitor.py","--quick"]):
                self.assertEqual(m.main(),0)
                result=json.loads((pathlib.Path(tmp)/"quick-latest.json").read_text())
        self.assertEqual(result["open_detail_candidates"],3) # dogs held as backup
        self.assertEqual(result["open_details_skipped_by_filter"],0)
        self.assertEqual(result["verified"],3)
        self.assertEqual(len(result["results"]),3)
        self.assertTrue(all(row.get("verified_by_detail") for row in result["results"]))

    def test_open_becomes_eligible_after_prior_summary_only(self):
        i=item()
        a=i["openAssignments"][0]
        matched=m.fingerprint(i,a,"open")
        matched["verified_by_detail"]=True
        matched["eligible_alert"]=True
        summary={**matched,"eligible_alert":False,"verified_by_detail":False}
        with tempfile.TemporaryDirectory() as t:
            db=pathlib.Path(t)/"history.sqlite3"
            self.assertFalse(m.storage(db,[summary],True))
            self.assertEqual(len(m.storage(db,[matched],True)),1)
            self.assertEqual(len(m.storage(db,[matched],True)),0)

    def test_urgent_dog_reserve_alerts_are_bounded_per_day(self):
        from unittest.mock import patch
        from datetime import date
        dogs=[]
        for n in range(5):
            dogs.append({"assignment_id":str(1200+n),"status":"open",
                         "start":"2026-10-28","end":"2026-11-08","pets":{"dog":1},
                         "country":"Germany","city":"Berlin","score":50,
                         "verified_by_detail":True,"eligible_alert":True})
        with tempfile.TemporaryDirectory() as td:
            db=pathlib.Path(td)/"test.sqlite3"
            with patch.object(m.plan,"today",return_value=date(2026,10,16)):
                first=m.storage(db,[x.copy() for x in dogs],True)
                self.assertEqual(len(first),3)
                second=m.storage(db,[x.copy() for x in dogs],True)
                self.assertEqual(len(second),0)
            with patch.object(m.plan,"today",return_value=date(2026,10,17)):
                remaining=m.storage(db,[x.copy() for x in dogs],True)
                self.assertEqual(len(remaining),2)

    def test_partial_unverified_summary_never_requeues_existing_alert(self):
        i=item()
        row=m.fingerprint(i,i["openAssignments"][0],"open")
        verified={**row,"verified_by_detail":True,"eligible_alert":True}
        summary={**row,"verified_by_detail":False,"eligible_alert":False}
        with tempfile.TemporaryDirectory() as t:
            db=pathlib.Path(t)/"history.sqlite3"
            self.assertEqual(len(m.storage(db,[verified],True)),1)
            self.assertEqual(len(m.storage(db,[summary],True)),0)
            self.assertEqual(len(m.storage(db,[verified],True)),0)

    def test_dedup_and_reopening(self):
        i = item()
        a = i["openAssignments"][0]
        open_row = m.fingerprint(i,a,"open")
        open_row["verified_by_detail"] = True
        open_row["eligible_alert"] = True
        with tempfile.TemporaryDirectory() as t:
            db = pathlib.Path(t)/"history.sqlite3"
            self.assertEqual(len(m.storage(db,[open_row],True)),1)
            self.assertEqual(len(m.storage(db,[open_row],True)),0)
            self.assertEqual(len(m.storage(db,[{**open_row,"status":"reviewing"}],True)),0)
            self.assertEqual(len(m.storage(db,[open_row],True)),1)

if __name__ == "__main__":
    unittest.main()
