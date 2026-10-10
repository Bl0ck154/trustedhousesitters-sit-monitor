import unittest,tempfile,sqlite3,pathlib
from unittest.mock import patch
import telegram_card as card
import telegram_controls as ctrl
import telegram_card_controller as controller
import housing_preferences as prefs
import monitor

ITEM={"assignment_id":"901","status":"open","title":"Listing","photo_urls":[]}
def callback(data):
    return {"callback_query":{"id":"x","data":data,"from":{"id":123},
       "message":{"chat":{"type":"private","id":123},"message_id":77}}}
class QuickTests(unittest.TestCase):
    def test_home_images_exclude_pet_images(self):
        house={"publicId":"remote_media/media/photo/a/home.jpeg"}
        pet={"publicId":"remote_media/media/photo/b/pet.jpeg"}
        house={"publicId":"remote_media/media/photo/a/abcdef0123456789"}
        out=monitor.enrich_detail({"assignment_id":"901"},
            {"photos":[house,pet],"pets":[{"photos":[pet]}]})
        self.assertEqual(len(out["photo_urls"]),1)
        self.assertEqual(len(out["pet_photo_urls"]),1)
    def test_app_button_set_once_and_hide(self):
        with tempfile.TemporaryDirectory() as td:
            db=pathlib.Path(td)/"t.db"
            with sqlite3.connect(db) as conn:
                ctrl.init_db(conn);ctrl.pending(conn,ITEM,77,attached=True)
            calls=[]
            def api(t,m,args):
                calls.append((m,args));return True
            with patch.object(ctrl,"load_snapshot",lambda aid,conn:ITEM):
                for _ in range(2):
                    self.assertEqual(controller.handle(callback("t3:a:901"),"t","123",api_func=api,db_path=db),"application_marked")
                self.assertIn("Мене підтвердили",calls[-1][1]["reply_markup"])
                self.assertEqual(controller.handle(callback("t3:i:901:1"),"t","123",api_func=api,db_path=db),"dismissed")
                with sqlite3.connect(db) as conn:self.assertTrue(prefs.is_ignored(conn,"901"))
                self.assertEqual(controller.handle(callback("t3:i:901:0"),"t","123",api_func=api,db_path=db),"restored")
                with sqlite3.connect(db) as conn:self.assertFalse(prefs.is_ignored(conn,"901"))
if __name__=="__main__":unittest.main()
