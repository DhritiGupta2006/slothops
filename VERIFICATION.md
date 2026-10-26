# SlothOps verification — October 26, 2026

## Release suite

**41 tests passed in 10.66 seconds** on Windows with Python 3.14.7. The complete release run used the installed environment in `requirements-lock.txt`.

The suite includes core filesystem tests and Streamlit AppTest flows. It verifies approval before execution; preview without mutation; stale source and changed retained-copy rejection; distinct targets for filename collisions; no overwriting; recoverable quarantine; safe restore; path/link exclusions; real hash-based duplicate planning; summary input deduplication; long-text chunk coverage; invalid output/connectivity handling; recurring routine scheduling and leases; navigation through all eight screens; and demo → duplicate preview → approved execution → updated dashboard.

The earlier sandbox core-only run passed 38 tests with one hard-link test skipped. Running the complete suite outside that sandbox let the hard-link test and Streamlit's local socket pair run normally, producing the 41-pass release result. The UI test also caught a Windows long-path issue in deeply nested quarantine destinations; the executor now uses extended Windows paths. Earlier development failures are not counted as passing tests.

## Real Ollama inference

The optional integration script was run against the user's installed **`gemma3:4b`** model, using only synthetic notes and an isolated verification database.

| Check | Observed result |
| --- | --- |
| Ollama connectivity/model readiness | Passed against the local server |
| Invoice classification | `Finance`, from an actual generated response |
| Long input | 6,656 characters processed in 2 sections |
| Summary and overview | Both section summaries plus a combined overview generated |
| Action evidence | 5 extracted actions passed source-quote matching |
| Final-section task | Leena's release checklist task was found with the stated October 30 date |
| Actual summary processing time | 237.5 seconds across the section and overview requests |
| Fake result fallback | None; invalid/unavailable model calls raise errors |

The initial longer inference attempt lost its Ollama connection. After starting the installed server again, the real integration retry completed successfully with a 600-second per-request timeout. The application defaults to 300 seconds per request and allows 30–600 seconds in Settings. Generation speed depends on the machine and model; this one sample is not a general benchmark.

The exact successful, synthetic response is saved in `docs/live-ollama-result.json`. This was an integration smoke test, not a comprehensive extraction-quality evaluation. The model inferred some task ownership from speakers and did not preserve every conditional commitment in the meeting. Source-quote validation checks provenance, not semantic correctness. The app exposes the evidence and asks users to review owners, dates, and task wording. Extracted tasks have no automatic execution path.

## Browser and dashboard

The running app was opened and visually inspected at `http://127.0.0.1:8501`. The dark green dashboard, navigation, genuine local-model connection indicator, zero initial metrics, and fresh demo setup were visible. The live app has its own state; test and model-verification records are isolated from it. Demo setup creates files without adding completed actions or summaries.

The local preview image is excluded from the source ZIP and Git because its sidebar may display a machine-specific demo folder path. Use a clean screenshot before publishing publicly.

## Scope limits

Source repository: [DhritiGupta2006/slothops](https://github.com/DhritiGupta2006/slothops). The source is public on GitHub; the application runs locally. No remote app deployment, DEV publication, or challenge submission was performed. Week 3's stated October 25 deadline had passed as of this October 26 build. No eligibility is claimed.

This remains a single-user local MVP. It has no OCR, permanent deletion, remote authentication, or protection against a malicious process racing filesystem checks or editing SQLite. A filesystem operation and its SQLite record are not one atomic transaction; recovery inspection exists for uncertain states. Quarantine preserves bytes and does not free disk space. Recurring work needs an open app tab or the optional worker process.
