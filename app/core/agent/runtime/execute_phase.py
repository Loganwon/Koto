from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.agent._file_task_stepwise_helpers import (
    stepwise_docx_target_path as _stepwise_docx_target_path,
)
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_plan_presentation import (
    tool_plan_description as _plan_presentation_description,
)
from app.core.agent.file_task_plan_presentation import (
    tool_plan_title as _plan_presentation_title,
)
from app.core.agent.file_task_targeting import (
    resolve_explicit_output_against_request_target as _targeting_resolve_explicit_output_against_request_target,
)

logger = logging.getLogger(__name__)


class _FileTaskRuntimePart3:
    def _tool_plan_title(self, tool_name: str) -> str:
        return _plan_presentation_title(tool_name)

    def _tool_plan_description(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        files: List[FileTaskFile],
        request: FileTaskRequest,
    ) -> str:
        return _plan_presentation_description(
            self, tool_name, tool_args, files, request
        )

    def _inferred_write_plan_step(
        self, request: FileTaskRequest, files: List[FileTaskFile]
    ) -> Dict[str, Any]:
        source = self._first_file_name(files, {"xlsx", "xlsm", "csv"})
        docx_target = (
            self._typed_target_display_path(request, {"docx", "doc"})
            or self._first_file_name(files, {"docx"}, target=True)
            or self._first_file_name(files, {"docx"})
        )
        pptx_target = (
            self._typed_target_display_path(request, {"pptx", "ppt"})
            or self._first_file_name(files, {"pptx"}, target=True)
            or self._first_file_name(files, {"pptx"})
        )
        text_target = self._typed_target_display_path(
            request, {"txt", "md", "csv", "json", "py", "js", "html", "css"}
        ) or self._first_file_name(
            files, {"txt", "md", "csv", "json", "py", "js", "html", "css"}, target=True
        )
        if source and docx_target:
            return {
                "id": "inferred_write",
                "title": "写入 Word 表格",
                "description": f"读取完成后，把 {source} 的表格数据写入 {docx_target}。",
            }
        if text_target:
            return {
                "id": "inferred_write",
                "title": "写回文本文件",
                "description": f"读取完成后，把处理结果写回 {text_target}。",
            }
        if pptx_target:
            return {
                "id": "inferred_write",
                "title": "更新演示文稿",
                "description": f"读取完成后，由模型选择已准入的 PPT 工具更新 {pptx_target}。",
            }
        target = self._display_path(request.target_path) or next(
            (
                self._display_path(file_info.path)
                for file_info in files
                if file_info.target and file_info.path
            ),
            "目标文件",
        )
        return {
            "id": "inferred_write",
            "title": "写入目标文件",
            "description": f"读取完成后，把处理结果写入 {target}。",
        }

    def _typed_target_display_path(
        self, request: FileTaskRequest, types: set[str]
    ) -> str:
        raw = str(request.target_path or "").strip()
        suffix = Path(raw).suffix.lstrip(".").lower()
        if raw and suffix in types:
            return self._display_path(raw)
        return ""

    def _first_file_name(
        self, files: List[FileTaskFile], types: set[str], *, target: bool = False
    ) -> str:
        for file_info in files:
            file_type = (
                file_info.type
                or Path(file_info.path or file_info.name).suffix.lstrip(".")
            ).lower()
            if target and not file_info.target:
                continue
            if types and file_type not in types:
                continue
            return file_info.name or self._display_path(file_info.path)
        return ""

    def _display_path(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        path_parts = text.replace("\\", "/").rsplit("/", 1)
        return path_parts[len(path_parts) - 1] if path_parts else text

    def _repair_tool_args_for_context(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        request: FileTaskRequest,
        files: List[FileTaskFile],
        *,
        generated_artifacts: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        args = dict(tool_args or {})
        if (
            tool_name
            in {
                "write_docx_content",
                "insert_docx_paragraph",
                "insert_image_into_docx",
                "clear_docx_review_marks",
            }
            and not str(args.get("path") or "").strip()
        ):
            target = self._single_target_path_for_types(request, files, {"docx", "doc"})
            if target:
                args["path"] = target
        if tool_name == "insert_image_into_docx":
            raw_image_path = str(args.get("image_path") or "").strip()
            if not self._resolve_task_file_path(raw_image_path):
                generated_image = self._latest_generated_image_artifact_path(
                    generated_artifacts or [], raw_image_path
                )
                if generated_image:
                    args["image_path"] = generated_image
        if (
            tool_name == "insert_docx_paragraph"
            and self._task_requests_docx_append_end(request.task)
        ):
            args.pop("before_heading", None)
            args.pop("after_heading", None)
        if (
            tool_name == "design_pptx_theme_layout"
            and not str(args.get("path") or "").strip()
        ):
            target = self._single_target_path_for_types(request, files, {"pptx", "ppt"})
            if target:
                args["path"] = target
        if tool_name == "write_sheet_data" and not str(args.get("path") or "").strip():
            target = self._single_target_path_for_types(
                request, files, {"xlsx", "xlsm"}
            )
            if target:
                args["path"] = target
        if tool_name == "insert_excel_as_docx_table":
            if not str(args.get("target_path") or "").strip():
                target = self._single_target_path_for_types(
                    request, files, {"docx", "doc"}
                )
                if target:
                    args["target_path"] = target
            if not str(args.get("source_path") or "").strip():
                source = self._single_source_path_for_types(
                    request, files, {"xlsx", "xlsm"}
                )
                if source:
                    args["source_path"] = source
        if tool_name == "write_docx_content" and "paragraphs" not in args:
            for key in ("content", "text", "markdown", "body"):
                value = args.get(key)
                if str(value or "").strip():
                    args["paragraphs"] = value
                    break
        return args

    def _remember_generated_artifacts(
        self, target: List[Dict[str, Any]], artifacts: List[Dict[str, Any]]
    ) -> None:
        seen = {
            os.path.normcase(str(item.get("path") or "").strip())
            for item in target
            if str(item.get("path") or "").strip()
        }
        for artifact in artifacts or []:
            if not isinstance(artifact, dict):
                continue
            kind = str(artifact.get("kind") or "").strip().lower()
            path = str(artifact.get("path") or "").strip()
            if kind != "image" or not path or not os.path.exists(path):
                continue
            key = os.path.normcase(path)
            if key in seen:
                continue
            seen.add(key)
            target.append(dict(artifact))

    def _latest_generated_image_artifact_path(
        self, artifacts: List[Dict[str, Any]], requested_path: str = ""
    ) -> str:
        images = [
            artifact
            for artifact in artifacts or []
            if isinstance(artifact, dict)
            and str(artifact.get("kind") or "").strip().lower() == "image"
            and str(artifact.get("path") or "").strip()
            and os.path.exists(str(artifact.get("path") or "").strip())
        ]
        if not images:
            return ""
        requested_name = Path(str(requested_path or "").replace("\\", "/")).name.lower()
        if requested_name:
            for artifact in reversed(images):
                artifact_name = str(artifact.get("name") or "").strip().lower()
                artifact_path = str(artifact.get("path") or "").strip()
                if (
                    artifact_name == requested_name
                    or Path(artifact_path).name.lower() == requested_name
                ):
                    return artifact_path
        return str(images[len(images) - 1].get("path") or "").strip()

    def _has_docx_write_target(
        self, request: FileTaskRequest, files: List[FileTaskFile]
    ) -> bool:
        target = self._single_target_path_for_types(request, files, {"docx", "doc"})
        target_type = (
            Path(str(request.target_path or target or "")).suffix.lstrip(".").lower()
        )
        return target_type in {"docx", "doc"}

    def _generated_image_artifact_key(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        resolved = self._resolve_task_file_path(text) or text
        try:
            return os.path.normcase(os.path.normpath(resolved))
        except Exception:
            return resolved.lower()

    def _generated_image_artifact_name(self, artifact: Dict[str, Any]) -> str:
        name = str(artifact.get("name") or "").strip()
        if name:
            return name
        path = str(artifact.get("path") or "").strip()
        return Path(path.replace("\\", "/")).name if path else "图表图片"

    def _generated_docx_image_quality_failure(
        self,
        check_payload: Dict[str, Any],
        pending_images: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not pending_images:
            return check_payload
        names = [
            self._generated_image_artifact_name(item)
            for item in pending_images[:8]
            if isinstance(item, dict)
        ]
        remaining_text = "仍有生成图表未插入 DOCX：" + (
            "、".join(name for name in names if name) or "剩余图表图片"
        )
        payload = dict(check_payload or {})
        criteria = list(payload.get("criteria_results") or [])
        criteria.append(
            self._quality_gate_result(
                criterion="generated_chart_images_inserted_into_docx",
                passed=False,
                detail=remaining_text,
                priority="critical",
            )
        )
        remaining = list(payload.get("remaining") or [])
        remaining.insert(0, remaining_text)
        payload.update(
            {
                "passed": False,
                "status": "quality_gate_failed",
                "summary": "文件已有变更，但生成的图表图片没有全部写入目标 DOCX。",
                "remaining": remaining,
                "criteria_results": criteria,
            }
        )
        return payload

    def _task_requests_docx_append_end(self, task: Any) -> bool:
        text = str(task or "")
        return bool(
            re.search(
                r"(?:追加|附加|加到.{0,12}末尾|放到.{0,12}末尾|写到.{0,12}末尾|文末|末尾|最后|append|at the end|end of)",
                text,
                re.IGNORECASE,
            )
        )

    def _single_target_path_for_types(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        file_types: set[str],
    ) -> str:
        target_path = str(request.target_path or "").strip()
        if target_path:
            suffix = Path(target_path).suffix.lower().lstrip(".")
            if not suffix or suffix in file_types:
                return target_path
        candidates: List[str] = []
        for file_info in files or []:
            if not getattr(file_info, "target", False):
                continue
            path = str(file_info.path or file_info.name or "").strip()
            suffix = str(file_info.type or "").strip().lower().lstrip(".") or Path(
                path
            ).suffix.lower().lstrip(".")
            if path and suffix in file_types:
                candidates.append(path)
        unique = list(dict.fromkeys(candidates))
        return unique[0] if len(unique) == 1 else ""

    def _single_source_path_for_types(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        file_types: set[str],
    ) -> str:
        candidates: List[str] = []
        for file_info in files or []:
            if getattr(file_info, "target", False):
                continue
            path = str(file_info.path or file_info.name or "").strip()
            suffix = str(file_info.type or "").strip().lower().lstrip(".") or Path(
                path
            ).suffix.lower().lstrip(".")
            if path and suffix in file_types:
                candidates.append(path)
        unique = list(dict.fromkeys(candidates))
        return unique[0] if len(unique) == 1 else ""

    def _resolve_task_file_path(self, path: Any) -> str:
        raw = str(path or "").strip()
        if not raw:
            return ""
        if os.path.isabs(raw) and os.path.exists(raw):
            return os.path.normpath(raw)
        try:
            from app.core.agent import task_tools

            resolved = task_tools._resolve_path(raw)  # type: ignore[attr-defined]
            if resolved and os.path.exists(resolved):
                return os.path.normpath(resolved)
        except Exception as exc:
            logger.debug(
                "[FileTaskRuntime] workspace path resolution skipped for %r: %s",
                raw,
                exc,
            )
        return ""

    def _plan_summary(
        self, request: FileTaskRequest, files: List[FileTaskFile], write_intent: bool
    ) -> str:
        explicit_output = _targeting_resolve_explicit_output_against_request_target(
            str(request.target_path or "").strip(),
            self._explicit_output_path_from_task(request.task),
        )
        if write_intent and explicit_output:
            suffix = "，并引用 1 段选区" if request.selection else ""
            return f"准备生成 {Path(explicit_output).name}{suffix}。"
        target = request.target_path or next((f.path for f in files if f.target), "")
        has_selection = bool(request.selection)
        if write_intent and target:
            suffix = "，并引用 1 段选区" if has_selection else ""
            return f"准备更新 {Path(target).name}{suffix}。"
        if files and has_selection:
            return f"准备处理 {len(files)} 个文件和 1 段选区。"
        if files:
            return f"准备处理 {len(files)} 个文件。"
        if has_selection:
            return "准备处理 1 段选区。"
        return "准备处理当前任务。"

    def _verification_target_path(
        self, request: FileTaskRequest, file_changes: List[Dict[str, Any]]
    ) -> str:
        # Preparation already resolves explicit output/source contracts.
        # Verification consumes that target and actual change receipts,
        # rather than performing a second free-text target selection.
        return str(request.target_path or "").strip()

    def _stepwise_docx_target_path(
        self, request: FileTaskRequest, files: List[FileTaskFile]
    ) -> str:
        return _stepwise_docx_target_path(request, files)
