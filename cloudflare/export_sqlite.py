#!/usr/bin/env python3
"""Offline, read-only migration export from private Netcup data to Cloudflare D1.

No production change. SQL output contains private application and Telegram data:
keep it out of git and remove it after secure import and validation.
"""
import argparse
import datetime as dt
import json
import pathlib
import re
import sqlite3
import sys

TABLES = {
    "telegram_delivery.sqlite3": (
        "watch", "watch_transitions", "delivery", "controls",
        "control_instances", "applications", "confirmed_stays",
        "ignored_assignments", "button_sends", "keyboard_updates",
    ),
    "history.sqlite3": ("records",),
}

COLUMNS = {
    "watch": ("assignment_id", "status", "payload", "last_checked", "last_change", "message_id"),
    "watch_transitions": ("assignment_id", "proposed_status", "first_seen", "observation_count"),
    "delivery": ("event_key", "state", "updated_at", "message_id"),
    "controls": ("assignment_id", "album_message_id", "control_message_id", "updated_at"),
    "control_instances": ("assignment_id", "message_id", "created_at"),
    "applications": ("assignment_id", "applied_at", "owner_note", "stage"),
    "confirmed_stays": ("assignment_id", "start", "end", "city", "country", "title", "confirmed_at"),
    "ignored_assignments": ("assignment_id", "reason", "updated_at"),
    "button_sends": ("assignment_id", "message_id", "action", "sent_at", "state", "sent_messages"),
    "keyboard_updates": ("assignment_id", "message_id", "requested_at"),
    "records": ("assignment_id", "status", "payload", "updated_at"),
}

def literal(value):
    if value is None: return "NULL"
    if isinstance(value, bool): return str(int(value))
    if isinstance(value, (float, int)): return repr(value)
    if isinstance(value, (str, bytes)):
        if isinstance(value, bytes): return "X'" + value.hex() + "'"
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(type(value).__name__)

def source_rows(path, table):
    uri="file:"+str(path.resolve())+"?mode=ro"
    with sqlite3.connect(uri, uri=True) as cx:
        existing={r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if table not in existing: return []
        fields={r[1] for r in cx.execute("PRAGMA table_info("+table+")")}
        cols=COLUMNS[table]
        selected=[c for c in cols if c in fields]
        if not selected:return []
        return [dict(zip(selected,row)) for row in
                cx.execute("SELECT "+",".join(selected)+" FROM "+table)]

def insert(table,row):
    cols=list(row)
    return "INSERT OR REPLACE INTO "+table+" ("+",".join(cols)+") VALUES ("+",".join(map(literal,row.values()))+");"

def json_rows(path):
    if not path.is_file():return []
    data=json.loads(path.read_text(encoding="utf8"))
    return [x for x in data.get("results",[]) if isinstance(x,dict)]

def valid_id(value):return bool(re.fullmatch(r"\d{1,15}",str(value or "")))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data",type=pathlib.Path,required=True,help="PRIVATE backup data/ directory")
    p.add_argument("--output",type=pathlib.Path,required=True,help="PRIVATE output SQL file outside repository")
    p.add_argument("--earliest-start",default=None)
    args=p.parse_args()
    if args.earliest_start:dt.date.fromisoformat(args.earliest_start)
    data=args.data.resolve();out=args.output.resolve()
    if not data.is_dir():p.error("data backup directory does not exist")
    if out.parent==data or data in out.parents:p.error("keep output outside the original data backup")
    if out.exists():p.error("refusing to overwrite existing migration file")
    if out.is_relative_to(pathlib.Path(__file__).resolve().parent.parent):p.error("refusing to write private SQL into repository")
    rows_by_table={table:[] for table in COLUMNS}
    for db_name,tables in TABLES.items():
        path=data/db_name
        if not path.exists():
            print("WARN: missing "+db_name, file=sys.stderr)
            continue
        for table in tables:
            rows_by_table[table].extend(source_rows(path,table))
    by_id={str(x.get("assignment_id")):x for x in rows_by_table["records"] if valid_id(x.get("assignment_id"))}
    # Supplement missing history from last full search and detail snapshots.
    for listing in json_rows(data/"latest.json"):
        aid=str(listing.get("assignment_id",""))
        if valid_id(aid) and aid not in by_id:
            by_id[aid]={"assignment_id":aid,"status":str(listing.get("status") or "unknown"),
                        "payload":json.dumps(listing,ensure_ascii=False),
                        "updated_at":str(listing.get("observed_at") or dt.datetime.now(dt.timezone.utc).isoformat())}
    path=data/"listings"
    if path.is_dir():
        for entry in path.glob("*.json"):
            if not valid_id(entry.stem) or entry.stem in by_id:continue
            try:item=json.loads(entry.read_text(encoding="utf8"))
            except (ValueError,OSError):continue
            if isinstance(item,dict) and str(item.get("assignment_id"))==entry.stem:
                by_id[entry.stem]={"assignment_id":entry.stem,"status":str(item.get("status") or "unknown"),
                    "payload":json.dumps(item,ensure_ascii=False),
                    "updated_at":str(item.get("observed_at") or dt.datetime.now(dt.timezone.utc).isoformat())}
    rows_by_table["records"]=list(by_id.values())
    lines=["-- PRIVATE: Contains personal metadata; never commit, email or publish.","BEGIN TRANSACTION;"]
    if args.earliest_start:lines.append(insert("settings",{"key":"earliest_start_backup","value":args.earliest_start}))
    cooldown=data/"http-access-cooldown.json"
    if cooldown.exists():
        try:
            until=int(float(json.loads(cooldown.read_text()).get("until",0))*1000)
            if until>dt.datetime.now(dt.timezone.utc).timestamp()*1000:
                lines.append(insert("settings",{"key":"access_until","value":str(until)}))
        except (ValueError,TypeError,OSError):pass
    totals={}
    for table,rows in rows_by_table.items():
        n=0
        for row in rows:
            if "assignment_id" in row and not valid_id(row["assignment_id"]):continue
            if table=="applications" and "stage" not in row:row["stage"]="applied"
            lines.append(insert(table,row));n+=1
        totals[table]=n
    # Historical pending notifications are preserved but NEVER sent on import.
    pending=data/"pending-notifications.jsonl"
    pending_n=0
    if pending.exists():
        for line in pending.read_text(encoding="utf8").splitlines():
            try:x=json.loads(line)
            except ValueError:continue
            aid=str(x.get("assignment_id",""))
            if not valid_id(aid):continue
            lines.append(insert("pending_notifications",{"assignment_id":aid,
              "discovered_at":str(x.get("discovered_at") or dt.datetime.now(dt.timezone.utc).isoformat()),
              "payload":json.dumps(x,ensure_ascii=False),"state":"imported_hold"}))
            pending_n+=1
    lines.append("COMMIT;")
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("x",encoding="utf8") as fd:fd.write("\n".join(lines)+"\n")
    try:out.chmod(0o600)
    except OSError:pass
    print(json.dumps({"table_counts":totals,"pending_imported_on_hold":pending_n,
                      "private_file_created":True,"file_bytes":out.stat().st_size},ensure_ascii=False))
    return 0

if __name__=="__main__":raise SystemExit(main())
