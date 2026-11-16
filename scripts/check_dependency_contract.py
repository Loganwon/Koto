"""Check direct runtime requirements against exact lock pins, without networking.

This is a dependency-file contract, not a full resolver, installed-environment
closure check, or vulnerability scan. Imports are checked only when requested.
Diagnostics contain package names and file locations, never requirement URLs
or exception messages that could contain credentials. Named platforms use x64
reference environments; --platform current uses the actual host environment.
"""

from __future__ import annotations

import argparse
import importlib
import json
import platform
import re
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

DIRECT_FILES = (
    "config/requirements.txt",
    "config/requirements_core.txt",
    "config/requirements_desktop.txt",
)
LOCK_FILE = "config/requirements.lock"
IMPORT_MODULES = (
    "openai",
    "flask_wtf",
    "html2docx",
    "ebooklib",
    "send2trash",
    "pythonjsonlogger.json",
)
PLATFORMS = {
    "linux": {
        "sys_platform": "linux",
        "platform_system": "Linux",
        "os_name": "posix",
        "platform_machine": "x86_64",
    },
    "win32": {
        "sys_platform": "win32",
        "platform_system": "Windows",
        "os_name": "nt",
        "platform_machine": "AMD64",
    },
    "darwin": {
        "sys_platform": "darwin",
        "platform_system": "Darwin",
        "os_name": "posix",
        "platform_machine": "x86_64",
    },
}


def _read(root: Path, filename: str, issues: list[dict]) -> list[dict]:
    try:
        lines = (root / filename).read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        issues.append({"code": "unreadable_requirement_file", "file": filename})
        return []
    result = []
    for number, raw in enumerate(lines, 1):
        line = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
        if not line or line.startswith("#"):
            continue
        location = {"file": filename, "line": number}
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            issues.append({"code": "invalid_requirement", **location})
            continue
        if requirement.url is not None:
            issues.append(
                {
                    "code": "unapproved_requirement_url",
                    **location,
                    "package": requirement.name,
                }
            )
            continue
        result.append({**location, "requirement": requirement})
    return result


def check_imports() -> dict:
    failures = []
    for module in IMPORT_MODULES:
        try:
            importlib.import_module(module)
        except Exception as error:
            failures.append({"module": module, "error_type": type(error).__name__})
    return {
        "enabled": True,
        "status": "failed" if failures else "passed",
        "checked": list(IMPORT_MODULES),
        "failures": failures,
    }


def check_contract(
    root: Path,
    *,
    target_platforms: tuple[str, ...] = ("linux", "win32", "darwin"),
    python_version: str = "3.11",
    include_imports: bool = False,
) -> dict:
    root = root.resolve()
    issues: list[dict] = []
    direct = [row for filename in DIRECT_FILES for row in _read(root, filename, issues)]
    locked = _read(root, LOCK_FILE, issues)
    pins: dict[str, list[dict]] = {}
    for row in locked:
        requirement = row["requirement"]
        specifiers = list(requirement.specifier)
        valid_pin = len(specifiers) == 1 and specifiers[0].operator == "=="
        try:
            version = str(Version(specifiers[0].version)) if valid_pin else None
        except InvalidVersion:
            version = None
        if version is None:
            issues.append(
                {
                    "code": "lock_requires_exact_pin",
                    "file": row["file"],
                    "line": row["line"],
                    "package": requirement.name,
                }
            )
            continue
        pins.setdefault(canonicalize_name(requirement.name), []).append(
            {**row, "version": version}
        )

    environments = []
    checked = 0
    for target in target_platforms:
        environment = default_environment()
        if target != "current":
            environment.update(PLATFORMS[target])
        environment.update(
            python_version=".".join(python_version.split(".")[:2]),
            python_full_version=(
                python_version
                if python_version.count(".") == 2
                else python_version + ".0"
            ),
            extra="",
        )
        environments.append(
            {
                key: environment[key]
                for key in (
                    "sys_platform",
                    "platform_system",
                    "platform_machine",
                    "python_version",
                    "python_full_version",
                )
            }
        )
        active_pins = {}
        for name, candidates in pins.items():
            active = [
                row
                for row in candidates
                if row["requirement"].marker is None
                or row["requirement"].marker.evaluate(environment)
            ]
            if len(active) > 1:
                issues.append(
                    {
                        "code": "ambiguous_lock_pin",
                        "file": LOCK_FILE,
                        "package": name,
                        "target_platform": environment["sys_platform"],
                        "lines": [row["line"] for row in active],
                    }
                )
            elif active:
                active_pins[name] = active[0]
        for row in direct:
            requirement = row["requirement"]
            if requirement.marker is not None and not requirement.marker.evaluate(
                environment
            ):
                continue
            checked += 1
            selected = active_pins.get(canonicalize_name(requirement.name))
            location = {
                "file": row["file"],
                "line": row["line"],
                "package": requirement.name,
                "target_platform": environment["sys_platform"],
            }
            if selected is None:
                issues.append({"code": "missing_lock_pin", **location})
            elif not requirement.specifier.contains(
                selected["version"], prereleases=True
            ):
                issues.append(
                    {
                        "code": "lock_constraint_mismatch",
                        **location,
                        "locked_version": selected["version"],
                        "lock_line": selected["line"],
                    }
                )
    imports = (
        check_imports()
        if include_imports
        else {"enabled": False, "status": "not_requested"}
    )
    return {
        "schema_version": 1,
        "check": "dependency_contract",
        "status": "failed" if issues or imports["status"] == "failed" else "passed",
        "scope": "Direct requirements versus exact runtime lock pins; not a full resolver or CVE scan.",
        "direct_files": list(DIRECT_FILES),
        "lock_file": LOCK_FILE,
        "target_environments": environments,
        "direct_requirement_count": len(direct),
        "active_requirement_checks": checked,
        "locked_package_count": len(pins),
        "issues": issues,
        "imports": imports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--platform", choices=("all", "current", *PLATFORMS), default="all"
    )
    parser.add_argument("--python-version", default=platform.python_version())
    parser.add_argument("--check-imports", action="store_true")
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", args.python_version):
        parser.error("--python-version must be major.minor or major.minor.patch")
    targets = tuple(PLATFORMS) if args.platform == "all" else (args.platform,)
    report = check_contract(
        args.root,
        target_platforms=targets,
        python_version=args.python_version,
        include_imports=args.check_imports,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
