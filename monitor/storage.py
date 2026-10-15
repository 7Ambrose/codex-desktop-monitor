import contextlib
import json
import sqlite3
import threading
import time
from pathlib import Path


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, title TEXT, cwd TEXT, model TEXT,
          turn_id TEXT, revision INTEGER NOT NULL DEFAULT 0,
          state TEXT NOT NULL, started REAL, updated REAL,
          prompt TEXT NOT NULL DEFAULT '', last_message TEXT NOT NULL DEFAULT '',
          review TEXT, pause_reason TEXT, pause_confirmed INTEGER DEFAULT 0,
          review_count INTEGER DEFAULT 0, reviewed_at REAL DEFAULT 0,
          control TEXT DEFAULT 'checkpoint', last_event TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY, task_id TEXT, turn_id TEXT,
          at REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS events_task ON events(task_id, id);
        CREATE TABLE IF NOT EXISTS reviews (
          id INTEGER PRIMARY KEY, task_id TEXT, turn_id TEXT, revision INTEGER,
          at REAL, verdict TEXT, result TEXT, usage TEXT, stale INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS decisions (
          id INTEGER PRIMARY KEY, task_id TEXT, turn_id TEXT, at REAL, action TEXT, reason TEXT
        );
        CREATE TABLE IF NOT EXISTS notices (
          id TEXT PRIMARY KEY, task_id TEXT, turn_id TEXT, kind TEXT,
          at REAL, message TEXT, acknowledged INTEGER NOT NULL DEFAULT 0
        );
        """)
        self.db.commit()

    @contextlib.contextmanager
    def transaction(self):
        with self.lock:
            try:
                yield self.db
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def task(self, task_id):
        with self.lock:
            row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return dict(row) if row else None

    def tasks(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM tasks ORDER BY updated DESC LIMIT 100")]

    def events(self, task_id, limit=24):
        with self.lock:
            rows = self.db.execute("SELECT * FROM events WHERE task_id=? ORDER BY id DESC LIMIT ?", (task_id, limit)).fetchall()
            return [{**dict(r), "payload": json.loads(r["payload"])} for r in reversed(rows)]

    def reviews(self, task_id):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM reviews WHERE task_id=? ORDER BY id DESC LIMIT 10", (task_id,))]

    def prune(self, days):
        cutoff = time.time() - days * 86400
        with self.transaction() as db:
            for table in ("events", "reviews", "decisions", "notices"):
                db.execute(f"DELETE FROM {table} WHERE at < ?", (cutoff,))
            db.execute("DELETE FROM tasks WHERE updated < ? AND state NOT IN ('running','pause_requested','waiting_user')", (cutoff,))

