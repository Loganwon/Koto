from __future__ import annotations

import importlib.util
import marshal
from pathlib import Path
from typing import Any, MutableMapping


def restore_current_module(
    module_file: str, namespace: MutableMapping[str, Any]
) -> None:
    """Execute the sibling .pyc for a missing source module into the current namespace."""
    pyc_path = Path(importlib.util.cache_from_source(module_file))
    if not pyc_path.exists():
        raise ModuleNotFoundError(f"Compiled module not found: {pyc_path}")

    data = pyc_path.read_bytes()
    if len(data) < 16:
        raise ImportError(f"Compiled module header is invalid: {pyc_path}")

    code = marshal.loads(data[16:])  # nosec B302 — trusted .pyc from own bundle
    exec(code, namespace, namespace)  # nosec B102 — trusted .pyc from own bundle
