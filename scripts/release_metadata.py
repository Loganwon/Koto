"""Shared release-version and source-metadata contract for Koto builds."""

from __future__ import annotations

import json
import re
from pathlib import Path


SEMANTIC_VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)[.](?:0|[1-9][0-9]*)[.](?:0|[1-9][0-9]*)"
)


def validate_release_version(value: str) -> str:
    version = str(value or "").strip()
    if not SEMANTIC_VERSION_PATTERN.fullmatch(version):
        raise ValueError(
            "release version must use stable semantic version format MAJOR.MINOR.PATCH"
        )
    return version


def _python_package_version(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
    if not match:
        raise ValueError(f"release metadata is missing __version__: {path}")
    return match.group(1).strip()


def read_release_metadata(root: Path) -> dict[str, str]:
    root = root.resolve()
    package = json.loads((root / "web/package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(
        (root / "web/package-lock.json").read_text(encoding="utf-8")
    )
    lock_root = package_lock.get("packages", {}).get("", {})
    return {
        "VERSION": (root / "VERSION").read_text(encoding="utf-8").strip(),
        "launcher/__init__.py": _python_package_version(
            root / "launcher/__init__.py"
        ),
        "web/package.json": str(package.get("version") or "").strip(),
        "web/package-lock.json": str(package_lock.get("version") or "").strip(),
        "web/package-lock.json#root": str(lock_root.get("version") or "").strip(),
    }


def validate_release_metadata(root: Path, expected_version: str = "") -> dict[str, str]:
    metadata = read_release_metadata(root)
    source_version = validate_release_version(metadata["VERSION"])
    expected = validate_release_version(expected_version or source_version)
    mismatches = {
        source: version
        for source, version in metadata.items()
        if version != expected
    }
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## [{expected}]" not in changelog:
        mismatches["CHANGELOG.md"] = "missing release section"
    if mismatches:
        details = ", ".join(
            f"{source}={value!r}" for source, value in sorted(mismatches.items())
        )
        raise ValueError(
            f"release metadata does not match expected version {expected}: {details}"
        )
    return {"version": expected, **metadata}
