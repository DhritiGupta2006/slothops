"""Optional REAL inference check. Writes only to a specified verification folder."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from slothops.ai import Ollama, summarize
from slothops.demo import MEETING
from slothops.storage import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="verification/live")
    parser.add_argument("--model", default="gemma3:4b")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    store = Store(output / "live-check.sqlite3")
    client = Ollama(model=args.model, timeout=args.timeout)
    client.ready()
    category, reason = client.classify("INVOICE 1042. Design services INR 12,000. Payment due Friday.")
    print(json.dumps({"classification": category, "reason": reason}), flush=True)
    # More than one chunk; the final chunk contains an explicit, independently checkable task.
    text = MEETING + ("\nContext: This is synthetic project background. The app runs locally; file changes require approval.\n" * 58)
    text += "\nLeena: I will write the release checklist by 30 October 2026.\n"
    def progress(index, total, message):
        print(message, flush=True)
    row, cached = summarize(store, client, text, "Real Ollama synthetic meeting check", progress)
    result = json.loads(row["result"])
    report = {"model": args.model, "classification": category, "classification_reason": reason,
              "chunks": row["chunks"], "input_chars": row["input_chars"], "elapsed_seconds": row["elapsed_seconds"],
              "action_count": len(result["actions"]), "cached": cached, "result": result}
    (output / "result.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    assert category == "Finance", report
    assert row["chunks"] >= 2
    assert any("checklist" in action["task"].lower() for action in result["actions"]), "Final-section task was missed by the model"
    print(json.dumps({key: value for key, value in report.items() if key != "result"}), flush=True)


if __name__ == "__main__":
    main()
