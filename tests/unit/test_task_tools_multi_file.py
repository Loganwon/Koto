from __future__ import annotations

import json

from app.core.agent.toolkits.foundation import multi_file as task_tools_multi_file


def test_compare_files_is_deterministic_and_read_only(tmp_path) -> None:
    left = tmp_path / "left.txt"
    right = tmp_path / "right.txt"
    left.write_text("alpha\nbeta\n", encoding="utf-8")
    right.write_text("alpha\ngamma\n", encoding="utf-8")

    result = json.loads(
        task_tools_multi_file.compare_files(
            "left.txt,right.txt",
            "content",
            resolve_path=lambda name: str(tmp_path / name),
        )
    )

    assert result["aspect"] == "content"
    assert list(result["similarities"]) == ["left.txt vs right.txt"]
    assert result["differences"]
    assert left.read_text(encoding="utf-8") == "alpha\nbeta\n"
    assert right.read_text(encoding="utf-8") == "alpha\ngamma\n"


def test_compare_files_rejects_missing_or_insufficient_sources() -> None:
    assert "至少需要两个文件" in task_tools_multi_file.compare_files(
        "one.docx",
        "content",
        resolve_path=lambda path: path,
    )
    assert "文件不存在: missing.pdf" in task_tools_multi_file.compare_files(
        "one.docx,missing.pdf",
        "content",
        resolve_path=lambda path: None if path == "missing.pdf" else path,
    )
