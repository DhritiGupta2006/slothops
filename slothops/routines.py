"""Durable, bounded recurring chores. File writes always return to approvals."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

from .ai import Ollama, summarize
from .engine import duplicates, organize
from .files import READABLE, extract_file, root_path, scan_folder
from .storage import Store, encode, now


OPERATIONS = {
    "organize_types": "Organize by file type → approval queue",
    "organize_ai": "Organize documents with Ollama → approval queue",
    "duplicates": "Find duplicates → approval queue",
    "summarize_folder": "Summarize text documents → saved summaries",
}


def create_routine(store: Store, name: str, operation: str, folder: str, interval_minutes: int, options: dict) -> str:
    if operation not in OPERATIONS:
        raise ValueError("Choose a supported operation.")
    if not 1 <= interval_minutes <= 10080:
        raise ValueError("Choose an interval between one minute and one week.")
    root = root_path(folder)
    if not name.strip():
        raise ValueError("Give the routine a name.")
    clean = {"limit": max(1, min(int(options.get("limit", 50)), 500)),
             "model": str(options.get("model", "gemma3:4b")),
             "base_url": str(options.get("base_url", "http://127.0.0.1:11434")),
             "timeout": max(30, min(int(options.get("timeout", 300)), 600))}
    # Validate address even when creation does not call the model.
    Ollama(clean["base_url"], clean["model"], clean["timeout"])
    routine_id = uuid4().hex
    next_run = (datetime.now(timezone.utc) + timedelta(minutes=interval_minutes)).isoformat(timespec="seconds")
    with store.connect() as db:
        db.execute("INSERT INTO routines(id,name,operation,root,options,interval_minutes,next_run) VALUES(?,?,?,?,?,?,?)",
                   (routine_id, name.strip()[:150], operation, str(root), encode(clean), interval_minutes, next_run))
        store.event("routine", "created", f"Scheduled {name.strip()}", {"routine_id": routine_id, "operation": operation, "interval_minutes": interval_minutes}, db)
    return routine_id


def toggle_routine(store: Store, routine_id: str, enabled: bool):
    with store.connect() as db:
        db.execute("UPDATE routines SET enabled=? WHERE id=?", (int(enabled), routine_id))
        store.event("routine", "enabled" if enabled else "paused", "Updated routine", {"routine_id": routine_id}, db)


def run_routine(store: Store, routine_id: str, *, force: bool = False, exclude: Path | None = None) -> dict:
    stamp = now()
    lease = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(timespec="seconds")
    with store.connect() as db:
        due = "" if force else " AND next_run<=?"
        args = [lease, routine_id, stamp] + ([] if force else [stamp])
        claimed = db.execute("UPDATE routines SET lease_until=? WHERE id=? AND enabled=1 AND (lease_until IS NULL OR lease_until<?)" + due, args).rowcount
        if not claimed:
            return {"status": "skipped", "message": "Not due, paused, or already running"}
        row = dict(db.execute("SELECT * FROM routines WHERE id=?", (routine_id,)).fetchone())
        store.event("routine", "started", row["name"], {"routine_id": routine_id}, db)
    options = json.loads(row["options"])
    def heartbeat(*_):
        refreshed = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(timespec="seconds")
        with store.connect() as db:
            db.execute("UPDATE routines SET lease_until=? WHERE id=?", (refreshed, routine_id))
    try:
        operation = row["operation"]
        client = Ollama(options["base_url"], options["model"], options["timeout"])
        if operation in {"organize_ai", "organize_types"}:
            plan_id = organize(store, row["root"], client=client if operation == "organize_ai" else None,
                               limit=options["limit"], exclude=exclude, progress=heartbeat)
            count = len(store.actions(plan_id=plan_id, status="pending"))
            message = f"Created {count} proposed moves; approval required"
        elif operation == "duplicates":
            plan_id = duplicates(store, row["root"], limit=options["limit"], exclude=exclude, progress=heartbeat)
            count = len(store.actions(plan_id=plan_id, status="pending"))
            message = f"Created {count} proposed cleanups; approval required"
        elif operation == "summarize_folder":
            report = scan_folder(root_path(row["root"]), limit=options["limit"], exclude=exclude)
            added, reused, skipped = 0, 0, len(report.skipped)
            for path in report.files:
                heartbeat()
                if path.suffix.lower() not in READABLE:
                    skipped += 1
                    continue
                try:
                    text = extract_file(path)
                except (ValueError, OSError) as exc:
                    skipped += 1
                    store.event("routine_document", "skipped", f"{path.name}: {exc}", {"routine_id": routine_id})
                    continue
                _, cached = summarize(store, client, text, path.name, heartbeat)
                reused += int(cached)
                added += int(not cached)
            message = f"Saved {added} new summaries; reused {reused}; skipped {skipped}" + ("; scan limit reached" if report.limited else "")
        else:
            raise ValueError("Unsupported routine operation.")
        status = "success"
    except Exception as exc:
        status, message = "failed", str(exc)[:600]
    next_run = (datetime.now(timezone.utc) + timedelta(minutes=row["interval_minutes"])).isoformat(timespec="seconds")
    with store.connect() as db:
        db.execute("UPDATE routines SET last_status=?,next_run=?,lease_until=NULL WHERE id=?", (message, next_run, routine_id))
        store.event("routine", status, message, {"routine_id": routine_id}, db)
    return {"status": status, "message": message}


def run_due(store: Store, *, exclude: Path | None = None) -> list[dict]:
    due = store.all("SELECT id FROM routines WHERE enabled=1 AND next_run<=? ORDER BY next_run", (now(),))
    return [run_routine(store, row["id"], exclude=exclude) for row in due]
