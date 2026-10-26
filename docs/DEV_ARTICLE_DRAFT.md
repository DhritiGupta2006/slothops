---
title: "SlothOps: I gave my digital chores to a local AI—and made it ask before touching a file"
description: "A local Ollama assistant that turns clutter into reviewable plans and tracks completed work without invented productivity numbers."
tags: ai, python, opensource, productivity
published: false
---

> **Publication note:** This is a draft about a project inspired by Hacktoberfest's “Slow and Steady” theme. Week 3's stated deadline was October 25, 2026; this build is dated October 26. I am not presenting this as an eligible Week 3 submission. The source is available on [GitHub](https://github.com/DhritiGupta2006/slothops); the app runs locally and has no hosted demo.
>
> **AI disclosure:** This app and article were developed with substantial AI assistance. The implementation, limitations, and verification results are included for review; no claim of unaided authorship is intended.

I do not need another chatbot to tell me that my Downloads folder is messy. I need something that turns that mess into a short list of changes I can understand—and that leaves the files alone until I agree.

That is the idea behind **SlothOps**: a local AI assistant for digital chores, with a Laziness Dashboard that has to earn every number it displays.

The first useful version has three jobs: suggest homes for scattered documents, find byte-for-byte duplicate files, and turn long conversations into a summary with next steps. Recurring chores make those jobs repeatable. Ollama supplies the local language model; ordinary Python code controls the filesystem.

## The sloth has a very small permission slip

The tempting implementation is to give an agent a folder and say, “Clean this up.” I chose a narrower contract:

1. Read the folder and build a plan.
2. Show the source, destination, retained duplicate, explanation, and content hash.
3. Let the user select and approve specific actions.
4. Recheck the files before executing those actions.
5. Record what actually happened, and provide a restore path.

The model never writes a path or executes a command. It returns a validated document category from a fixed list: Work, Finance, Personal, Study, Reference, or Other. Python maps that category to a folder under `Organized/`. File type rules handle media and unsupported text extraction, and the UI identifies those decisions as rules rather than AI.

A successful organizer preview still counts as **zero completed chores**. It is only a proposal.

## “Are you sure?” is not enough if the file changed

A useful idea from [Stop trusting the agent: bind tool-call approvals to the exact call](https://dev.to/whatsonyourmind/stop-trusting-the-agent-bind-tool-call-approvals-to-the-exact-call-5080) is that approval should describe a particular action, not float around as a general session flag.

SlothOps applies that principle to local files. Each proposed action records a source fingerprint and its exact destination. The executor checks the approved root, validates paths, and compares the file again immediately before moving it. If a note changed after preview, the action fails and gets no completion credit.

For duplicate cleanup, the retained copy is also rechecked. Two files with the same name are not necessarily duplicates, and two files with the same size are not necessarily duplicates. SlothOps compares SHA-256 hashes after grouping candidates by size.

Here is the part of the executor that matters:

```python
verify(source, json.loads(action["snapshot"]))
if action["kind"] == "quarantine":
    keeper = safe_path(root, action["keeper"])
    verify(keeper, json.loads(action["keeper_snapshot"]))
    if fingerprint(keeper)["sha256"] != fingerprint(source)["sha256"]:
        raise SafetyError("The retained copy no longer matches.")
```

An approved duplicate moves into `.slothops/quarantine/`; there is no permanent-delete button. That tidies the working folder while preserving an explicit restore path. It does **not** reclaim disk space, and the UI says so.

Restore has its own checks: the moved content must still match, and the original location must be free. A newly created replacement file is never overwritten.

## The AI part earns its place

Extension rules can tell me that a file is text. They cannot reliably tell me whether an ambiguously named note is a budget, a project discussion, or a personal plan. The local model supplies that semantic step by reading a disclosed excerpt of the document.

The second AI workflow handles conversations and meetings. It processes the full accepted input in sections, extracts decisions and action items, and combines the section summaries into an overview. Action items retain their section number and an exact quote from the source. If the model supplies an action without a matching quote, the result is rejected.

Matching a quote is useful evidence; it is not proof that the model interpreted the task correctly. Owners and dates can still be misread. The UI asks the reader to review them, and extracted meeting tasks are never executed automatically.

An unavailable Ollama server produces setup instructions. Missing models, invalid JSON, incomplete generation, and timeouts produce explicit errors. There is no canned summary standing in for a failed model call. [How I fixed silent Ollama failures in my local AI Assistant](https://dev.to/neox7/how-i-fixed-silent-ollama-failures-in-my-local-ai-assistant-54n3) reinforced that installation, connectivity, and real readiness are distinct states worth exposing.

## Why the open pieces matter

SlothOps uses Streamlit, Python, SQLite, and Ollama, with a downloaded open-weight completion model. The default configuration uses `gemma3:4b`; the model can be swapped for another compatible installed local model. Model weights have their own license terms; the app source is MIT licensed.

This setup makes several things practical:

- The document text stays on the machine for inference. Ollama requests are restricted to loopback addresses, environment proxies and redirects are disabled, and cloud-backed tags are excluded.
- After installing dependencies and downloading the weights, these workflows can run without an internet connection.
- There is no per-request hosted-model account to configure for the core workflow.
- The category prompt, summary schema, executor checks, and effort assumptions are ordinary source code that can be inspected and changed.

Local inference still costs electricity, memory, and time. The model's quality still matters. “Local” also does not mean encrypted: SQLite stores generated summaries, source quotes, and file paths in plain local storage. The app is a desktop tool for one trusted user, not a hardened remote file-management service.

## A dashboard that is allowed to stay at zero

An automation dashboard can look impressive before it has done anything. I wanted the opposite.

SlothOps reports:

- **Chores completed:** successful file actions plus unique saved summaries.
- **Estimated minutes saved:** explicit assumptions attached to completed work.
- **Approvals pending:** actual pending actions in SQLite.
- **Notes distilled:** saved summaries, deduplicated by input text and model.

The effort assumptions are deliberately visible: 30 seconds for a completed organizer move, 20 seconds for a completed duplicate cleanup, and estimated reading time at 200 words per minute (with a one-minute floor) minus actual summary processing time. Summary estimates cannot go below zero.

These are **effort estimates**, not evidence that a user became more productive. Planning earns nothing. A failed action earns nothing. Reopening a cached summary earns nothing. Restoring a file removes its previous completion and savings credit. Demo generation creates real synthetic files and leaves the metrics alone.

That means a slow model can produce a useful summary with zero estimated minutes saved. The number is allowed to be boring.

## Repeat the boring parts, keep the approval step

The routine planner supports four operations: organizer planning by type, organizer planning with Ollama, duplicate planning, and document summarization. It does not accept arbitrary shell commands.

The app runs due routines while a browser tab is open. An optional local worker can keep them running with the browser closed. Both use SQLite leases to avoid dispatching the same routine concurrently. After downtime, an overdue routine runs once rather than replaying every missed interval.

The boundary stays the same: a routine can create a new file plan, but it cannot approve it. Read-only summaries can complete automatically; file changes wait for a human.

## Try it in a few minutes

On Windows, open Ollama and run `StartSlothOps.cmd`. If needed, download the default model with `ollama pull gemma3:4b` and select it in Settings.

For a compact demonstration:

1. Create a demo folder.
2. Find its two identical file pairs.
3. Inspect the retained copies and approve quarantine.
4. Restore a file and watch its dashboard credit disappear.
5. Load the synthetic meeting and run a real local summary.
6. Create a recurring duplicate check and run it once.

The tests exercise stale-file rejection, destination collisions, retained-copy changes, restore protection, missing Ollama, invalid AI output, chunk coverage, recurring chores, and Streamlit navigation. A separate optional script performs real classification and a multi-section summary using the installed model; its results are isolated from the app's dashboard. The accompanying `VERIFICATION.md` records what was actually run for this build.

## What I would improve next

The MVP's boundaries are intentional. It has no OCR, no permanent deletion, and no agent-written code execution. Its filesystem checks are useful protections for normal local use, not a guarantee against a malicious process racing file changes. Filesystem writes and SQLite commits are separate, so an interruption can require inspection before an action is credited. Uncertain states remain visible.

The next work I would value most is stronger race-resistant filesystem handling, a measured evaluation set for category and action extraction quality, and optional user-calibrated effort estimates. Those would improve the trustworthiness of the chores it already handles.

For now, SlothOps does something modest and useful: it turns a vague chore into a plan I can inspect, executes only the changes I approve, and keeps an honest record afterward.

The sloth can take its time. My files deserve that.
