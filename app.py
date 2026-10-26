"""SlothOps — run with: python -m streamlit run app.py"""

from __future__ import annotations

from datetime import datetime
import html
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from slothops.ai import AIError, Ollama, local_url, summarize, summary_markdown
from slothops.demo import MEETING, create_demo
from slothops.engine import duplicates, execute, organize, reconcile, reject, restore
from slothops.files import SafetyError, extract_bytes, root_path
from slothops.routines import OPERATIONS, create_routine, run_due, run_routine, toggle_routine
from slothops.storage import Store


PROJECT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("SLOTHOPS_DATA_DIR", str(PROJECT / "data"))).expanduser().absolute()
DATA.mkdir(parents=True, exist_ok=True)
STORE = Store(DATA / "slothops.sqlite3")
SETTINGS_FILE = DATA / "settings.json"
PAGES = ["Laziness Dashboard", "Folder Organizer", "Duplicate Cleaner", "Meeting Notes", "Approvals", "Recurring Chores", "Activity & Restore", "Settings"]

st.set_page_config(page_title="SlothOps · Your chores, handled", page_icon="🦥", layout="wide", initial_sidebar_state="expanded")

st.markdown("""<style>
.stApp {background:#111714;}
.block-container {padding-top:2.2rem; padding-bottom:3rem; max-width:1460px;}
[data-testid="stSidebar"] {background:#171f1a; border-right:1px solid #2b382e;}
[data-testid="stSidebar"] .block-container {padding-top:1.8rem;}
h1,h2,h3 {letter-spacing:-.045em !important; font-weight:650 !important;}
h1 {font-size:2.35rem !important;}
h3 {font-size:1.2rem !important;}
[data-testid="stMetric"] {background:#1b241f; border:1px solid #304033; border-radius:17px; padding:20px 23px;}
[data-testid="stMetricValue"] {color:#c0e994; font-size:2.1rem;}
[data-testid="stMetricLabel"] {color:#aab8aa;}
.hero {display:flex; align-items:center; justify-content:space-between; gap:24px; padding:30px 36px; border:1px solid #42553a; border-radius:24px; background:linear-gradient(110deg,#263923,#1a2b20 75%); margin:18px 0 26px;}
.hero h2 {font-size:2.5rem; line-height:1.12; margin:8px 0 14px; color:#f0f5e8;}
.hero p {color:#bdcbb8; max-width:580px; font-size:1rem; line-height:1.65; margin:0;}
.eyebrow {font-size:.72rem; letter-spacing:.17em; color:#b9e37c; font-weight:700; text-transform:uppercase;}
.sloth {font-size:6.3rem; background:#b9d895; width:158px; height:158px; border-radius:50%; display:flex; align-items:center; justify-content:center; transform:rotate(-8deg); flex-shrink:0;}
.brand {font-size:1.65rem; letter-spacing:-.055em; font-weight:750; color:#edf3e9; margin-bottom:2px;}
.brand span {color:#b9e37c;}
.muted {color:#9bad9c; font-size:.88rem; line-height:1.6;}
.prose {white-space:pre-wrap; overflow-wrap:anywhere; font-size:1rem; line-height:1.7; color:#dae4d7;}
.pill {display:inline-block; border:1px solid #3c5138; background:#243220; border-radius:30px; padding:5px 11px; font-size:.73rem; color:#c8e6ae; margin:0 7px 8px 0;}
.step {font-size:.75rem; color:#a3bb8a; font-weight:650; letter-spacing:.09em; margin-bottom:12px;}
.stButton button {border-radius:10px; min-height:42px; font-weight:600;}
[data-testid="stVerticalBlockBorderWrapper"] > div {border-radius:17px;}
div[data-testid="stAlert"] {border-radius:12px;}
footer {visibility:hidden;}
@media(max-width:1000px) {.hero{padding:24px;} .hero h2{font-size:1.85rem;} .sloth{display:none;}}
</style>""", unsafe_allow_html=True)


def prose(value: str):
    # Model/document content is escaped; it cannot load remote Markdown images or HTML.
    st.markdown('<div class="prose">' + html.escape(str(value)) + '</div>', unsafe_allow_html=True)


