from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.verify_release_candidate import verify_candidate


def _write_candidate(
    dist: Path,
    *,
    version: str = "1.2.3",
    eligible: bool = True,
    reasons: list[str] | None = None,
    include_installer: bool = True,
) -> tuple[Path, Path]:
    reasons = list(reasons or [])
    artifacts = [dist / f"Koto_v{version}_Windows.zip"]
    if include_installer:
        artifacts.append(dist / f"Koto_v{version}_Setup.exe")
    dist.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(artifacts[0], "w") as archive:
        archive.writestr("Koto.exe", b"portable-app")
    for index, artifact in enumerate(artifacts[1:], 1):
        artifact.write_bytes(f"artifact-{index}".encode())

    entries = [
        {
            "name": artifact.name,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "size_bytes": artifact.stat().st_size,
        }
        for artifact in artifacts
    ]
    manifest = dist / f"Koto_v{version}_release-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "version": version,
                "source_version": version,
                "generated_at": datetime.now(UTC).isoformat(),
                "git_revision": "a" * 40,
                "git_dirty": not eligible,
                "worktree_changed_during_build": False,
                "release_eligible": eligible,
                "build_mode": "formal" if eligible else "diagnostic",
                "diagnostic_reasons": reasons,
                "artifacts": entries,
            }
        ),
        encoding="utf-8",
    )
    checksums = dist / f"Koto_v{version}_SHA256SUMS.txt"
    checksums.write_text(
        "".join(f"{entry['sha256']} *{entry['name']}\n" for entry in entries),
        encoding="utf-8",
    )
    return manifest, checksums


def _write_source_metadata(root: Path, version: str) -> None:
    (root / "launcher").mkdir(parents=True, exist_ok=True)
    (root / "web").mkdir(exist_ok=True)
    (root / "VERSION").write_text(version, encoding="utf-8")
    (root / "launcher/__init__.py").write_text(
        f'__version__ = "{version}"\n', encoding="utf-8"
    )
    (root / "web/package.json").write_text(
        json.dumps({"version": version}), encoding="utf-8"
    )
    (root / "web/package-lock.json").write_text(
        json.dumps({"version": version, "packages": {"": {"version": version}}}),
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(f"## [{version}]\n", encoding="utf-8")


def test_verify_release_candidate_accepts_exact_formal_artifacts(tmp_path: Path):
    _write_candidate(tmp_path)

    result = verify_candidate(version="1.2.3", dist_dir=tmp_path)

    assert result["release_eligible"] is True
    assert {entry["name"] for entry in result["artifacts"]} == {
        "Koto_v1.2.3_Setup.exe",
        "Koto_v1.2.3_Windows.zip",
    }
    assert result["build_mode"] == "formal"


def test_verify_release_candidate_rejects_eligible_dirty_or_drifting_manifest(
    tmp_path: Path,
):
    manifest, _ = _write_candidate(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["git_dirty"] = True
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="dirty worktree"):
        verify_candidate(version="1.2.3", dist_dir=tmp_path)

    payload["git_dirty"] = False
    payload["worktree_changed_during_build"] = True
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen worktree"):
        verify_candidate(version="1.2.3", dist_dir=tmp_path)


def test_verify_release_candidate_requires_complete_source_provenance(tmp_path: Path):
    manifest, _ = _write_candidate(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    payload["source_version"] = "1.2.2"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="source version mismatch"):
        verify_candidate(version="1.2.3", dist_dir=tmp_path)

    payload["source_version"] = "1.2.3"
    payload["generated_at"] = "2026-07-19T12:00:00"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="must include a timezone"):
        verify_candidate(version="1.2.3", dist_dir=tmp_path)

    payload["generated_at"] = datetime.now(UTC).isoformat()
    payload["git_revision"] = "abc123"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="full 40-character Git revision"):
        verify_candidate(version="1.2.3", dist_dir=tmp_path)


