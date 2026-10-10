"""Responsive Telegram callback dispatcher for TrustedHousesitters.

Fast getUpdates polling/ACK is separate from slow media edits. A bounded thread
pool serializes edits per Telegram message and retains only the newest queued
button press. Repeated identical taps in a short burst are coalesced.

No raw update contents, tokens or chat IDs are written to logs.
"""
import concurrent.futures
import json
import sys
import threading
import time

from setup_telegram import api, TOKEN_FILE, CHAT_FILE
from telegram_callbacks import read_offset, save_offset
from telegram_controls import handle_callback
from telegram_commands import handle_message

def event_log(**kwargs):
    print(json.dumps(kwargs,ensure_ascii=False,separators=(",",":")),flush=True)

class FastDispatcher:
    def __init__(self, token, chat_id, api_func=api, callback_handler=handle_callback, workers=3):
        self.token=token
        self.chat_id=chat_id
        self.api=api_func
        self.callback_handler=callback_handler
        self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=workers,thread_name_prefix="ths-button")
        self.ack_pool=concurrent.futures.ThreadPoolExecutor(max_workers=4,thread_name_prefix="ths-ack")
        self.lock=threading.Lock()
        self.pending={}
        self.active=set()
        self.recent={}
        self.completed=0
        self.collapsed=0

    def ack(self,update,duplicate=False):
        callback=(update.get("callback_query") or {})
        cid=callback.get("id")
        if not cid:return
        start=time.monotonic()
        try:
            action=str(callback.get("data") or "")
            if duplicate and action.startswith("t3:d:"):
                label="Опис уже надіслано або надсилається"
            elif duplicate and action.startswith(("t3:g:","t3:t:")):
                label="Галерея вже надіслана або завантажується"
            else:
                label=("Надсилаю повний опис…" if action.startswith("t3:d:") else
                       "Надсилаю фотографії…" if action.startswith(("t3:g:","t3:t:")) else
                       "Заявка зберігається…" if action.startswith(("t3:a:","t3:u:")) else
                       "Налаштування збережу…" if action.startswith("t3:i:") else "")
            args={"callback_query_id":cid}
            if label:args["text"]=label
            self.api(self.token,"answerCallbackQuery",args)
        except Exception as ex:
            # Expired callbacks may be unacknowledgeable, but the edit can still
            # succeed and newer button presses must not stall.
            event_log(event="ack_error",error_type=type(ex).__name__,code=str(ex)[:65])
        else:
            ms=round((time.monotonic()-start)*1000)
            if ms>500:event_log(event="slow_ack",ms=ms)

    def ack_async(self,update,duplicate=False):
        return self.ack_pool.submit(self.ack,update,duplicate)

    def enqueue(self,update):
        cb=update.get("callback_query") or {}
        message=cb.get("message") or {}
        chat=message.get("chat") or {}
        data=str(cb.get("data") or "")
        # Long, on-demand gallery/description actions must not block each other.
        suffix=data.split(":")[1] if data.startswith(("t3:d:","t3:g:","t3:t:")) else ""
        ident=(str(chat.get("id") or ""),str(message.get("message_id") or ""),suffix)
        if not ident[0] or not ident[1]:return False
        data=str(cb.get("data") or "")
        when=time.monotonic()
        with self.lock:
            # Same exact button tapped 3x in quick succession should not cause
            # 3 edits or flip 'applied' repeatedly.
            recent_key=(ident,data)
            last=self.recent.get(recent_key)
            window=30 if data.startswith("t3:d:") else 120 if data.startswith(("t3:g:","t3:t:")) else 1.0
            if last is not None and when-last<window:
                event_log(event="coalesced_same_button",type=data.split(":")[1] if ":" in data else "other")
                return False
            self.recent[recent_key]=when
            if len(self.recent)>512:
                self.recent={k:v for k,v in self.recent.items() if when-v<5}
            self.pending[ident]=(update,when)
            if ident not in self.active:
                self.active.add(ident)
                self.pool.submit(self._drain,ident)
        return True

    def _drain(self,key):
        # Brief debounce collects near-simultaneous updates into one final edit.
        time.sleep(0.06)
        while True:
            with self.lock:
                job=self.pending.pop(key,None)
                if job is None:
                    self.active.discard(key)
                    return
            update,queued_at=job
            start=time.monotonic()
            methods=[]
            def api_without_second_ack(token,method,args=None):
                if method=="answerCallbackQuery":
                    return True
                call_start=time.monotonic()
                try:
                    value=self.api(token,method,args)
                    methods.append((method,round((time.monotonic()-call_start)*1000)))
                    return value
                except Exception as exc:
                    methods.append((method,"FAILED"))
                    raise
            api_without_second_ack._fast_photo_upload=True
            try:
                result=self.callback_handler(update,self.token,self.chat_id,api_func=api_without_second_ack)
                self.completed+=1
                event_log(event="button",button=str((update.get("callback_query") or {}).get("data","")).split(":")[1:2],
                          result=result,queue_ms=round((start-queued_at)*1000),
                          total_ms=round((time.monotonic()-queued_at)*1000),api_methods=methods)
            except Exception as exc:
                # This specific event is acknowledged and consumed, not allowed to
                # poison the entire polling stream or block newer button presses.
                event_log(event="button_error",error=type(exc).__name__,reason=str(exc)[:85],
                          latency_ms=round((time.monotonic()-queued_at)*1000),api_methods=methods)
            time.sleep(0.005)

    def close(self):
        self.ack_pool.shutdown(wait=True)
        self.pool.shutdown(wait=True)