def load_settings() -> dict:
    defaults = {"base_url": "http://127.0.0.1:11434", "model": "gemma3:4b", "timeout": 300, "folder": ""}
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return {**defaults, **{key: value for key, value in saved.items() if key in defaults}}
    except (OSError, ValueError, TypeError, AttributeError):
        return defaults


SETTINGS = load_settings()


def save_settings(changes: dict):
    updated = {**load_settings(), **changes}
    temporary = SETTINGS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(updated, indent=2), encoding="utf-8")
    temporary.replace(SETTINGS_FILE)


@st.cache_data(ttl=20, show_spinner=False)
def check_ollama(base_url: str) -> tuple[list[str], str]:
    try:
        return [model["name"] for model in Ollama(base_url).models()], ""
    except AIError as exc:
        return [], str(exc)


def client() -> Ollama:
    return Ollama(SETTINGS["base_url"], SETTINGS["model"], int(SETTINGS["timeout"]))


def navigate(page: str):
    st.session_state["page"] = page


def use_demo():
    folder = create_demo(DATA / "samples")
    st.session_state["folder_input"] = str(folder)
    st.session_state["folder"] = str(folder)
    save_settings({"folder": str(folder)})
    st.session_state["notice"] = "Fresh demo files created. No AI results or completed chores were preloaded."


def select_folder():
    try:
        folder = str(root_path(st.session_state["folder_input"]))
        st.session_state["folder"] = folder
        save_settings({"folder": folder})
        st.session_state["notice"] = "Working folder updated."
    except (OSError, ValueError) as exc:
        st.session_state["notice"] = str(exc)


def require_folder() -> str | None:
    folder = st.session_state.get("folder", SETTINGS["folder"])
    if not folder:
        st.info("Choose a folder in the sidebar, or create a demo folder to try SlothOps.")
        st.button("Create a demo folder", on_click=use_demo, key="main_demo")
        return None
    st.caption("Working folder")
    st.code(folder, language=None)
    return folder


def progress_bar():
    bar = st.progress(0, text="Getting ready…")
    def update(index, total, message):
        bar.progress(min(1.0, index / max(1, total)), text=message)
    return bar, update


def table_for_actions(actions: list[dict]) -> pd.DataFrame:
    rows = []
    for action in actions:
        root = Path(action["root"])
        def relative(value):
            try:
                return str(Path(value).relative_to(root)) if value else "—"
            except ValueError:
                return str(value)
        rows.append({"Action": "Move" if action["kind"] == "move" else "Quarantine",
                     "Source": relative(action["source"]), "Destination": relative(action["target"]),
                     "Keep": relative(action["keeper"]), "Reason": action["reason"],
                     "SHA-256": json.loads(action["snapshot"])["sha256"], "Status": action["status"]})
    return pd.DataFrame(rows)


def show_plan(plan_id: str):
    plan = STORE.one("SELECT * FROM plans WHERE id=?", (plan_id,))
    if not plan:
        return
    metadata = json.loads(plan["metadata"])
    actions = STORE.actions(plan_id=plan_id)
    st.subheader("Your preview")
    st.caption(f"{metadata['scanned']} files scanned · {len(actions)} proposed actions · files remain unchanged until approval")
    if metadata.get("limited"):
        st.warning("The scan limit was reached. This preview covers only the scanned files.")
    if actions:
        st.dataframe(table_for_actions(actions), hide_index=True, width="stretch")
        if metadata.get("recoverable_bytes") is not None:
            st.caption(f"{metadata['recoverable_bytes']:,} duplicate bytes can be set aside. Quarantine does not free disk space.")
        st.button("Review in Approvals →", on_click=navigate, args=("Approvals",), key="open_" + plan_id, type="primary")
    else:
        st.success("Nothing new to propose. Files may already be organized or have pending approvals.")
    if metadata.get("skipped"):
        with st.expander(f"Skipped or excluded ({len(metadata['skipped'])})"):
            st.text("\n".join(metadata["skipped"]))


