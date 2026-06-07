from __future__ import annotations

import re
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_workspace_stylesheet_contract() -> str:
    """Return the assistant CSS manifest plus local imports used by layout guards."""
    css_dir = _repo_root() / "web" / "static" / "css"
    manifest_path = css_dir / "workspace-assistant.css"
    manifest = manifest_path.read_text(encoding="utf-8")
    parts = [manifest]
    for match in re.finditer(r"@import\s+url\([\"']?([^\"')]+)[\"']?\)", manifest):
        target = match.group(1).strip()
        if not target or "://" in target or target.startswith("/"):
            continue
        imported_path = (manifest_path.parent / target).resolve()
        try:
            imported_path.relative_to(css_dir.resolve())
        except ValueError:
            continue
        if imported_path.exists():
            parts.append(imported_path.read_text(encoding="utf-8"))
    return "\n".join(parts)
