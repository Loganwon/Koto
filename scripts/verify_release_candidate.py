"""Verify an exact Koto Windows release candidate and its provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

try:
    from .packaging_privacy import validate_package_entry
    from .release_metadata import validate_release_metadata, validate_release_version
except ImportError:  # Direct script execution.
    from packaging_privacy import validate_package_entry
    from release_metadata import validate_release_metadata, validate_release_version


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_checksums(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"invalid checksum line {line_number}: {raw_line!r}")
        digest, filename = parts
        filename = filename.lstrip("*")
        if len(digest) != 64 or any(
            char not in "0123456789abcdefABCDEF" for char in digest
        ):
            raise ValueError(f"invalid SHA-256 on line {line_number}")
        if not filename or Path(filename).name != filename:
            raise ValueError(
                f"unsafe checksum filename on line {line_number}: {filename!r}"
            )
        if filename in entries:
            raise ValueError(f"duplicate checksum entry: {filename}")
        entries[filename] = digest.lower()
    return entries


def verify_portable_archive_privacy(path: Path) -> None:
    """Reject portable archives containing builder-owned runtime state."""

    forbidden_prefixes = (
        "_internal/app/core/chats",
        "_internal/app/core/workspace",
    )
    forbidden_settings_prefix = "_internal/app/core/config/user_settings.json"
    try:
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                name = entry.filename.replace("\\", "/").strip("/")
                content = None
                if name.lower() in {
                    "config/deepseek_config.env.example",
                    "_internal/config/deepseek_config.env.example",
                    "config/personality_matrix.json",
                    "_internal/config/personality_matrix.json",
                }:
                    if entry.file_size > 16384:
                        raise ValueError("portable archive configuration default is too large: " + name)
                    content = archive.read(entry)
                try:
                    if not entry.is_dir():
                        validate_package_entry(name, content)
                except ValueError as exc:
                    raise ValueError("portable archive contains personal runtime state or unsafe configuration: " + name) from exc
                if any(
                    name == prefix or name.startswith(f"{prefix}/")
                    for prefix in forbidden_prefixes
                ) or name.startswith(forbidden_settings_prefix):
                    raise ValueError(
                        "portable archive contains personal runtime state: " + name
                    )
    except zipfile.BadZipFile as exc:
        raise ValueError(f"portable archive is not a valid ZIP: {path.name}") from exc


def verify_candidate(
    *,
    version: str,
    dist_dir: Path,
    allow_ineligible: bool = False,
    allow_missing_installer: bool = False,
    expected_git_revision: str = "",
    source_root: Path | None = None,
) -> dict[str, object]:
    version = validate_release_version(version)
    if source_root is not None:
        validate_release_metadata(source_root, version)
    dist_dir = dist_dir.resolve()
    manifest_path = dist_dir / f"Koto_v{version}_release-manifest.json"
    checksum_path = dist_dir / f"Koto_v{version}_SHA256SUMS.txt"
    zip_name = f"Koto_v{version}_Windows.zip"
    setup_name = f"Koto_v{version}_Setup.exe"

    for required in (manifest_path, checksum_path, dist_dir / zip_name):
        if not required.is_file():
            raise FileNotFoundError(f"release candidate file is missing: {required}")
    if not allow_missing_installer and not (dist_dir / setup_name).is_file():
        raise FileNotFoundError(
            f"release candidate file is missing: {dist_dir / setup_name}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported release manifest schema")
    if manifest.get("version") != version:
        raise ValueError(
            f"manifest version mismatch: expected {version}, got {manifest.get('version')!r}"
        )
    if manifest.get("source_version") != version:
        raise ValueError(
            "manifest source version mismatch: "
            f"expected {version}, got {manifest.get('source_version')!r}"
        )
    generated_at = manifest.get("generated_at")
    if not isinstance(generated_at, str):
        raise ValueError("manifest is missing generated_at provenance")
    try:
        generated_time = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            "manifest generated_at is not a valid ISO-8601 timestamp"
        ) from exc
    if generated_time.tzinfo is None:
        raise ValueError("manifest generated_at must include a timezone")
    eligible = manifest.get("release_eligible")
    reasons = manifest.get("diagnostic_reasons")
    if not isinstance(eligible, bool) or not isinstance(reasons, list):
        raise ValueError("manifest is missing release eligibility metadata")
    if eligible and reasons:
        raise ValueError("eligible manifest cannot contain diagnostic reasons")
    if not eligible and not reasons:
        raise ValueError("ineligible manifest must explain its diagnostic reasons")
    if not eligible and not allow_ineligible:
        raise ValueError(
            f"release candidate is diagnostic-only: {', '.join(map(str, reasons))}"
        )
    if allow_missing_installer and "missing_installer" not in reasons:
        raise ValueError("missing installer override is not recorded in the manifest")
    build_mode = manifest.get("build_mode")
    expected_build_mode = "formal" if eligible else "diagnostic"
    if build_mode != expected_build_mode:
        raise ValueError(
            f"manifest build mode mismatch: expected {expected_build_mode}, got {build_mode!r}"
        )
    if eligible:
        if manifest.get("git_dirty") is not False:
            raise ValueError(
                "eligible release candidate cannot come from a dirty worktree"
            )
        if manifest.get("worktree_changed_during_build") is not False:
            raise ValueError(
                "eligible release candidate must come from a frozen worktree"
            )
    else:
        if not isinstance(manifest.get("git_dirty"), (bool, type(None))):
            raise ValueError("manifest git_dirty provenance must be boolean or null")
        if not isinstance(
            manifest.get("worktree_changed_during_build"), (bool, type(None))
        ):
            raise ValueError(
                "manifest worktree_changed_during_build provenance must be boolean or null"
            )

    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise ValueError("manifest does not contain release artifacts")
    artifacts: dict[str, dict[str, object]] = {}
    for entry in raw_artifacts:
        if not isinstance(entry, dict):
            raise ValueError("manifest artifact entry must be an object")
        name = entry.get("name")
        if not isinstance(name, str) or Path(name).name != name or name in artifacts:
            raise ValueError(f"invalid or duplicate manifest artifact name: {name!r}")
        artifacts[name] = entry

    expected_names = {zip_name}
    if not allow_missing_installer:
        expected_names.add(setup_name)
    if set(artifacts) != expected_names:
        raise ValueError(
            f"manifest artifact set mismatch: expected {sorted(expected_names)}, got {sorted(artifacts)}"
        )

    checksums = parse_checksums(checksum_path)
    if set(checksums) != expected_names:
        raise ValueError(
            f"checksum artifact set mismatch: expected {sorted(expected_names)}, got {sorted(checksums)}"
        )

    verified: list[dict[str, object]] = []
    for name in sorted(expected_names):
        artifact_path = dist_dir / name
        if not artifact_path.is_file():
            raise FileNotFoundError(f"manifest artifact is missing: {artifact_path}")
        actual_size = artifact_path.stat().st_size
        actual_hash = sha256(artifact_path)
        entry = artifacts[name]
        if entry.get("size_bytes") != actual_size:
            raise ValueError(f"artifact size mismatch: {name}")
        if str(entry.get("sha256") or "").lower() != actual_hash:
            raise ValueError(f"manifest SHA-256 mismatch: {name}")
        if checksums[name] != actual_hash:
            raise ValueError(f"checksum file SHA-256 mismatch: {name}")
        verified.append(
            {"name": name, "sha256": actual_hash, "size_bytes": actual_size}
        )

    verify_portable_archive_privacy(dist_dir / zip_name)

    revision = manifest.get("git_revision")
    if eligible and (
        not isinstance(revision, str)
        or len(revision.strip()) != 40
        or any(char not in "0123456789abcdefABCDEF" for char in revision.strip())
    ):
        raise ValueError(
            "eligible release candidate must record a full 40-character Git revision"
        )
    expected_revision = str(expected_git_revision or "").strip()
    if (
        expected_revision
        and str(revision or "").strip().lower() != expected_revision.lower()
    ):
        raise ValueError(
            f"release candidate Git revision mismatch: expected {expected_revision}, got {revision!r}"
        )
    return {
        "version": version,
        "source_version": manifest.get("source_version"),
        "release_eligible": eligible,
        "build_mode": build_mode,
        "diagnostic_reasons": reasons,
        "git_revision": revision,
        "artifacts": verified,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--allow-ineligible", action="store_true")
    parser.add_argument("--allow-missing-installer", action="store_true")
    parser.add_argument("--expected-git-revision", default="")
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    result = verify_candidate(
        version=args.version,
        dist_dir=args.dist_dir,
        allow_ineligible=args.allow_ineligible,
        allow_missing_installer=args.allow_missing_installer,
        expected_git_revision=args.expected_git_revision,
        source_root=args.source_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, TypeError, ValueError) as exc:
        print(f"Release candidate verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
