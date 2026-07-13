"""File-conversion operations used by :mod:`task_tools`.

The public task-tools module owns workspace-path policy and keeps compatibility
symbols for existing callers.  This module owns converter selection and the
stable result payloads for DOCX/PDF and general file conversion.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence


def convert_docx_to_pdf_with_docx2pdf(source: str, target: str) -> str:
    from docx2pdf import convert

    convert(source, target)
    return "docx2pdf"


def convert_docx_to_pdf_with_word(source: str, target: str) -> str:
    import win32com.client  # type: ignore

    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    doc = None
    try:
        doc = word.Documents.Open(source)
        doc.SaveAs(target, FileFormat=17)
    finally:
        if doc is not None:
            doc.Close(False)
        word.Quit()
    return "word_com"


def convert_docx_to_pdf_with_libreoffice(source: str, target: str) -> str:
    executable = (
        shutil.which("soffice")
        or shutil.which("libreoffice")
        or shutil.which("soffice.exe")
    )
    if not executable:
        raise RuntimeError("LibreOffice/soffice not found")
    out_dir = os.path.dirname(target) or os.getcwd()
    os.makedirs(out_dir, exist_ok=True)
    completed = subprocess.run(
        [
            executable,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            out_dir,
            source,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(message or "LibreOffice conversion failed")
    generated = str(Path(out_dir) / (Path(source).stem + ".pdf"))
    if os.path.normcase(os.path.abspath(generated)) != os.path.normcase(
        os.path.abspath(target)
    ):
        if os.path.exists(target):
            os.remove(target)
        shutil.move(generated, target)
    return "libreoffice"


def normalize_conversion_extension(target_format: str) -> str:
    clean = str(target_format or "").strip().lower().lstrip(".")
    if not clean:
        return ""
    try:
        from web.file_converter import FORMAT_ALIASES

        ext = str(FORMAT_ALIASES.get(clean, f".{clean}") or "").strip().lower()
    except Exception:
        ext = f".{clean}"
    return ext if not ext or ext.startswith(".") else f".{ext}"


def convert_docx_to_pdf(
    path: str,
    target_path: str,
    *,
    resolve_path: Callable[[str], Optional[str]],
    resolve_output_path: Callable[[str, str, str, str], Optional[str]],
    result_path: Callable[[str, str], str],
    success_result: Callable[..., str],
    blocked_write_result: Callable[..., str],
    converters: Sequence[Callable[[str, str], str]],
) -> str:
    """Convert DOCX/DOC to PDF while preserving the task-result contract."""
    resolved = resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)
    if Path(resolved).suffix.lower() not in {".docx", ".doc"}:
        return json.dumps(
            {"error": "Only DOCX/DOC inputs are supported"}, ensure_ascii=False
        )
    target = resolve_output_path(path, resolved, target_path, ".pdf")
    if not target:
        return json.dumps(
            {"error": f"Invalid target path: {target_path}"}, ensure_ascii=False
        )
    os.makedirs(os.path.dirname(target), exist_ok=True)
    target_exists_before = os.path.exists(target)
    display_path = target_path or str(Path(path).with_suffix(".pdf"))

    errors: list[str] = []
    for converter in converters:
        try:
            engine = converter(resolved, target)
            if not os.path.exists(target):
                raise RuntimeError("converter reported success but PDF was not created")
            return success_result(
                result_path(display_path, target),
                operation="convert_docx_to_pdf",
                summary=f"已将 Word 文档转换为 PDF：{Path(target).name}",
                file_type="pdf",
                change_type="modify" if target_exists_before else "create",
                summary_code="CONVERT_OK",
                source_path=result_path(path, resolved),
                converter=engine,
                focus=True,
            )
        except Exception as exc:
            errors.append(f"{converter.__name__}: {str(exc).strip()}")

    return blocked_write_result(
        result_path(display_path, target),
        summary="当前环境没有可用的 DOCX 转 PDF 引擎。",
        suggested_next_step="安装 Microsoft Word、LibreOffice/soffice 或 docx2pdf 后重试。",
        operation="convert_docx_to_pdf",
        file_type="pdf",
        source_path=result_path(path, resolved),
        converter_errors=errors,
    )


def convert_file(
    file_path: str,
    target_format: str,
    output_path: str,
    *,
    resolve_path: Callable[[str], Optional[str]],
    resolve_output_path: Callable[[str, str, str, str], Optional[str]],
    result_path: Callable[[str, str], str],
    success_result: Callable[..., str],
    blocked_write_result: Callable[..., str],
) -> str:
    """Convert a workspace file using ``web.file_converter``."""
    resolved = resolve_path(file_path)
    if not resolved:
        return json.dumps({"error": f"File not found: {file_path}"}, ensure_ascii=False)
    target_ext = normalize_conversion_extension(target_format)
    if not target_ext:
        return json.dumps({"error": "target_format is required"}, ensure_ascii=False)

    target = resolve_output_path(file_path, resolved, output_path, target_ext)
    if not target:
        return json.dumps(
            {"error": f"Invalid output path: {output_path}"}, ensure_ascii=False
        )
    os.makedirs(os.path.dirname(target), exist_ok=True)
    target_exists_before = os.path.exists(target)
    display_path = output_path or str(Path(file_path).with_suffix(target_ext))

    try:
        from web.file_converter import convert

        result = convert(
            source_path=resolved, target_format=target_ext, output_path=target
        )
    except Exception as exc:
        return blocked_write_result(
            result_path(display_path, target),
            summary=f"转换失败：{str(exc).strip()}",
            suggested_next_step="确认源文件格式受支持，并安装本地转换依赖后重试。",
            operation="convert_file",
            file_type=target_ext.lstrip("."),
            source_path=result_path(file_path, resolved),
            target_format=target_ext.lstrip("."),
            converter_errors=[str(exc).strip()],
        )

    if not isinstance(result, Mapping):
        return blocked_write_result(
            result_path(display_path, target),
            summary="转换器没有返回结构化结果。",
            suggested_next_step="请重试或改用专门的格式转换工具。",
            operation="convert_file",
            file_type=target_ext.lstrip("."),
            source_path=result_path(file_path, resolved),
            target_format=target_ext.lstrip("."),
            converter_errors=[str(result)],
        )

    output = os.path.normpath(str(result.get("output_path") or target))
    to_format = str(result.get("to_format") or target_ext.lstrip(".")).strip().lower()
    from_format = (
        str(result.get("from_format") or Path(resolved).suffix.lstrip("."))
        .strip()
        .lower()
    )
    warning = str(result.get("warning") or "").strip()
    if result.get("success") and os.path.exists(output):
        return success_result(
            result_path(display_path, output),
            operation="convert_file",
            summary=str(
                result.get("message")
                or f"已转换为 {to_format.upper()}：{Path(output).name}"
            ),
            file_type=to_format or target_ext.lstrip("."),
            change_type="modify" if target_exists_before else "create",
            summary_code="CONVERT_OK",
            source_path=result_path(file_path, resolved),
            target_format=to_format or target_ext.lstrip("."),
            from_format=from_format,
            to_format=to_format or target_ext.lstrip("."),
            converter="web.file_converter",
            warning=warning,
            focus=True,
        )

    error = str(result.get("error") or result.get("message") or "转换失败").strip()
    return blocked_write_result(
        result_path(display_path, output),
        summary=error,
        suggested_next_step="确认该来源格式与目标格式组合受支持，并安装本地转换依赖后重试。",
        operation="convert_file",
        file_type=to_format or target_ext.lstrip("."),
        source_path=result_path(file_path, resolved),
        target_format=to_format or target_ext.lstrip("."),
        from_format=from_format,
        to_format=to_format or target_ext.lstrip("."),
        converter_errors=[error],
    )


def list_conversions(file_ext: str = "") -> str:
    """Return the structured conversion matrix or a source-format slice."""
    try:
        from web.file_converter import get_supported_conversions

        matrix = get_supported_conversions()
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    if file_ext:
        source_ext = normalize_conversion_extension(file_ext)
        targets = [item.lstrip(".") for item in matrix.get(source_ext, [])]
        summary = (
            f"{source_ext.lstrip('.')} 可转换为：{', '.join(targets)}"
            if targets
            else f"暂不支持从 {source_ext.lstrip('.')} 转换"
        )
        return json.dumps(
            {
                "success": True,
                "source_format": source_ext.lstrip("."),
                "targets": targets,
                "summary": summary,
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "success": True,
            "conversions": {
                key.lstrip("."): [item.lstrip(".") for item in values]
                for key, values in matrix.items()
            },
            "summary": "已返回全部支持的格式转换矩阵",
        },
        ensure_ascii=False,
    )