def dashboard():
    st.markdown('<span class="eyebrow">Your personal chore autopilot</span>', unsafe_allow_html=True)
    st.title("Laziness Dashboard")
    st.caption("Less busywork. More doing absolutely anything else.")
    st.markdown('<div class="hero"><div><div class="eyebrow">Slow is a feature.</div><h2>Take a breath.<br>Give your chores to a sloth.</h2><p>Turn folder chaos into a plan, long conversations into clear next steps, and repetitive work into a routine. You stay in control of every file change.</p></div><div class="sloth" aria-label="Sloth">🦥</div></div>', unsafe_allow_html=True)
    metrics = STORE.metrics()
    columns = st.columns(4)
    for column, label, value, help_text in zip(columns,
        ["Chores completed", "Est. minutes saved", "Awaiting approval", "Notes distilled"],
        [metrics["completed"], metrics["minutes_saved"], metrics["pending"], metrics["summaries"]],
        ["Completed file actions plus unique saved summaries. Restored file actions are excluded.",
         "A transparent effort estimate, not a measured productivity claim.",
         "Proposed file actions. Pending work earns no savings credit.", "Unique input text + model pairs; reopening a result earns no extra credit."]):
        column.metric(label, value, help=help_text)
    st.write("")
    st.subheader("What can we take off your plate?")
    for column, step, title, description, page, button in zip(st.columns(3),
        ["01 / LESS CLUTTER", "02 / FEWER REPEATS", "03 / CLEARER THINKING"],
        ["A home for every file", "One copy is plenty", "Skip the wall of text"],
        ["Sort by file type, or let your local model read document excerpts and suggest a category.",
         "Compare file contents with SHA-256. Set identical copies aside with an easy restore.",
         "Get a local summary, decisions, and action items with quotes from the source."],
        ["Folder Organizer", "Duplicate Cleaner", "Meeting Notes"],
        ["Organize a folder →", "Find duplicates →", "Distill my notes →"]):
        with column, st.container(border=True):
            st.markdown(f'<div class="step">{step}</div>', unsafe_allow_html=True)
            st.subheader(title)
            st.caption(description)
            st.button(button, on_click=navigate, args=(page,), width="stretch")
    left, right = st.columns([1.4, 1])
    with left:
        st.subheader("Recent activity")
        events = STORE.all("SELECT at,kind,status,message FROM events ORDER BY id DESC LIMIT 6")
        if events:
            st.dataframe(pd.DataFrame(events), hide_index=True, width="stretch")
        else:
            with st.container(border=True):
                st.markdown("**A clean slate feels good.**")
                st.caption("Your first completed chore will appear here. Start with synthetic demo files to explore safely.")
                st.button("Create fresh demo files", on_click=use_demo)
    with right, st.container(border=True):
        st.subheader("Honest effort estimates")
        st.caption("Each completed move: 30 seconds. Each completed duplicate cleanup: 20 seconds. Summaries: estimated reading time at 200 words/minute (minimum 1 minute), less actual processing time, floored at zero.")
        st.caption("Planning, demo generation, failed actions, and cached summaries add no savings. Restoring a file removes its credit.")
        if metrics["attention"]:
            st.warning(f"{metrics['attention']} actions need attention. See Activity & Restore.")


def organizer_page():
    st.title("A home for every file")
    st.caption("Preview a calmer folder before anything moves.")
    folder = require_folder()
    if not folder:
        return
    with st.container(border=True):
        mode = st.radio("How should SlothOps sort?", ["Local AI document categories", "File type rules (no AI)"], horizontal=True)
        st.caption("AI reads the first 6,000 extracted characters into Work, Finance, Personal, Study, Reference, or Other. Images and unsupported documents use clearly labeled file type rules. Organized and internal folders are excluded.")
        limit = st.slider("Maximum files in this scan", 1, 500, 25)
        if st.button("Build organizer preview", type="primary"):
            bar, update = progress_bar()
            try:
                plan_id = organize(STORE, folder, client=client() if mode.startswith("Local") else None, limit=limit, exclude=DATA, progress=update)
                st.session_state["organizer_plan"] = plan_id
                bar.progress(1.0, text="Preview ready. No files moved.")
            except Exception as exc:
                bar.empty()
                st.error(str(exc))
    if st.session_state.get("organizer_plan"):
        show_plan(st.session_state["organizer_plan"])


