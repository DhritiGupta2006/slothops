"""Optional local worker: python -m slothops.worker. Does not approve file changes."""

import argparse
import os
from pathlib import Path
import time

from .routines import run_due
from .storage import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run due routines once and exit")
    parser.add_argument("--data-dir", default=os.environ.get("SLOTHOPS_DATA_DIR", "data"))
    args = parser.parse_args()
    data = Path(args.data_dir).expanduser().absolute()
    store = Store(data / "slothops.sqlite3")
    print(f"SlothOps worker using {data}. File actions require approval in the app.", flush=True)
    try:
        while True:
            for result in run_due(store, exclude=data):
                print(f"{result['status']}: {result['message']}", flush=True)
            if args.once:
                return
            time.sleep(15)
    except KeyboardInterrupt:
        print("Worker stopped. Routines resume when a worker or app is running.")


if __name__ == "__main__":
    main()
