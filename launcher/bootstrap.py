#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
"""Koto environment bootstrap — Python version check, dependency verification, venv management."""

import logging
import json
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("koto.launcher.bootstrap")

MIN_PYTHON = (3, 10)

# (import_name, display_name)
REQUIRED_PACKAGES = [
    ("flask", "flask"),
    ("docx", "python-docx"),
    ("openpyxl", "openpyxl"),
    ("PIL", "Pillow"),
    ("pandas", "pandas"),
]

# Heavy optional packages that should not block startup
OPTIONAL_PACKAGES = {
    "torch": "LoRA training (pip install -r config/requirements_training.txt)",
    "faster_whisper": "local STT (pip install faster-whisper)",
    "pytesseract": "OCR (pip install pytesseract)",
}


def check_python_version() -> bool:
    """Verify Python version meets minimum requirement."""
    current = sys.version_info[:2]
    if current < MIN_PYTHON:
        logger.error(
            "Python %s.%s is required, but %s.%s is installed.",
            *MIN_PYTHON, *current,
        )
        return False
    logger.info("Python %s.%s — OK", *current)
    return True


def check_core_dependencies() -> dict[str, bool]:
    """Check which core dependencies are available."""
    results: dict[str, bool] = {}
    for import_name, display_name in REQUIRED_PACKAGES:
        try:
            __import__(import_name)
            results[display_name] = True
        except ImportError:
            results[display_name] = False
            logger.warning("Missing core dependency: %s", display_name)
    return results


def check_optional_dependencies() -> dict[str, bool]:
    """Check which optional dependencies are available (non-blocking)."""
    results: dict[str, bool] = {}
    for pkg, note in OPTIONAL_PACKAGES.items():
        try:
            __import__(pkg)
            results[pkg] = True
        except ImportError:
            results[pkg] = False
            logger.debug("Optional: %s not installed (%s)", pkg, note)
    return results


def get_python_info() -> dict:
    """Return information about the current Python environment."""
    return {
        "executable": sys.executable,
        "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "prefix": sys.prefix,
        "in_venv": sys.prefix != sys.base_prefix,
    }


def find_entry_script(mode: str = "desktop") -> str | None:
    """Resolve the single declared entry script for ``mode``.

    P7 intentionally removed candidate probing.  Falling through from the
    desktop runtime to a server-only script made damaged or mismatched
    packages appear to start through a different lifecycle.
    """
    root = Path(__file__).resolve().parent.parent
    manifest_path = root / "config" / "runtime_entrypoints.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.error("Cannot read canonical runtime entrypoint manifest: %s", exc)
        return None

    normalized_mode = mode if mode in {"desktop", "server"} else "desktop"
    relative_path = manifest.get(normalized_mode)
    if not isinstance(relative_path, str) or not relative_path.strip():
        logger.error("No canonical %s entrypoint is declared", normalized_mode)
        return None

    path = (root / relative_path).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        logger.error("Entrypoint escapes the application root: %s", relative_path)
        return None
    return str(path) if path.is_file() else None


def run_health_report() -> bool:
    """Print a health report and return True if all core checks pass."""
    py_ok = check_python_version()
    core = check_core_dependencies()
    opt = check_optional_dependencies()
    info = get_python_info()

    missing = [k for k, v in core.items() if not v]
    all_ok = py_ok and len(missing) == 0

    print("\n  Koto Environment Health Report")
    print("  " + "-" * 32)
    print(f"  Python:       {info['version']} ({info['executable']})")
    print(f"  Virtual env:  {'Yes' if info['in_venv'] else 'No'}")
    print(f"  Core deps:    {len(core) - len(missing)}/{len(core)} OK")
    if missing:
        print(f"  Missing:      {', '.join(missing)}")
        print(f"  Run: pip install -r config/requirements.txt")
    avail = [k for k, v in opt.items() if v]
    print(f"  Optional:     {len(avail)}/{len(opt)} available")
    print()

    return all_ok
