-- App-server v1 operational tables

CREATE TABLE IF NOT EXISTS app_threads (
    id TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    cwd TEXT NOT NULL,
    status TEXT NOT NULL,
    name TEXT,
    created_at_ts INTEGER NOT NULL,
    updated_at_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS app_turns (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    turn_id TEXT,
    state TEXT NOT NULL,
    output_text TEXT,
    error TEXT,
    created_at_ts INTEGER NOT NULL,
    updated_at_ts INTEGER NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES app_threads(id)
);
CREATE INDEX IF NOT EXISTS idx_app_turns_thread ON app_turns(thread_id, created_at_ts DESC);

CREATE TABLE IF NOT EXISTS app_agents (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    status TEXT NOT NULL,
    mode TEXT NOT NULL,
    created_at_ts INTEGER NOT NULL,
    updated_at_ts INTEGER NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES app_threads(id)
);

CREATE TABLE IF NOT EXISTS app_events (
    cursor INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    channels TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_app_events_cursor ON app_events(cursor);

