from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.release_metadata import validate_release_metadata, validate_release_version


def _write_release_metadata(root: Path, version: str = "1.2.3") -> None:
    (root / "launcher").mkdir(parents=True)
    (root / "web").mkdir()
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
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
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## [{version}]\n", encoding="utf-8"
    )


def test_release_metadata_accepts_one_exact_source_version(tmp_path: Path):
    _write_release_metadata(tmp_path)

    result = validate_release_metadata(tmp_path, "1.2.3")

    assert result["version"] == "1.2.3"
    assert set(result.values()) == {"1.2.3"}


def test_release_metadata_reports_every_mismatched_surface(tmp_path: Path):
    _write_release_metadata(tmp_path)
    (tmp_path / "web/package.json").write_text(
        json.dumps({"version": "1.2.2"}), encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")

    with pytest.raises(ValueError) as error:
        validate_release_metadata(tmp_path, "1.2.3")

    message = str(error.value)
    assert "web/package.json='1.2.2'" in message
    assert "CHANGELOG.md='missing release section'" in message


@pytest.mark.parametrize(
    "version",
    ["", "v1.2.3", "1.2", "01.2.3", "1.2.3-rc1", "2026.07.19"],
)
def test_release_version_rejects_noncanonical_versions(version: str):
    with pytest.raises(ValueError, match="stable semantic version"):
        validate_release_version(version)


def test_release_version_cli_fails_concisely_on_tag_source_mismatch(tmp_path: Path):
    _write_release_metadata(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_release_version.py",
            "--root",
            str(tmp_path),
            "--expected-version",
            "1.2.4",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Release version validation failed:" in result.stderr
    assert "VERSION='1.2.3'" in result.stderr
    assert "Traceback" not in result.stderr
