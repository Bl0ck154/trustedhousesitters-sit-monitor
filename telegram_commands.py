"""Private Telegram commands: manual application status, housing plan and backups."""
import html
import sqlite3
from pathlib import Path
from setup_telegram import api
import telegram_controls as controls
import housing_state as housing
import housing_reporting as report

DB=Path(__file__).resolve().parent/"data"/"telegram_delivery.sqlite3"

def app_list(conn):
    return report.applications_text(conn)

def handle_message(update,token,chat_id,api_func=api,db_path=DB):
    msg=update.get("message") or {}
    chat=msg.get("chat") or {}
    actor=msg.get("from") or {}
    if chat.get("type")!="private" or str(chat.get("id"))!=str(chat_id) or str(actor.get("id"))!=str(chat_id):
        return "ignored"
    raw=str(msg.get("text") or "").strip()
    argv=raw.split()
    if not argv:return "ignored"
    cmd=argv[0].split("@")[0].lower()
    commands={"/applications","/zayavki","/help","/start",
              "/plan","/options","/report","/confirm","/reject",
              "/talking","/applied","/withdraw","/status"}
    if cmd not in commands:return "ignored"
    with sqlite3.connect(db_path,timeout=8) as cx:
        controls.init_db(cx)
        housing.ensure(cx)
        if cmd in ("/applications","/zayavki"):
            body=app_list(cx)
        elif cmd=="/plan":
            body=report.plan_text(cx)
        elif cmd=="/options":
            body=report.options_text(cx)
        elif cmd=="/report":
            body=report.daily_text(cx)
        elif cmd in ("/help","/start"):
            body=("🏠 <b>Монітор житла</b>\n"
                  "/plan — календар підтвердженого житла і прогалини\n"
                  "/options — коти, дрібні тварини та резерв із собаками\n"
                  "/applications — мої заявки\n"
                  "/report — короткий підсумок\n\n"
                  "/talking ID — власник відповів\n"
                  "/confirm ID — підтверджено саме твоє проживання\n"
                  "/reject ID — відмова\n"
                  "/applied ID — подана заявка\n"
                  "/withdraw ID — відкликана заявка\n"
                  "Під оголошенням є кнопка підтвердження з додатковим запитанням.\n"
                  "Статуси змінюються тільки вручну, не за публічним статусом THS.")
        else:
            stage={"/confirm":"confirmed","/reject":"rejected",
                   "/talking":"talking","/applied":"applied",
                   "/withdraw":"withdrawn"}.get(cmd)
            if cmd=="/status" and len(argv)==3:
                _,aid,stage=argv
            elif len(argv)==2 and stage:
                aid=argv[1]
            else:
                stage=None
            if stage not in housing.STAGES or not str(aid if stage else "").isdigit():
                body="Використання: /confirm 2123228 або /status 2123228 talking"
            else:
                try:
                    new=housing.update(cx,aid,stage,controls.DATA/"listings")
                    body="✅ "+html.escape(str(aid))+": "+housing.LABELS[new]
                    if stage=="confirmed":body+="\n\n"+report.plan_text(cx)
                    elif stage in ("rejected","withdrawn"):body+="\n\n"+report.plan_text(cx)
                except ValueError as exc:
                    body="⚠️ "+html.escape(str(exc))
    api_func(token,"sendMessage",{"chat_id":str(chat_id),"text":body,
        "parse_mode":"HTML","disable_web_page_preview":"true",
        "reply_to_message_id":str(msg.get("message_id") or ""),
        "allow_sending_without_reply":"true"})
    return "command"
