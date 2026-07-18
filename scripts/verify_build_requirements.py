from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path


def read_exact_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if "==" not in line:
            raise ValueError(f"build requirement must use an exact == pin: {raw_line}")
        name, version = (part.strip() for part in line.split("==", 1))
        if not name or not version:
            raise ValueError(f"invalid build requirement: {raw_line}")
        pins[name] = version
    if not pins:
        raise ValueError("build requirements lock is empty")
    return pins


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify pinned Windows build tools")
    parser.add_argument("lockfile", type=Path)
    args = parser.parse_args()

    try:
        pins = read_exact_pins(args.lockfile)
    except (OSError, ValueError) as exc:
        print(f"[build-tools] invalid lockfile: {exc}")
        return 1

    failures: list[str] = []
    for package, expected in pins.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            failures.append(f"{package}: missing (expected {expected})")
            continue
        if actual != expected:
            failures.append(f"{package}: {actual} installed, expected {expected}")

    if failures:
        print("[build-tools] pinned toolchain mismatch:")
        for failure in failures:
            print(f"  - {failure}")
        print(f"Run: python -m pip install -r {args.lockfile}")
        return 1

    summary = ", ".join(f"{name}=={version}" for name, version in pins.items())
    print(f"[build-tools] OK: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
