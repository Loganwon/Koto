"""Independent artifact-based scoring for the public office task evaluation."""

from __future__ import annotations

import hashlib
import csv
from decimal import Decimal
import io
from pathlib import Path
import re
import zipfile


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def document_text(path):
    path = Path(path)
    if path.suffix == ".docx":
        from docx import Document
        doc = Document(path)
        return "\n".join([p.text for p in doc.paragraphs] + [
            " | ".join(cell.text for cell in row.cells) for table in doc.tables for row in table.rows
        ])
    if path.suffix == ".pptx":
        from pptx import Presentation
        return "\n".join(str(getattr(shape, "text", "")) for slide in Presentation(path).slides for shape in slide.shapes)
    if path.suffix == ".xlsx":
        from openpyxl import load_workbook
        book = load_workbook(path, data_only=False)
        text = "\n".join(str(cell.value) for sheet in book for row in sheet for cell in row if cell.value is not None)
        book.close()
        return text
    return path.read_bytes().decode("utf-8-sig")


def artifact_snapshot(folder):
    """Record semantic and style state before execution, independently of tools."""
    folder = Path(folder)
    result = {}
    for path in folder.iterdir():
        if not path.is_file():
            continue
        record = {"sha256": digest(path)}
        if path.suffix == ".docx":
            from docx import Document
            doc = Document(path)
            record["paragraph_xml"] = [p._p.xml for p in doc.paragraphs]
            record["table_xml"] = [table._tbl.xml for table in doc.tables]
            with zipfile.ZipFile(path) as package:
                record["preserved_parts"] = {
                    name: hashlib.sha256(package.read(name)).hexdigest()
                    for name in package.namelist()
                    if name.startswith(("word/header", "word/footer", "word/styles"))
                }
        elif path.suffix == ".xlsx":
            from openpyxl import load_workbook
            book = load_workbook(path, data_only=False)
            record["cells"] = {
                cell.coordinate: {"value": cell.value, "style": list(cell._style or [])}
                for row in book.active for cell in row
            }
            record["dimensions"] = [book.active.max_row, book.active.max_column]
            book.close()
        elif path.suffix == ".pptx":
            with zipfile.ZipFile(path) as package:
                record["slide_xml"] = {
                    name: hashlib.sha256(package.read(name)).hexdigest()
                    for name in package.namelist()
                    if (name.startswith("ppt/slides/slide") and name.endswith(".xml"))
                    or name.startswith("ppt/theme/")
                }
        result[path.name] = record
    return result


def terminal_success(events):
    from app.core.services.file_task_event_semantics import file_task_terminal_status
    terminals = [event for event in events if event["type"] == "run.finished"]
    return bool(terminals) and all(file_task_terminal_status("run.finished", event["payload"]) == "completed" for event in terminals)


def answer_from_events(events):
    finished = [str(event["payload"].get("content") or event["payload"].get("text") or "")
                for event in events if event["type"] == "message.finished"]
    if any(finished):
        return next(value for value in reversed(finished) if value)
    chunks = [str(event["payload"].get("delta") or event["payload"].get("text") or "")
              for event in events if event["type"] == "message.delta"]
    if any(chunks):
        return "".join(chunks)
    terminals = [event["payload"] for event in events if event["type"] == "run.finished"]
    return "\n".join(str(item.get("answer") or item.get("content") or item.get("summary") or "") for item in terminals)


