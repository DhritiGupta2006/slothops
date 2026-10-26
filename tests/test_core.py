import io
import json
import os
from pathlib import Path
import zipfile

import pytest
import requests

from slothops.ai import AIError, Ollama, chunks, local_url, summarize, validate_summary
from slothops.demo import MEETING, create_demo
from slothops.engine import duplicates, execute, organize, reconcile, reject, restore
from slothops.files import SafetyError, extract_bytes, fingerprint, safe_path, scan_folder
from slothops.routines import create_routine, run_due, run_routine, toggle_routine
from slothops.storage import Store


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    return root, Store(tmp_path / "state" / "slothops.sqlite3")


def put(root, name, text="sample"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_preview_never_moves_and_never_credits(workspace):
    root, store = workspace
    source = put(root, "note.txt")
    plan = organize(store, root)
    assert source.exists()
    assert not (root / "Organized").exists()
    assert store.metrics() == {"completed": 0, "files": 0, "summaries": 0, "minutes_saved": 0.0, "pending": 1, "attention": 0}
    assert len(store.actions(plan_id=plan)) == 1


def test_execution_requires_approval(workspace):
    root, store = workspace
    source = put(root, "note.txt")
    plan = organize(store, root)
    with pytest.raises(SafetyError):
        execute(store, [store.actions(plan_id=plan)[0]["id"]])
    assert source.exists()


def test_move_exactly_once_and_restore(workspace):
    root, store = workspace
    source = put(root, "note.txt", "original content")
    plan = organize(store, root)
    action = store.actions(plan_id=plan)[0]
    assert execute(store, [action["id"], action["id"]], approved=True)["done"] == 1
    assert not source.exists()
    assert Path(action["target"]).read_text() == "original content"
    assert store.metrics()["files"] == 1
    assert execute(store, [action["id"]], approved=True)["skipped"] == 1
    restore(store, action["id"], approved=True)
    assert source.read_text() == "original content"
    assert store.metrics()["completed"] == 0


def test_changed_source_fails_without_credit(workspace):
    root, store = workspace
    source = put(root, "note.txt", "old")
    plan = organize(store, root)
    action = store.actions(plan_id=plan)[0]
    source.write_text("new", encoding="utf-8")
    assert execute(store, [action["id"]], approved=True)["failed"] == 1
    assert source.read_text() == "new"
    assert not Path(action["target"]).exists()
    assert store.metrics()["completed"] == 0


def test_collision_never_overwrites(workspace):
    root, store = workspace
    put(root, "note.txt", "incoming")
    plan = organize(store, root)
    action = store.actions(plan_id=plan)[0]
    target = Path(action["target"])
    put(root, str(target.relative_to(root)), "existing")
    assert execute(store, [action["id"]], approved=True)["failed"] == 1
    assert target.read_text() == "existing"
    assert (root / "note.txt").read_text() == "incoming"


def test_existing_filename_gets_unique_target(workspace):
    root, store = workspace
    put(root, "one/note.txt", "one")
    put(root, "two/note.txt", "two")
    plan = organize(store, root)
    actions = store.actions(plan_id=plan)
    assert len({row["target"] for row in actions}) == 2
    assert execute(store, [row["id"] for row in actions], approved=True)["done"] == 2


def test_duplicates_compare_hash_not_name_or_size(workspace):
    root, store = workspace
    put(root, "keep.txt", "same")
    put(root, "copy/renamed.bin", "same")
    put(root, "different.txt", "diff")
    plan = duplicates(store, root)
    actions = store.actions(plan_id=plan)
    assert len(actions) == 1
    action = actions[0]
    assert action["kind"] == "quarantine"
    assert execute(store, [action["id"]], approved=True)["done"] == 1
    assert Path(action["keeper"]).exists()
    assert Path(action["target"]).read_text() == "same"
    restore(store, action["id"], approved=True)
    assert Path(action["source"]).exists()


def test_duplicate_keeper_changed_blocks_cleanup(workspace):
    root, store = workspace
    put(root, "a.txt", "same")
    put(root, "b.txt", "same")
    plan = duplicates(store, root)
    action = store.actions(plan_id=plan)[0]
    Path(action["keeper"]).write_text("changed")
    assert execute(store, [action["id"]], approved=True)["failed"] == 1
    assert Path(action["source"]).exists()


def test_pending_plans_do_not_duplicate_approvals(workspace):
    root, store = workspace
    put(root, "a.txt")
    organize(store, root)
    organize(store, root)
    assert store.metrics()["pending"] == 1


def test_rejection_changes_no_files(workspace):
    root, store = workspace
    source = put(root, "a.txt")
    plan = organize(store, root)
    assert reject(store, [store.actions(plan_id=plan)[0]["id"]]) == 1
    assert source.exists()
    assert store.metrics()["completed"] == 0


def test_restore_never_overwrites_replacement(workspace):
    root, store = workspace
    source = put(root, "a.txt", "old")
    plan = organize(store, root)
    action = store.actions(plan_id=plan)[0]
    execute(store, [action["id"]], approved=True)
    source.write_text("replacement")
    with pytest.raises(SafetyError):
        restore(store, action["id"], approved=True)
    assert source.read_text() == "replacement"
    assert Path(action["target"]).read_text() == "old"


def test_restore_refuses_modified_content(workspace):
    root, store = workspace
    put(root, "a.txt")
    plan = organize(store, root)
    action = store.actions(plan_id=plan)[0]
    execute(store, [action["id"]], approved=True)
    Path(action["target"]).write_text("edited after move")
    with pytest.raises(SafetyError):
        restore(store, action["id"], approved=True)


def test_root_escape_and_internal_paths_blocked(workspace):
    root, _ = workspace
    for value in [root.parent / "outside.txt", root / ".." / "outside.txt", root / ".slothops" / "private.txt"]:
        with pytest.raises(SafetyError):
            safe_path(root, value)


def test_hardlinks_are_excluded(workspace):
    root, store = workspace
    a = put(root, "a.txt")
    try:
        os.link(a, root / "b.txt")
    except OSError:
        pytest.skip("Filesystem does not support hard links")
    assert not scan_folder(root).files
    with pytest.raises(SafetyError):
        fingerprint(a)


def test_symlink_cannot_escape(workspace):
    root, store = workspace
    outside = put(root.parent, "outside.txt", "private")
    try:
        (root / "link.txt").symlink_to(outside)
    except OSError:
        pytest.skip("Windows symbolic link privilege is unavailable")
    assert not scan_folder(root).files
    with pytest.raises(SafetyError):
        safe_path(root, root / "link.txt")


def test_scan_limit_is_explicit(workspace):
    root, store = workspace
    put(root, "a.txt")
    put(root, "b.txt")
    plan = organize(store, root, limit=1)
    metadata = json.loads(store.one("SELECT metadata FROM plans WHERE id=?", (plan,))["metadata"])
    assert metadata["limited"] is True
    assert metadata["scanned"] == 1


def test_demo_has_real_duplicates_and_no_metrics(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    root = create_demo(tmp_path / "samples")
    plan = duplicates(store, root, exclude=tmp_path)
    assert len(store.actions(plan_id=plan)) == 2
    assert store.metrics()["completed"] == 0


def test_interrupted_move_can_be_reconciled(workspace):
    root, store = workspace
    source = put(root, "a.txt")
    plan = organize(store, root)
    action = store.actions(plan_id=plan)[0]
    target = Path(action["target"])
    target.parent.mkdir(parents=True)
    source.rename(target)
    with store.connect() as db:
        db.execute("UPDATE actions SET status='running' WHERE id=?", (action["id"],))
    assert reconcile(store, action["id"]) == "done"
    assert store.metrics()["files"] == 1


@pytest.mark.parametrize("value", ["https://example.com", "http://127.0.0.1.evil.com", "http://localhost@evil.com", "http://localhost/path", "http://localhost?x=1", "file:///tmp/model"])
def test_remote_ollama_addresses_blocked(value):
    with pytest.raises(AIError):
        local_url(value)


def test_ollama_uses_no_environment_proxy():
    assert Ollama().session.trust_env is False
    assert local_url("http://localhost:11434/") == "http://127.0.0.1:11434"


def test_cloud_models_filtered(monkeypatch):
    client = Ollama()
    monkeypatch.setattr(client, "_request", lambda *a, **k: {"models": [{"name": "local:4b"}, {"name": "big:cloud"}, {"name": "alias", "remote_model": "cloud"}]})
    assert [item["name"] for item in client.models()] == ["local:4b"]


def test_network_failure_is_actionable(monkeypatch):
    client = Ollama()
    def fail(*args, **kwargs):
        raise requests.ConnectionError()
    monkeypatch.setattr(client.session, "request", fail)
    with pytest.raises(AIError, match="Cannot reach Ollama"):
        client.ready()


def test_bad_json_never_becomes_fake_ai(monkeypatch):
    client = Ollama()
    monkeypatch.setattr(client, "_request", lambda *a, **k: {"done": True, "response": "not JSON"})
    with pytest.raises(AIError, match="invalid JSON"):
        client.generate("summarize", "text", {})


def test_unverified_action_evidence_rejected():
    with pytest.raises(AIError, match="source quote"):
        validate_summary({"summary": "A summary", "decisions": [], "actions": [{"task": "Delete everything", "owner": None, "due": None, "evidence": "a made up quote"}]}, MEETING)


def test_chunking_covers_all_text():
    text = ("Long paragraph with details.\n" * 1000) + "IMPORTANT FINAL ACTION"
    parts = chunks(text)
    assert "".join(parts) == text
    assert all(len(part) <= 6000 for part in parts)
    assert parts[-1].endswith("IMPORTANT FINAL ACTION")


class StubOllama:
    """A deterministic test double, never used by the app or integration checks."""
    model = "test-only-stub"
    def ready(self):
        pass
    def generate(self, instruction, text, schema):
        if "overview" in schema["properties"]:
            return {"overview": "Combined test summary"}
        return {"summary": "Test summary", "decisions": [], "actions": []}


def test_summaries_saved_once_per_text_and_model(workspace):
    root, store = workspace
    text = "notes " * 1500
    row, cached = summarize(store, StubOllama(), text, "Test")
    assert not cached
    assert row["chunks"] == 2
    same, cached = summarize(store, StubOllama(), text, "New title")
    assert cached and same["id"] == row["id"]
    assert store.metrics()["summaries"] == 1


def test_failed_ai_records_no_summary_credit(workspace):
    root, store = workspace
    class BadModel(StubOllama):
        def generate(self, *args):
            raise AIError("Model failed")
    with pytest.raises(AIError):
        summarize(store, BadModel(), MEETING, "Failure")
    assert store.metrics()["completed"] == 0
    assert not store.all("SELECT * FROM summaries")


def test_no_silent_document_truncation():
    with pytest.raises(ValueError, match="silently truncated"):
        extract_bytes(b"a" * 100, ".txt", max_chars=20)


def test_docx_extraction():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Meeting note</w:t></w:r></w:p></w:body></w:document>')
    assert extract_bytes(buffer.getvalue(), ".docx") == "Meeting note"


def test_routine_creates_approvals_without_moving(workspace):
    root, store = workspace
    source = put(root, "a.txt")
    routine = create_routine(store, "Tidy", "organize_types", str(root), 60, {})
    result = run_routine(store, routine, force=True)
    assert result["status"] == "success"
    assert source.exists() and store.metrics()["pending"] == 1
    assert store.metrics()["completed"] == 0
    assert run_routine(store, routine)["status"] == "skipped"


def test_paused_routine_does_not_run(workspace):
    root, store = workspace
    put(root, "a.txt")
    routine = create_routine(store, "Tidy", "organize_types", str(root), 1, {})
    toggle_routine(store, routine, False)
    assert run_routine(store, routine, force=True)["status"] == "skipped"
    assert store.metrics()["pending"] == 0


def test_worker_runs_overdue_routine_once(workspace):
    root, store = workspace
    put(root, "a.txt")
    routine = create_routine(store, "Tidy", "organize_types", str(root), 1, {})
    with store.connect() as db:
        db.execute("UPDATE routines SET next_run='2000-01-01T00:00:00+00:00' WHERE id=?", (routine,))
    assert len(run_due(store)) == 1
    assert run_due(store) == []


def test_active_lease_prevents_overlapping_workers(workspace):
    root, store = workspace
    put(root, "a.txt")
    routine = create_routine(store, "Tidy", "organize_types", str(root), 1, {})
    with store.connect() as db:
        db.execute("UPDATE routines SET lease_until='2099-01-01T00:00:00+00:00' WHERE id=?", (routine,))
    assert run_routine(store, routine, force=True)["status"] == "skipped"


def test_unsupported_routine_rejected(workspace):
    root, store = workspace
    with pytest.raises(ValueError):
        create_routine(store, "Bad", "execute_shell", str(root), 60, {})
