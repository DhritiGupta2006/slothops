"""SQLite persistence. A planned action is never credited as completed work."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, operation TEXT NOT NULL,
                    root TEXT NOT NULL, created_at TEXT NOT NULL, metadata TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(id),
                    kind TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL,
                    snapshot TEXT NOT NULL, keeper TEXT, keeper_snapshot TEXT,
                    reason TEXT NOT NULL, estimated_seconds REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', error TEXT,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS action_status ON actions(status);
                CREATE TABLE IF NOT EXISTS summaries (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, title TEXT NOT NULL,
                    source_hash TEXT NOT NULL, model TEXT NOT NULL, input_chars INTEGER NOT NULL,
                    chunks INTEGER NOT NULL, result TEXT NOT NULL, elapsed_seconds REAL NOT NULL,
                    baseline_seconds REAL NOT NULL, estimated_seconds REAL NOT NULL,
                    UNIQUE(source_hash, model)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
                    kind TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL,
                    detail TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS routines (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, operation TEXT NOT NULL,
                    root TEXT NOT NULL, options TEXT NOT NULL, interval_minutes INTEGER NOT NULL,
                    next_run TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    last_status TEXT NOT NULL DEFAULT 'Never run', lease_until TEXT
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def all(self, sql: str, args=()) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args).fetchall()]

    def one(self, sql: str, args=()) -> dict | None:
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def event(self, kind: str, status: str, message: str, detail=None, db=None):
        values = (now(), kind, status, message, encode(detail or {}))
        sql = "INSERT INTO events(at,kind,status,message,detail) VALUES(?,?,?,?,?)"
        if db is not None:
            db.execute(sql, values)
        else:
            with self.connect() as conn:
                conn.execute(sql, values)

    def metrics(self) -> dict:
        with self.connect() as db:
            files = db.execute("SELECT COUNT(*),COALESCE(SUM(estimated_seconds),0) FROM actions WHERE status='done'").fetchone()
            summaries = db.execute("SELECT COUNT(*),COALESCE(SUM(estimated_seconds),0) FROM summaries").fetchone()
            pending = db.execute("SELECT COUNT(*) FROM actions WHERE status='pending'").fetchone()[0]
            failed = db.execute("SELECT COUNT(*) FROM actions WHERE status IN ('failed','running','restoring')").fetchone()[0]
        return {"completed": files[0] + summaries[0], "files": files[0], "summaries": summaries[0],
                "minutes_saved": round((files[1] + summaries[1]) / 60, 1),
                "pending": pending, "attention": failed}

    def actions(self, plan_id: str | None = None, status: str | None = None) -> list[dict]:
        conditions, args = [], []
        if plan_id:
            conditions.append("a.plan_id=?")
            args.append(plan_id)
        if status:
            conditions.append("a.status=?")
            args.append(status)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return self.all("SELECT a.*,p.root,p.title,p.metadata FROM actions a JOIN plans p ON a.plan_id=p.id" + where + " ORDER BY p.created_at DESC,a.source", args)
