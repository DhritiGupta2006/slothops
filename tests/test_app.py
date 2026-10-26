from pathlib import Path

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"


def test_all_pages_render_when_ollama_is_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOTHOPS_DATA_DIR", str(tmp_path / "app-state"))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "Laziness Dashboard"
    assert [m.value for m in app.metric] == ["0", "0.0", "0", "0"]
    for page in ["Folder Organizer", "Duplicate Cleaner", "Meeting Notes", "Approvals", "Recurring Chores", "Activity & Restore", "Settings"]:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, (page, [str(e.value) for e in app.exception])


def test_demo_to_duplicate_preview_is_real_and_non_mutating(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOTHOPS_DATA_DIR", str(tmp_path / "app-state"))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    next(button for button in app.sidebar.button if button.label == "Create demo folder").click().run()
    folder = Path(app.session_state["folder"])
    assert (folder / "team-meeting.txt").exists()
    app.sidebar.radio[0].set_value("Duplicate Cleaner").run()
    next(button for button in app.button if button.label == "Find identical files").click().run()
    assert not app.exception
    assert (folder / "copies" / "team-meeting-copy.txt").exists()
    app.sidebar.radio[0].set_value("Approvals").run()
    assert not app.exception
    assert len(app.multiselect[0].options) == 2
    execute_button = next(button for button in app.button if button.label.startswith("Approve & execute"))
    assert execute_button.disabled
    app.checkbox[0].check().run()
    app.checkbox[1].check().run()
    next(button for button in app.button if button.label.startswith("Approve & execute")).click().run()
    assert not app.exception
    assert not (folder / "copies" / "team-meeting-copy.txt").exists()
    assert (folder / "team-meeting.txt").exists()
    app.sidebar.radio[0].set_value("Laziness Dashboard").run()
    assert app.metric[0].value == "2"
