"""Private per-assignment dismissal choices."""
import pathlib
import sqlite3

DB=pathlib.Path(__file__).resolve().parent/"data"/"telegram_delivery.sqlite3"

def ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS ignored_assignments (
        assignment_id TEXT PRIMARY KEY,
        reason TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

def is_ignored(conn, aid):
    ensure(conn)
    return conn.execute("SELECT 1 FROM ignored_assignments WHERE assignment_id=?",
                        (str(aid),)).fetchone() is not None

def set_ignored(conn, aid, value, reason="not_interested"):
    aid=str(aid)
    if not aid.isdecimal():
        raise ValueError("Invalid assignment")
    ensure(conn)
    with conn:
        if value:
            conn.execute("""INSERT INTO ignored_assignments(assignment_id,reason)
                 VALUES (?,?) ON CONFLICT(assignment_id) DO UPDATE SET
                 reason=excluded.reason,updated_at=CURRENT_TIMESTAMP""",(aid,reason))
        else:
            conn.execute("DELETE FROM ignored_assignments WHERE assignment_id=?",(aid,))
    return bool(value)

def ignored_in_connection(conn):
    ensure(conn)
    return {str(row[0]) for row in conn.execute("SELECT assignment_id FROM ignored_assignments")}

def ignored_ids(db_path=DB):
    if not pathlib.Path(db_path).is_file():
        return set()
    with sqlite3.connect(db_path,timeout=6) as conn:
        ensure(conn)
        return {str(row[0]) for row in conn.execute("SELECT assignment_id FROM ignored_assignments")}
