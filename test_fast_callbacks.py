import copy
import json
import threading
import time
import unittest
import telegram_card as card
import telegram_fast_callbacks as fast

def item(n=14):
    return {
      "assignment_id":"2123228","title":"Test 14 photo sit",
      "url":"https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/austria/salzburg/hallein/l/297534/",
      "city":"Hallein","country":"Austria","start":"2026-10-26","end":"2026-11-05","nights":10,
      "pets":{"cat":2},"transport_accessible":True,"internet":"highSpeed",
      "coordinates":{"lat":47.68,"lon":13.09},
      "photo_urls":[f"https://res.cloudinary.com/trustedhousesitters/image/upload/house/p_{i}.jpg" for i in range(n)]
    }

def cb(action="t2:p:2123228:0:0",uid=1,mid=77):
 return {"update_id":uid,"callback_query":{"id":str(uid),"data":action,
     "message":{"chat":{"type":"private","id":777},"message_id":mid},"from":{"id":777}}}

class FastTests(unittest.TestCase):
 def test_file_id_cache_reuses_telegram_photo(self):
    import tempfile, pathlib
    from unittest.mock import patch
    import telegram_media_cache as cache
    with tempfile.TemporaryDirectory() as td:
        with patch.object(cache, "DB", pathlib.Path(td)/"media.sqlite3"):
            url="https://res.cloudinary.com/trustedhousesitters/image/upload/house/photo.jpg"
            self.assertEqual(cache.resolve(url),url)
            self.assertTrue(cache.remember(url,{"photo":[{"file_id":"small"},{"file_id":"large-id"}]}))
            self.assertEqual(cache.resolve(url),"large-id")

 def test_many_photos_and_no_url_buttons(self):
    x=item(26)
    markup=card.controls(x,photo=11)
    self.assertIn("Усі фото (26)",markup)
    self.assertIn("t3:g:2123228",markup)
    self.assertIn("t3:d:2123228",markup)
    self.assertNotIn("google.com",markup)
    self.assertNotIn("trustedhousesitters.com",markup)
    self.assertNotIn("t2:f:",markup)
    self.assertEqual(card.parse("t3:g:2123228"),("g","2123228",None,0))
    self.assertEqual(card.cover(x,25),x["photo_urls"][25])
    self.assertIn("google.com",card.caption(x))
    self.assertIn("trustedhousesitters.com",card.caption(x))
 def test_rapid_three_duplicate_taps_only_one_edit(self):
    actions=[]
    ack=[]
    def fake_api(tok,method,data=None):
        if method=="answerCallbackQuery":ack.append(method)
        return True
    def handler(event,tok,chat,api_func):
        actions.append(event["callback_query"]["data"])
        time.sleep(0.14)
        return "expanded"
    d=fast.FastDispatcher("fake","777",api_func=fake_api,callback_handler=handler)
    for i in range(3):
        u=cb(uid=i+1)
        d.ack(u);d.enqueue(u)
    d.close()
    self.assertEqual(len(ack),3)
    self.assertEqual(actions,["t2:p:2123228:0:0"])
 def test_two_messages_not_head_of_line_blocked(self):
    order=[]
    lock=threading.Lock()
    def handler(event,tok,chat,api_func):
        mid=event["callback_query"]["message"]["message_id"]
        if mid==77:time.sleep(.23)
        with lock:order.append(mid)
        return "expanded"
    d=fast.FastDispatcher("fake","777",api_func=lambda *x:True,callback_handler=handler)
    d.enqueue(cb(uid=1,mid=77))
    d.enqueue(cb(uid=2,mid=78))
    d.close()
    self.assertEqual(order[0],78)

if __name__=="__main__":unittest.main()
