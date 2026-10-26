# 🦥 SlothOps

**The local AI assistant for the digital chores you keep putting off.**

[Source on GitHub](https://github.com/DhritiGupta2006/slothops) · [Build verification](VERIFICATION.md) · [DEV article draft](docs/DEV_ARTICLE_DRAFT.md)

A polished Streamlit app that organizes folders, distills long notes, detects identical files, and schedules repeat chores. Ollama runs the model locally. You approve every file change. SQLite keeps the history, and the Laziness Dashboard reports completed work and transparent effort estimates.

## Start on Windows

1. Open the Ollama Windows app. A downloaded local model is required for AI features. The default is **`gemma3:4b`**.
2. Double-click **`StartSlothOps.cmd`** in this folder. It creates an isolated Python environment and installs dependencies if needed, then opens the app at **http://127.0.0.1:8501**. Keep its window open.
3. Click **Create demo folder**. These are real synthetic files with two duplicate pairs, documents, a meeting, and an image. No model results or dashboard successes are preloaded.
4. Try **Duplicate Cleaner → Find identical files → Approvals**. Select actions, review the paths, and approve. Use **Activity & Restore** to put files back.
5. In **Meeting Notes**, click **Load sample meeting**, then **Summarize with local AI**.

Python 3.11+ is required. The local build was prepared with Python 3.14. If a model is missing, download it once:

```powershell
ollama pull gemma3:4b
```

In **Settings**, refresh the connection and select any compatible downloaded local completion model. Model weights and their licenses are separate from this app's MIT license. Download size, memory requirements, output quality, and speed depend on the selected model and your hardware.

## Manual setup

Run from this folder:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

On macOS/Linux, use `python3 -m venv .venv` and `.venv/bin/python` for the remaining commands. Windows uses a non-overwriting rename with extended paths for deep folders. On POSIX, moves use exclusive same-volume hard links followed by unlinking the source; unsupported filesystems fail without replacing files. The primary target is Windows.

## What works

| Workflow | Actual behavior |
| --- | --- |
| AI organizer | Extracts TXT, MD, CSV, JSON, LOG, PDF, DOCX, and other supported text, sends the first 6,000 characters to local Ollama, validates one of six categories, and proposes a destination under `Organized/`. |
| Rule organizer | Sorts by extension without AI; supported even when Ollama is offline. Images, audio, video, archives, code, documents, and other files have explicit categories. |
| Duplicate cleaner | Groups by size and SHA-256, chooses a visible retained copy, and proposes moving the extras to `.slothops/quarantine/<plan>/`. Identical names alone do not count. |
| Approvals | Displays exact source, destination, retained copy, reason, and hash. Explicit selection and approval are required. Contents are checked again before execution. |
| Restore | Reverses completed moves and quarantine actions if their contents still match and the original path is free. Never overwrites a replacement. |
| Meeting notes | Reads up to 240,000 characters in sections, summarizes each section, combines overviews, and preserves section-level decisions and actions. Each extracted action must quote matching source text. |
| Recurring chores | Repeats organizer planning, duplicate planning, or document summarization. Filesystem plans always return to approvals. Read-only AI summaries can run automatically. |
| Audit | SQLite records plans, approvals, successes, failures, restores, summaries, and routine runs. Audit JSON and summary Markdown/JSON are downloadable. |

**No arbitrary shell execution, model-generated code execution, email sending, permanent deletion, OCR, or autonomous execution of extracted meeting tasks is included.** Quarantine is deliberate recoverable cleanup; it does **not** free disk space. Restore is explicit approval too.

Classification is based on an excerpt and can be wrong; review it before approval. PDFs must contain text and have at most 200 pages. Documents must be at most 20 MB. The scan caps at 500 files and excludes files over 100 MB. Limits and skipped files are shown. Full summaries reject oversized inputs instead of silently truncating them. Unsupported or unreadable organizer documents use a clearly labeled file type rule; an AI connectivity/generation failure aborts the plan rather than masquerading as AI classification.

## Recurring chores

Create a chore in **Recurring Chores** and choose the operation, folder, interval, and per-run file cap. Use **Run now** for an immediate run. Otherwise, the first run is after the selected interval. The saved chore retains the model and connection settings from creation.

Scheduling runs every 30 seconds while an app browser tab is open. For browser-independent scheduling, double-click **`StartWorker.cmd`**, or run:

```powershell
.venv\Scripts\python.exe -m slothops.worker
```

The optional worker polls every 15 seconds. It must remain running; no Windows service, login task, or startup entry is installed. After sleep/downtime, each overdue routine runs once and schedules the next interval from completion. SQLite leases prevent simultaneous tabs/workers dispatching the same routine. A crashed run's lease expires after 15 minutes; live calls renew it. Pausing prevents future runs; an already executing run finishes. Routine errors are logged and retried at the next interval. Existing pending file actions are not repeatedly proposed by normal subsequent scans.

## Honest dashboard math

The dashboard starts at zero. Demo creation and previews do not earn credit.

- **Chores completed:** completed file actions plus unique saved summaries. A moved file is one chore; an entire folder is not arbitrarily counted as another chore.
- **Estimated minutes saved:** 30 seconds for each completed organizer move, 20 seconds for each completed duplicate quarantine, plus each summary's estimated reading effort (200 words/minute, minimum 60 seconds) minus actual processing time, floored at zero.
- **Awaiting approval:** actual pending SQLite actions.
- Reopening or regenerating the same text with the same model reuses its saved result and earns no extra credit. A different model is a different summary job.
- Failed/rejected/planned work earns no credit. Restoring a file removes that action's completion and estimate credit. These are configurable-in-code effort assumptions, **not measured productivity or benchmark claims**.

## Local data and safety boundaries

By default, state lives in `data/` beside `app.py`: `settings.json`, `slothops.sqlite3`, and generated demo folders under `samples/`. Override with `SLOTHOPS_DATA_DIR`; give the app and worker the same absolute directory if overriding. Quarantined content stays under the selected document folder, not in SQLite.

Ollama requests accept only loopback addresses. HTTP redirects and environment proxies are disabled; cloud-tagged/remote models are excluded. After dependencies and model weights are downloaded, the app's inference and file operations need no internet. Streamlit usage statistics are disabled. The local Ollama server and its configuration remain part of the trust boundary; this app is not a network sandbox for other processes.

The model suggests a category or returns structured notes. It cannot pick arbitrary paths, change approval state, or run commands. Categories are allowlisted. Paths must remain within the approved root. Symbolic links, junctions/reparse points, hard-linked source files, internal quarantine, development environments, and Git internals are excluded. The approved root identity and source fingerprints are rechecked. Duplicate cleanup additionally rechecks the retained copy. Destination creation is exclusive and does not overwrite.

This is a single-user desktop MVP, not a security boundary against another process actively racing filesystem changes or modifying SQLite. Keep folders quiet while approving actions. Filesystem changes and SQLite commits are separate; interruption can leave an uncertain action. **Activity & Restore → Needs attention → Inspect completed move** verifies actual content/location without replaying a write. If verification fails, inspect the displayed paths and build a fresh preview. A crash during exclusive link/unlink can leave both paths present; that case requires manual review and receives no success credit. Never manually delete `.slothops/quarantine` if you might need its contents.

Summaries, quoted source text, filenames, and absolute paths are stored unencrypted in local SQLite. Original pasted documents are not stored in full by default. Protect and back up state alongside your documents. Bind the server to `127.0.0.1`; there is no remote-user authentication.

## Tests and real AI verification

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Tests cover preview-only behavior, approval, stale files, duplicates, keeper changes, collision prevention, restore, filesystem boundaries, missing Ollama, invalid JSON, chunk coverage, duplicate summary credit, routine scheduling, and the Streamlit UI. Deterministic AI test doubles appear only in tests and are named accordingly.

To exercise your actual installed Ollama model with synthetic data:

```powershell
.venv\Scripts\python.exe scripts/check_live_ollama.py --model gemma3:4b
```

This performs real classification and a multi-section summary, verifies a task at the end of the source, and saves its result in `verification/live/`. It uses its own SQLite database and does not inflate the app dashboard. It can fail if the model is unavailable, too slow, or misses the expected task; failure is reported honestly. See `VERIFICATION.md` for results from this build.

Generate another fresh sample folder:

```powershell
.venv\Scripts\python.exe -m slothops.demo --parent data/samples
```

## Troubleshooting

- **Local AI offline:** open the Ollama Windows app or run `ollama serve`, then refresh Settings. File type sorting and duplicate checks remain available.
- **Model missing:** use `ollama list`; pull a local model and select the exact installed tag. No weights are downloaded automatically by SlothOps.
- **Slow or incomplete generation:** try a smaller completion model; raise the per-request timeout in Settings. All chunks must succeed before a summary is saved. Long inputs can take many requests.
- **Destination occupied / file changed:** inspect the file, reject the obsolete plan, and generate a fresh preview. SlothOps will not overwrite or trust an old fingerprint.
- **Port 8501 is occupied:** stop an existing Streamlit instance, or use `python -m streamlit run app.py --server.port 8502` from the environment.
- **Setup blocked:** the first installation needs package-registry access. Run the launcher from a writable extracted folder. On Windows, `py -3 -m venv .venv` must complete successfully before installing dependencies.
- **Moved to another computer/folder:** virtual environments are not portable. Recreate `.venv` and install requirements. The source ZIP excludes the prepared environment, private state, and verification databases.

## Project map

`app.py` is the UI. `slothops/ai.py` owns real inference and summary validation; `files.py` handles bounded extraction and paths; `engine.py` plans and executes approved file actions; `storage.py` persists audit and metrics; `routines.py` and `worker.py` handle scheduling. `tests/` exercises core and UI behavior. `docs/DEV_ARTICLE_DRAFT.md` is the prepared write-up. `requirements-lock.txt` records the tested environment.

## Hacktoberfest and publication

The idea was inspired by the **Week 3 “Slow and Steady”** theme. The stated Week 3 deadline was **October 25, 2026**, and this build is dated **October 26, 2026**. This repository and its article draft **do not claim Week 3 eligibility or submission**. Any later event needs a separate check of its actual rules. The DEV article is provided as a draft; no DEV post or challenge entry has been published or submitted.

MIT licensed. Contributions welcome: stronger race-resistant file handling, a verified OCR workflow, and user-measured effort baselines are useful next steps.
