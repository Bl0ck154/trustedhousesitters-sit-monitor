"""Private user-controlled application statuses and confirmed housing timeline.

This database is NEVER synchronized with THS account status. Only an explicit
private command/button confirmation adds a stay to the itinerary.
"""
import datetime as dt
import json
import sqlite3
import housing_plan as plan

STAGES={"applied","talking","confirmed","rejected","withdrawn"}
LABELS={
    "applied":"📨 Подано","talking":"💬 Обговорюємо",
    "confirmed":"🏠 Підтверджено для мене","rejected":"❌ Відмовили",
    "withdrawn":"↩️ Відкликано"
}
def ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS applications(
        assignment_id TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL,
        owner_note TEXT
    )""")
    fields={row[1] for row in conn.execute("PRAGMA table_info(applications)")}
    if "stage" not in fields:
        conn.execute("ALTER TABLE applications ADD COLUMN stage TEXT NOT NULL DEFAULT 'applied'")
    conn.execute("""CREATE TABLE IF NOT EXISTS confirmed_stays(
        assignment_id TEXT PRIMARY KEY,
        start TEXT NOT NULL,end TEXT NOT NULL,city TEXT,country TEXT,
        title TEXT,confirmed_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS pending_confirmations(
        prompt_message_id INTEGER PRIMARY KEY,
        assignment_id TEXT NOT NULL,
        created_at REAL NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS housing_meta(
        name TEXT PRIMARY KEY,value TEXT NOT NULL
    )""")
    conn.commit()

def confirmed(conn):
    ensure(conn)
    return [dict(zip(("assignment_id","start","end","city","country","title"),row))
            for row in conn.execute("""SELECT assignment_id,start,end,city,country,title
                                       FROM confirmed_stays ORDER BY start""")]

def stage(conn,aid):
    ensure(conn)
    row=conn.execute("SELECT stage FROM applications WHERE assignment_id=?",(str(aid),)).fetchone()
    return row[0] if row else None

def snapshot(conn,aid,archive_dir=None):
    aid=str(aid)
    if not aid.isdecimal():return None
    row=conn.execute("SELECT payload FROM watch WHERE assignment_id=?",(aid,)).fetchone()
    if row:
        try:return json.loads(row[0])
        except (ValueError,TypeError):pass
    if archive_dir is not None:
        f=archive_dir/(aid+".json")
        if f.is_file():
            try:return json.loads(f.read_text())
            except (ValueError,OSError):return None
    return None

def update(conn,aid,target,archive_dir=None):
    """Set a manual stage after validating date overlap and assignment identity.

    Never infer a user's success from the public listing status.
    Returns the new stage (or raises ValueError).
    """
    aid=str(aid)
    if not aid.isdecimal() or target not in STAGES:
        raise ValueError("Unknown assignment or stage")
    ensure(conn)
    item=snapshot(conn,aid,archive_dir)
    if not item:
        raise ValueError("Невідоме оголошення")
    old=stage(conn,aid)
    if target=="confirmed":
        try:
            dt.date.fromisoformat(str(item["start"]))
            dt.date.fromisoformat(str(item["end"]))
        except (KeyError,ValueError,TypeError):
            raise ValueError("В оголошенні немає правильних дат")
        if dt.date.fromisoformat(str(item["end"]))<=dt.date.fromisoformat(str(item["start"])):
            raise ValueError("Некоректний період")
        for stay in confirmed(conn):
            if stay["assignment_id"]!=aid and plan.overlaps(item,stay):
                raise ValueError("Цей сіт перетинається з уже підтвердженим")
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    with conn:
        conn.execute("""INSERT INTO applications (assignment_id,applied_at,stage)
                        VALUES (?,?,?)
                        ON CONFLICT(assignment_id) DO UPDATE SET stage=excluded.stage""",
                     (aid,now,target))
        if target=="confirmed":
            conn.execute("""INSERT INTO confirmed_stays
                         (assignment_id,start,end,city,country,title,confirmed_at)
                         VALUES (?,?,?,?,?,?,?)
                         ON CONFLICT(assignment_id) DO UPDATE SET
                         start=excluded.start,end=excluded.end,city=excluded.city,
                         country=excluded.country,title=excluded.title,
                         confirmed_at=excluded.confirmed_at""",
                         (aid,item["start"],item["end"],item.get("city"),item.get("country"),
                          item.get("title"),now))
        else:
            conn.execute("DELETE FROM confirmed_stays WHERE assignment_id=?",(aid,))
    return target

def _raise(message):
    raise ValueError(message)

def applications(conn):
    ensure(conn)
    rows=conn.execute("""SELECT assignment_id,applied_at,stage FROM applications
                         ORDER BY applied_at DESC""").fetchall()
    return [dict(zip(("assignment_id","applied_at","stage"),row)) for row in rows]
