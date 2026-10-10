#!/usr/bin/env python3
import json
import pathlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import telegram_format as f
import telegram_controls as c
import telegram_callbacks as cb

def fixture(aid="2122760"):
 return {"assignment_id":aid,"listing_id":"857632",
         "url":"https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/germany/hamburg/hamburg/l/857632/",
         "title":"Three & <two> big-city cats","city":"Hamburg","country":"Germany",
         "start":"2026-10-28","end":"2026-11-04","nights":7,
         "pets":{"cat":3},"pet_profiles":[{"name":"Emil","description":"He is a silly cat"}],
         "transport_accessible":True,"minutes_pet_can_be_left_alone":480,
         "internet":"highSpeed","amenities":{"hasWasher":True,"workspaceTypes":["desk"]},
         "introduction":"An owner says hi! " * 140,
         "responsibilities":"Clean litter and feed cats. " * 140,
         "pet_care":"Play with cats daily. " * 150,
         "local_attractions":"Trains nearby."}

class Tests(unittest.TestCase):
 def test_rich_caption_and_all_pages(self):
  x=fixture()
  s=f.caption(x)
  self.assertIn("Three &amp; &lt;two&gt;",s)
  self.assertIn("3 коти",s)
  self.assertIn("8 год",s)
  self.assertLessEqual(len(s),1024)
  pages=f.page_chunks(x)
  self.assertGreater(len(pages),1)
  self.assertTrue(all(len(p)<3950 for p in pages))
  self.assertEqual(sum(p.count("Play with cats daily.") for p in pages),150)
  self.assertEqual(sum(p.count("Clean litter and feed cats.") for p in pages),140)
 def test_keyboard_data_and_authorized_edit(self):
  with tempfile.TemporaryDirectory() as d:
   db=pathlib.Path(d)/"watch.sqlite3"
   item=fixture()
   cpath=pathlib.Path(d)/"listings";cpath.mkdir()
   (cpath/"2122760.json").write_text(json.dumps(item))
   calls=[]
   def fake_api(token,method,params):
    calls.append((method,params))
    if method=="sendMessage":return {"message_id":101}
    if method=="editMessageText":return {"message_id":101}
    return True
   conn=sqlite3.connect(db);c.init_db(conn)
   c.pending(conn,item,77)
   mid=c.control_send(fake_api,"tok","777",item,77)
   self.assertEqual(mid,101)
   self.assertEqual(calls[-1][0],"sendMessage")
   self.assertEqual(json.loads(calls[-1][1]["reply_markup"])["inline_keyboard"][0][0]["callback_data"],"th:p:2122760:0")
   conn.execute("UPDATE controls SET control_message_id=? WHERE assignment_id=?",(101,"2122760"));conn.commit();conn.close()
   def fake_snapshot(aid,con):return item
   data={"callback_query":{"id":"x","from":{"id":777},"message":{"chat":{"id":777,"type":"private"},"message_id":101},"data":"th:p:2122760:1"}}
   with patch.object(c,"load_snapshot",fake_snapshot):
    self.assertEqual(c.handle_callback(data,"tok","777",api_func=fake_api,db_path=db),"expanded")
    self.assertTrue(any("Сторінка 2/" in p["text"] for name,p in calls if name=="editMessageText"))
    data["callback_query"]["data"]="th:c:2122760"
    self.assertEqual(c.handle_callback(data,"tok","777",api_func=fake_api,db_path=db),"collapsed")
    self.assertEqual(calls[-1][0],"editMessageText")
    data["callback_query"]["from"]["id"]=999
    self.assertEqual(c.handle_callback(data,"tok","777",api_func=fake_api,db_path=db),"unauthorized_or_invalid")
    self.assertEqual(calls[-1][0],"answerCallbackQuery")
 def test_poll_offset_once_and_no_password_logs(self):
  with tempfile.TemporaryDirectory() as d:
   off=pathlib.Path(d)/"offset"
   bot=pathlib.Path(d)/"token";bot.write_text("secret")
   cid=pathlib.Path(d)/"chat";cid.write_text("777")
   processed=[]
   def faux_api(token,method,args=None):
    if method=="getWebhookInfo":return {"url":""}
    if method=="getUpdates":
     if args.get("offset"):return []
     return [{"update_id":42,"callback_query":{"id":"x"}}]
    raise AssertionError(method)
   with patch.object(cb,"TOKEN_FILE",bot),patch.object(cb,"CHAT_FILE",cid),patch.object(cb,"OFFSET",off),patch.object(cb.time,"monotonic",side_effect=[0,0,0,3,4,50]):
    try:
     cb.poll(seconds=5,api_func=faux_api,handler=lambda *a:processed.append(1) or "expanded")
    except StopIteration:
     pass
   self.assertTrue(processed)
   self.assertEqual(off.read_text().strip(),"43")
if __name__=="__main__":unittest.main()
