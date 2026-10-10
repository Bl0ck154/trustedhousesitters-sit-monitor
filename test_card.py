import json
import pathlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import telegram_card as card
import telegram_card_controller as controller
import telegram_controls as ctrl

def item():
 return {
  "assignment_id":"2123228","title":"Example host's <cats> & home",
  "url":"https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/austria/salzburg/hallein/l/297534/",
  "city":"Hallein","country":"Austria","start":"2026-10-26","end":"2026-11-05","nights":10,
  "pets":{"cat":2},"cats":2,"transport_accessible":True,"internet":"highSpeed",
  "coordinates":{"lat":47.6,"lon":13.1},
  "photo_urls":["https://res.cloudinary.com/trustedhousesitters/image/upload/a.jpg",
                "https://res.cloudinary.com/trustedhousesitters/image/upload/b.jpg",
                "https://res.cloudinary.com/trustedhousesitters/image/upload/c.jpg"],
  "pet_care":"Feed kitten 3-4 times a day. "+"Pet care detail "*90,
  "introduction":"Lovely home. "*190,
  "responsibilities":"Water plants. "*100
 }
class CardTests(unittest.TestCase):
 def test_caption_bold_geo_and_pages(self):
  x=item()
  caption=card.caption(x)
  self.assertIn('<b>Hallein, Austria</b>',caption)
  self.assertIn('maps/search',caption)
  self.assertIn('Example host',caption)
  self.assertLess(len(caption),1024)
  pages=card.detail_pages(x)
  self.assertGreater(len(pages),1)
  for i in range(len(pages)):self.assertLessEqual(len(card.caption(x,'full',i)),1024)
  kb=card.controls(x)
  self.assertIn('t3:d:2123228',kb)
  self.assertNotIn('google.com/maps',kb)
  self.assertNotIn('th:m:',kb)
 def test_photo_navigation_only_one_message(self):
  with tempfile.TemporaryDirectory() as t:
   db=pathlib.Path(t)/"db"
   con=sqlite3.connect(db);ctrl.init_db(con);ctrl.pending(con,item(),77,attached=True);con.close()
   calls=[]
   def fake(tok,method,params):
    calls.append((method,params))
    return True
   update={"callback_query":{"id":"aaa","message":{"chat":{"id":777,"type":"private"},"message_id":77},
                             "from":{"id":777},"data":"t2:f:2123228:s:1"}}
   with patch.object(ctrl,"load_snapshot",lambda aid,db:item()):
    res=controller.handle(update,'secret','777',api_func=fake,db_path=db)
    self.assertEqual(res,'photo_changed')
    self.assertEqual([a for a,_ in calls],['answerCallbackQuery','editMessageMedia'])
    self.assertEqual(json.loads(calls[1][1]["media"])["media"],card.cover(item(),1))
    calls.clear()
    update["callback_query"]["data"]="t2:p:2123228:1:1"
    self.assertEqual(controller.handle(update,'secret','777',api_func=fake,db_path=db),'expanded')
    self.assertEqual([a for a,_ in calls],['answerCallbackQuery','editMessageCaption'])
    calls.clear()
    update["callback_query"]["data"]="t2:c:2123228:1"
    self.assertEqual(controller.handle(update,'secret','777',api_func=fake,db_path=db),'collapsed')
    self.assertEqual([a for a,_ in calls],['answerCallbackQuery','editMessageCaption'])
 def test_invalid_chat_no_mutation(self):
  event={"callback_query":{"id":"x","from":{"id":999},"message":{"chat":{"id":777,"type":"private"},"message_id":77},
                           "data":"t2:a:2123228:s:0"}}
  called=[]
  r=controller.handle(event,'tok','777',api_func=lambda a,b,c:called.append(b) or True)
  self.assertEqual(r,'unauthorized_or_invalid')
  self.assertEqual(called,['answerCallbackQuery'])
if __name__=="__main__":unittest.main()