def duplicates_page():
    st.title("One copy is plenty")
    st.caption("Same content, different names? Let's compare the actual bytes.")
    folder = require_folder()
    if not folder:
        return
    st.info("Cleanup is recoverable: approved duplicates move to .slothops/quarantine inside this folder. The retained copy is checked again before every move. Disk space is not freed.")
    limit = st.slider("Maximum files to compare", 1, 500, 100)
    if st.button("Find identical files", type="primary"):
        bar, update = progress_bar()
        try:
            st.session_state["duplicates_plan"] = duplicates(STORE, folder, limit=limit, exclude=DATA, progress=update)
            bar.progress(1.0, text="Comparison complete. No files moved.")
        except Exception as exc:
            bar.empty()
            st.error(str(exc))
    if st.session_state.get("duplicates_plan"):
        show_plan(st.session_state["duplicates_plan"])


def display_summary(row: dict):
    result = json.loads(row["result"])
    st.subheader("The useful version")
    prose(row["title"])
    st.caption(f"{row['model']} · {row['input_chars']:,} characters · {row['chunks']} sections · {row['elapsed_seconds']:.1f}s processing")
    with st.container(border=True):
        prose(result["overview"])
    st.subheader("Decisions")
    if result["decisions"]:
        for decision in result["decisions"]:
            prose("• " + decision)
    else:
        st.caption("No explicit decisions extracted.")
    st.subheader("Action items")
    for index, action in enumerate(result["actions"], 1):
        with st.container(border=True):
            prose(f"{index}. {action['task']}")
            prose(f"Owner: {action['owner'] or 'Unassigned'}  ·  Due: {action['due'] or 'Not stated'}")
            with st.expander(f"Source quote · section {action['section']}"):
                prose(action["evidence"])
    if not result["actions"]:
        st.caption("No concrete action items extracted.")
    st.caption("AI output can be mistaken. Quotes are matched to the input; review task wording, owners, and dates before acting. Extracted tasks are never executed automatically.")
    if row["chunks"] > 1:
        with st.expander("Read every section summary"):
            for section in result["sections"]:
                st.markdown(f"**Section {section['section']}**")
                prose(section["summary"])
    col1, col2 = st.columns(2)
    col1.download_button("Download Markdown", summary_markdown(row), file_name="slothops-summary.md", mime="text/markdown", key="md_" + row["id"])
    col2.download_button("Download action items JSON", json.dumps(result, indent=2, ensure_ascii=False), file_name="slothops-actions.json", mime="application/json", key="json_" + row["id"])


def notes_page():
    st.title("Skip the wall of text")
    st.caption("Local summaries, explicit decisions, and the next steps hiding in your notes.")
    write_tab, library_tab = st.tabs(["Distill notes", "Saved summaries"])
    with write_tab:
        title = st.text_input("Summary title", value="Meeting recap")
        source = st.radio("Input", ["Paste text", "Upload a document"], horizontal=True)
        text = ""
        if source == "Paste text":
            if st.button("Load sample meeting"):
                st.session_state["notes_text"] = MEETING
            text = st.text_area("Conversation, meeting notes, or document text", height=230, key="notes_text", placeholder="Paste the conversation you would rather not reread…")
        else:
            uploaded = st.file_uploader("Choose a text document", type=["txt", "md", "csv", "json", "log", "pdf", "docx"])
            if uploaded:
                try:
                    text = extract_bytes(uploaded.getvalue(), Path(uploaded.name).suffix)
                    st.caption(f"Extracted {len(text):,} characters. Scanned PDFs need OCR before import.")
                except Exception as exc:
                    st.error(str(exc))
        st.caption("Up to 240,000 characters, processed in sections. Original text is sent only to your local Ollama server. Saved results and source quotes remain in local SQLite.")
        if st.button("Summarize with local AI", type="primary", disabled=not text.strip()):
            bar, update = progress_bar()
            try:
                row, cached = summarize(STORE, client(), text, title, update)
                st.session_state["summary_id"] = row["id"]
                bar.progress(1.0, text="Retrieved saved result." if cached else "Summary saved locally.")
                if cached:
                    st.info("This text and model already have a saved result. No extra task or savings credit was added.")
            except Exception as exc:
                bar.empty()
                st.error(str(exc))
        if st.session_state.get("summary_id"):
            row = STORE.one("SELECT * FROM summaries WHERE id=?", (st.session_state["summary_id"],))
            if row:
                display_summary(row)
    with library_tab:
        rows = STORE.all("SELECT * FROM summaries ORDER BY created_at DESC")
        if rows:
            lookup = {row["id"]: row for row in rows}
            selected = st.selectbox("Saved result", list(lookup), format_func=lambda key: lookup[key]["title"] + " · " + lookup[key]["created_at"], key="saved_summary")
            if selected != st.session_state.get("summary_id"):
                display_summary(lookup[selected])
            else:
                st.caption("This result is shown in the Distill notes tab.")
        else:
            st.info("Your saved summaries will appear here after a successful local AI run.")


