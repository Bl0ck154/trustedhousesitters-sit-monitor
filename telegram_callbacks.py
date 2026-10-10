#!/usr/bin/env python3
"""Short-lived Telegram callback polling worker (runs via once-a-minute cron).

Dedicated THS bot is already paired. No web server or incoming public port.
"""
import datetime as dt
import json
import os
import pathlib
import sys
import time
from setup_telegram import api, TOKEN_FILE, CHAT_FILE
from telegram_controls import handle_callback
from telegram_commands import handle_message

DATA=pathlib.Path(__file__).resolve().parent/"data"
OFFSET=DATA/"callback_update_offset"

def read_offset():
    if not OFFSET.is_file():return None
    txt=OFFSET.read_text().strip()
    return int(txt) if txt.isdecimal() else None

def save_offset(value):
    temp=DATA/("callback_update_offset."+str(os.getpid())+".tmp")
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,"w") as f:f.write(str(value)+"\n")
    os.replace(temp,OFFSET)

def poll(seconds=48,api_func=api,handler=handle_callback):
    if not TOKEN_FILE.is_file() or not CHAT_FILE.is_file():
        print("Telegram bot not paired")
        return 2
    token=TOKEN_FILE.read_text().strip()
    chat=CHAT_FILE.read_text().strip()
    if not chat.lstrip("-").isdigit():return 2
    # Never delete another webhook here. Owner already removed the old one.
    webhook=api_func(token,"getWebhookInfo")
    if webhook.get("url"):
        print("Webhook already active. Callback polling paused.")
        return 2
    deadline=float('inf') if seconds is None else time.monotonic()+seconds
    offset=read_offset()
    done=0
    rejected=0
    failures=0
    while time.monotonic()<deadline:
        timeout=9 if seconds is None else min(9,max(0,int(deadline-time.monotonic())))
        if timeout==0:break
        args={"timeout":str(timeout),"limit":"50",
              "allowed_updates":json.dumps(["callback_query","message"])}
        if offset is not None:args["offset"]=str(offset)
        try:
            updates=api_func(token,"getUpdates",args)
        except Exception as ex:
            print("Callback poll API failure",type(ex).__name__,file=sys.stderr)
            return 2
        if not isinstance(updates,list):
            print("Invalid update batch",file=sys.stderr)
            return 2
        for update in updates:
            uid=update.get("update_id")
            if not isinstance(uid,int):
                continue
            try:
                if "callback_query" in update:
                    result=handler(update,token,chat)
                    if result in ("expanded","collapsed","unchanged_or_edit_rejected","application_marked","application_unmarked","map_sent"):done+=1
                    else:rejected+=1
                elif "message" in update:
                    res=handle_message(update,token,chat)
                    if res=="command":done+=1
                    else:rejected+=1
            except Exception as ex:
                # Do not advance the offset; a transient Telegram failure can retry.
                failures+=1
                print("Callback handler failure",type(ex).__name__,file=sys.stderr)
                return 2
            offset=max(offset or 0,uid+1)
            save_offset(offset)
    print(json.dumps({"buttons_served":done,"ignored":rejected,"failures":failures}))
    return 0

if __name__=="__main__":
    # Under systemd --forever removes the 12-second gap between cron workers.
    # Telegram getUpdates is long polling: it delivers button presses as soon
    # as they arrive, rather than polling only at the next cron minute.
    raise SystemExit(poll(seconds=None if "--forever" in sys.argv else 48))
