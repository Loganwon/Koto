# ══════════════════════════════════════════════════════════════
# task_tools.py — Composable file-operation tools for TaskAgent
#
# These tools are the building blocks the AI orchestrates freely
# to accomplish user tasks on workspace files.  Each tool is
# self-contained: read → process → write, with no hardcoded
# workflow assumptions.
# ══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.agent.base import AgentPlugin
from app.core.agent.path_utils import default_search_roots, resolve_existing_path

logger = logging.getLogger(__name__)

_TEXT_LIMIT_MIN = 1_000
_TEXT_LIMIT_DEFAULT = 60_000
_TEXT_LIMIT_DOCX_DEFAULT = 24_000
_TEXT_LIMIT_MAX = 200_000
_TASK_TOOL_LLM_CALL_TIMEOUT = float(os.getenv("KOTO_FILE_TASK_LLM_TIMEOUT", "45"))

# ── Workspace root (same resolver as WorkspaceEditorPlugin) ──────────────────
_WORKSPACE_ROOT: Optional[str] = None


def _get_workspace_root() -> str:
    global _WORKSPACE_ROOT
    if _WORKSPACE_ROOT is None:
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        _WORKSPACE_ROOT = str(project_root / "workspace")
    return _WORKSPACE_ROOT


def _safe_resolve(relative_path: str) -> Optional[str]:
    """Resolve a user path inside workspace root. Returns None on traversal."""
    root = _get_workspace_root()
    # Strip leading "workspace/" prefix — the model sometimes includes it even
    # though paths are already relative to the workspace root.
    stripped = relative_path.replace("\\", "/")
    if stripped.startswith("workspace/"):
        stripped = stripped[len("workspace/") :]
    try:
        resolved = os.path.normpath(os.path.join(root, stripped))
        if not resolved.startswith(os.path.normpath(root)):
            return None
        return resolved
    except (ValueError, TypeError):
        return None


def _resolve_path(path: str) -> Optional[str]:
    """Accept both absolute and relative-to-workspace paths."""
    if os.path.isabs(path):
        return path if os.path.exists(path) else None

    # Keep workspace-relative priority for backward compatibility.
    ws_candidate = _safe_resolve(path)
    if ws_candidate and os.path.exists(ws_candidate):
        return ws_candidate

    roots = [_get_workspace_root(), *default_search_roots()]
    resolved, _ = resolve_existing_path(path, roots=roots)
    return resolved


def _result_path(raw_path: str, resolved_path: str) -> str:
    """Return a workspace-relative path so the frontend can match it to wsSourcePath.

    Falls back to absolute path when the file is outside the workspace root.
    Frontend refresh (_refreshChangedFile) compares this to state.wsSourcePath which
    is always workspace-relative, so returning absolute paths breaks the match.
    """
    target = resolved_path or raw_path
    if not target:
        return raw_path
    ws_root = _get_workspace_root()
    try:
        rel = os.path.relpath(target, ws_root).replace("\\", "/")
        if not rel.startswith(".."):
            return rel
    except (ValueError, TypeError):
        pass
    return target


def _normalize_text_limit(max_chars: Any, default: int) -> int:
    try:
        value = int(max_chars)
    except (TypeError, ValueError):
        value = default
    return min(max(_TEXT_LIMIT_MIN, value), _TEXT_LIMIT_MAX)


def _read_pdf_excerpt(
    path: str,
    *,
    max_chars: int,
    start_page: int = 1,
    end_page: int = 0,
) -> str:
    """Read only a window of PDF pages to avoid full-document extraction stalls."""
    start_page = max(1, int(start_page or 1))
    end_page = max(0, int(end_page or 0))

    def _collect_from_pdfplumber() -> str:
        import pdfplumber  # type: ignore

        parts: list[str] = []
        total = 0
        with pdfplumber.open(path) as pdf:
            last_page = min(end_page or len(pdf.pages), len(pdf.pages))
            for index in range(start_page - 1, last_page):
                page_text = ""
                try:
                    page_text = pdf.pages[index].extract_text() or ""
                except Exception as exc:
                    logger.debug(
                        "[TaskTools] pdfplumber page %s failed: %s", index + 1, exc
                    )
                if not page_text.strip():
                    continue
                block = f"[Page {index + 1}]\n{page_text.strip()}"
                parts.append(block)
                total += len(block)
                if total >= max_chars:
                    break
        return "\n\n".join(parts)

    def _collect_from_pypdf() -> str:
        reader = None
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(path)
        except ImportError:
            from PyPDF2 import PdfReader  # type: ignore

            reader = PdfReader(path)

        parts: list[str] = []
        total = 0
        last_page = min(end_page or len(reader.pages), len(reader.pages))
        for index in range(start_page - 1, last_page):
            try:
                page_text = reader.pages[index].extract_text() or ""
            except Exception as exc:
                logger.debug("[TaskTools] pypdf page %s failed: %s", index + 1, exc)
                page_text = ""
            if not page_text.strip():
                continue
            block = f"[Page {index + 1}]\n{page_text.strip()}"
            parts.append(block)
            total += len(block)
            if total >= max_chars:
                break
        return "\n\n".join(parts)

    for collector in (_collect_from_pdfplumber, _collect_from_pypdf):
        try:
            excerpt = collector()
            if excerpt.strip():
                return excerpt[:max_chars]
        except ImportError:
            continue
        except Exception as exc:
            logger.debug("[TaskTools] PDF excerpt collector failed: %s", exc)

    from app.core.workflow_engine import parse_source_file

    return parse_source_file(path)[:max_chars]


def _success_result(
    path: str,
    *,
    operation: str,
    summary: str,
    file_type: str = "",
    change_type: str = "modify",
    preview: str = "",
    focus: bool = False,
    **extra: Any,
) -> str:
    payload: Dict[str, Any] = {
        "success": True,
        "path": path,
        "file_type": file_type or Path(str(path)).suffix.lstrip(".").lower(),
        "change_type": change_type,
        "operation": operation,
        "summary": summary,
        "preview": preview[:400],
        "focus": focus,
    }
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False, default=str)


# ══════════════════════════════════════════════════════════════
# Tool implementations
# ══════════════════════════════════════════════════════════════


