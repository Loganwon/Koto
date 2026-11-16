"""Helpers for source-architecture tests that inspect split module graphs.

P5 deliberately replaced several monolithic files with import facades.  Guard
tests should validate the reachable implementation, not assume every token
must remain in the entry module forever.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_FRONTEND_IMPORT_RE = re.compile(
    r"(?:@import\s+url\(|(?:import|export)\s+(?:[^'\"]*?\s+from\s+)?)[\"']([^\"']+)[\"']"
)


def _resolve_frontend_import(owner: Path, specifier: str) -> Path | None:
    if not specifier.startswith("."):
        return None
    candidate = (owner.parent / specifier).resolve()
    choices = [candidate]
    if not candidate.suffix:
        choices.extend(candidate.with_suffix(ext) for ext in (".ts", ".js", ".css"))
        choices.extend(candidate / f"index{ext}" for ext in (".ts", ".js"))
    for choice in choices:
        try:
            choice.relative_to(ROOT)
        except ValueError:
            continue
        if choice.is_file():
            return choice
    return None


def read_frontend_graph(relative_path: str) -> str:
    """Return a frontend entry file plus all reachable local source imports."""
    pending = [(ROOT / relative_path).resolve()]
    seen: set[Path] = set()
    sources: list[str] = []
    while pending:
        path = pending.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        source = path.read_text(encoding="utf-8")
        sources.append(source)
        for specifier in _FRONTEND_IMPORT_RE.findall(source):
            imported = _resolve_frontend_import(path, specifier)
            if imported is not None and imported not in seen:
                pending.append(imported)
    return "\n".join(sources)


_P5_FRONTEND_PARTITIONS: dict[str, tuple[str, ...]] = {
    "chat-ui": ("chat-rich-rendering",),
    "docx-extensions": ("docx-image-extension", "docx-pagination-extension"),
    "docx-pptx-toolbar": ("pptx-toolbar-actions",),
    "frontend-observer": (
        "frontend-observer-targeting",
        "frontend-observer-document-actions",
    ),
    "fs-tree": ("fs-tree-pointer-drag", "fs-tree-search", "fs-tree-file-loader"),
    "pdf-viewer": ("pdf-note-drag",),
    "selection-toolbar": (
        "selection-toolbar-types",
        "selection-toolbar-targeting",
        "selection-toolbar-document-actions",
    ),
    "skills": ("skills-community-panel", "skills-presets"),
    "state": ("state-tab-lifecycle", "state-editor-layout", "state-recent-files"),
    "task-dispatcher": ("task-dispatcher-payload", "task-followup-context"),
}


def read_frontend_partitions(relative_path: str) -> str:
    """Read an entry and only its P5 implementation partitions.

    Unlike :func:`read_frontend_graph`, this deliberately excludes shared
    dependencies.  It is useful for ownership guards whose negative assertions
    must not be polluted by legitimate symbols inside an imported utility.
    """
    root = (ROOT / relative_path).resolve()
    base_stem = root.stem
    allowed_stems = set(_P5_FRONTEND_PARTITIONS.get(base_stem, ()))
    pending = [root]
    seen: set[Path] = set()
    sources: list[str] = []
    while pending:
        path = pending.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        source = path.read_text(encoding="utf-8")
        sources.append(source)
        for specifier in _FRONTEND_IMPORT_RE.findall(source):
            imported = _resolve_frontend_import(path, specifier)
            if imported is None or imported in seen:
                continue
            is_partition = (
                root.suffix == ".css"
                or imported.stem.startswith(f"{base_stem}-part")
                or imported.stem in allowed_stems
            )
            if is_partition:
                pending.append(imported)
    return "\n".join(sources)


class _PartitionAwarePath(type(Path())):
    def read_text(self, *args, **kwargs) -> str:  # type: ignore[override]
        try:
            relative = self.resolve().relative_to(ROOT)
        except ValueError:
            return super().read_text(*args, **kwargs)
        if self.suffix in {".ts", ".js", ".css"} and "build" not in relative.parts:
            return read_frontend_partitions(relative.as_posix())
        return super().read_text(*args, **kwargs)


def partition_aware_root() -> Path:
    """Return a Path whose frontend ``read_text`` includes P5 partitions."""
    return _PartitionAwarePath(str(ROOT))


def read_python_partitions(relative_path: str) -> str:
    """Return a Python facade together with its shared owner and P5 partitions."""
    path = (ROOT / relative_path).resolve()
    shared_owners = {
        "task_tools": "task_tools_common.py",
    }
    paths = [path]
    shared_name = shared_owners.get(path.stem)
    if shared_name:
        shared_path = path.parent / shared_name
        if shared_path.is_file():
            paths.append(shared_path)
    paths.extend(sorted(path.parent.glob(f"{path.stem}_part_*.py")))
    return "\n".join(item.read_text(encoding="utf-8") for item in paths)
