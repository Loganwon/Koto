"""Write a release manifest and SHA-256 file for release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_revision(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def validate_version(value: str) -> str:
    version = str(value or "").strip()
    if not version or not version[0].isalnum():
        raise ValueError("version must start with an alphanumeric character")
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+-" for char in version):
        raise ValueError("version contains characters unsafe for release filenames")
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hash-output", type=Path, required=True)
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()
    version = validate_version(args.version)

    entries = []
    artifact_names: set[str] = set()
    for artifact in args.artifacts:
        if not artifact.is_file():
            raise FileNotFoundError(f"Release artifact is missing: {artifact}")
        if artifact.name in artifact_names:
            raise ValueError(f"Release artifact names must be unique: {artifact.name}")
        artifact_names.add(artifact.name)
        entries.append(
            {
                "name": artifact.name,
                "sha256": sha256(artifact),
                "size_bytes": artifact.stat().st_size,
            }
        )

    root = Path(__file__).resolve().parents[1]
    manifest = {
        "schema_version": 1,
        "version": version,
        "generated_at": datetime.now(UTC).isoformat(),
        "git_revision": git_revision(root),
        "artifacts": entries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.hash_output.write_text(
        "".join(f"{entry['sha256']} *{entry['name']}\n" for entry in entries),
        encoding="utf-8",
    )
    print(f"Wrote release manifest: {args.output}")
    print(f"Wrote SHA-256 checksums: {args.hash_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
