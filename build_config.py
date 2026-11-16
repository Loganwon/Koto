"""Shared build configuration for Koto packaging helpers."""

from __future__ import annotations

from fnmatch import fnmatchcase
import hashlib
import importlib.machinery
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import struct
import sys
import sysconfig
import tempfile

PROTECTED_DIRS: tuple[str, ...] = (
    "app/core/agent",
    "app/core/llm",
    "app/core/memory",
    "app/core/workflow",
    "app/core/skills",
    "app/core/learning",
    "app/core/routing",
    "app/core/goal",
    "app/core/tasks",
)

# These modules are intentionally kept as Python orchestration facades.
# PyInstaller stores them in its bytecode archive while implementation
# dependencies in the same protected directory remain native extensions.
CYTHON_PYTHON_FACADE_FILES: tuple[str, ...] = (
    "app/core/agent/file_task_runtime.py",
    "app/core/agent/task_tools.py",
)
# Import-time dispatcher intentionally remains Python; native initialization on
# scheduler threads has caused instability on Windows.
CYTHON_PYTHON_SOURCE_FILES: tuple[str, ...] = ("app/core/routing/local_dispatcher.py",)
# These existing modules may contain installation credentials. They must never
# be accepted as Python source in a staged or fallback release.
CYTHON_CREDENTIAL_SOURCE_FILES: tuple[str, ...] = ("app/core/llm/_license.py",)

CYTHON_BUILD_RELATIVE_DIR = "build/cython_lib"
CYTHON_EXTENSION_SUFFIXES: tuple[str, ...] = (".pyd", ".so")
CYTHON_PROVENANCE_MANIFEST = ".koto-cython-provenance.json"
CYTHON_PROVENANCE_VERSION = 1
CYTHON_BUILD_INPUT_FILES = (
    "build_config.py",
    "build_cython.py",
    "koto.spec",
    "Build_Release.ps1",
    "scripts/packaging_privacy.py",
)

# Runtime-owned data can appear inside the source package after interactive use.
# It must never enter a staged app overlay or any release artifact.
APP_RUNTIME_STATE_DIRS: tuple[str, ...] = (
    "app/core/chats",
    "app/core/workspace",
)
APP_RUNTIME_STATE_FILE_GLOBS: tuple[str, ...] = ("app/core/config/user_settings.json*",)


def is_app_runtime_state_path(relative_path: str | Path) -> bool:
    """Return whether a repository-relative app path is personal runtime state."""

    normalized = str(relative_path).replace("\\", "/").strip("/")
    if any(
        normalized == directory or normalized.startswith(f"{directory}/")
        for directory in APP_RUNTIME_STATE_DIRS
    ):
        return True
    return any(
        fnmatchcase(normalized, pattern) for pattern in APP_RUNTIME_STATE_FILE_GLOBS
    )


def protected_dir_paths(root: str | Path) -> set[str]:
    """Return normalized absolute protected directory paths for PyInstaller."""

    root_path = Path(root).resolve()
    return {str((root_path / rel_path).resolve()) for rel_path in PROTECTED_DIRS}


def cython_build_root(root: str | Path) -> Path:
    """Return the isolated output root for compiled protected modules."""

    return (Path(root).resolve() / CYTHON_BUILD_RELATIVE_DIR).resolve()


def staged_cython_extensions(
    root: str | Path, build_root: str | Path | None = None
) -> list[Path]:
    """List compiled protected modules from the isolated build tree."""

    build_root = (
        Path(build_root).resolve()
        if build_root is not None
        else cython_build_root(root)
    )
    artifacts: list[Path] = []
    for relative_dir in PROTECTED_DIRS:
        staged_dir = build_root / relative_dir
        if not staged_dir.is_dir():
            continue
        artifacts.extend(
            path
            for path in staged_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in CYTHON_EXTENSION_SUFFIXES
        )
    return sorted(artifacts)


def has_staged_cython_extension(
    root: str | Path, source_file: str | Path, build_root: str | Path | None = None
) -> bool:
    """Return whether a source module has a matching staged extension."""

    root_path = Path(root).resolve()
    source_path = Path(source_file).resolve()
    try:
        relative_stem = source_path.relative_to(root_path).with_suffix("")
    except ValueError:
        return False
    selected_root = (
        Path(build_root).resolve()
        if build_root is not None
        else cython_build_root(root_path)
    )
    staged_stem = selected_root / relative_stem
    return any(
        next(
            staged_stem.parent.glob(f"{staged_stem.name}*{suffix}"),
            None,
        )
        is not None
        for suffix in CYTHON_EXTENSION_SUFFIXES
    )


