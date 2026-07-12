"""Preview or remove Cython artifacts that override source modules.

Usage:
    .venv\\Scripts\\python.exe scripts/clean_inplace_cython_artifacts.py
    .venv\\Scripts\\python.exe scripts/clean_inplace_cython_artifacts.py --apply

The default mode only lists risky artifacts.  Use ``--apply`` after closing all
source-mode Koto processes.  Release packaging regenerates its own compiled
artifacts, so this command only restores predictable source-mode imports.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.startup_diagnostics import (  # noqa: E402
    _source_shadowing_extensions,
    remove_source_shadowing_extensions,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove in-place .pyd files that shadow Koto source modules."
    )
    parser.add_argument("--apply", action="store_true", help="Delete the listed artifacts")
    args = parser.parse_args()

    artifacts = _source_shadowing_extensions(ROOT)
    if not artifacts:
        print("No in-place Cython artifacts are shadowing source modules.")
        return 0

    if not args.apply:
        print(f"Found {len(artifacts)} source-shadowing artifact(s):")
        for artifact in artifacts:
            print(f"  {artifact.relative_to(ROOT)}")
        print("\nPreview only. Close source-mode Koto processes, then rerun with --apply.")
        return 0

    removed, blocked = remove_source_shadowing_extensions(ROOT)
    for artifact in removed:
        print(f"Removed: {artifact.relative_to(ROOT)}")
    for artifact, error in blocked:
        print(f"Locked:  {artifact.relative_to(ROOT)} ({error})", file=sys.stderr)

    if blocked:
        print("Stop the listed source-mode processes and rerun this command.", file=sys.stderr)
        return 1
    print(f"Removed {len(removed)} source-shadowing artifact(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
