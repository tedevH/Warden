"""SQLite persistence: tasks, the action audit log, findings, notifications, transaction history, settings.

Default file: data/lend.db (LEND_DB).
"""
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_SETTINGS = {
    "spending_cap": 50.0,
    "allowlist": ["maplebank.localhost", "mail.localhost", "pizza.localhost"],
    "profile": {"name": "Margaret", "accessibility": ["low_vision"], "phone": os.getenv("USER_PHONE", "")},
    "caregiver": {"name": "Daniel", "phone": os.getenv("CAREGIVER_PHONE", "")},
    "confirm_window_s": 60,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, user_id TEXT, kind TEXT, goal TEXT, state TEXT, outcome TEXT, step TEXT, narration TEXT,
  screenshot TEXT, summary TEXT, question TEXT, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, task_id TEXT, kind TEXT, url TEXT, element TEXT,
  classification TEXT, tier INTEGER, decision TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, user_id TEXT, task_id TEXT, kind TEXT, severity TEXT,
  title TEXT, evidence TEXT, explanation TEXT, fkey TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, user_id TEXT, audience TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS txns (
  tkey TEXT PRIMARY KEY, user_id TEXT, date TEXT, merchant TEXT, amount REAL, category TEXT, first_seen REAL);
CREATE TABLE IF NOT EXISTS seen_hosts (host TEXT PRIMARY KEY, first_seen REAL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""
TASK_COLS = ["id", "user_id", "kind", "goal", "state", "outcome", "step", "narration", "screenshot", "summary",
             "question", "created", "updated"]


class Store:
    def __init__(self, path=None):
        path = path or os.getenv("LEND_DB", str(ROOT / "data" / "lend.db"))
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)

    def _exec(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def _all(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    # ---- tasks ----
    def save_task(self, t: dict):
        vals = [json.dumps(t.get(c)) if c == "narration" else t.get(c) for c in TASK_COLS]
        self._exec(f"INSERT OR REPLACE INTO tasks ({','.join(TASK_COLS)}) VALUES ({','.join('?' * len(TASK_COLS))})",
                   vals)

    def load_tasks(self, limit=50):
        rows = self._all("SELECT * FROM tasks ORDER BY created DESC LIMIT ?", (limit,))
        for r in rows:
            r["narration"] = json.loads(r["narration"] or "[]")
        return rows

    def fail_interrupted(self):
        self._exec("UPDATE tasks SET state='failed', summary='Interrupted by a restart.' "
                   "WHERE state IN ('planning','running','awaiting_confirm')")

    # ---- audit log ----
    def log_action(self, task_id, kind, url, element, classification, tier, decision, reason):
        self._exec("INSERT INTO actions (ts, task_id, kind, url, element, classification, tier, decision, reason)"
                   " VALUES (?,?,?,?,?,?,?,?,?)",
                   (time.time(), task_id, kind, url, json.dumps(element) if element else None,
                    classification, tier, decision, reason))

    def actions(self, task_id=None, limit=200):
        if task_id:
            return self._all("SELECT * FROM actions WHERE task_id=? ORDER BY id DESC LIMIT ?", (task_id, limit))
        return self._all("SELECT * FROM actions ORDER BY id DESC LIMIT ?", (limit,))

    # ---- findings / notifications ----
    def add_finding(self, user_id, task_id, kind, severity, title, evidence, explanation, fkey=None) -> bool:
        """Returns True if this finding is new (fkey dedupes repeats)."""
        cur = self._exec("INSERT OR IGNORE INTO findings (ts, user_id, task_id, kind, severity, title, evidence,"
                         " explanation, fkey) VALUES (?,?,?,?,?,?,?,?,?)",
                         (time.time(), user_id, task_id, kind, severity, title, json.dumps(evidence), explanation,
                          fkey or f"{kind}:{title}"))
        return cur.rowcount > 0

    def findings(self, limit=100):
        rows = self._all("SELECT * FROM findings ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["evidence"] = json.loads(r["evidence"] or "null")
        return rows

    def notify(self, user_id, audience, text):
        self._exec("INSERT INTO notifications (ts, user_id, audience, text) VALUES (?,?,?,?)",
                   (time.time(), user_id, audience, text))

    def notifications(self, limit=50):
        return self._all("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,))

    # ---- transaction history (spend baselines) ----
    def upsert_txns(self, user_id, rows):
        now = time.time()
        with self.lock:
            self.db.executemany(
                "INSERT OR IGNORE INTO txns (tkey, user_id, date, merchant, amount, category, first_seen)"
                " VALUES (?,?,?,?,?,?,?)",
                [(f"{user_id}:{r['key']}", user_id, r["date"], r["merchant"], r["amount"], r.get("category", ""), now)
                 for r in rows])
            self.db.commit()

    def txns(self, user_id):
        return self._all("SELECT date, merchant, amount, category, tkey AS key FROM txns WHERE user_id=?"
                         " ORDER BY date", (user_id,))

    # ---- seen hosts ----
    def seen_hosts(self):
        return {r["host"] for r in self._all("SELECT host FROM seen_hosts")}

    def mark_seen(self, host):
        self._exec("INSERT OR IGNORE INTO seen_hosts (host, first_seen) VALUES (?, ?)", (host, time.time()))

    # ---- settings ----
    def settings(self):
        out = json.loads(json.dumps(DEFAULT_SETTINGS))
        for r in self._all("SELECT key, value FROM settings"):
            out[r["key"]] = json.loads(r["value"])
        return out

    def update_settings(self, changes: dict):
        for k, v in changes.items():
            if k not in DEFAULT_SETTINGS:
                raise KeyError(k)
            self._exec("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, json.dumps(v)))
        return self.settings()

    def wipe(self):
        """Demo reset: clear everything except settings."""
        for t in ("tasks", "actions", "findings", "notifications", "txns", "seen_hosts"):
            self._exec(f"DELETE FROM {t}")