def approvals_page():
    st.title("You have the final say")
    st.caption("Review exactly what will change. Approve the actions you want; reject the rest.")
    pending = STORE.actions(status="pending")
    if not pending:
        st.success("All clear. No file actions are awaiting approval.")
        return
    plans = {action["plan_id"]: f"{action['title']} · {action['plan_id'][:8]} · {action['root']}" for action in pending}
    chosen = st.selectbox("Plan to review", list(plans), format_func=plans.get)
    actions = [action for action in pending if action["plan_id"] == chosen]
    st.code(actions[0]["root"], language=None)
    st.dataframe(table_for_actions(actions), hide_index=True, width="stretch")
    lookup = {action["id"]: action for action in actions}
    selected = st.multiselect("Choose actions to approve or reject", list(lookup),
        format_func=lambda key: f"{Path(lookup[key]['source']).relative_to(lookup[key]['root'])} → {Path(lookup[key]['target']).relative_to(lookup[key]['root'])}", key="pick_" + chosen)
    all_actions = st.checkbox(f"Select all {len(actions)} actions in this plan", key="all_" + chosen)
    ids = list(lookup) if all_actions else selected
    confirmed = st.checkbox("I reviewed these source, destination, and retained-copy paths.", key="confirm_" + chosen)
    left, right = st.columns(2)
    if left.button(f"Approve & execute {len(ids)} actions", type="primary", disabled=not ids or not confirmed, width="stretch"):
        with st.spinner("Checking file contents and executing approved actions…"):
            result = execute(STORE, ids, approved=True)
        st.session_state["notice"] = f"Completed {result['done']} actions; {result['failed']} failed safely; {result['skipped']} already handled."
        if result["errors"]:
            st.session_state["action_errors"] = result["errors"]
        st.rerun()
    if right.button("Reject selected actions", disabled=not ids, width="stretch"):
        count = reject(STORE, ids)
        st.session_state["notice"] = f"Rejected {count} actions. No files changed."
        st.rerun()
    st.caption("Every source hash and retained copy is checked again. Changed files and occupied destinations fail safely. A plan earns no savings until an action completes.")


def local_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d %b %Y, %H:%M %Z")
    except ValueError:
        return value


def routines_page():
    st.title("Put chores on repeat")
    st.caption("A little setup. A lot less remembering.")
    st.info("Routines run while this app has an open browser tab, or while the optional worker is running. After sleep or downtime, each overdue routine runs once. File changes always wait for your approval.")
    folder = st.session_state.get("folder", SETTINGS["folder"])
    with st.expander("Create a recurring chore", expanded=True), st.form("routine_form"):
        name = st.text_input("Chore name", placeholder="Tidy my downloads every morning")
        operation = st.selectbox("Supported operation", list(OPERATIONS), format_func=OPERATIONS.get)
        target = st.text_input("Folder for this routine", value=folder)
        interval = st.selectbox("Repeat every", [60, 360, 1440, 10080, 1], format_func=lambda value: {1: "1 minute (testing)", 60: "1 hour", 360: "6 hours", 1440: "1 day", 10080: "1 week"}[value], index=2)
        limit = st.number_input("Maximum files per run", min_value=1, max_value=500, value=50)
        st.caption("AI chores save the current model and connection settings. No shell commands, email, or arbitrary model-generated code are supported.")
        if st.form_submit_button("Create recurring chore", type="primary"):
            try:
                create_routine(STORE, name, operation, target, interval, {**SETTINGS, "limit": limit})
                st.success("Routine saved. Use Run now below for its first run, or wait for the next scheduled time.")
            except Exception as exc:
                st.error(str(exc))
    rows = STORE.all("SELECT * FROM routines ORDER BY name")
    if not rows:
        return
    st.subheader("Your routines")
    for row in rows:
        with st.container(border=True):
            prose(row["name"])
            st.caption(OPERATIONS.get(row["operation"], row["operation"]))
            st.text(row["root"])
            st.caption(f"{'Enabled' if row['enabled'] else 'Paused'} · every {row['interval_minutes']} min · next: {local_time(row['next_run'])}")
            prose(row["last_status"])
            col1, col2 = st.columns(2)
            if col1.button("Run now", key="run_" + row["id"], disabled=not row["enabled"]):
                with st.spinner("Running supported chore locally…"):
                    result = run_routine(STORE, row["id"], force=True, exclude=DATA)
                st.session_state["notice"] = result["message"]
                st.rerun()
            if col2.button("Pause" if row["enabled"] else "Resume", key="toggle_" + row["id"]):
                toggle_routine(STORE, row["id"], not bool(row["enabled"]))
                st.rerun()
    with st.expander("Run routines with the browser closed"):
        st.caption("Start the optional worker from the SlothOps folder. Leave it running; closing the worker stops scheduling. Nothing is installed as a Windows startup task.")
        st.code('.venv\\Scripts\\python.exe -m slothops.worker', language="powershell")


