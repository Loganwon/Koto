"""Deterministic, read-only comparison operations for file tasks."""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Callable, Optional

from app.core.file.text_extraction import parse_source_file

PathResolver = Callable[[str], Optional[str]]


def compare_files(
    file_paths: str,
    aspect: str,
    *,
    resolve_path: PathResolver,
) -> str:
    """Compare files without starting a nested model or workflow."""

    requested = [
        item.strip() for item in str(file_paths or "").split(",") if item.strip()
    ]
    if len(requested) < 2:
        return json.dumps({"error": "至少需要两个文件进行对比"}, ensure_ascii=False)

    resolved: list[str] = []
    for item in requested:
        path = resolve_path(item)
        if not path:
            return json.dumps({"error": f"文件不存在: {item}"}, ensure_ascii=False)
        resolved.append(path)

    contents = {path: parse_source_file(path) for path in resolved}
    similarities: dict[str, float] = {}
    differences: list[dict[str, object]] = []
    for left_index, left_path in enumerate(resolved):
        for right_path in resolved[left_index + 1 :]:
            left = contents[left_path]
            right = contents[right_path]
            label = f"{Path(left_path).name} vs {Path(right_path).name}"
            similarities[label] = round(
                difflib.SequenceMatcher(None, left, right).ratio(), 3
            )
            diff_lines = list(
                difflib.unified_diff(
                    left.splitlines(),
                    right.splitlines(),
                    fromfile=Path(left_path).name,
                    tofile=Path(right_path).name,
                    lineterm="",
                )
            )
            if diff_lines:
                differences.append({"pair": label, "unified_diff": diff_lines[:200]})

    average = sum(similarities.values()) / len(similarities) if similarities else 0.0
    return json.dumps(
        {
            "files": resolved,
            "aspect": str(aspect or "content"),
            "similarities": similarities,
            "differences": differences,
            "summary": f"平均相似度: {average:.1%}",
        },
        ensure_ascii=False,
    )


__all__ = ["compare_files"]
