"""Compare validated snapshots without fetching or modifying anything."""

import argparse
import json
from pathlib import Path

from snapshot import SnapshotError, compare
from validate_layout import validate_layout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    args = parser.parse_args()
    try:
        validate_layout(args.candidate)
        result = compare(args.current, args.candidate)
        print(json.dumps(result, indent=2))
        return 0
    except (SnapshotError, OSError, ValueError, TypeError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