def read_sheet_data(path: str, sheet_name: str = "", max_rows: int = 500) -> str:
    """Read spreadsheet cells as structured JSON.

    Returns JSON: {"sheet": "<name>", "headers": [...], "rows": [[...], ...]}
    """
    resolved = _resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)

    try:
        import openpyxl

        wb = openpyxl.load_workbook(resolved, read_only=True, data_only=True)
        target_sheet = sheet_name or wb.sheetnames[0]
        if target_sheet not in wb.sheetnames:
            wb.close()
            return json.dumps(
                {
                    "error": f"Sheet '{target_sheet}' not found. Available: {wb.sheetnames}"
                },
                ensure_ascii=False,
            )
        ws = wb[target_sheet]
        headers: list[str] = []
        rows: list[list] = []
        for i, row in enumerate(ws.iter_rows(max_row=max_rows + 1, values_only=True)):
            cells = [v if v is not None else "" for v in row]
            if i == 0:
                headers = [str(c) for c in cells]
            else:
                rows.append(cells)
        wb.close()
        return json.dumps(
            {
                "sheet": target_sheet,
                "headers": headers,
                "rows": rows,
                "row_count": len(rows),
            },
            ensure_ascii=False,
            default=str,
        )
    except ImportError:
        return json.dumps({"error": "openpyxl not installed"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def write_sheet_data(path: str, sheet_name: str = "", updates: str = "[]") -> str:
    """Write cells to a spreadsheet.

    `updates` is a JSON array: [{"row": 1, "col": 1, "value": "..."}, ...]
    Row and col are 1-indexed.
    """
    resolved = _resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)

    try:
        cell_updates = json.loads(updates) if isinstance(updates, str) else updates
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid updates JSON: {e}"}, ensure_ascii=False)

    try:
        import openpyxl

        # Backup before writing
        backup = resolved + ".bak"
        shutil.copy2(resolved, backup)

        wb = openpyxl.load_workbook(resolved)
        target = sheet_name or wb.sheetnames[0]
        if target not in wb.sheetnames:
            wb.close()
            return json.dumps(
                {"error": f"Sheet '{target}' not found"}, ensure_ascii=False
            )
        ws = wb[target]

        count = 0
        for u in cell_updates:
            row = int(u.get("row", 0))
            col = int(u.get("col", 0))
            value = u.get("value", "")
            if row < 1 or col < 1:
                continue
            cell = ws.cell(row=row, column=col)
            # Detect Excel formulas — write as formula, not literal string
            if isinstance(value, str) and value.startswith("="):
                cell.value = value
            else:
                cell.value = value
            count += 1

        wb.save(resolved)
        wb.close()
        target_sheet = sheet_name or target
        return _success_result(
            _result_path(path, resolved),
            operation="write_sheet_data",
            summary=f"已写入 {count} 个单元格到工作表“{target_sheet}”",
            file_type="xlsx",
            change_type="modify",
            cells_written=count,
            sheet=target_sheet,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def read_docx_content(path: str, max_chars: int = _TEXT_LIMIT_DOCX_DEFAULT) -> str:
    """Read DOCX paragraphs as structured JSON.

    Returns JSON with paragraphs and tables.
    """
    resolved = _resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)

    max_chars = _normalize_text_limit(max_chars, _TEXT_LIMIT_DOCX_DEFAULT)

    try:
        from docx import Document as DocxDocument

        doc = DocxDocument(resolved)
        paragraphs = []
        tables = []
        total = 0
        for p in doc.paragraphs:
            if total >= max_chars:
                break
            paragraphs.append(
                {
                    "text": p.text,
                    "style": p.style.name if p.style else "",
                }
            )
            total += len(p.text)

        for table_index, table in enumerate(doc.tables):
            if total >= max_chars:
                break
            table_rows = []
            for row_index, row in enumerate(table.rows):
                if row_index >= 20 or total >= max_chars:
                    break
                values = [cell.text for cell in row.cells]
                table_rows.append(values)
                total += sum(len(v) for v in values)
            tables.append(
                {
                    "index": table_index,
                    "rows": table_rows,
                    "row_count": len(table.rows),
                    "column_count": len(table.columns),
                }
            )

        return json.dumps(
            {
                "paragraphs": paragraphs,
                "tables": tables,
                "total_paragraphs": len(doc.paragraphs),
                "total_tables": len(doc.tables),
            },
            ensure_ascii=False,
        )
    except ImportError:
        return json.dumps({"error": "python-docx not installed"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def parse_file_to_text(
    path: str,
    max_chars: int = _TEXT_LIMIT_DEFAULT,
    start_page: int = 1,
    end_page: int = 0,
) -> str:
    """Parse any supported file to plain text (DOCX/XLSX/PPTX/PDF/TXT/CSV)."""
    resolved = _resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)

    try:
        from app.core.workflow_engine import parse_source_file

        suffix = Path(resolved).suffix.lower()
        if suffix == ".pdf":
            text = _read_pdf_excerpt(
                resolved,
                max_chars=max_chars,
                start_page=start_page,
                end_page=end_page,
            )
        else:
            text = parse_source_file(resolved)
        if not text.strip():
            return f"(File parsed but no text content: {path})"
        return text[:max_chars]
    except Exception as e:
        return f"Error parsing file: {e}"


def _resolve_task_file_entries(
    task_files: Optional[List[Dict[str, str]]],
) -> List[Dict[str, str]]:
    """Resolve task file metadata into concrete files that can be staged."""
    resolved_entries: List[Dict[str, str]] = []
    seen: set[str] = set()

    for item in task_files or []:
        if not isinstance(item, dict):
            continue

        raw_path = str(item.get("path") or "").strip()
        raw_name = str(item.get("name") or "").strip()
        resolved_path = _resolve_path(raw_path or raw_name)
        if not resolved_path or not os.path.isfile(resolved_path):
            continue

        key = os.path.normcase(os.path.abspath(resolved_path))
        if key in seen:
            continue
        seen.add(key)

        resolved_entries.append(
            {
                "display_name": raw_name or os.path.basename(resolved_path),
                "source_path": resolved_path,
            }
        )

    return resolved_entries


def _unique_staged_name(name: str, used_names: set[str]) -> str:
    """Return a unique basename for files mirrored into the sandbox workdir."""
    candidate = os.path.basename(name or "") or "task_file"
    stem, ext = os.path.splitext(candidate)
    normalized = candidate.lower()
    index = 2
    while normalized in used_names:
        candidate = f"{stem}_{index}{ext}"
        normalized = candidate.lower()
        index += 1
    used_names.add(normalized)
    return candidate


def _stage_task_files_for_sandbox(
    resolved_entries: List[Dict[str, str]], sandbox_dir: str
) -> List[Dict[str, str]]:
    """Copy resolved task files into the sandbox workdir for basename-based access."""
    staged_entries: List[Dict[str, str]] = []
    used_names: set[str] = set()

    for entry in resolved_entries:
        staged_name = _unique_staged_name(entry["display_name"], used_names)
        staged_path = os.path.join(sandbox_dir, staged_name)
        shutil.copy2(entry["source_path"], staged_path)
        staged_entries.append(
            {
                **entry,
                "staged_name": staged_name,
                "staged_path": staged_path,
            }
        )

    return staged_entries


def _prepend_task_file_context(code: str, staged_entries: List[Dict[str, str]]) -> str:
    """Expose task file paths to sandbox code and keep basename access working."""
    if not staged_entries:
        return code

    absolute_paths = {
        entry["display_name"]: entry["source_path"] for entry in staged_entries
    }
    staged_paths = {
        entry["display_name"]: entry["staged_path"] for entry in staged_entries
    }
    staged_names = [entry["staged_name"] for entry in staged_entries]

    workspace_root = _get_workspace_root()
    preamble = (
        "# Attached task files are mirrored into the sandbox working directory.\n"
        f"TASK_WORKSPACE_ROOT = {json.dumps(workspace_root, ensure_ascii=False)}\n"
        f"TASK_FILE_PATHS = {json.dumps(absolute_paths, ensure_ascii=False)}\n"
        f"TASK_SANDBOX_FILE_PATHS = {json.dumps(staged_paths, ensure_ascii=False)}\n"
        f"TASK_SANDBOX_FILES = {json.dumps(staged_names, ensure_ascii=False)}\n"
        "# After creating a file in the workspace, print: KOTO_CREATED:<absolute_path>\n"
        "# e.g. print('KOTO_CREATED:' + output_path)\n\n"
    )
    return preamble + code


def _parse_koto_created_paths(stdout: str) -> List[str]:
    """Extract KOTO_CREATED:<path> markers printed by sandbox code."""
    paths: List[str] = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if line.startswith("KOTO_CREATED:"):
            candidate = line[len("KOTO_CREATED:") :].strip()
            if candidate and os.path.isabs(candidate) and os.path.isfile(candidate):
                paths.append(candidate)
    return paths


def _format_sandbox_result(result: Dict[str, Any]) -> str:
    """Normalize sandbox execution output into a single text payload."""
    parts = []
    if result.get("stdout"):
        parts.append(result["stdout"])
    if result.get("stderr"):
        parts.append(f"[stderr] {result['stderr']}")
    generated_files = result.get("files") or result.get("images") or {}
    if generated_files:
        parts.append(f"[{len(generated_files)} image(s) generated]")
    if result.get("error"):
        parts.append(f"[error] {result['error']}")
    return "\n".join(parts) if parts else "(no output)"


def run_python_in_sandbox(
    code: str, timeout: int = 30, task_files: Optional[List[Dict[str, str]]] = None
) -> str:
    """Execute Python code in the sandbox. Returns stdout + stderr + images.

    If the code prints ``KOTO_CREATED:<absolute_path>`` lines, those paths are
    returned as a JSON suffix so the task agent can emit file_change events.
    """
    try:
        from app.core.sandbox import run_python

        resolved_task_files = _resolve_task_file_entries(task_files)
        if resolved_task_files:
            with tempfile.TemporaryDirectory(prefix="koto-task-") as tmpdir:
                staged_entries = _stage_task_files_for_sandbox(
                    resolved_task_files, tmpdir
                )
                prepared_code = _prepend_task_file_context(code, staged_entries)
                result = run_python(prepared_code, timeout=timeout, work_dir=tmpdir)
                return _wrap_sandbox_result(result)

        result = run_python(code, timeout=timeout)
        return _wrap_sandbox_result(result)
    except Exception as e:
        return f"Sandbox error: {e}"


def _wrap_sandbox_result(result: Dict[str, Any]) -> str:
    """Format sandbox result; append __koto_created__ JSON if files were created."""
    text = _format_sandbox_result(result)
    created = _parse_koto_created_paths(result.get("stdout", ""))
    if created:
        text += "\n__koto_created__:" + json.dumps(created, ensure_ascii=False)
    return text


def list_workspace_files(path: str = "", recursive: bool = False) -> str:
    """List files in workspace directory. Returns JSON array of file info."""
    root = _get_workspace_root()
    target = _safe_resolve(path) if path else root
    if target is None or not os.path.isdir(target):
        return json.dumps({"error": f"Directory not found: {path}"}, ensure_ascii=False)

    entries = []
    try:
        if recursive:
            for dirpath, dirnames, filenames in os.walk(target):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for fname in filenames:
                    if fname.startswith("."):
                        continue
                    fpath = os.path.join(dirpath, fname)
                    rel = os.path.relpath(fpath, root).replace("\\", "/")
                    try:
                        st = os.stat(fpath)
                        entries.append({"name": rel, "size": st.st_size})
                    except OSError:
                        pass
                    if len(entries) >= 300:
                        break
        else:
            for item in sorted(os.listdir(target)):
                if item.startswith("."):
                    continue
                fpath = os.path.join(target, item)
                rel = os.path.relpath(fpath, root).replace("\\", "/")
                is_dir = os.path.isdir(fpath)
                entries.append(
                    {
                        "name": rel,
                        "type": "dir" if is_dir else "file",
                        "size": 0 if is_dir else os.path.getsize(fpath),
                    }
                )
    except PermissionError:
        return json.dumps({"error": "Permission denied"}, ensure_ascii=False)

    return json.dumps(entries, ensure_ascii=False)


def open_file_in_editor(path: str) -> str:
    """Open a file in the frontend editor so the user can view it.
    Use this when the user wants to open, view, or navigate to a file
    — NOT for reading content. The file will be brought into focus in the UI.
    """
    resolved = _resolve_path(path)
    if not resolved or not os.path.isfile(resolved):
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)
    fname = os.path.basename(resolved)
    root = _get_workspace_root()
    rel = os.path.relpath(resolved, root).replace("\\", "/") if root else resolved
    return _success_result(
        rel,
        operation="open_file",
        summary=f"已打开 {fname}",
        file_type=Path(resolved).suffix.lstrip(".").lower(),
        change_type="open",
        focus=True,
    )


def copy_file(source: str, destination: str) -> str:
    """Copy a file within the workspace."""
    src = _resolve_path(source)
    if not src:
        return json.dumps({"error": f"Source not found: {source}"}, ensure_ascii=False)
    dst = _safe_resolve(destination)
    if not dst:
        return json.dumps(
            {"error": f"Invalid destination: {destination}"}, ensure_ascii=False
        )
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return _success_result(
            _result_path(destination, dst),
            operation="copy_file",
            summary=f"已复制文件到 {os.path.basename(dst)}",
            change_type="create",
            file_type=Path(dst).suffix.lstrip(".").lower(),
            focus=True,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def create_file(path: str, content: str = "") -> str:
    """Create a new file in the workspace."""
    resolved = _safe_resolve(path)
    if not resolved:
        return json.dumps({"error": f"Invalid path: {path}"}, ensure_ascii=False)
    if os.path.exists(resolved):
        return json.dumps({"error": "File already exists"}, ensure_ascii=False)
    try:
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)
        return _success_result(
            _result_path(path, resolved),
            operation="create_file",
            summary=f"已创建文件 {os.path.basename(resolved)}",
            change_type="create",
            preview=content,
            focus=True,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def llm_extract(text: str, fields: str, instructions: str = "") -> str:
    """Use LLM to extract structured data from text.

    Args:
        text: The source text to extract from.
        fields: Comma-separated field names to extract.
        instructions: Optional additional instructions for the LLM.

    Returns: JSON object with field names as keys.
    """
    from app.core.workflow_engine import call_llm_json

    field_list = [f.strip() for f in fields.split(",") if f.strip()]
    prompt = (
        f"从以下文本中提取指定字段的值。\n\n"
        f"字段列表: {json.dumps(field_list, ensure_ascii=False)}\n\n"
        f"文本:\n---\n{text[:6000]}\n---\n\n"
    )
    if instructions:
        prompt += f"额外要求: {instructions}\n\n"
    prompt += (
        "以 JSON 对象输出，key 为字段名，value 为提取到的值。"
        "找不到的字段值设为 null。只输出 JSON。"
    )
    try:
        result = call_llm_json(prompt, call_timeout=_TASK_TOOL_LLM_CALL_TIMEOUT)
        if isinstance(result, dict):
            return json.dumps(result, ensure_ascii=False)
        return json.dumps({"raw": str(result)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def llm_transform(text: str, instruction: str) -> str:
    """Use LLM to transform text according to instruction.

    Args:
        text: The source text to transform.
        instruction: What transformation to apply.

    Returns: The transformed text.
    """
    from app.core.workflow_engine import call_llm

    prompt = f"{instruction}\n\n原文:\n---\n{text[:6000]}\n---"
    try:
        return call_llm(prompt, call_timeout=_TASK_TOOL_LLM_CALL_TIMEOUT)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
# New tools for DocAgent - Multi-file operations
# ══════════════════════════════════════════════════════════════


def compare_files(file_paths: str, aspect: str = "content") -> str:
    """Compare multiple files and return similarity analysis.

    Args:
        file_paths: Comma-separated list of file paths to compare.
        aspect: What to compare ("content", "structure").

    Returns: JSON with similarity scores and differences.
    """
    import asyncio

    from app.core.agent.doc_agent import FileHandle
    from app.core.file.multi_file_coordinator import get_file_coordinator

    paths = [p.strip() for p in file_paths.split(",") if p.strip()]
    if len(paths) < 2:
        return json.dumps({"error": "至少需要两个文件进行对比"}, ensure_ascii=False)

    resolved_paths = []
    for p in paths:
        resolved = _resolve_path(p)
        if not resolved:
            return json.dumps({"error": f"文件不存在: {p}"}, ensure_ascii=False)
        resolved_paths.append(resolved)

    try:
        files = [FileHandle(path=p) for p in resolved_paths]
        coordinator = get_file_coordinator()

        # Run async comparison in sync context
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                coordinator.compare_documents(files, aspect)
            )
        finally:
            loop.close()

        return json.dumps(result.to_dict(), ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def extract_to_file(
    source_path: str,
    target_path: str,
    extract_query: str,
    insert_position: str = "end",
) -> str:
    """Extract data from source file and inject into target file.

    Args:
        source_path: Path to source file (e.g., Excel with data).
        target_path: Path to target file (e.g., Word document).
        extract_query: Description of what to extract.
        insert_position: Where to insert ("start", "end", "cursor").

    Returns: JSON with operation result and change details.
    """
    import asyncio

    from app.core.agent.doc_agent import FileHandle
    from app.core.file.multi_file_coordinator import get_file_coordinator

    src = _resolve_path(source_path)
    if not src:
        return json.dumps({"error": f"源文件不存在: {source_path}"}, ensure_ascii=False)

    tgt = _resolve_path(target_path)
    if not tgt:
        # Target can be new file
        tgt = _safe_resolve(target_path)
        if not tgt:
            return json.dumps(
                {"error": f"目标路径无效: {target_path}"}, ensure_ascii=False
            )

    try:
        source = FileHandle(path=src)
        target = FileHandle(path=tgt)
        coordinator = get_file_coordinator()

        loop = asyncio.new_event_loop()
        try:
            change = loop.run_until_complete(
                coordinator.extract_and_inject(
                    source, target, extract_query, insert_position
                )
            )
        finally:
            loop.close()

        return json.dumps(
            {
                "success": change.change_type != "none",
                "change": change.to_dict(),
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def annotate_file(path: str, annotations: str = "[]") -> str:
    """Add annotations/highlights to a file.

    Args:
        path: Path to the file to annotate.
        annotations: JSON array of annotations:
            [{"range_start": 0, "range_end": 100, "comment": "...", "color": "yellow"}]

    Returns: JSON with annotation results.
    """
    import asyncio

    from app.core.file.multi_file_coordinator import get_file_coordinator

    resolved = _resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)

    try:
        ann_list = (
            json.loads(annotations) if isinstance(annotations, str) else annotations
        )
    except json.JSONDecodeError as e:
        return json.dumps(
            {"error": f"无效的 annotations JSON: {e}"}, ensure_ascii=False
        )

    try:
        coordinator = get_file_coordinator()

        loop = asyncio.new_event_loop()
        try:
            changes = loop.run_until_complete(
                coordinator.annotate_file(resolved, ann_list)
            )
        finally:
            loop.close()

        return json.dumps(
            {
                "success": True,
                "annotations_added": len(changes),
                "changes": [c.to_dict() for c in changes],
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def insert_excel_as_docx_table(
    source_path: str,
    target_path: str,
    sheet_name: str = "",
    table_title: str = "",
    max_rows: int = 200,
) -> str:
    """Insert spreadsheet data into a DOCX file as a real Word table."""
    source_resolved = _resolve_path(source_path)
    if not source_resolved:
        return json.dumps(
            {"error": f"File not found: {source_path}"}, ensure_ascii=False
        )

    target_resolved = _resolve_path(target_path)
    if not target_resolved:
        if os.path.isabs(target_path):
            target_resolved = os.path.normpath(target_path)
        else:
            target_resolved = _safe_resolve(target_path)
    if not target_resolved:
        return json.dumps({"error": f"Invalid path: {target_path}"}, ensure_ascii=False)

    try:
        import openpyxl
        from docx import Document

        workbook = openpyxl.load_workbook(
            source_resolved, read_only=True, data_only=True
        )
        target_sheet = sheet_name or workbook.sheetnames[0]
        if target_sheet not in workbook.sheetnames:
            workbook.close()
            return json.dumps(
                {
                    "error": f"Sheet '{target_sheet}' not found. Available: {workbook.sheetnames}"
                },
                ensure_ascii=False,
            )

        worksheet = workbook[target_sheet]
        raw_rows: List[List[str]] = []
        for row in worksheet.iter_rows(values_only=True):
            if len(raw_rows) >= max_rows + 1:
                break
            values = ["" if value is None else str(value) for value in row]
            if any(value.strip() for value in values):
                raw_rows.append(values)
        workbook.close()

        if not raw_rows:
            return json.dumps(
                {"error": f"Sheet '{target_sheet}' has no data"}, ensure_ascii=False
            )

        column_count = max(len(row) for row in raw_rows)
        normalized_rows = [row + [""] * (column_count - len(row)) for row in raw_rows]
        headers = normalized_rows[0]
        data_rows = normalized_rows[1:]

        os.makedirs(os.path.dirname(target_resolved), exist_ok=True)
        target_exists = os.path.exists(target_resolved)
        if target_exists:
            shutil.copy2(target_resolved, target_resolved + ".bak")
            try:
                document = Document(target_resolved)
            except Exception as open_err:
                return json.dumps(
                    {
                        "error": (
                            f"无法用 python-docx 打开 {os.path.basename(target_resolved)}"
                            f"（{open_err}）。"
                            "请改用 run_python_code + python-docx 手动追加表格，"
                            "或用 openpyxl 读取数据后用脚本写入 docx。"
                        )
                    },
                    ensure_ascii=False,
                )
        else:
            document = Document()

        if document.paragraphs and any(p.text.strip() for p in document.paragraphs):
            document.add_paragraph("")

        if table_title:
            title_paragraph = document.add_paragraph(table_title)
            try:
                title_paragraph.style = "Heading 2"
            except Exception:
                pass

        table = document.add_table(rows=len(normalized_rows), cols=column_count)
        try:
            table.style = "Table Grid"
        except Exception:
            pass

        for row_index, row_values in enumerate(normalized_rows):
            for column_index, value in enumerate(row_values):
                table.cell(row_index, column_index).text = value

        document.save(target_resolved)

        preview_lines = []
        if headers:
            preview_lines.append(" | ".join(headers[:6]))
        for row_values in data_rows[:3]:
            preview_lines.append(" | ".join(row_values[:6]))

        return _success_result(
            _result_path(target_path, target_resolved),
            operation="insert_excel_as_docx_table",
            summary=f"已将工作表“{target_sheet}”的 {len(data_rows)} 行数据写入 Word 表格",
            file_type="docx",
            change_type="modify" if target_exists else "create",
            preview="\n".join(preview_lines),
            focus=True,
            source_path=_result_path(source_path, source_resolved),
            sheet=target_sheet,
            rows_written=len(data_rows),
            columns_written=column_count,
            table_title=table_title,
            table_count=1,
        )
    except ImportError as exc:
        return json.dumps({"error": f"Missing dependency: {exc}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def verify_task_completion(
    task_description: str, file_states: str = "[]", model_mode: str = "auto"
) -> str:
    """Verify whether a task was completed successfully.

    Uses a heuristic: if all tracked files are marked as modified, the task is
    considered complete.  A separate LLM call was previously used here but it
    proved unreliable — local Ollama models frequently hallucinated failure
    messages (e.g. "未检测到文件变更记录") even when file_states clearly showed
    modified=true, causing the loop to continue unnecessarily and the final
    result text to be wrong.

    Args:
        task_description: The original task description.
        file_states: JSON array of file state info:
            [{"path": "...", "exists": true, "modified": true, "preview": "..."}]

    Returns: JSON with verification result.
    """
    try:
        states = (
            json.loads(file_states) if isinstance(file_states, str) else file_states
        )
    except json.JSONDecodeError:
        states = []

    if not states:
        return json.dumps(
            {"completed": False, "summary": "无文件状态信息"}, ensure_ascii=False
        )

    all_modified = all(s.get("modified") for s in states if isinstance(s, dict))
    if not all_modified:
        # Some files not yet written; let the loop continue
        unmodified = [
            os.path.basename(str(s.get("path") or ""))
            for s in states
            if isinstance(s, dict) and not s.get("modified")
        ]
        return json.dumps(
            {
                "completed": False,
                "confidence": 0.5,
                "summary": f"以下文件尚未修改：{', '.join(unmodified)}",
                "remaining_steps": [f"写入 {n}" for n in unmodified],
            },
            ensure_ascii=False,
        )

    modified_names = [
        os.path.basename(str(s.get("path") or ""))
        for s in states
        if isinstance(s, dict) and s.get("modified")
    ]
    summary = "文件已成功修改：" + "、".join(n for n in modified_names if n)
    return json.dumps(
        {
            "completed": True,
            "confidence": 1.0,
            "summary": summary,
            "remaining_steps": [],
        },
        ensure_ascii=False,
    )


def read_file_range(path: str, start_line: int = 1, end_line: int = 100) -> str:
    """Read a specific range of lines from a file.

    Args:
        path: File path.
        start_line: Starting line number (1-indexed).
        end_line: Ending line number (inclusive).

    Returns: The specified lines as text.
    """
    resolved = _resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)

    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), end_line)

        selected = lines[start_idx:end_idx]
        return "".join(selected)
    except Exception as e:
        return f"Error: {e}"


def write_docx_content(path: str, paragraphs: str = "[]") -> str:
    """Write paragraphs to a DOCX file.

    Args:
        path: Path to the DOCX file (will be created if not exists).
        paragraphs: JSON array of paragraph objects:
            [{"text": "...", "style": "Heading 1"}, {"text": "..."}]

    Returns: JSON with operation result.
    """
    resolved = _safe_resolve(path)
    if not resolved:
        return json.dumps({"error": f"无效路径: {path}"}, ensure_ascii=False)

    try:
        para_list = (
            json.loads(paragraphs) if isinstance(paragraphs, str) else paragraphs
        )
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"无效的 paragraphs JSON: {e}"}, ensure_ascii=False)

    try:
        from docx import Document

        # Create or load document
        file_exists = os.path.exists(resolved)
        if file_exists:
            doc = Document(resolved)
            # Backup
            shutil.copy2(resolved, resolved + ".bak")
        else:
            doc = Document()
            os.makedirs(os.path.dirname(resolved), exist_ok=True)

        for p in para_list:
            text = p.get("text", "")
            style = p.get("style")
            para = doc.add_paragraph(text)
            if style:
                try:
                    para.style = style
                except Exception:
                    pass  # Style not found, use default

        doc.save(resolved)
        preview = "\n".join(str(p.get("text", "")) for p in para_list[:3])
        return _success_result(
            _result_path(path, resolved),
            operation="write_docx_content",
            summary=f"已写入 {len(para_list)} 个段落到 Word 文档",
            file_type="docx",
            change_type="modify" if file_exists else "create",
            preview=preview,
            focus=True,
            paragraphs_written=len(para_list),
        )
    except ImportError:
        return json.dumps({"error": "python-docx not installed"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def write_pptx_slides(path: str, updates: str = "[]") -> str:
    """Update text in existing PPTX slides.

    updates: JSON array of:
      [{"slide_index": 0, "shape_name": "标题 1", "text": "新内容"}, ...]
    or
      [{"slide_index": 0, "shape_index": 0, "text": "新内容"}, ...]
    slide_index is 0-based.
    """
    resolved = _resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)

    try:
        upd_list = json.loads(updates) if isinstance(updates, str) else updates
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid updates JSON: {e}"}, ensure_ascii=False)

    try:
        import shutil as _sh

        from pptx import Presentation
        from pptx.util import Pt

        _sh.copy2(resolved, resolved + ".bak")
        prs = Presentation(resolved)
        slides_updated = 0

        for upd in upd_list:
            slide_idx = int(upd.get("slide_index", 0))
            if slide_idx < 0 or slide_idx >= len(prs.slides):
                continue
            slide = prs.slides[slide_idx]
            new_text = str(upd.get("text", ""))

            shape_name = upd.get("shape_name")
            shape_index = upd.get("shape_index")
            target_shape = None

            for i, shape in enumerate(slide.shapes):
                if shape_name and shape.name == shape_name:
                    target_shape = shape
                    break
                if shape_index is not None and i == int(shape_index):
                    target_shape = shape
                    break

            if target_shape and target_shape.has_text_frame:
                # Preserve first run's font settings; replace paragraph text
                tf = target_shape.text_frame
                if tf.paragraphs:
                    para = tf.paragraphs[0]
                    # Keep existing run formatting, just replace text
                    if para.runs:
                        para.runs[0].text = new_text
                        for run in para.runs[1:]:
                            run.text = ""
                    else:
                        para.text = new_text
                slides_updated += 1

        prs.save(resolved)
        return _success_result(
            _result_path(path, resolved),
            operation="write_pptx_slides",
            summary=f"已更新 {slides_updated} 个形状的文字内容",
            file_type="pptx",
            change_type="modify",
            slides_updated=slides_updated,
        )
    except ImportError:
        return json.dumps(
            {
                "error": "python-pptx not installed. Use run_python_code with python-pptx instead."
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def add_pptx_slides(path: str, slides: str = "[]") -> str:
    """Append new slides to an existing PPTX file.

    slides: JSON array of:
      [{"title": "幻灯片标题", "content": "第一行\\n第二行\\n第三行", "layout_index": 1}, ...]
    layout_index: 0=空白, 1=标题+内容(默认), 2=章节标题, etc.
    """
    resolved = _resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)

    try:
        slides_list = json.loads(slides) if isinstance(slides, str) else slides
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid slides JSON: {e}"}, ensure_ascii=False)

    try:
        import shutil as _sh

        from pptx import Presentation
        from pptx.util import Inches, Pt

        _sh.copy2(resolved, resolved + ".bak")
        prs = Presentation(resolved)
        slides_added = 0

        for slide_data in slides_list:
            layout_idx = int(slide_data.get("layout_index", 1))
            layout_idx = min(layout_idx, len(prs.slide_layouts) - 1)
            layout = prs.slide_layouts[layout_idx]
            slide = prs.slides.add_slide(layout)

            title_text = slide_data.get("title", "")
            content_text = slide_data.get("content", "")

            # Set title placeholder if available
            if slide.shapes.title and title_text:
                slide.shapes.title.text = title_text

            # Set body/content placeholder if available
            for ph in slide.placeholders:
                if ph.placeholder_format.idx == 1 and content_text:
                    tf = ph.text_frame
                    tf.clear()
                    lines = content_text.split("\n")
                    for i, line in enumerate(lines):
                        if i == 0:
                            tf.paragraphs[0].text = line
                        else:
                            p = tf.add_paragraph()
                            p.text = line
                    break

            slides_added += 1

        total_slides = len(prs.slides)
        prs.save(resolved)
        return _success_result(
            _result_path(path, resolved),
            operation="add_pptx_slides",
            summary=f"已新增 {slides_added} 张幻灯片，当前共 {total_slides} 张",
            file_type="pptx",
            change_type="modify",
            slides_added=slides_added,
            total_slides=total_slides,
        )
    except ImportError:
        return json.dumps(
            {"error": "python-pptx not installed. Use run_python_code instead."},
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
# TaskToolsPlugin — registers all tools above into ToolRegistry
# ══════════════════════════════════════════════════════════════


class TaskToolsPlugin(AgentPlugin):
    """File-focused tools for the TaskAgent."""

    def __init__(
        self, socketio=None, task_files: Optional[List[Dict[str, str]]] = None
    ):
        self._socketio = socketio
        self._task_files = list(task_files or [])

    def _run_python_code(self, code: str, timeout: int = 30) -> str:
        return run_python_in_sandbox(code, timeout=timeout, task_files=self._task_files)

    @property
    def name(self) -> str:
        return "TaskTools"

    @property
    def description(self) -> str:
        return "Composable file-operation tools for dynamic task execution."

    def get_tools(self) -> List[Dict[str, Any]]:
        tools = [
            {
                "name": "read_sheet_data",
                "func": read_sheet_data,
                "description": (
                    "Read spreadsheet (xlsx) cells as structured JSON with headers and rows. "
                    "Args: path (str), sheet_name (str, optional), max_rows (int, default 500). "
                    "Returns: {sheet, headers, rows, row_count}"
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "path": {"type": "STRING"},
                        "sheet_name": {"type": "STRING"},
                        "max_rows": {"type": "INTEGER"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "write_sheet_data",
                "func": write_sheet_data,
                "description": (
                    "Write cells to a spreadsheet (xlsx). Creates a backup before writing. "
                    "Args: path (str), sheet_name (str, optional), "
                    "updates (JSON string of [{row, col, value}, ...]). "
                    "Row and col are 1-indexed."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "path": {"type": "STRING"},
                        "sheet_name": {"type": "STRING"},
                        "updates": {"type": "STRING"},
                    },
                    "required": ["path", "updates"],
                },
            },
            {
                "name": "read_docx_content",
                "func": read_docx_content,
                "description": (
                    "Read DOCX document paragraphs and tables as structured JSON with text/style info. "
                    "Args: path (str), max_chars (int, default 24000). "
                    "Returns: {paragraphs, tables, total_paragraphs, total_tables}"
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "path": {"type": "STRING"},
                        "max_chars": {"type": "INTEGER"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "parse_file_to_text",
                "func": parse_file_to_text,
                "description": (
                    "Parse any supported file (DOCX/XLSX/PPTX/PDF/TXT/CSV) to plain text. "
                    "Use this for a quick overview or staged reading of file contents. "
                    "For PDFs, you can pass start_page/end_page to read only a page window. "
                    "Args: path (str), max_chars (int, default 60000), start_page (int, optional), end_page (int, optional). "
                    "Returns: plain text string."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "path": {"type": "STRING"},
                        "max_chars": {"type": "INTEGER"},
                        "start_page": {"type": "INTEGER"},
                        "end_page": {"type": "INTEGER"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "run_python_code",
                "func": self._run_python_code,
                "description": (
                    "Execute Python code in a secure sandbox. "
                    "Use for data processing, calculations, chart generation. "
                    "Has access to pandas, openpyxl, matplotlib, numpy. "
                    "Current task files are mirrored into the sandbox working directory under their file names, "
                    "and absolute source paths are available via TASK_FILE_PATHS. "
                    "Args: code (str), timeout (int, default 30). "
                    "Returns: stdout + stderr."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "code": {"type": "STRING"},
                        "timeout": {"type": "INTEGER"},
                    },
                    "required": ["code"],
                },
            },
            {
                "name": "list_workspace_files",
                "func": list_workspace_files,
                "description": (
                    "List files in the workspace directory. "
                    "Args: path (str, relative subdir), recursive (bool). "
                    "Returns: JSON array of {name, type, size}."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "path": {"type": "STRING"},
                        "recursive": {"type": "BOOLEAN"},
                    },
                    "required": [],
                },
            },
            {
                "name": "open_file_in_editor",
                "func": open_file_in_editor,
                "description": (
                    "Open a file in the frontend editor so the user can view it. "
                    "Use this when the user asks to open, view, show, or navigate to a file. "
                    "Do NOT use for reading content — use parse_file_to_text for that. "
                    "Args: path (str, file path relative to workspace)."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "path": {"type": "STRING"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "copy_file",
                "func": copy_file,
                "description": (
                    "Copy a file within the workspace. "
                    "Args: source (str), destination (str). Both relative to workspace."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "source": {"type": "STRING"},
                        "destination": {"type": "STRING"},
                    },
                    "required": ["source", "destination"],
                },
            },
            {
                "name": "create_file",
                "func": create_file,
                "description": (
                    "Create a new file in the workspace with given content. "
                    "Args: path (str, relative), content (str)."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "path": {"type": "STRING"},
                        "content": {"type": "STRING"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "llm_extract",
                "func": llm_extract,
                "description": (
                    "Use AI to extract structured data from text. "
                    "Args: text (str — the source text), "
                    "fields (str — comma-separated field names to extract), "
                    "instructions (str, optional — extra guidance). "
                    "Returns: JSON object with extracted values."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "text": {"type": "STRING"},
                        "fields": {"type": "STRING"},
                        "instructions": {"type": "STRING"},
                    },
                    "required": ["text", "fields"],
                },
            },
            {
                "name": "llm_transform",
                "func": llm_transform,
                "description": (
                    "Use AI to transform/rewrite text according to an instruction. "
                    "Args: text (str), instruction (str). "
                    "Returns: transformed text."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "text": {"type": "STRING"},
                        "instruction": {"type": "STRING"},
                    },
                    "required": ["text", "instruction"],
                },
            },
            # ── New tools for DocAgent ─────────────────────────────────────
            {
                "name": "compare_files",
                "func": compare_files,
                "description": (
                    "Compare multiple files for similarities and differences. "
                    "Args: file_paths (str — comma-separated file paths), "
                    "aspect (str — 'content' or 'structure', default 'content'). "
                    "Returns: JSON with similarity scores and specific differences."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "file_paths": {"type": "STRING"},
                        "aspect": {"type": "STRING"},
                    },
                    "required": ["file_paths"],
                },
            },
            {
                "name": "extract_to_file",
                "func": extract_to_file,
                "description": (
                    "Extract data from one file and inject into another. "
                    "Use for cross-file operations like 'copy data from Excel to Word'. "
                    "Args: source_path (str), target_path (str), "
                    "extract_query (str — what to extract), "
                    "insert_position (str — 'start'/'end'/'cursor', default 'end'). "
                    "Returns: JSON with change details."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "source_path": {"type": "STRING"},
                        "target_path": {"type": "STRING"},
                        "extract_query": {"type": "STRING"},
                        "insert_position": {"type": "STRING"},
                    },
                    "required": ["source_path", "target_path", "extract_query"],
                },
            },
            {
                "name": "annotate_file",
                "func": annotate_file,
                "description": (
                    "Add annotations or highlights to a file. "
                    "Args: path (str), annotations (JSON array of "
                    "[{range_start, range_end, comment, color}]). "
                    "Returns: JSON with annotation results."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "path": {"type": "STRING"},
                        "annotations": {"type": "STRING"},
                    },
                    "required": ["path", "annotations"],
                },
            },
            {
                "name": "verify_task_completion",
                "func": verify_task_completion,
                "description": (
                    "Ask AI to verify if a task was completed successfully. "
                    "Args: task_description (str), "
                    "file_states (JSON array of [{path, exists, modified, preview}]), "
                    "model_mode (optional: auto/local). "
                    "Returns: JSON with {completed, confidence, summary, remaining_steps}."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "task_description": {"type": "STRING"},
                        "file_states": {"type": "STRING"},
                        "model_mode": {"type": "STRING"},
                    },
                    "required": ["task_description"],
                },
            },
            {
                "name": "read_file_range",
                "func": read_file_range,
                "description": (
                    "Read a specific range of lines from a text file. "
                    "Args: path (str), start_line (int, 1-indexed), end_line (int). "
                    "Returns: the specified lines as text."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "path": {"type": "STRING"},
                        "start_line": {"type": "INTEGER"},
                        "end_line": {"type": "INTEGER"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "write_docx_content",
                "func": write_docx_content,
                "description": (
                    "Write paragraphs to a DOCX file (create or append). "
                    "Args: path (str), paragraphs (JSON array of [{text, style}]). "
                    "Returns: JSON with operation result."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "path": {"type": "STRING"},
                        "paragraphs": {"type": "STRING"},
                    },
                    "required": ["path", "paragraphs"],
                },
            },
            {
                "name": "insert_excel_as_docx_table",
                "func": insert_excel_as_docx_table,
                "description": (
                    "Read an Excel sheet and append it to a DOCX file as a real Word table. "
                    "Use this when the task is '把 Excel 数据加入 Word / 新建表格'. "
                    "Args: source_path (xlsx), target_path (docx), sheet_name (optional), "
                    "table_title (optional), max_rows (optional, default 200)."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "source_path": {"type": "STRING"},
                        "target_path": {"type": "STRING"},
                        "sheet_name": {"type": "STRING"},
                        "table_title": {"type": "STRING"},
                        "max_rows": {"type": "INTEGER"},
                    },
                    "required": ["source_path", "target_path"],
                },
            },
            {
                "name": "write_pptx_slides",
                "func": write_pptx_slides,
                "description": (
                    "Modify text content in an existing PPTX file. "
                    "Use to update slide text, titles, or bullet points in-place. "
                    "Args: path (str — PPTX file path), "
                    "updates (JSON array of [{slide_index (0-based), shape_name or shape_index, text}]). "
                    "Returns: JSON with slides_updated count."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "path": {"type": "STRING"},
                        "updates": {"type": "STRING"},
                    },
                    "required": ["path", "updates"],
                },
            },
            {
                "name": "add_pptx_slides",
                "func": add_pptx_slides,
                "description": (
                    "Add new slides to an existing PPTX file. "
                    "Args: path (str — PPTX file path), "
                    "slides (JSON array of [{title, content (bullet lines, one per \\n), layout_index (optional, default 1)}]). "
                    "Returns: JSON with slides_added count and new total."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "path": {"type": "STRING"},
                        "slides": {"type": "STRING"},
                    },
                    "required": ["path", "slides"],
                },
            },
        ]

        # editor_live_update requires socketio — only register if available
        if self._socketio:
            tools.append(
                {
                    "name": "editor_live_update",
                    "func": self._editor_live_update,
                    "description": (
                        "Push live cell/text updates to the frontend editor. "
                        "Args: type (str — 'set_cell'|'set_cells'|'set_html'|'insert_text'), "
                        "plus type-specific kwargs."
                    ),
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "type": {"type": "STRING"},
                        },
                        "required": ["type"],
                    },
                }
            )

        return tools

    def _editor_live_update(self, type: str, **kwargs) -> str:
        """Push a change to the live editor via WebSocket."""
        if not self._socketio:
            return "Error: no WebSocket connection"
        payload = {"type": type, **kwargs}
        try:
            self._socketio.emit(
                "agent_execute_command",
                {"action": "editor_apply", "payload": payload},
                namespace="/doc",
            )
            return f"Applied: {type}"
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