def activity_page():
    st.title("A trail you can trust")
    st.caption("Inspect what happened, recover after an interruption, or put a file back.")
    history_tab, restore_tab, recovery_tab = st.tabs(["Activity log", "Restore files", "Needs attention"])
    with history_tab:
        events = STORE.all("SELECT * FROM events ORDER BY id DESC LIMIT 1000")
        st.caption("Latest 1,000 events. All events remain in SQLite.")
        if events:
            data = pd.DataFrame(events)
            st.dataframe(data.drop(columns=["detail"]), hide_index=True, width="stretch")
            st.download_button("Download audit JSON", json.dumps(events, ensure_ascii=False, indent=2), "slothops-audit.json", "application/json")
        else:
            st.info("No activity yet.")
    with restore_tab:
        actions = STORE.actions(status="done")
        if not actions:
            st.info("Completed file moves and quarantine actions will appear here.")
        else:
            lookup = {action["id"]: action for action in actions}
            chosen = st.selectbox("File to restore", list(lookup), format_func=lambda key: lookup[key]["source"] + " · " + lookup[key]["kind"])
            row = lookup[chosen]
            st.caption("Current location → original location")
            st.code(row["target"] + "\n→ " + row["source"], language=None)
            confirmed = st.checkbox("Restore this file to its original path", key="restore_" + chosen)
            if st.button("Restore file", disabled=not confirmed, type="primary"):
                try:
                    restore(STORE, chosen, approved=True)
                    st.session_state["notice"] = "File restored. Its estimated savings credit was removed."
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
    with recovery_tab:
        actions = [action for action in STORE.actions() if action["status"] in {"failed", "running", "restoring"}]
        if not actions:
            st.success("No failed or interrupted actions.")
        for action in actions:
            with st.container(border=True):
                prose(Path(action["source"]).name + " · " + action["status"])
                st.code(action["source"] + "\n→ " + action["target"], language=None)
                if action["error"]:
                    prose(action["error"])
                st.caption("If the app was interrupted after a move, inspect its actual state. This check never moves a file. Otherwise, build a fresh preview after resolving the cause.")
                if st.button("Inspect completed move", key="inspect_" + action["id"]):
                    try:
                        status = reconcile(STORE, action["id"])
                        st.session_state["notice"] = f"Filesystem state verified: {status}."
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))


