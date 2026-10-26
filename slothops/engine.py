"""Plan first, approve exact actions, revalidate, then move without overwriting."""

from __future__ import annotations

from collections import defaultdict
import json
import os
from pathlib import Path
from uuid import uuid4

from .ai import Ollama
from .files import (READABLE, SafetyError, extract_file, fingerprint, identity,
                    root_path, safe_path, scan_folder, type_category, verify)
from .storage import Store, encode, now


def move_exclusive(source: Path, target: Path):
    """Move without replacing a file (Windows rename, POSIX exclusive link/unlink).

    The short-lived extra hard link is removed if unlinking the source fails.
    Unsupported filesystems fail safely instead of falling back to overwrite-prone moves.
    """
    if target.exists() or target.is_symlink():
        raise SafetyError("The destination already exists. Nothing was overwritten.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # Windows os.rename raises FileExistsError if the destination exists.
        # Extended paths also support deeply nested quarantine destinations.
        def extended(path: Path) -> str:
            value = str(path.absolute())
            if value.startswith("\\\\?\\"):
                return value
            if value.startswith("\\\\"):
                return "\\\\?\\UNC\\" + value[2:]
            return "\\\\?\\" + value
        os.rename(extended(source), extended(target))
        return
    os.link(source, target, follow_symlinks=False)
    try:
        source.unlink()
    except BaseException:
        if source.exists() and target.exists() and os.path.samefile(source, target):
            target.unlink()
        raise


def _reserve(root: Path, relative: Path, occupied: set[str]) -> Path:
    candidate = safe_path(root, relative, internal=True)
    index = 1
    while str(candidate).casefold() in occupied or candidate.exists():
        candidate = safe_path(root, relative.with_name(f"{relative.stem}__{index}{relative.suffix}"), internal=True)
        index += 1
    occupied.add(str(candidate).casefold())
    return candidate


def _active_sources(store: Store) -> set[tuple[str, str]]:
    rows = store.all("SELECT source,snapshot FROM actions WHERE status IN ('pending','running','restoring')")
    return {(row["source"].casefold(), json.loads(row["snapshot"])["sha256"]) for row in rows}


def _save_plan(store: Store, plan_id: str, title: str, operation: str, root: Path, metadata: dict, actions: list[dict]):
    with store.connect() as db:
        db.execute("INSERT INTO plans VALUES(?,?,?,?,?,?)", (plan_id, title, operation, str(root), now(), encode(metadata)))
        for action in actions:
            db.execute("""INSERT INTO actions(id,plan_id,kind,source,target,snapshot,keeper,keeper_snapshot,reason,estimated_seconds)
                          VALUES(?,?,?,?,?,?,?,?,?,?)""", (
                action["id"], plan_id, action["kind"], str(action["source"]), str(action["target"]),
                encode(action["snapshot"]), str(action["keeper"]) if action.get("keeper") else None,
                encode(action["keeper_snapshot"]) if action.get("keeper_snapshot") else None,
                action["reason"], action["estimated_seconds"]))
        store.event("plan", "success", f"{title}: {len(actions)} actions awaiting approval", {"plan_id": plan_id, **metadata}, db)


def organize(store: Store, folder: str | Path, *, client: Ollama | None = None,
             limit: int = 100, exclude: Path | None = None, progress=None) -> str:
    root = root_path(folder)
    if client:
        client.ready()
    report = scan_folder(root, limit=limit, skip_organized=True, exclude=exclude)
    plan_id, actions, active = uuid4().hex, [], _active_sources(store)
    occupied = {row["target"].casefold() for row in store.all("SELECT target FROM actions WHERE status IN ('pending','running')")}
    skipped = list(report.skipped)
    for index, path in enumerate(report.files):
        if progress:
            progress(index, len(report.files), f"Classifying {path.name}…")
        before = fingerprint(path)
        if (str(path).casefold(), before["sha256"]) in active:
            skipped.append(f"{path.name}: already has an active approval")
            continue
        if client and path.suffix.lower() in READABLE:
            try:
                # Classification uses a clearly disclosed excerpt; summaries read the full input.
                text = extract_file(path)
                category, reason = client.classify(text)
                reason = f"Ollama · {client.model} · first 6,000 characters: {reason}"
            except ValueError as exc:
                # Extraction failures are explicit file-type rules, never presented as AI output.
                category, reason = type_category(path), f"File type rule; text unavailable: {exc}"
        else:
            category, reason = type_category(path), "File type rule (no AI): " + (path.suffix or "no extension")
        verify(safe_path(root, path), before)
        target = _reserve(root, Path("Organized") / category / path.name, occupied)
        actions.append({"id": uuid4().hex, "kind": "move", "source": path, "target": target,
                        "snapshot": before, "reason": reason, "estimated_seconds": 30.0})
    _save_plan(store, plan_id, "Organize folder", "organize_ai" if client else "organize_types", root,
               {"root_identity": identity(root), "scanned": len(report.files), "limited": report.limited,
                "skipped": skipped, "model": client.model if client else None}, actions)
    return plan_id


def duplicates(store: Store, folder: str | Path, *, limit: int = 500, exclude: Path | None = None, progress=None) -> str:
    root = root_path(folder)
    report = scan_folder(root, limit=limit, exclude=exclude)
    by_size, by_hash = defaultdict(list), defaultdict(list)
    for path in report.files:
        by_size[path.stat().st_size].append(path)
    candidates = [path for group in by_size.values() if len(group) > 1 for path in group]
    for index, path in enumerate(candidates):
        if progress:
            progress(index, len(candidates), f"Comparing contents: {path.name}…")
        snapshot = fingerprint(safe_path(root, path))
        by_hash[snapshot["sha256"]].append((path, snapshot))
    plan_id, actions, active = uuid4().hex, [], _active_sources(store)
    occupied = set()
    groups = 0
    for digest, group in sorted(by_hash.items()):
        if len(group) < 2:
            continue
        group.sort(key=lambda item: (len(item[0].relative_to(root).parts), str(item[0]).casefold()))
        keeper, keeper_snapshot = group[0]
        groups += 1
        for path, snapshot in group[1:]:
            if (str(path).casefold(), digest) in active:
                report.skipped.append(f"{path.name}: already has an active approval")
                continue
            target = _reserve(root, Path(".slothops") / "quarantine" / plan_id / path.relative_to(root), occupied)
            actions.append({"id": uuid4().hex, "kind": "quarantine", "source": path, "target": target,
                            "snapshot": snapshot, "keeper": keeper, "keeper_snapshot": keeper_snapshot,
                            "reason": f"Identical SHA-256; keep {keeper.relative_to(root)}. Recoverable cleanup, no permanent deletion.",
                            "estimated_seconds": 20.0})
    _save_plan(store, plan_id, "Clean up duplicates", "duplicates", root,
               {"root_identity": identity(root), "scanned": len(report.files), "limited": report.limited,
                "groups": groups, "skipped": report.skipped,
                "recoverable_bytes": sum(a["snapshot"]["size"] for a in actions)}, actions)
    return plan_id


def _root_for(action: dict) -> Path:
    root = root_path(action["root"])
    expected = json.loads(action["metadata"])["root_identity"]
    if identity(root) != expected:
        raise SafetyError("The approved root folder was replaced. Create a fresh plan.")
    return root


def execute(store: Store, action_ids: list[str], *, approved: bool = False) -> dict:
    if approved is not True:
        raise SafetyError("Explicit approval is required before changing files.")
    results = {"done": 0, "failed": 0, "skipped": 0, "errors": []}
    for action_id in dict.fromkeys(action_ids):
        action = store.one(
            "SELECT a.*,p.root,p.metadata FROM actions a JOIN plans p ON a.plan_id=p.id WHERE a.id=?", (action_id,))
        if not action:
            results["skipped"] += 1
            continue
        with store.connect() as db:
            claimed = db.execute("UPDATE actions SET status='running',error=NULL WHERE id=? AND status='pending'", (action_id,)).rowcount
            if claimed:
                store.event("approval", "approved", "Approved exact file action", {"action_id": action_id, "source": action["source"], "target": action["target"]}, db)
        if not claimed:
            results["skipped"] += 1
            continue
        try:
            root = _root_for(action)
            source = safe_path(root, action["source"])
            target = safe_path(root, action["target"], internal=action["kind"] == "quarantine")
            if action["kind"] not in {"move", "quarantine"}:
                raise SafetyError("Unsupported file action.")
            verify(source, json.loads(action["snapshot"]))
            if action["kind"] == "quarantine":
                keeper = safe_path(root, action["keeper"])
                verify(keeper, json.loads(action["keeper_snapshot"]))
                if fingerprint(keeper)["sha256"] != fingerprint(source)["sha256"]:
                    raise SafetyError("The retained copy no longer matches.")
            # Validate every newly created destination component before dispatch.
            target.parent.mkdir(parents=True, exist_ok=True)
            safe_path(root, target, internal=action["kind"] == "quarantine")
            move_exclusive(source, target)
            with store.connect() as db:
                db.execute("UPDATE actions SET status='done',finished_at=? WHERE id=? AND status='running'", (now(), action_id))
                store.event(action["kind"], "success", f"Moved {source.name}", {"action_id": action_id, "source": str(source), "target": str(target)}, db)
            results["done"] += 1
        except Exception as exc:
            message = str(exc)[:600]
            with store.connect() as db:
                db.execute("UPDATE actions SET status='failed',error=?,finished_at=? WHERE id=?", (message, now(), action_id))
                store.event("file_action", "failed", message, {"action_id": action_id}, db)
            results["failed"] += 1
            results["errors"].append(f"{Path(action['source']).name}: {message}")
    return results


def reject(store: Store, action_ids: list[str]):
    with store.connect() as db:
        count = 0
        for action_id in dict.fromkeys(action_ids):
            count += db.execute("UPDATE actions SET status='rejected',finished_at=? WHERE id=? AND status='pending'", (now(), action_id)).rowcount
        store.event("approval", "rejected", f"Rejected {count} planned actions", {}, db)
    return count


def restore(store: Store, action_id: str, *, approved: bool = False):
    if approved is not True:
        raise SafetyError("Approve the restore before changing files.")
    action = store.one("SELECT a.*,p.root,p.metadata FROM actions a JOIN plans p ON a.plan_id=p.id WHERE a.id=?", (action_id,))
    if not action or action["status"] != "done":
        raise SafetyError("Only completed file actions can be restored.")
    with store.connect() as db:
        if not db.execute("UPDATE actions SET status='restoring' WHERE id=? AND status='done'", (action_id,)).rowcount:
            raise SafetyError("This action is already being changed in another session.")
        store.event("restore", "approved", "Approved restoring a file", {"action_id": action_id}, db)
    try:
        root = _root_for(action)
        current = safe_path(root, action["target"], internal=action["kind"] == "quarantine")
        original = safe_path(root, action["source"])
        verify(current, json.loads(action["snapshot"]), content_only=True)
        if original.exists():
            raise SafetyError("The original path is occupied. Restore will never overwrite it.")
        original.parent.mkdir(parents=True, exist_ok=True)
        safe_path(root, original)
        move_exclusive(current, original)
        with store.connect() as db:
            db.execute("UPDATE actions SET status='restored',error=NULL,finished_at=? WHERE id=?", (now(), action_id))
            store.event("restore", "success", f"Restored {original.name}", {"action_id": action_id}, db)
    except Exception as exc:
        with store.connect() as db:
            db.execute("UPDATE actions SET status='done',error=? WHERE id=?", (str(exc)[:600], action_id))
            store.event("restore", "failed", str(exc)[:600], {"action_id": action_id}, db)
        raise


def reconcile(store: Store, action_id: str):
    """Read-only file inspection after interruption; never replay a filesystem write."""
    action = store.one("SELECT a.*,p.root,p.metadata FROM actions a JOIN plans p ON a.plan_id=p.id WHERE a.id=?", (action_id,))
    if not action or action["status"] not in {"running", "restoring", "failed"}:
        raise SafetyError("No interrupted action to inspect.")
    root = _root_for(action)
    source = safe_path(root, action["source"])
    target = safe_path(root, action["target"], internal=action["kind"] == "quarantine")
    restoring = action["status"] == "restoring"
    if restoring:
        source, target = target, source
    if source.exists() or not target.exists():
        raise SafetyError("A completed move cannot be verified. Review both paths manually; no success or savings was recorded.")
    verify(target, json.loads(action["snapshot"]), content_only=True)
    status = "restored" if restoring else "done"
    with store.connect() as db:
        db.execute("UPDATE actions SET status=?,error=NULL,finished_at=? WHERE id=? AND status=?", (status, now(), action_id, action["status"]))
        store.event("recovery", "success", "Verified completed filesystem state after interruption", {"action_id": action_id, "status": status}, db)
    return status
