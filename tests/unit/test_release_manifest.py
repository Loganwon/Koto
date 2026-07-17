from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def test_release_manifest_records_each_artifact_and_sha256(tmp_path: Path):
    artifact = tmp_path / "Koto_v1.2.3_Windows.zip"
    artifact.write_bytes(b"release artifact")
    manifest = tmp_path / "release-manifest.json"
    checksums = tmp_path / "SHA256SUMS.txt"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/write_release_manifest.py",
            "--version",
            "1.2.3",
            "--output",
            str(manifest),
            "--hash-output",
            str(checksums),
            str(artifact),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    expected_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert "Wrote release manifest" in result.stdout
    assert payload["schema_version"] == 1
    assert isinstance(payload["git_dirty"], bool)
    assert payload["worktree_changed_during_build"] is None
    assert payload["version"] == "1.2.3"
    assert payload["artifacts"] == [
        {
            "name": artifact.name,
            "sha256": expected_hash,
            "size_bytes": artifact.stat().st_size,
        }
    ]
    assert (
        checksums.read_text(encoding="utf-8") == f"{expected_hash} *{artifact.name}\n"
    )


def test_release_manifest_accepts_build_start_provenance(tmp_path: Path):
    artifact = tmp_path / "Koto.zip"
    artifact.write_bytes(b"artifact")
    manifest = tmp_path / "manifest.json"
    checksums = tmp_path / "checksums.txt"

    subprocess.run(
        [
            sys.executable,
            "scripts/write_release_manifest.py",
            "--version",
            "1.2.3",
            "--output",
            str(manifest),
            "--hash-output",
            str(checksums),
            "--git-revision",
            "build-start-revision",
            "--git-dirty",
            "true",
            "--worktree-changed-during-build",
            "true",
            str(artifact),
        ],
        check=True,
    )

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["git_revision"] == "build-start-revision"
    assert payload["git_dirty"] is True
    assert payload["worktree_changed_during_build"] is True


def test_release_manifest_rejects_unsafe_version_and_duplicate_artifact_names(
    tmp_path: Path,
):
    first = tmp_path / "one" / "Koto.zip"
    second = tmp_path / "two" / "Koto.zip"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    manifest = tmp_path / "release-manifest.json"
    checksums = tmp_path / "SHA256SUMS.txt"

    unsafe_version = subprocess.run(
        [
            sys.executable,
            "scripts/write_release_manifest.py",
            "--version",
            "1/unsafe",
            "--output",
            str(manifest),
            "--hash-output",
            str(checksums),
            str(first),
        ],
        capture_output=True,
        text=True,
    )
    duplicate_names = subprocess.run(
        [
            sys.executable,
            "scripts/write_release_manifest.py",
            "--version",
            "1.2.3",
            "--output",
            str(manifest),
            "--hash-output",
            str(checksums),
            str(first),
            str(second),
        ],
        capture_output=True,
        text=True,
    )

    assert unsafe_version.returncode != 0
    assert "unsafe for release filenames" in unsafe_version.stderr
    assert duplicate_names.returncode != 0
    assert "artifact names must be unique" in duplicate_names.stderr