def settings_page():
    st.title("Keep it local")
    st.caption("Your model. Your folders. Your pace.")
    names, error = check_ollama(SETTINGS["base_url"])
    with st.form("settings"):
        address = st.text_input("Local Ollama address", value=SETTINGS["base_url"])
        choices = names or [SETTINGS["model"]]
        selected = st.selectbox("Downloaded local model", choices, index=choices.index(SETTINGS["model"]) if SETTINGS["model"] in choices else 0)
        timeout = st.number_input("Model timeout (seconds per request)", 30, 600, int(SETTINGS["timeout"]), step=30)
        if st.form_submit_button("Save local settings", type="primary"):
            try:
                local_url(address)
                save_settings({"base_url": address, "model": selected, "timeout": timeout})
                check_ollama.clear()
                st.rerun()
            except AIError as exc:
                st.error(str(exc))
    if error:
        st.warning(error)
    else:
        st.success(f"Ollama is reachable · {len(names)} downloaded local models found")
    col1, col2 = st.columns(2)
    if col1.button("Refresh connection"):
        check_ollama.clear()
        st.rerun()
    if col2.button("Test selected model"):
        try:
            with st.spinner("Checking a real local inference…"):
                active = client()
                active.ready()
                category, _ = active.classify("INVOICE 1042. Payment for design services is due Friday.")
            st.success(f"Real Ollama response received · category: {category}. No productivity credit added.")
        except AIError as exc:
            st.error(str(exc))
    with st.expander("Ollama setup and privacy", expanded=bool(error)):
        st.markdown("1. Open the Ollama Windows app, or run `ollama serve`.\n2. Download a local model once: `ollama pull gemma3:4b`.\n3. Refresh the connection, select the downloaded model, and save.")
        st.caption("Only loopback addresses are accepted. Redirects and environment proxies are disabled. Cloud-tagged models are excluded. Model licenses are separate from the app's MIT license. After installing dependencies and downloading a model, inference works without internet.")
        st.caption("Keep the app bound to 127.0.0.1. This is a single-user desktop app, without remote-user authentication. SQLite contains local paths, generated summaries, and quoted source text; protect this folder like your documents.")
    st.subheader("Local storage")
    st.code(str(DATA), language=None)
    st.caption("Back up this folder with the document folders it references. Quarantined files remain in .slothops/quarantine under each selected working folder. Never remove quarantine content you may want to restore.")


with st.sidebar:
    st.markdown('<div class="brand">🦥 Sloth<span>Ops</span></div><div class="muted">Your chores. A slower pace.</div>', unsafe_allow_html=True)
    st.write("")
    st.radio("Workspace", PAGES, key="page", label_visibility="collapsed")
    st.divider()
    st.markdown("**Working folder**")
    if "folder_input" not in st.session_state:
        st.session_state["folder_input"] = SETTINGS["folder"]
    st.text_input("Folder path", key="folder_input", placeholder="Paste a local folder path", label_visibility="collapsed")
    st.button("Use this folder", on_click=select_folder, width="stretch")
    st.button("Create demo folder", on_click=use_demo, width="stretch")
    st.caption("Demo files are synthetic. All operations and AI responses are real.")
    st.divider()
    model_names, connection_error = check_ollama(SETTINGS["base_url"])
    if connection_error:
        st.warning("Local AI offline")
        st.caption("File type sorting and duplicate checks still work. See Settings for connection help.")
    elif SETTINGS["model"] not in model_names:
        st.warning("Select an installed model in Settings")
    else:
        st.markdown('<span class="pill">● LOCAL AI CONNECTED</span>', unsafe_allow_html=True)
        st.text(SETTINGS["model"])
    st.caption("Open weights · local inference · explicit approvals")

if st.session_state.get("notice"):
    st.info(st.session_state.pop("notice"))
if st.session_state.get("action_errors"):
    for message in st.session_state.pop("action_errors"):
        st.error(message)


@st.fragment(run_every=30)
def routine_tick():
    # Shared SQLite leases prevent two tabs/workers from dispatching the same due run.
    results = run_due(STORE, exclude=DATA)
    for result in results:
        if result["status"] == "failed":
            st.warning("A recurring chore needs attention. See Recurring Chores and Activity.")
        elif result["status"] == "success":
            st.toast(result["message"], icon="🦥")


routine_tick()
{
    "Laziness Dashboard": dashboard,
    "Folder Organizer": organizer_page,
    "Duplicate Cleaner": duplicates_page,
    "Meeting Notes": notes_page,
    "Approvals": approvals_page,
    "Recurring Chores": routines_page,
    "Activity & Restore": activity_page,
    "Settings": settings_page,
}[st.session_state["page"]]()

st.write("")
st.caption("SlothOps 0.1 · Built for a little less busywork. Every file change needs your say-so.")
