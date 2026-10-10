import json
import pathlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import telegram_controls as c
import telegram_quality as q
import telegram_commands as cmd
import telegram_format as fmt

def fixture():
 return {"assignment_id":"2123228","listing_id":"297534",
         "title":"Example host's lovely <cats>",
         "url":"https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/austria/salzburg/hallein/l/297534/",
         "city":"Hallein","country":"Austria","start":"2026-10-26","end":"2026-11-05","nights":10,
         "pets":{"cat":2},"cats":2,"transport_accessible":True,"internet":"highSpeed",
         "coordinates":{"lat":47.68,"lon":13.09,"precision":"locality"},
         "pet_care":"We feed him 3-4 times a day. Give medication each evening.",
         "responsibilities":"No car required; there is public transport.","score":80}

class FeatureTests(unittest.TestCase):
 def test_real_flags_and_priority(self):
  x=fixture();d=q.priority(x)
  self.assertTrue(any("годування" in e["label"] for e in d["flags"]))
  self.assertTrue(any("ліки" in e["label"] for e in d["flags"]))
  self.assertFalse(any("авто" in e["label"] for e in d["flags"]))
  self.assertIn("⚠️",fmt.caption(x))
  self.assertTrue(any("Важливі умови" in title for title,body in fmt.sections(x)))
 def test_application_toggle_and_list(self):
  with tempfile.TemporaryDirectory() as t:
   db=pathlib.Path(t)/"db.sqlite3"
   cx=sqlite3.connect(db);c.init_db(cx)
   item=fixture()
   cx.execute("CREATE TABLE watch (assignment_id TEXT PRIMARY KEY,status TEXT,payload TEXT)")
   cx.execute("INSERT INTO watch VALUES (?,?,?)",(item["assignment_id"],"reviewing",json.dumps(item)))
   self.assertTrue(c.toggle_application(cx,"2123228"))
   self.assertTrue(c.is_applied("2123228",cx))
   self.assertIn("Hallein",cmd.app_list(cx))
   self.assertIn("reviewing",cmd.app_list(cx))
   self.assertFalse(c.toggle_application(cx,"2123228"))
   self.assertFalse(c.is_applied("2123228",cx))
   cx.close()
 def test_buttons_application_and_native_venue(self):
  with tempfile.TemporaryDirectory() as t:
   db=pathlib.Path(t)/"db.sqlite3";cx=sqlite3.connect(db);c.init_db(cx)
   item=fixture();c.pending(cx,item,20)
   cx.execute("UPDATE controls SET control_message_id=21 WHERE assignment_id='2123228'");cx.commit();cx.close()
   calls=[]
   def fake(token,method,payload):
    calls.append((method,payload))
    if method=="sendVenue":return {"message_id":42}
    return True
   event={"callback_query":{"id":"callback","from":{"id":777},"message":{"chat":{"id":777,"type":"private"},"message_id":21},"data":"th:a:2123228:c"}}
   with patch.object(c,"load_snapshot",lambda aid,conn:item):
    r=c.handle_callback(event,"tok","777",api_func=fake,db_path=db)
    self.assertEqual(r,"application_marked")
    self.assertEqual(calls[0][0],"answerCallbackQuery")
    self.assertIn("✅ Заявку подано",calls[-1][1]["reply_markup"])
    event["callback_query"]["data"]="th:m:2123228"
    self.assertEqual(c.handle_callback(event,"tok","777",api_func=fake,db_path=db),"map_sent")
    v=[payload for name,payload in calls if name=="sendVenue"][0]
    self.assertEqual(v["latitude"],47.68)
    self.assertIn("не точна адреса",v["address"])
 def test_foreign_user_cannot_mark_or_map(self):
  with tempfile.TemporaryDirectory() as t:
   event={"callback_query":{"id":"xx","from":{"id":778},"message":{"chat":{"id":777,"type":"private"},"message_id":21},"data":"th:a:2123228:c"}}
   calls=[]
   r=c.handle_callback(event,"tok","777",api_func=lambda token,method,fields:calls.append(method) or True,db_path=pathlib.Path(t)/"db.sqlite3")
   self.assertEqual(r,"unauthorized_or_invalid")
   self.assertEqual(calls,["answerCallbackQuery"])
 def test_application_command_private_only(self):
  with tempfile.TemporaryDirectory() as t:
   db=pathlib.Path(t)/"db.sqlite3";cx=sqlite3.connect(db);c.init_db(cx)
   item=fixture()
   cx.execute("CREATE TABLE watch (assignment_id TEXT PRIMARY KEY,status TEXT,payload TEXT)")
   cx.execute("INSERT INTO watch VALUES (?,?,?)",("2123228","open",json.dumps(item)))
   c.toggle_application(cx,"2123228");cx.close()
   msg={"message":{"chat":{"id":777,"type":"private"},"from":{"id":777},"message_id":19,"text":"/applications"}}
   calls=[]
   r=cmd.handle_message(msg,"tok","777",api_func=lambda tok,m,f:calls.append((m,f)) or {"message_id":100},db_path=db)
   self.assertEqual(r,"command")
   self.assertIn("Hallein",calls[0][1]["text"])
   msg["message"]["from"]["id"]=778
   self.assertEqual(cmd.handle_message(msg,"tok","777",api_func=lambda *a:None,db_path=db),"ignored")
if __name__=="__main__":unittest.main()