def run(seconds=None,api_func=api,callback_handler=handle_callback):
    if not TOKEN_FILE.exists() or not CHAT_FILE.exists():
        event_log(event="error",reason="not_paired")
        return 2
    token=TOKEN_FILE.read_text().strip()
    chat_id=CHAT_FILE.read_text().strip()
    if not chat_id.lstrip("-").isdigit():return 2
    webhook=api_func(token,"getWebhookInfo")
    if webhook.get("url"):
        event_log(event="error",reason="webhook_present")
        return 2
    dispatcher=FastDispatcher(token,chat_id,api_func=api_func,callback_handler=callback_handler)
    offset=read_offset()
    deadline=time.monotonic()+seconds if seconds is not None else float("inf")
    streak=0
    try:
        while time.monotonic()<deadline:
            timeout=5 if seconds is None else min(5,max(0,int(deadline-time.monotonic())))
            if timeout==0:break
            args={"timeout":str(timeout),"limit":"100",
                  "allowed_updates":json.dumps(["callback_query","message"])}
            if offset is not None:args["offset"]=str(offset)
            try:
                updates=api_func(token,"getUpdates",args)
                streak=0
            except Exception as exc:
                streak+=1
                delay=min(2*streak,15)
                event_log(event="poll_error",error=type(exc).__name__,reason=str(exc)[:65],
                          consecutive=streak,backoff_s=delay)
                time.sleep(delay)
                continue
            if not isinstance(updates,list):
                event_log(event="poll_error",reason="invalid_response")
                time.sleep(2)
                continue
            for update in updates:
                uid=update.get("update_id")
                if not isinstance(uid,int):continue
                if "callback_query" in update:
                    accepted=dispatcher.enqueue(update)
                    dispatcher.ack_async(update,duplicate=not accepted)
                elif "message" in update:
                    # Private slash commands are rare; keep lightweight.
                    try:
                        handle_message(update,token,chat_id,api_func=api_func)
                    except Exception as exc:
                        event_log(event="command_error",error=type(exc).__name__)
                offset=max(uid+1,offset or 0)
                save_offset(offset)
    finally:
        dispatcher.close()
    return 0

if __name__=="__main__":
    raise SystemExit(run())
