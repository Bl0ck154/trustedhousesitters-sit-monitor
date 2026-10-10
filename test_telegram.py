#!/usr/bin/env python3
"""Offline Telegram dispatch tests. Never contact real Telegram."""
import contextlib
import datetime
import importlib
import io
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import dispatch_telegram as d


def fixture(when="2026-10-09T19:18:47+00:00", reviewing=False):
    return {"discovered_at": when, "eligible_alert": True,
            "transport_accessible": True, "verified_by_detail": True,
            "listing_id": "857632", "assignment_id": "2122760",
            "url": "https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/germany/hamburg/hamburg/l/857632/",
            "city": "Hamburg", "country": "Germany", "start": "2026-10-28", "end": "2026-11-04",
            "nights": 7, "pets": {"cat":3}, "cats":3, "dogs":0,
            "status": "reviewing" if reviewing else "open", "application_count":2,
            "internet":"highSpeed"}


class TelegramTests(unittest.TestCase):
    def test_message_escapes_titles(self):
        x = fixture()
        x["city"] = "<fake>"
        msg = d.message(x)
        self.assertIn("&lt;fake&gt;", msg)
        self.assertNotIn("<fake>", msg)

    def test_delivery_idempotence_and_new_reopening(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            queue = root / "queue.jsonl"
            token = root / "telegram_bot_token"
            chat = root / "telegram_chat_id"
            token.write_text("test-token\n")
            chat.write_text("12345\n")
            queue.write_text(json.dumps(fixture())+"\n")
            sent = []
            def fake_api(token, method, params):
                sent.append((method,params["chat_id"]))
                return {"message_id":100+len(sent)}
            with patch.object(d,"QUEUE",queue),patch.object(d,"DB",root/"sent.sqlite3"),patch.object(d,"TOKEN_FILE",token),patch.object(d,"CHAT_FILE",chat),patch.object(d,"api",fake_api),patch.object(d.monitor,"validate_detail",lambda item: item),patch.object(sys,"argv",["dispatch_telegram.py"]):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(d.main(),0)
                    self.assertEqual(d.main(),0)
                self.assertEqual(len(sent),1)
                reopened = fixture("2026-10-11T12:30:00+00:00")
                with queue.open("a") as f:
                    f.write(json.dumps(reopened)+"\n")
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(d.main(),0)
                self.assertEqual(len(sent),2)

    def test_stale_is_not_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory)
            queue=root/"queue.jsonl"
            token=root/"telegram_bot_token"
            chat=root/"telegram_chat_id"
            token.write_text("test-token");chat.write_text("1234")
            queue.write_text(json.dumps(fixture())+"\n")
            with patch.object(d,"QUEUE",queue),patch.object(d,"DB",root/"sent.sqlite3"),patch.object(d,"TOKEN_FILE",token),patch.object(d,"CHAT_FILE",chat),patch.object(d,"api") as api,patch.object(d.monitor,"validate_detail",lambda x:{**x,"status":"reviewing"}),patch.object(sys,"argv",["dispatch_telegram.py"]):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(d.main(),0)
                api.assert_not_called()
                con=sqlite3.connect(root/"sent.sqlite3")
                self.assertEqual(con.execute("select state from delivery").fetchone()[0],"stale")
                con.close()

    def test_uncertain_delivery_is_not_resent(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory)
            queue=root/"queue.jsonl";queue.write_text(json.dumps(fixture())+"\n")
            token=root/"telegram_bot_token";token.write_text("test-token")
            chat=root/"telegram_chat_id";chat.write_text("1234")
            calls=[]
            def broken_api(*args):
                calls.append(1)
                raise RuntimeError("network failure")
            with patch.object(d,"QUEUE",queue),patch.object(d,"DB",root/"sent.sqlite3"),patch.object(d,"TOKEN_FILE",token),patch.object(d,"CHAT_FILE",chat),patch.object(d,"api",broken_api),patch.object(d.monitor,"validate_detail",lambda x:x),patch.object(sys,"argv",["dispatch_telegram.py"]):
                with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(d.main(),2)
                    self.assertEqual(d.main(),0)
                self.assertEqual(len(calls),1)

if __name__=="__main__":
    unittest.main()