def _file_sha256(root: Path, path: Path) -> str:
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Build input or artifact escapes its declared root")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cython_build_input_snapshot(root: str | Path) -> dict:
    """Hash source/build inputs without reading personal runtime state."""
    root = Path(root).resolve()
    app = root / "app"
    if not app.is_dir():
        raise ValueError("Current app source tree is missing")
    sources = {
        path.relative_to(root).as_posix(): _file_sha256(root, path)
        for path in sorted(app.rglob("*.py"))
        if path.is_file() and not is_app_runtime_state_path(path.relative_to(root))
    }
    if not sources:
        raise ValueError("Current app source tree has no Python modules")
    build_files = {
        name: _file_sha256(root, root / name) for name in CYTHON_BUILD_INPUT_FILES
    }
    toolchain = {}
    for package in ("Cython", "setuptools", "pyinstaller"):
        try:
            toolchain[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            toolchain[package] = None
    return {
        "app_sources": sources,
        "build_files": build_files,
        "abi": {
            "implementation": sys.implementation.name,
            "cache_tag": sys.implementation.cache_tag,
            "python_version": list(sys.version_info[:3]),
            "soabi": sysconfig.get_config_var("SOABI"),
            "platform": sysconfig.get_platform(),
            "machine": platform.machine(),
            "pointer_bits": struct.calcsize("P") * 8,
            "extension_suffixes": list(importlib.machinery.EXTENSION_SUFFIXES),
        },
        "protected_dirs": list(PROTECTED_DIRS),
        "python_facades": list(CYTHON_PYTHON_FACADE_FILES),
        "python_sources": list(CYTHON_PYTHON_SOURCE_FILES),
        "credential_sources": list(CYTHON_CREDENTIAL_SOURCE_FILES),
        "toolchain": toolchain,
    }


def _overlay_artifact_hashes(build_root: Path) -> dict[str, str]:
    app = build_root / "app"
    if not app.is_dir():
        raise ValueError("Staged app overlay is missing")
    artifacts = {}
    for path in sorted(app.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(build_root)
        if is_app_runtime_state_path(relative):
            raise ValueError("Personal runtime state is present in the staged overlay")
        if "__pycache__" in relative.parts or path.suffix.lower() == ".pyc":
            raise ValueError(
                "Unstaged runtime bytecode is present in the staged overlay"
            )
        artifacts[relative.as_posix()] = _file_sha256(build_root, path)
    if not artifacts:
        raise ValueError("Staged app overlay is empty")
    return artifacts


def _validate_overlay_module_coverage(inputs: dict, artifacts: dict[str, str]) -> None:
    """Every current module must be represented; stale native modules are rejected."""
    sources = inputs["app_sources"]
    native_modules = {}
    for relative in artifacts:
        if relative.endswith(".py") and relative not in sources:
            raise ValueError("Staged Python module has no current source module")
        if Path(relative).suffix.lower() not in CYTHON_EXTENSION_SUFFIXES:
            continue
        suffix = next(
            (
                value
                for value in importlib.machinery.EXTENSION_SUFFIXES
                if relative.endswith(value)
            ),
            None,
        )
        if suffix is None:
            raise ValueError(
                "Staged native extension does not match the current Python ABI"
            )
        source = relative[: -len(suffix)] + ".py"
        if source not in sources:
            raise ValueError("Staged native extension has no current source module")
        if source in native_modules:
            raise ValueError(
                "Staged overlay contains duplicate native variants for one module"
            )
        native_modules[source] = relative
    if not native_modules:
        raise ValueError("Staged overlay has no compiled modules")
    for source in CYTHON_CREDENTIAL_SOURCE_FILES:
        if source in sources and (source in artifacts or source not in native_modules):
            raise ValueError(
                "Credential-bearing source is not protected by a native-only artifact"
            )
    for source, digest in sources.items():
        if source in artifacts:
            if artifacts[source] != digest:
                raise ValueError(
                    "Staged Python source differs from its current source module"
                )
            if source in native_modules:
                raise ValueError(
                    "Staged Python and native modules ambiguously shadow one another"
                )
        elif source not in native_modules:
            raise ValueError(
                "A current app source module is missing from the staged overlay"
            )


def validate_staged_cython_provenance(
    root: str | Path, build_root: str | Path | None = None
) -> tuple[bool, str]:
    """Read-only, fail-closed validation of the complete staged overlay provenance."""
    root = Path(root).resolve()
    staged = (
        Path(build_root).resolve()
        if build_root is not None
        else cython_build_root(root)
    )
    manifest_path = staged / CYTHON_PROVENANCE_MANIFEST
    if not manifest_path.is_file():
        return False, "Staged Cython provenance manifest is missing"
    if not manifest_path.resolve().is_relative_to(staged):
        return False, "Staged Cython provenance manifest is outside its declared root"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != CYTHON_PROVENANCE_VERSION
        ):
            return False, "Staged Cython provenance schema is unsupported"
        current = cython_build_input_snapshot(root)
        recorded = manifest.get("inputs")
        if not isinstance(recorded, dict):
            return False, "Staged Cython provenance inputs are missing"
        for key in (
            "abi",
            "build_files",
            "protected_dirs",
            "python_facades",
            "python_sources",
            "credential_sources",
            "toolchain",
            "app_sources",
        ):
            if recorded.get(key) != current[key]:
                return False, f"Staged Cython provenance differs from current {key}"
        artifacts = _overlay_artifact_hashes(staged)
        if manifest.get("artifacts") != artifacts:
            return False, "Staged Cython artifact hashes or file set changed"
        _validate_overlay_module_coverage(current, artifacts)
    except (OSError, ValueError, TypeError, KeyError):
        return False, "Staged Cython provenance is invalid or unreadable"
    return (
        True,
        "Staged Cython provenance matches current source, build configuration and ABI",
    )


def write_staged_cython_provenance(
    root: str | Path, build_root: str | Path | None = None, *, expected_inputs: dict
) -> Path:
    """Publish provenance only after a successful build with unchanged inputs."""
    root = Path(root).resolve()
    staged = (
        Path(build_root).resolve()
        if build_root is not None
        else cython_build_root(root)
    )
    current = cython_build_input_snapshot(root)
    if expected_inputs != current:
        raise ValueError(
            "Source/build inputs changed during Cython compilation; provenance was not published"
        )
    artifacts = _overlay_artifact_hashes(staged)
    _validate_overlay_module_coverage(current, artifacts)
    manifest = {
        "schema_version": CYTHON_PROVENANCE_VERSION,
        "inputs": current,
        "artifacts": artifacts,
    }
    destination = staged / CYTHON_PROVENANCE_MANIFEST
    staged.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=staged,
            prefix=".cython-provenance-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(manifest, stream, ensure_ascii=True, sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return destination
