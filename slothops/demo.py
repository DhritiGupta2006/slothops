"""Generate real sample files, never fabricated AI results or dashboard credit."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime
from pathlib import Path
from uuid import uuid4


MEETING = """SlothOps launch planning — 26 October 2026

Maya: Let's keep the first release local. We agreed that no document text goes to a hosted AI service.
Arun: I will test the Windows launcher by Friday. I'll report the result in the project notes.
Maya: I'll draft the README by 29 October 2026.
Sam: We should use recoverable quarantine for duplicates. Permanent deletion is out of scope.
Maya: Agreed. Keep the original file if anything changes after preview.
Arun: The dashboard must label time savings as estimates. We haven't measured anyone's actual time saved.
Sam: I'll record the demo once the launcher is tested. No date agreed yet.
Maya: Let's review the safety tests at our next meeting. No one has been assigned that review yet.
"""


def create_demo(parent: Path | str) -> Path:
    parent = Path(parent).expanduser().absolute()
    parent.mkdir(parents=True, exist_ok=True)
    folder = parent / ("demo-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6])
    folder.mkdir(exist_ok=False)
    files = {
        "team-meeting.txt": MEETING,
        "invoice-october.txt": "INVOICE 1042\nFrom: Example Studio\nTo: Demo Customer\nDesign services: INR 12,000\nDue: 30 October 2026\nThis is synthetic demo data.\n",
        "weekend-plan.md": "# Weekend\nTake a walk, water the plants, and cook lunch with friends.\n",
        "python-study.txt": "Study notes: Python context managers\nUse a with statement to release resources even when an exception occurs.\n",
        "budget.csv": "category,planned_inr\nfood,6000\ntransport,2000\nbooks,1000\n",
        "hello.py": "print('Slow and steady.')\n",
        "copies/team-meeting-copy.txt": MEETING,
        "copies/invoice-copy.txt": "INVOICE 1042\nFrom: Example Studio\nTo: Demo Customer\nDesign services: INR 12,000\nDue: 30 October 2026\nThis is synthetic demo data.\n",
    }
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (folder / "tiny-image.png").write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jD1sAAAAASUVORK5CYII="))
    return folder


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", default="data/samples")
    args = parser.parse_args()
    print(create_demo(args.parent))
