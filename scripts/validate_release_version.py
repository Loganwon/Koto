"""Validate that every Koto source metadata surface matches one release version."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from .release_metadata import validate_release_metadata
except ImportError:  # Direct script execution.
    from release_metadata import validate_release_metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", default="")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    result = validate_release_metadata(args.root, args.expected_version)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Release version validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
