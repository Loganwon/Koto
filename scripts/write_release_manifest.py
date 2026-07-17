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


def git_dirty(root: Path) -> bool | None:
    """Report whether artifact inputs differ from the recorded revision."""
    try:
        output = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return bool(output.strip())
    except (OSError, subprocess.CalledProcessError):
        return None


def validate_version(value: str) -> str:
    version = str(value or "").strip()
    if not version or not version[0].isalnum():
        raise ValueError("version must start with an alphanumeric character")
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+-" for char in version):
        raise ValueError("version contains characters unsafe for release filenames")
    return version


def parse_optional_bool(value: str | None, *, fallback: bool | None) -> bool | None:
    if value is None:
        return fallback
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    if normalized == "unknown":
        return None
    raise ValueError(f"invalid boolean state: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hash-output", type=Path, required=True)
    parser.add_argument("--git-revision", default=None)
    parser.add_argument("--git-dirty", choices=("true", "false", "unknown"))
    parser.add_argument(
        "--worktree-changed-during-build",
        choices=("true", "false", "unknown"),
    )
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
        "git_revision": args.git_revision or git_revision(root),
        "git_dirty": parse_optional_bool(
            args.git_dirty,
            fallback=git_dirty(root),
        ),
        "worktree_changed_during_build": parse_optional_bool(
            args.worktree_changed_during_build,
            fallback=None,
        ),
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
