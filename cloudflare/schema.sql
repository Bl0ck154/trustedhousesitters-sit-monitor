-- Idempotent D1 schema. Personal data is imported from a private, read-only Netcup backup.
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS leases(name TEXT PRIMARY KEY,expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS records(assignment_id TEXT PRIMARY KEY,status TEXT NOT NULL,payload TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_records_updated ON records(updated_at DESC);
CREATE TABLE IF NOT EXISTS watch(assignment_id TEXT PRIMARY KEY,status TEXT NOT NULL,payload TEXT NOT NULL,last_checked TEXT,last_change TEXT,message_id INTEGER);
CREATE INDEX IF NOT EXISTS idx_watch_checked ON watch(last_checked);
CREATE TABLE IF NOT EXISTS watch_transitions(assignment_id TEXT PRIMARY KEY,proposed_status TEXT NOT NULL,first_seen TEXT NOT NULL,observation_count INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS delivery(event_key TEXT PRIMARY KEY,state TEXT NOT NULL,updated_at TEXT NOT NULL,message_id INTEGER);
CREATE TABLE IF NOT EXISTS pending_notifications(assignment_id TEXT PRIMARY KEY,discovered_at TEXT NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending');
CREATE INDEX IF NOT EXISTS idx_pending_state ON pending_notifications(state,discovered_at);
CREATE TABLE IF NOT EXISTS controls(assignment_id TEXT PRIMARY KEY,album_message_id INTEGER NOT NULL,control_message_id INTEGER,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS control_instances(assignment_id TEXT NOT NULL,message_id INTEGER NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(assignment_id,message_id));
CREATE TABLE IF NOT EXISTS applications(assignment_id TEXT PRIMARY KEY,applied_at TEXT NOT NULL,owner_note TEXT,stage TEXT NOT NULL DEFAULT 'applied');
CREATE TABLE IF NOT EXISTS confirmed_stays(assignment_id TEXT PRIMARY KEY,start TEXT NOT NULL,end TEXT NOT NULL,city TEXT,country TEXT,title TEXT,confirmed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pending_confirmations(prompt_message_id INTEGER PRIMARY KEY,assignment_id TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ignored_assignments(assignment_id TEXT PRIMARY KEY,reason TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS telegram_updates(update_id INTEGER PRIMARY KEY,received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS daily_reports(local_day TEXT PRIMARY KEY,state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS button_sends(assignment_id TEXT NOT NULL,message_id INTEGER NOT NULL,action TEXT NOT NULL,sent_at REAL NOT NULL,state TEXT NOT NULL,sent_messages INTEGER DEFAULT 0,PRIMARY KEY(assignment_id,message_id,action));
CREATE TABLE IF NOT EXISTS keyboard_updates(assignment_id TEXT NOT NULL,message_id INTEGER NOT NULL,requested_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(assignment_id,message_id));

-- Optional inbound mail relay for user-configured Sittify notification emails.
CREATE TABLE IF NOT EXISTS inbound_alerts(message_key TEXT PRIMARY KEY,source TEXT NOT NULL,subject TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',received_at TEXT NOT NULL,sent_at TEXT);
CREATE INDEX IF NOT EXISTS idx_inbound_alerts_state ON inbound_alerts(state,received_at);