def test_verify_release_candidate_cross_checks_the_checked_out_source(tmp_path: Path):
    dist = tmp_path / "dist"
    source = tmp_path / "source"
    _write_candidate(dist)
    _write_source_metadata(source, "1.2.2")

    with pytest.raises(ValueError, match="does not match expected version 1.2.3"):
        verify_candidate(version="1.2.3", dist_dir=dist, source_root=source)

    _write_source_metadata(source, "1.2.3")
    result = verify_candidate(version="1.2.3", dist_dir=dist, source_root=source)
    assert result["source_version"] == "1.2.3"


def test_verify_release_candidate_requires_the_expected_revision(tmp_path: Path):
    _write_candidate(tmp_path)

    result = verify_candidate(
        version="1.2.3",
        dist_dir=tmp_path,
        expected_git_revision="a" * 40,
    )
    assert result["git_revision"] == "a" * 40

    with pytest.raises(ValueError, match="Git revision mismatch"):
        verify_candidate(
            version="1.2.3",
            dist_dir=tmp_path,
            expected_git_revision="different-revision",
        )


def test_verify_release_candidate_rejects_ineligible_or_tampered_artifacts(
    tmp_path: Path,
):
    _write_candidate(tmp_path, eligible=False, reasons=["allow_dirty_worktree"])
    with pytest.raises(ValueError, match="diagnostic-only"):
        verify_candidate(version="1.2.3", dist_dir=tmp_path)

    verify_candidate(
        version="1.2.3",
        dist_dir=tmp_path,
        allow_ineligible=True,
    )
    (tmp_path / "Koto_v1.2.3_Windows.zip").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="size mismatch|SHA-256 mismatch"):
        verify_candidate(
            version="1.2.3",
            dist_dir=tmp_path,
            allow_ineligible=True,
        )


def test_verify_release_candidate_requires_recorded_missing_installer_override(
    tmp_path: Path,
):
    _write_candidate(
        tmp_path,
        eligible=False,
        reasons=["missing_installer"],
        include_installer=False,
    )

    result = verify_candidate(
        version="1.2.3",
        dist_dir=tmp_path,
        allow_ineligible=True,
        allow_missing_installer=True,
    )
    assert result["diagnostic_reasons"] == ["missing_installer"]

    manifest = tmp_path / "Koto_v1.2.3_release-manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["diagnostic_reasons"] = ["skip_cython"]
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="not recorded"):
        verify_candidate(
            version="1.2.3",
            dist_dir=tmp_path,
            allow_ineligible=True,
            allow_missing_installer=True,
        )


def test_verify_release_candidate_rejects_wrong_checksum_artifact_set(tmp_path: Path):
    _, checksums = _write_candidate(tmp_path)
    checksums.write_text(
        checksums.read_text(encoding="utf-8") + ("0" * 64) + " *old-build.zip\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="checksum artifact set mismatch"):
        verify_candidate(version="1.2.3", dist_dir=tmp_path)


@pytest.mark.parametrize(
    "private_path",
    [
        "_internal/app/core/chats/private.json",
        "_internal/app/core/workspace/clipboard/history.json",
        "_internal/app/core/config/user_settings.json",
        "_internal/app/core/config/user_settings.json.lock",
    ],
)
def test_verify_release_candidate_rejects_personal_runtime_state(
    tmp_path: Path, private_path: str
):
    manifest, checksums = _write_candidate(tmp_path)
    archive_path = tmp_path / "Koto_v1.2.3_Windows.zip"
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr(private_path, "private")

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    entry = next(
        item for item in payload["artifacts"] if item["name"] == archive_path.name
    )
    entry["sha256"] = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    entry["size_bytes"] = archive_path.stat().st_size
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    checksum_lines = checksums.read_text(encoding="utf-8").splitlines()
    checksums.write_text(
        "\n".join(
            (
                f"{entry['sha256']} *{archive_path.name}"
                if archive_path.name in line
                else line
            )
            for line in checksum_lines
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="personal runtime state"):
        verify_candidate(version="1.2.3", dist_dir=tmp_path)


def test_verify_release_candidate_cli_reports_concise_failure(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_release_candidate.py",
            "--version",
            "1.2.3",
            "--dist-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Release candidate verification failed:" in result.stderr
    assert "Traceback" not in result.stderr
