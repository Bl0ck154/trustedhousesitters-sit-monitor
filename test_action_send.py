import json
import pathlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import telegram_card as card
import telegram_controls as controls
import telegram_action_send as actions
import telegram_card_controller as controller

def listing(n=27):
 return {
   "assignment_id":"2122760","listing_id":"857632","title":"Three & < friendly cats",
   "url":"https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/germany/hamburg/hamburg/l/857632/",
   "city":"Hamburg","country":"Germany","start":"2026-10-28","end":"2026-11-04","nights":7,
   "pets":{"cat":3},"internet":"highSpeed","transport_accessible":True,
   "pet_care":"Feed each cat as instructed. "+"Always fresh water. "*60,
   "introduction":"Owners' instructions. "+"Host introduction. "*70,
   "responsibilities":"Clean litterboxes twice daily. "*43,
   "local_attractions":"You are located near train services.",
   "coordinates":{"lat":53.5,"lon":10.0},
   "photo_urls":["https://res.cloudinary.com/trustedhousesitters/image/upload/v1/photo_%s.jpg"%i for i in range(n)],
 }
def click(action="t3:d:2122760"):
 return {"callback_query":{"id":"test-id","data":action,
    "from":{"id":777},"message":{"chat":{"id":777,"type":"private"},"message_id":88}}}
class ActionTests(unittest.TestCase):
 def test_simple_keyboard_no_photo_navigation_or_duplicate_links(self):
  x=listing()
  k=card.controls(x)
  self.assertIn("t3:d:2122760",k)
  self.assertIn("t3:g:2122760",k)
  self.assertIn("27",k)
  self.assertNotIn("t2:f:",k)
  self.assertNotIn("google.com",k)
  self.assertNotIn("trustedhousesitters.com",k)
  self.assertEqual(card.parse("t3:g:2122760"),("g","2122760",None,0))
 def test_complete_description_message_sections(self):
  x=listing()
  messages=actions.full_description(x)
  self.assertTrue(messages)
  self.assertTrue(all(len(msg)<4096 for msg in messages))
  text="\n".join(messages)
  for must in ["Обов'язки","Догляд за тваринами","Про власника","Район","fresh water","train services"]:
   self.assertIn(must,text)
  self.assertIn("&lt; friendly cats",text)
  out=[]
  def mock(token,method,fields):
   out.append((method,fields))
   return {"message_id":len(out)+200}
  ids=actions.send_description("secret","777",x,reply_to=88,api_func=mock)
  self.assertEqual(len(ids),len(messages))
  self.assertTrue(all(method=="sendMessage" and field["parse_mode"]=="HTML"
                      and field["reply_to_message_id"]=="88" for method,field in out))
 def test_gallery_27_in_3_native_albums(self):
  x=listing(27)
  calls=[]
  def fake_api(token,method,fields):
   calls.append((method,json.loads(fields["media"])))
   return [{"message_id":start+1} for start in range(len(calls[-1][1]))]
  with patch.object(actions.cache,"resolve",lambda url:"known_file_id_"+url.rsplit("/",1)[-1]):
   with patch.object(actions.cache,"remember",lambda url,record: True):
    mids=actions.send_gallery("secret","777",x,reply_to=88,api_func=fake_api)
  self.assertEqual(len(mids),27)
  self.assertEqual([len(m) for method,m in calls],[10,10,7])
  self.assertEqual([method for method,m in calls],["sendMediaGroup"]*3)
  self.assertTrue(all(str(z["media"]).startswith("known_file_id") for _,m in calls for z in m))
 def test_button_sends_description_separately_dedup(self):
  x=listing(4)
  with tempfile.TemporaryDirectory() as td:
   db=pathlib.Path(td)/"db.sqlite"
   with sqlite3.connect(db) as con:
    controls.init_db(con)
    controls.pending(con,x,88,attached=True)
   methods=[]
   def fake(token,method,fields):
    methods.append(method)
    if method=="sendMessage":return {"message_id":100+len(methods)}
    return True
   with patch.object(controls,"load_snapshot",lambda aid,conn:x):
    result=controller.handle(click(),"token","777",api_func=fake,db_path=db)
    self.assertTrue(result.startswith("description_sent_"))
    self.assertNotIn("editMessageCaption",methods)
    self.assertNotIn("editMessageMedia",methods)
    count=len(methods)
    result2=controller.handle(click(),"token","777",api_func=fake,db_path=db)
    self.assertEqual(result2,"already_requested")
    self.assertEqual(methods[count:],["answerCallbackQuery"])
    with sqlite3.connect(db) as con:
     self.assertEqual(con.execute("SELECT state FROM button_sends").fetchone()[0],"sent")
 def test_unauthorized_cannot_trigger_new_messages(self):
  event=click()
  event["callback_query"]["from"]["id"]=999
  recorded=[]
  result=controller.handle(event,"tok","777",api_func=lambda token,method,params: recorded.append(method) or True)
  self.assertEqual(result,"unauthorized_or_invalid")
  self.assertEqual(recorded,["answerCallbackQuery"])
if __name__=="__main__":unittest.main()
