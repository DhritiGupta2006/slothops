---
title: "SlothOps: A Local AI for the Digital Chores I Keep Putting Off 🦥"
description: "Local Gemma inference, approval before file changes, and a Laziness Dashboard that counts completed work."
tags: hf26challenge, devchallenge, ai, python
published: false
---

*Inspired by the [Hacktoberfest Open-Source AI Challenge Week 3: Slow and Steady](https://dev.to/challenges/hacktoberfest-week3-2026-10-19). This build is dated October 26, 2026, after the challenge’s stated October 25 deadline; this write-up does not claim Week 3 eligibility.*

## What I Built

Sorting a folder is a small job. Reading a long conversation is a small job. Checking whether two files are actually the same is another small job.

Put enough of those jobs together, and they become the work you keep putting off.

I built **SlothOps**, a local AI assistant that turns those chores into something easier to finish: a reviewable plan, a concise summary, or a recurring routine.

It handles four kinds of busywork:

- **Folder organization:** a local model reads document excerpts and suggests categories such as Work, Finance, Personal, and Study. File type rules handle media and unsupported documents, with those decisions clearly labeled.
- **Conversation and meeting summaries:** long notes become an overview, decisions, and candidate action items with quotes from the source.
- **Duplicate cleanup:** SHA-256 hashes identify identical contents, even when filenames differ. Approved extras move into recoverable quarantine.
- **Recurring chores:** repeat folder checks, duplicate scans, or document summaries without having to remember each run.

The person who gets to be a little lazier is anyone facing a cluttered folder or a conversation they would rather not reread.

There is one deliberate boundary: **every file change needs approval.** The model can suggest a category; it cannot give itself permission to move a file.

## Demo

SlothOps runs locally on Windows. You can try the same synthetic files used during development:

1. Clone or download the [repository](https://github.com/DhritiGupta2006/slothops).
2. Open Ollama and download the default model with `ollama pull gemma3:4b` if it is not installed.
3. Run `StartSlothOps.cmd` and select **Create demo folder**.
4. Open **Duplicate Cleaner**, find the two duplicate pairs, and review the proposed changes in **Approvals**.
5. Approve a cleanup, then use **Activity & Restore** to put the file back.
6. Open **Meeting Notes**, load the sample meeting, and run a real local summary.

The sample folder contains actual synthetic documents and duplicate copies. It does not preload AI responses or successful dashboard activity.

For a result you can inspect immediately, the repository includes the [actual Gemma response from the integration check](https://github.com/DhritiGupta2006/slothops/blob/main/docs/live-ollama-result.json) and the [verification report](https://github.com/DhritiGupta2006/slothops/blob/main/VERIFICATION.md). There is no public hosted demo or recorded video attached to this write-up.

## Code

{% github https://github.com/DhritiGupta2006/slothops %}

The MIT-licensed source includes the app, Windows launchers, demo generator, tests, dependency files, and setup documentation. Model weights have their own license terms.

## How I Built It

The stack is **Python, Streamlit, SQLite, and Ollama**, with the downloaded **Gemma 3 4B** model (`gemma3:4b`) used for the verified AI runs.

The open-weight model supplies the semantic work. An extension can tell me that something is a text file; the model can read an excerpt and suggest whether it belongs with finances, project work, study material, or personal notes.

For summaries, SlothOps processes accepted input in sections, summarizes each section, and combines those summaries into an overview. Action items keep their section number and a matching source quote. A fabricated quote causes validation to fail. Matching evidence does not guarantee a correct interpretation, so owners, dates, and task wording still need review.

The file executor is ordinary Python with a small set of supported operations. Its workflow is:

**Scan → preview → select actions → approve → revalidate → execute → audit.**

Each planned action records the source fingerprint and exact destination. Before execution, the app checks the approved folder and file again. Duplicate cleanup also checks the copy being retained. A changed file or occupied destination causes the action to fail safely.

Cleanup moves duplicates into `.slothops/quarantine`; it does not permanently delete them or free disk space. Restore refuses to overwrite a replacement file.

Recurring routines use SQLite leases to prevent overlapping dispatches. They run while an app tab or the optional worker is open. A routine may prepare a file plan, but it cannot approve it. Extracted meeting tasks also have no automatic execution path.

Two DEV posts informed the approach: [@whatsonyourmind](https://dev.to/whatsonyourmind)’s [Stop trusting the agent: bind tool-call approvals to the exact call](https://dev.to/whatsonyourmind/stop-trusting-the-agent-bind-tool-call-approvals-to-the-exact-call-5080), and [@neox7](https://dev.to/neox7)’s [How I fixed silent Ollama failures in my local AI Assistant](https://dev.to/neox7/how-i-fixed-silent-ollama-failures-in-my-local-ai-assistant-54n3). They reinforced the value of specific approvals and visible readiness checks.

The release suite passed **41 tests**. A separate real-model check classified an invoice as Finance and summarized **6,656 characters across two sections**, including a checklist task near the end. It produced five candidate action items and took **237.5 seconds** for the summary workflow.

That check also exposed extraction limits: the model inferred some ownership from speakers and missed a conditional commitment. The evidence is available for inspection; this was a smoke test, not a claim of perfect extraction accuracy.

## Why Does Open Innovation Matter?

The documents this app handles can be personal. Running the model locally means the core workflow does not need to upload their text to a hosted inference provider.

SlothOps accepts loopback Ollama addresses, disables environment proxies and redirects for model calls, and excludes cloud-backed model tags. After dependencies and weights are downloaded, its core workflows can run without an internet connection.

The model can also be swapped for another compatible installed local model. The prompts, output validation, category list, execution checks, and effort assumptions are available in the source.

A closed API could provide useful classification and summaries too. What this approach gives the project is control over where inference happens and the ability to inspect and change the system around it without depending on a hosted-model account.

Local inference still uses memory, electricity, and time. Local storage also needs care: SQLite contains generated summaries, source quotes, and file paths. This is a single-user desktop MVP, not an encrypted document vault.

## My Agent Session

AI assistance contributed substantially to the implementation, tests, documentation, and this article. The [verification report](https://github.com/DhritiGupta2006/slothops/blob/main/VERIFICATION.md) records the completed checks and known limitations. An agent-session transcript has not been published, so no session embed is included here.

## The Lazy Payoff

The standout feature is the **Laziness Dashboard**: completed chores, estimated minutes saved, approvals pending, and saved summaries.

Its numbers have to come from completed work. A preview earns no completion credit. Failed or rejected actions earn none. Reopening a cached summary adds no credit, and restoring a moved file removes its previous credit.

The time assumptions are visible:

| Completed operation | Effort estimate |
| --- | --- |
| Organizer move | 30 seconds |
| Duplicate quarantine | 20 seconds |
| Summary | Reading time at 200 words/minute, with a one-minute minimum, minus actual processing time; never below zero |

These are estimates, not measured human time savings. Verification used synthetic data; I do not yet have a real-world weekly savings study. A slow summary can be useful while earning zero estimated minutes saved.

The practical payoff is fewer decisions to assemble from scratch: review a proposed destination, check the retained duplicate, or read the extracted next steps. SlothOps does the preparation and records the outcome.

## Prize Categories

**Technology alignment: Best Use of Gemma.** The verified classification and summarization workflows use the downloaded `gemma3:4b` model through Ollama. This identifies the partner technology used; it does not claim an accepted Week 3 entry.

My goal was simple: let a sloth handle the repetitive preparation, while I keep the final say over my files.