def score_case(case, folder, before, events, *, resumed=False):
    folder = Path(folder)
    answer = answer_from_events(events)
    checks = []
    for spec in case["checks"]:
        kind = spec["kind"]
        reason = ""
        try:
            path = folder / spec.get("file", "")
            if kind == "untouched_inputs":
                passed = all((folder / name).is_file() and digest(folder / name) == record["sha256"]
                             for name, record in before.items())
            elif kind == "only_target_changed":
                allowed = set(spec["files"])
                passed = all(name in allowed or ((folder / name).is_file() and digest(folder / name) == record["sha256"])
                             for name, record in before.items())
            elif kind == "answer_contains":
                passed = all(value in answer for value in spec["values"])
            elif kind == "answer_excludes":
                passed = all(value not in answer for value in spec["values"])
            elif kind == "grounded_numbers":
                text = document_text(path) if spec.get("file") else answer
                normalize = lambda number, unit: (str(Decimal(number).normalize()), "%" if unit == "％" else unit)
                allowed = {normalize(number, unit) for claim in spec["values"]
                           for number, unit in re.findall(r"(-?\d+(?:\.\d+)?)\s*(万元|[%％])", claim)}
                claims = {normalize(number, unit) for number, unit in re.findall(r"(-?\d+(?:\.\d+)?)\s*(万元|[%％])", text)}
                dates = set(re.findall(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", text))
                passed = claims <= allowed and dates <= set(spec.get("dates", []))
            elif kind == "exact_text":
                passed = document_text(path) == spec["expected"]
            elif kind == "csv_rows":
                # New files use the host platform's newline convention; scope
                # is measured by every logical row/cell, including row count.
                passed = list(csv.reader(io.StringIO(document_text(path)))) == spec["expected"]
            elif kind == "contains":
                text = document_text(path)
                passed = all(value in text for value in spec["values"])
            elif kind == "text_count":
                passed = document_text(path).count(spec["text"]) == spec["count"]
            elif kind == "absent":
                passed = not path.exists()
            elif kind == "no_success_terminal":
                from app.core.services.file_task_event_semantics import file_task_terminal_status
                passed = not any(event["type"] == "run.finished"
                                 and file_task_terminal_status("run.finished", event["payload"]) == "completed"
                                 for event in events)
            elif kind == "tool_failure_observed":
                passed = any(event["type"] == "tool.finished" and event["payload"].get("success") is False
                             for event in events)
            elif kind == "failure_evidence":
                passed = bool(answer.strip()) and any(
                    event["type"] == "tool.finished" and event["payload"].get("success") is False
                    for event in events
                )
            elif kind == "resume_receipt":
                passed = resumed and any(event["type"] == "file.changed" and event["payload"].get("recovered") for event in events)
            elif kind == "tool_name_call_count":
                passed = sum(event["type"] == "tool.started" and event["payload"].get("tool_name") == spec["name"]
                             for event in events) == spec["count"]
            elif kind == "generated_outputs":
                current = {item.name for item in folder.iterdir() if item.is_file()}
                expected = set(spec["files"])
                # Exact companion backups are a documented safety side effect,
                # not a second user-facing output or a repeated logical write.
                backups = {name + ".bak" for name in expected}
                passed = (current - before.keys()) - backups == expected
                passed = passed and all(digest(folder / name) == value["sha256"] for name, value in before.items())
            elif kind == "docx_prefix_preserved":
                from docx import Document
                doc = Document(path)
                original = before[path.name]
                passed = [p._p.xml for p in doc.paragraphs[:len(original["paragraph_xml"])]] == original["paragraph_xml"]
                if "extra" in spec:
                    passed = passed and len(doc.paragraphs) == len(original["paragraph_xml"]) + spec["extra"]
                passed = passed and [table._tbl.xml for table in doc.tables] == original["table_xml"]
                with zipfile.ZipFile(path) as package:
                    passed = passed and all(hashlib.sha256(package.read(name)).hexdigest() == value
                                            for name, value in original["preserved_parts"].items())
            elif kind in {"xlsx_cell", "xlsx_scope"}:
                from openpyxl import load_workbook
                book = load_workbook(path, data_only=False)
                sheet = book.active
                if kind == "xlsx_cell":
                    passed = sheet[spec["cell"]].value == spec["value"]
                else:
                    allowed = set(spec["allowed"])
                    passed = all((name in allowed or sheet[name].value == cell["value"])
                                 and list(sheet[name]._style or []) == cell["style"]
                                 for name, cell in before[path.name]["cells"].items())
                    passed = passed and [sheet.max_row, sheet.max_column] == before[path.name]["dimensions"]
                book.close()
            elif kind == "pptx_prefix_preserved":
                from pptx import Presentation
                original = before[path.name]["slide_xml"]
                with zipfile.ZipFile(path) as package:
                    passed = all(hashlib.sha256(package.read(name)).hexdigest() == value for name, value in original.items())
                count = sum(name.startswith("ppt/slides/slide") for name in original)
                passed = passed and len(Presentation(path).slides) == count + spec["extra"]
            else:
                raise ValueError("Unknown scoring rule")
        except Exception as exc:
            passed, reason = False, type(exc).__name__
        checks.append({"kind": kind, "passed": bool(passed), "reason": reason,
                       **{key: value for key, value in spec.items() if key not in {"kind", "expected"}}})
    expected_safe_failure = case["group"] == "recovery" and case["fault"] != "checkpoint_resume"
    if not expected_safe_failure:
        terminal_count = sum(event["type"] == "run.finished" for event in events)
        checks.append({"kind": "completed_terminal",
                       "passed": terminal_success(events) and terminal_count == len(case["phases"]),
                       "reason": "", "expected_phases": len(case["phases"]), "observed_terminals": terminal_count})
    passed = all(check["passed"] for check in checks)
    return {"passed": passed, "score": sum(check["passed"] for check in checks) / max(1, len(checks)),
            "checks": checks, "answer": answer}
