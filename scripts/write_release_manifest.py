"""Write a release manifest and SHA-256 file for release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

try:
    from .release_metadata import validate_release_version
except ImportError:  # Direct script execution.
    from release_metadata import validate_release_version


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
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hash-output", type=Path, required=True)
    parser.add_argument("--git-revision", default=None)
    parser.add_argument("--git-dirty", choices=("true", "false", "unknown"))
    parser.add_argument(
        "--worktree-changed-during-build",
        choices=("true", "false", "unknown"),
    )
    parser.add_argument(
        "--diagnostic-reason",
        action="append",
        choices=(
            "allow_dirty_worktree",
            "incremental_pyinstaller",
            "missing_installer",
            "prebuilt_frontend",
            "skip_cython",
            "skip_pyinstaller",
            "unsigned_artifacts",
        ),
        default=[],
    )
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()
    version = validate_release_version(args.version)
    source_version = validate_release_version(args.source_version)
    if source_version != version:
        raise ValueError(
            f"source version mismatch: expected {version}, got {source_version}"
        )

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
    git_dirty_state = parse_optional_bool(
        args.git_dirty,
        fallback=git_dirty(root),
    )
    worktree_changed_state = parse_optional_bool(
        args.worktree_changed_during_build,
        fallback=None,
    )
    diagnostic_reasons = []
    if git_dirty_state is not False:
        diagnostic_reasons.append("git_dirty" if git_dirty_state else "git_dirty_unknown")
    if worktree_changed_state is not False:
        diagnostic_reasons.append(
            "worktree_changed_during_build"
            if worktree_changed_state
            else "worktree_change_unknown"
        )
    diagnostic_reasons.extend(args.diagnostic_reason)
    diagnostic_reasons = list(dict.fromkeys(diagnostic_reasons))
    manifest = {
        "schema_version": 1,
        "version": version,
        "source_version": source_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "git_revision": args.git_revision or git_revision(root),
        "git_dirty": git_dirty_state,
        "worktree_changed_during_build": worktree_changed_state,
        "release_eligible": not diagnostic_reasons,
        "build_mode": "formal" if not diagnostic_reasons else "diagnostic",
        "diagnostic_reasons": diagnostic_reasons,
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
    try:
        raise SystemExit(main())
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Release manifest generation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
