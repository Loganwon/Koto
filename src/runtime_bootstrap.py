from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class RuntimeRoots:
    app_root: Path
    bundle_dir: Path


def resolve_runtime_roots(current_file: str) -> RuntimeRoots:
    """Resolve runtime roots for source and frozen entrypoints."""
    if getattr(sys, "frozen", False):
        app_root = Path(sys.executable).resolve().parent
        bundle_dir = Path(getattr(sys, "_MEIPASS", app_root))
    else:
        here = Path(current_file).resolve().parent
        app_root = here.parent if here.name == "src" else here
        bundle_dir = app_root
    return RuntimeRoots(app_root=app_root, bundle_dir=bundle_dir)


def add_sys_path(path: Path | str, *, append: bool = False) -> None:
    """Register an import path once while preserving caller order semantics."""
    candidate = os.path.abspath(str(path))
    normalized = os.path.normcase(os.path.normpath(candidate))
    existing = {
        os.path.normcase(os.path.normpath(os.path.abspath(entry)))
        for entry in sys.path
        if entry
    }
    if normalized in existing:
        return
    if append:
        sys.path.append(candidate)
    else:
        sys.path.insert(0, candidate)


def configure_process_environment(
    roots: RuntimeRoots,
    *,
    prepend_paths: Iterable[Path | str] = (),
    append_paths: Iterable[Path | str] = (),
    required_dirs: Iterable[Path | str] = (),
) -> RuntimeRoots:
    """Prepare cwd, import paths, and base runtime directories for an entrypoint."""
    os.chdir(str(roots.app_root))

    for path in prepend_paths:
        add_sys_path(path)
    for path in append_paths:
        add_sys_path(path, append=True)

    for directory in required_dirs:
        (roots.app_root / Path(directory)).mkdir(parents=True, exist_ok=True)

    return roots


def load_optional_gemini_env() -> None:
    """Load local .env-style Gemini config when the runtime support is available."""
    try:
        from app.core.llm.gemini_config import load_gemini_config_env
    except ImportError:
        return

    load_gemini_config_env(override=False)


def validate_startup_config_or_raise() -> None:
    """Run shared startup validation from either source or frozen entrypoints."""
    try:
        from src.config_validator import validate_startup_config
    except ImportError:
        from config_validator import validate_startup_config

    validate_startup_config()


def init_optional_langsmith() -> None:
    """Initialize LangSmith tracing only when the integration is available and healthy."""
    try:
        from app.core.monitoring.langsmith_tracer import init_langsmith

        init_langsmith()
    except Exception:
        pass