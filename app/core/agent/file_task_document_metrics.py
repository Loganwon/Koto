"""Host-observed DOCX structure deltas; tool/model payloads cannot assert them."""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

from app.core.agent.file_task_artifact_transaction import resolved_write_path


class VerifiedDocxResult(dict):
    def __init__(self, value=(), structure=None):
        super().__init__(value)
        self.verified_structure = dict(structure or {})


class VerifiedDocxText(str):
    def __new__(cls, value="", structure=None):
        instance = super().__new__(cls, value)
        instance.verified_structure = dict(structure or {})
        return instance


def docx_structure(path: Path) -> dict[str, int] | None:
    """Count structure without retaining private document text or large XML."""
    if not path.is_file():
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > 16 * 1024 * 1024:
                return None
            content = archive.read(info)
        if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
            return None
        root = ElementTree.fromstring(content)
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        return {
            "tables": sum(1 for _ in root.iter(namespace + "tbl")),
            "rows": sum(1 for _ in root.iter(namespace + "tr")),
        }
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ElementTree.ParseError):
        return None


def structure_before(transaction):
    if transaction.target.suffix.lower() != ".docx":
        return None
    return (
        docx_structure(transaction.backup)
        if transaction.preexisting
        else {"tables": 0, "rows": 0}
    )


def assert_transaction_structure_preserved(transaction):
    if transaction.target.suffix.lower() == ".docx" and transaction.preexisting:
        from app.core.file_assistant.docx_preservation import (
            assert_docx_structure_preserved,
        )

        assert_docx_structure_preserved(
            transaction.backup.read_bytes(), transaction.target.read_bytes()
        )


def with_verified_structure(value, transaction, before):
    if before is None:
        return value
    after = docx_structure(transaction.target)
    if after is None:
        return value
    facts = {
        "structure_verified": True,
        "structure_target": str(transaction.target),
        "docx_tables_before": before["tables"],
        "docx_tables_after": after["tables"],
        "docx_table_rows_before": before["rows"],
        "docx_table_rows_after": after["rows"],
    }
    if isinstance(value, dict):
        return VerifiedDocxResult(value, facts)
    if isinstance(value, str):
        return VerifiedDocxText(value, facts)
    return value


def attach_structure_to_changes(changes, result):
    for change in changes:
        for key in (
            "structure_verified",
            "structure_target",
            "docx_tables_before",
            "docx_tables_after",
            "docx_table_rows_before",
            "docx_table_rows_after",
        ):
            change.pop(key, None)
    if not isinstance(result, (VerifiedDocxResult, VerifiedDocxText)):
        return changes
    facts = result.verified_structure
    try:
        expected = resolved_write_path(facts["structure_target"])
        for change in changes:
            path = change.get("path") or change.get("file_path")
            if path and resolved_write_path(str(path)) == expected:
                change.update(facts)
    except (KeyError, OSError, ValueError):
        pass
    return changes


__all__ = [
    "docx_structure",
    "structure_before",
    "with_verified_structure",
    "attach_structure_to_changes",
    "assert_transaction_structure_preserved",
]
