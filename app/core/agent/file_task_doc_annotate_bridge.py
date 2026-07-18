from __future__ import annotations

import inspect
import logging
import math
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, List, Optional, Sequence

from app.core.agent.file_task_contract import (
    FileTaskEvent,
    FileTaskFile,
    FileTaskLedger,
    FileTaskRequest,
    FileTaskToolStreamChunk,
    FileTaskToolStreamResult,
)
from app.core.agent.file_task_doc_annotate_events import (
    build_live_write_progress_payload as _build_live_write_progress_payload,
)
from app.core.agent.file_task_doc_annotate_events import (
    build_review_progress_payload as _build_review_progress_payload,
)
from app.core.agent.file_task_doc_annotate_events import (
    runtime_payload as _runtime_payload,
)
from app.core.agent.file_task_doc_annotate_events import (
    tool_result_from_bridge_payload as _tool_result_from_bridge_payload,
)
from app.core.agent.file_task_doc_annotate_intent import (
    looks_like_direct_docx_rewrite_request,
    looks_like_docx_review_clear_request,
    looks_like_multi_file_compare_request,
    should_route_request,
    should_use_doc_annotate_bridge_execution,
)
from app.core.agent.file_task_failure import build_failed_run_payload
from app.core.agent.file_task_runtime_utils import workflow_checkpoint_from_options
from app.core.llm.model_mode import normalize_model_mode

logger = logging.getLogger(__name__)

_BATCH_RESUME_ARTIFACT_TYPE = "koto_large_task_resume_v1"
_BATCH_RESUME_ARTIFACT_CATEGORY = "batch_confirmation"


def _failed_run_event(
    ledger: FileTaskLedger,
    *,
    summary: str,
    code: str,
    phase: str,
    step_id: str,
    detail: str = "",
    status: str = "quality_gate_failed",
) -> FileTaskEvent:
    return ledger.event(
        "run.finished",
        build_failed_run_payload(
            status=status,
            code=code,
            phase=phase,
            summary=summary,
            detail=detail or summary,
            remaining=["修正失败原因后重新执行文档任务。"],
            runtime=_runtime_payload(status),
            mode="doc_annotate_bridge",
            execution_mode="doc_annotate_bridge",
        ),
        step_id=step_id,
    )


def _cancelled_run_event(
    ledger: FileTaskLedger,
    *,
    summary: str,
    step_id: str,
) -> FileTaskEvent:
    return ledger.event(
        "run.cancelled",
        {
            "summary": summary,
            "text": summary,
            "status": "cancelled",
            "completed_task": False,
            "mode": "doc_annotate_bridge",
            "execution_mode": "doc_annotate_bridge",
            "runtime": _runtime_payload("cancelled"),
        },
        step_id=step_id,
    )


def _request_options(request: FileTaskRequest) -> dict[str, Any]:
    return dict(request.options) if isinstance(request.options, dict) else {}


class _ProviderModelsAdapter:
    def __init__(self, provider: Any):
        self._provider = provider

    def generate_content(
        self,
        *,
        model: str = "",
        contents: Any = "",
        config: Any = None,
        **kwargs: Any,
    ) -> Any:
        call_kwargs: dict[str, Any] = dict(kwargs)
        if config is not None:
            temperature = getattr(config, "temperature", None)
            max_output_tokens = getattr(config, "max_output_tokens", None)
            system_instruction = getattr(config, "system_instruction", None)
            tools = getattr(config, "tools", None)
            if temperature is not None:
                call_kwargs.setdefault("temperature", temperature)
            if max_output_tokens is not None:
                call_kwargs.setdefault("max_tokens", max_output_tokens)
            if system_instruction is not None:
                call_kwargs.setdefault("system_instruction", system_instruction)
            if tools is not None:
                call_kwargs.setdefault("tools", tools)
        if (
            not call_kwargs.get("tools")
            and "extra_body" not in call_kwargs
            and str(model or "").lower().startswith("deepseek")
        ):
            call_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        system_instruction = call_kwargs.pop("system_instruction", None)
        tools = call_kwargs.pop("tools", None)
        response = self._provider.generate_content(
            prompt=contents,
            model=model,
            system_instruction=system_instruction,
            tools=tools,
            stream=False,
            **call_kwargs,
        )
        if isinstance(response, dict):
            return SimpleNamespace(
                text=str(response.get("content") or response.get("text") or ""),
                candidates=[],
                raw=response,
            )
        return SimpleNamespace(text=str(response or ""), candidates=[], raw=response)


class _ProviderClientAdapter:
    def __init__(self, provider: Any, *, provider_name: str = ""):
        self.models = _ProviderModelsAdapter(provider)
        self._koto_provider_name = provider_name


def _resolve_review_model_id(
    request: FileTaskRequest, *, gemini_client: Any = None
) -> str:
    requested_model = str(request.model_id or "").strip()
    normalized_mode = normalize_model_mode(request.model_mode, default="deepseek")
    if normalized_mode != "local":
        ignored = {
            "auto",
            "cloud",
            "gemini",
            "deepseek",
            "openai",
            "anthropic",
            "ollama",
        }
        if requested_model and requested_model.lower() not in ignored:
            return requested_model
        try:
            from app.core.llm.model_selection import (
                get_configured_cloud_model,
                get_provider_for_model_mode,
            )

            provider_name = get_provider_for_model_mode(normalized_mode)
            fallback_model = "deepseek-chat"
            if provider_name == "deepseek":
                from app.core.llm.deepseek_config import DEEPSEEK_DEFAULT_MODEL

                fallback_model = DEEPSEEK_DEFAULT_MODEL
            return get_configured_cloud_model(
                task_type="DOC_ANNOTATE",
                fallback_model=fallback_model,
                provider=provider_name,
            )
        except Exception as exc:
            logger.debug("[doc_annotate_bridge] cloud model resolution failed: %s", exc)
            return requested_model

    lowered_requested = requested_model.lower()
    if (
        lowered_requested
        and lowered_requested not in {"auto", "cloud", "local"}
        and not lowered_requested.startswith("gemini")
    ):
        return requested_model

    options = _request_options(request)
    local_model = str(options.get("local_model") or "").strip()
    if local_model:
        return local_model

    client_model = str(getattr(gemini_client, "_model_tag", "") or "").strip()
    if client_model:
        return client_model

    return "local"


def _build_feedback_client(request: FileTaskRequest, *, gemini_client: Any = None):
    normalized_mode = normalize_model_mode(request.model_mode, default="deepseek")
    if normalized_mode == "local":
        model_id = _resolve_review_model_id(request, gemini_client=gemini_client)
        try:
            from app.core.llm.ollama_provider import OllamaClientProxy

            return OllamaClientProxy(
                model_tag=None if model_id == "local" else model_id
            )
        except Exception as exc:
            logger.warning("[doc_annotate_bridge] Ollama client unavailable: %s", exc)
            return gemini_client

    try:
        from app.core.llm.model_selection import get_provider_for_model_mode

        provider_name = get_provider_for_model_mode(normalized_mode)
    except Exception as exc:
        logger.debug("[doc_annotate_bridge] provider resolution failed: %s", exc)
        provider_name = "deepseek"

    if provider_name != "deepseek":
        return gemini_client

    model_id = _resolve_review_model_id(request, gemini_client=gemini_client)
    try:
        from app.core.llm.provider_factory import get_llm_provider

        provider = get_llm_provider(
            provider="deepseek",
            model=model_id,
            allow_local_fallback=False,
        )
        return _ProviderClientAdapter(provider, provider_name="deepseek")
    except Exception as exc:
        logger.warning("[doc_annotate_bridge] DeepSeek provider unavailable: %s", exc)
        return gemini_client


def _build_feedback_system(request: FileTaskRequest, *, gemini_client: Any = None):
    from web.document_feedback import DocumentFeedbackSystem

    default_model_id = _resolve_review_model_id(request, gemini_client=gemini_client)
    feedback_client = _build_feedback_client(request, gemini_client=gemini_client)
    try:
        signature = inspect.signature(DocumentFeedbackSystem)
    except (TypeError, ValueError):
        signature = None

    if default_model_id and signature and "default_model_id" in signature.parameters:
        return DocumentFeedbackSystem(
            gemini_client=feedback_client,
            default_model_id=default_model_id,
        )

    return DocumentFeedbackSystem(gemini_client=feedback_client)


def _extract_workflow_checkpoint(request: FileTaskRequest) -> dict[str, Any]:
    checkpoint = workflow_checkpoint_from_options(_request_options(request))
    if not checkpoint:
        return {}
    if (
        str(checkpoint.get("adapter") or "doc_annotate_bridge").strip()
        != "doc_annotate_bridge"
    ):
        return {}
    return dict(checkpoint)


def _build_resume_files(
    request: FileTaskRequest, *, source_pdf: str, target_docx: str
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    def _append(
        path: str, file_type: str, *, target: bool = False, name: str = ""
    ) -> None:
        normalized = str(path or "").strip()
        if not normalized or normalized in seen_paths:
            return
        seen_paths.add(normalized)
        files.append(
            {
                "path": normalized,
                "name": name or os.path.basename(normalized),
                "type": file_type,
                "target": target,
            }
        )

    _append(source_pdf, "pdf", name=os.path.basename(source_pdf))
    _append(target_docx, "docx", target=True, name=os.path.basename(target_docx))

    for file_info in _request_files(request):
        path = str(file_info.path or file_info.name or "").strip()
        if not path:
            continue
        file_type = _file_type(file_info)
        if (
            file_type == "docx"
            and bool(file_info.target)
            and os.path.normcase(path) != os.path.normcase(target_docx)
        ):
            continue
        _append(
            path,
            file_type,
            target=bool(file_info.target)
            or os.path.normcase(path) == os.path.normcase(target_docx),
            name=str(file_info.name or os.path.basename(path)).strip()
            or os.path.basename(path),
        )

    return files


def _build_batch_resume_request(
    request: FileTaskRequest,
    *,
    source_pdf: str,
    target_docx: str,
    batch_index: int,
    total_batches: int,
) -> dict[str, Any]:
    options = _request_options(request)
    options.pop("batch_control", None)
    options["workflow_checkpoint"] = {
        "adapter": "doc_annotate_bridge",
        "policy": "confirm_each_batch",
        "batch_index": batch_index,
        "total_batches": total_batches,
        "source_path": source_pdf,
        "target_path": target_docx,
        "original_task": request.task,
    }

    payload: dict[str, Any] = {
        "task": request.task,
        "target_path": target_docx,
        "files": _build_resume_files(
            request, source_pdf=source_pdf, target_docx=target_docx
        ),
        "model_mode": request.model_mode,
        "model_id": request.model_id,
        "options": options,
    }
    if request.session_id:
        payload["session_id"] = request.session_id
    return payload


def _build_batch_confirmation_artifact(
    request: FileTaskRequest,
    *,
    source_pdf: str,
    target_docx: str,
    large_file_plan: dict[str, Any],
    batch_index: int,
) -> dict[str, Any]:
    batches = (
        large_file_plan.get("batches")
        if isinstance(large_file_plan.get("batches"), list)
        else []
    )
    total_batches = len(batches)
    batch = batches[batch_index - 1] if 1 <= batch_index <= total_batches else {}
    chunk_start = int(batch.get("chunk_start") or 0)
    chunk_end = int(batch.get("chunk_end") or 0)

    return {
        "artifact_type": _BATCH_RESUME_ARTIFACT_TYPE,
        "category": _BATCH_RESUME_ARTIFACT_CATEGORY,
        "title": f"继续执行第 {batch_index}/{total_batches} 批",
        "summary": str(
            batch.get("description") or large_file_plan.get("summary") or ""
        ).strip(),
        "suggested_next_step": f"确认后继续执行第 {batch_index}/{total_batches} 批审校。",
        "source_task": request.task,
        "target_path": target_docx,
        "batch_index": batch_index,
        "total_batches": total_batches,
        "chunk_start": chunk_start,
        "chunk_end": chunk_end,
        "action_label": f"继续第 {batch_index}/{total_batches} 批",
        "resume_request": _build_batch_resume_request(
            request,
            source_pdf=source_pdf,
            target_docx=target_docx,
            batch_index=batch_index,
            total_batches=total_batches,
        ),
        "runtime_context": _runtime_payload("awaiting_confirmation"),
    }


def _batch_state_from_plan(
    request: FileTaskRequest, large_file_plan: Optional[dict[str, Any]]
) -> dict[str, Any]:
    if not isinstance(large_file_plan, dict):
        return {}

    batches = (
        large_file_plan.get("batches")
        if isinstance(large_file_plan.get("batches"), list)
        else []
    )
    total_batches = len(batches)
    if total_batches <= 0:
        return {}

    checkpoint = _extract_workflow_checkpoint(request)
    try:
        batch_index = int(checkpoint.get("batch_index") or 0)
    except (TypeError, ValueError):
        batch_index = 0

    if batch_index <= 0:
        return {
            "awaiting_confirmation": True,
            "batch_index": 0,
            "total_batches": total_batches,
        }

    if batch_index > total_batches:
        return {
            "error": f"批次索引无效：{batch_index}/{total_batches}",
            "batch_index": batch_index,
            "total_batches": total_batches,
        }

    batch = batches[batch_index - 1] if 0 <= batch_index - 1 < total_batches else {}
    return {
        "awaiting_confirmation": False,
        "batch_index": batch_index,
        "total_batches": total_batches,
        "batch": batch,
        "chunk_range": (
            int(batch.get("chunk_start") or 0),
            int(batch.get("chunk_end") or 0),
        ),
        "has_next_batch": batch_index < total_batches,
        "next_batch_index": batch_index + 1,
    }


def _stream_single_docx_request(
    request: FileTaskRequest,
    *,
    target_docx: str,
    gemini_client: Any = None,
) -> Iterable[FileTaskEvent]:
    from web.document_feedback import DocumentFeedbackSystem

    ledger = FileTaskLedger(request.run_id)

    if not target_docx or not os.path.exists(target_docx):
        yield _failed_run_event(
            ledger,
            summary="未找到可修订的 DOCX 文稿，无法进入 Word 修订写回流程。",
            code="DOCX_TARGET_MISSING",
            phase="targeting",
            step_id="run",
        )
        return

    yield ledger.event(
        "run.started",
        {
            "task": request.task,
            "mode": "doc_annotate_bridge",
            "file_count": len(request.files),
            "target_path": target_docx,
            "model_mode": request.model_mode,
            "model_id": request.model_id,
        },
        step_id="run",
    )

    yield ledger.event(
        "plan.created",
        {
            "summary": "识别为单个 DOCX 审校任务，使用 Word 原生修订写回能力。",
            "steps": [
                {
                    "id": "review",
                    "title": "生成文稿修订建议",
                    "description": "读取并分析 DOCX 文稿，生成可直接写入 Word 的修订。",
                },
                {
                    "id": "write",
                    "title": "写回 Word 修订",
                    "description": "将修订直接写回原始 DOCX 文件。",
                },
                {
                    "id": "check",
                    "title": "核验输出",
                    "description": "确认已更新可打开的原始 DOCX 文件。",
                },
            ],
        },
        step_id="plan",
    )

    yield ledger.event(
        "step.started",
        {
            "title": "生成文稿修订建议",
            "detail": "读取并分析 DOCX 正文，定位需要直接改写的问题片段。",
        },
        step_id="review",
    )

    feedback = _build_feedback_system(request, gemini_client=gemini_client)
    model_id = (
        _resolve_review_model_id(request, gemini_client=gemini_client)
        or str(getattr(feedback, "default_model_id", "") or "").strip()
    )
    user_requirement = _merged_followup_requirement(request)

    review_finished = False
    write_started = False
    final_result: dict[str, Any] = {}

    for progress_event in feedback.full_annotation_loop_streaming(
        target_docx,
        user_requirement=user_requirement,
        model_id=model_id,
    ):
        stage = str(progress_event.get("stage") or "").strip().lower()
        message = str(progress_event.get("message") or "").strip()
        detail = str(progress_event.get("detail") or "").strip()

        if stage in {"reading", "analyzing", "info", "warning"}:
            progress_payload = _build_review_progress_payload(
                progress_event, default_path=target_docx
            )
            progress_detail = str(
                progress_payload.get("detail") or progress_payload.get("message") or ""
            ).strip()
            if progress_detail:
                yield ledger.event(
                    "step_progress",
                    progress_payload,
                    step_id="review",
                )
            continue

        if stage == "reading_complete":
            yield ledger.event(
                "tool.finished",
                {
                    "tool_name": "read_docx_content",
                    "success": True,
                    "path": target_docx,
                    "tool_args": {"path": target_docx},
                    "result_preview": detail
                    or message
                    or f"已读取 {os.path.basename(target_docx)}",
                },
                step_id="review",
            )
            continue

        if stage == "analysis_complete":
            review_finished = True
            yield ledger.event(
                "step.finished",
                {"summary": detail or message or "文稿分析完成。"},
                step_id="review",
            )
            yield ledger.event(
                "step.started",
                {
                    "title": "写回 Word 修订",
                    "detail": "将审校修订直接写回当前 DOCX 文件。",
                },
                step_id="write",
            )
            write_started = True
            continue

        if stage == "applying":
            if not write_started:
                if not review_finished:
                    review_finished = True
                    yield ledger.event(
                        "step.finished",
                        {"summary": "文稿分析完成，开始写回当前 DOCX。"},
                        step_id="review",
                    )
                yield ledger.event(
                    "step.started",
                    {
                        "title": "写回 Word 修订",
                        "detail": detail
                        or message
                        or "将审校修订直接写回当前 DOCX 文件。",
                    },
                    step_id="write",
                )
                write_started = True
            yield ledger.event(
                "step_progress",
                _build_live_write_progress_payload(
                    progress_event, default_path=target_docx
                ),
                step_id="write",
            )
            continue

        if stage == "complete":
            result = progress_event.get("result")
            if isinstance(result, dict):
                final_result = result
            break

        if stage == "cancelled":
            yield _cancelled_run_event(
                ledger,
                summary=message or detail or "文稿修订任务已取消。",
                step_id="write" if write_started else "review",
            )
            return

        if stage == "error":
            yield _failed_run_event(
                ledger,
                summary=message or detail or "文稿修订失败。",
                code="DOC_ANNOTATE_FAILED",
                phase="write" if write_started else "review",
                status="model_error",
                step_id="write" if write_started else "review",
            )
            return

    revised_file = str(final_result.get("revised_file") or "").strip()
    applied = int(final_result.get("applied") or 0)
    passed = bool(final_result.get("success") and revised_file and applied > 0)

    if write_started:
        write_summary = (
            f"已将 {applied} 条修订写回 {os.path.basename(revised_file)}。"
            if passed
            else (
                str(final_result.get("message") or "")
                or "未写回任何 Word 修订，请改用普通 DOCX 润色写回流程或重新生成可定位的修订。"
            )
        )
        yield ledger.event(
            "step.finished",
            {"summary": write_summary},
            step_id="write",
        )

    if passed:
        yield ledger.event(
            "file.changed",
            {
                "operation": "annotate_file",
                "path": revised_file,
                "file_path": revised_file,
                "summary": f"已将修订写回 {os.path.basename(revised_file)}。",
                "annotations_added": applied,
                "source_path": target_docx,
                "output_path": revised_file,
                "supported": True,
            },
            step_id="write",
        )

    yield ledger.event(
        "check.started",
        {"title": "核验原文写回"},
        step_id="check",
    )
    yield ledger.event(
        "check.finished",
        {
            "passed": passed,
            "status": "verified" if passed else "failed",
            "summary": (
                f"已更新可打开的 DOCX 原文 {os.path.basename(revised_file)}。"
                if passed
                else (
                    str(final_result.get("message") or "")
                    or "未写回任何 Word 修订，请改用普通 DOCX 润色写回流程或重新生成可定位的修订。"
                )
            ),
        },
        step_id="check",
    )

    summary = (
        f"已将 {applied} 条修订写回 {os.path.basename(revised_file)}。"
        if passed
        else (
            str(final_result.get("message") or "")
            or "DOCX 文稿修订未完成：未写回任何 Word 修订。"
        )
    )
    yield ledger.event(
        "run.finished",
        {
            "summary": summary,
            "completed_task": passed,
            "mode": "doc_annotate_bridge",
            "target_path": target_docx,
            "revised_file": revised_file,
            "annotations_added": applied,
            "runtime": _runtime_payload(
                "verified" if passed else "quality_gate_failed"
            ),
        },
        step_id="run",
    )


def stream_request(
    request: FileTaskRequest,
    *,
    workspace_root: str = "",
    gemini_client: Any = None,
) -> Iterable[FileTaskEvent]:
    target_docx = _resolve_existing_path(
        _find_target_docx_path(request), workspace_root
    )
    source_pdf = _resolve_existing_path(_find_pdf_file(request), workspace_root)

    if not source_pdf:
        yield from _stream_single_docx_request(
            request,
            target_docx=target_docx,
            gemini_client=gemini_client,
        )
        return

    from web.document_feedback import DocumentFeedbackSystem

    ledger = FileTaskLedger(request.run_id)

    if not source_pdf or not os.path.exists(source_pdf):
        yield _failed_run_event(
            ledger,
            summary="未找到可读取的 PDF 原文，无法进入 DOCX 审校修订流程。",
            code="PDF_SOURCE_MISSING",
            phase="targeting",
            step_id="run",
        )
        return
    if not target_docx or not os.path.exists(target_docx):
        yield _failed_run_event(
            ledger,
            summary="未找到可修订的 DOCX 译稿，无法进入 DOCX 审校修订流程。",
            code="DOCX_TARGET_MISSING",
            phase="targeting",
            step_id="run",
        )
        return

    yield ledger.event(
        "run.started",
        {
            "task": request.task,
            "mode": "doc_annotate_bridge",
            "file_count": len(request.files),
            "target_path": target_docx,
            "source_path": source_pdf,
            "model_mode": request.model_mode,
            "model_id": request.model_id,
        },
        step_id="run",
    )

    yield ledger.event(
        "plan.created",
        {
            "summary": "识别为 PDF 原文 + DOCX 译稿审校任务，改走 Word 修订写回流程。",
            "steps": [
                {
                    "id": "reference",
                    "title": "整理 PDF 原文窗口",
                    "description": "按页窗口提取原文，供译稿审校时对照。",
                },
                {
                    "id": "review",
                    "title": "生成译稿审校建议",
                    "description": "结合 PDF 原文和 DOCX 译稿，生成需要写入 Word 的修订。",
                },
                {
                    "id": "write",
                    "title": "写回 Word 修订",
                    "description": "将修订直接写回当前 DOCX 审校稿。",
                },
                {
                    "id": "check",
                    "title": "核验输出",
                    "description": "确认已生成可打开的审校稿文件。",
                },
            ],
        },
        step_id="plan",
    )

    yield ledger.event(
        "step.started",
        {
            "title": "整理 PDF 原文窗口",
            "detail": "按页窗口提取原文，避免整本 PDF 一次性塞进审校提示。",
        },
        step_id="reference",
    )

    try:
        reference_windows, reference_meta = _build_pdf_reference_windows(source_pdf)
    except Exception as exc:
        logger.warning("[DocAnnotateBridge] build reference windows failed: %s", exc)
        yield _failed_run_event(
            ledger,
            summary="PDF 原文解析失败，无法继续文档审校。",
            detail=str(exc),
            code="PDF_CONTEXT_READ_FAILED",
            phase="context_read",
            step_id="reference",
        )
        return

    preview = _reference_preview(reference_windows)
    yield ledger.event(
        "tool.finished",
        {
            "tool_name": "parse_file_to_text",
            "success": bool(reference_windows),
            "path": source_pdf,
            "tool_args": {
                "path": source_pdf,
                "window_pages": reference_meta.get("window_pages", 0),
                "window_count": reference_meta.get("window_count", 0),
            },
            "result_preview": preview or "已提取 PDF 原文参考窗口。",
        },
        step_id="reference",
    )
    yield ledger.event(
        "step.finished",
        {
            "summary": (
                f"已整理 {reference_meta.get('window_count', 0)} 个 PDF 原文窗口，"
                f"覆盖约 {reference_meta.get('pages_with_text', 0) or reference_meta.get('page_count', 0)} 页正文。"
            ),
        },
        step_id="reference",
    )

    feedback = _build_feedback_system(request, gemini_client=gemini_client)
    review_stats = _inspect_docx_review_workload(target_docx, feedback)
    large_file_plan = _build_large_file_plan(
        reference_meta,
        review_stats,
        model_mode=request.model_mode,
    )
    batch_state = _batch_state_from_plan(request, large_file_plan)
    model_id = (
        _resolve_review_model_id(request, gemini_client=gemini_client)
        or str(getattr(feedback, "default_model_id", "") or "").strip()
    )
    user_requirement = _merged_followup_requirement(request)

    if large_file_plan:
        yield ledger.event(
            "plan.confirmed",
            large_file_plan,
            step_id="review",
        )

    if batch_state.get("error"):
        yield _failed_run_event(
            ledger,
            summary=str(batch_state.get("error") or "批次状态无效。"),
            code="DOC_ANNOTATE_BATCH_INVALID",
            phase="planning",
            step_id="review",
        )
        return

    if large_file_plan and batch_state.get("awaiting_confirmation"):
        total_batches = int(batch_state.get("total_batches") or 0)
        yield ledger.event(
            "run.finished",
            {
                "summary": f"文件较大，已生成 {total_batches} 批执行计划，等待确认开始第 1/{total_batches} 批。",
                "completed_task": False,
                "mode": "doc_annotate_bridge",
                "source_path": source_pdf,
                "target_path": target_docx,
                "awaiting_confirmation": True,
                "batch_index": 0,
                "total_batches": total_batches,
                "runtime": _runtime_payload("awaiting_confirmation"),
                "next_action_artifact": _build_batch_confirmation_artifact(
                    request,
                    source_pdf=source_pdf,
                    target_docx=target_docx,
                    large_file_plan=large_file_plan,
                    batch_index=1,
                ),
            },
            step_id="run",
        )
        return

    current_batch_index = int(batch_state.get("batch_index") or 0)
    total_batches = int(batch_state.get("total_batches") or 0)
    current_batch = (
        batch_state.get("batch") if isinstance(batch_state.get("batch"), dict) else {}
    )
    chunk_range = (
        batch_state.get("chunk_range")
        if isinstance(batch_state.get("chunk_range"), tuple)
        else None
    )
    review_title = (
        f"执行第 {current_batch_index}/{total_batches} 批审校"
        if current_batch_index > 0 and total_batches > 0
        else "生成译稿审校建议"
    )
    review_detail = (
        str(current_batch.get("description") or "").strip()
        if current_batch_index > 0 and total_batches > 0
        else "结合 PDF 原文和 DOCX 译稿，生成需要写回 Word 的修订。"
    )

    yield ledger.event(
        "step.started",
        {
            "title": review_title,
            "detail": review_detail,
        },
        step_id="review",
    )

    review_finished = False
    write_started = False
    final_result: dict[str, Any] = {}

    for progress_event in feedback.full_annotation_loop_streaming(
        target_docx,
        user_requirement=user_requirement,
        model_id=model_id,
        reference_context=reference_windows,
        chunk_range=chunk_range,
        batch_index=current_batch_index,
        total_batches=total_batches,
    ):
        stage = str(progress_event.get("stage") or "").strip().lower()
        message = str(progress_event.get("message") or "").strip()
        detail = str(progress_event.get("detail") or "").strip()

        if stage in {"reading", "analyzing", "info", "warning"}:
            progress_payload = _build_review_progress_payload(
                progress_event, default_path=target_docx
            )
            progress_detail = str(
                progress_payload.get("detail") or progress_payload.get("message") or ""
            ).strip()
            if progress_detail:
                yield ledger.event(
                    "step_progress",
                    progress_payload,
                    step_id="review",
                )
            continue

        if stage == "reading_complete":
            yield ledger.event(
                "tool.finished",
                {
                    "tool_name": "read_docx_content",
                    "success": True,
                    "path": target_docx,
                    "tool_args": {"path": target_docx},
                    "result_preview": detail
                    or message
                    or f"已读取 {os.path.basename(target_docx)}",
                },
                step_id="review",
            )
            continue

        if stage == "analysis_complete":
            review_finished = True
            yield ledger.event(
                "step.finished",
                {"summary": detail or message or "原文对照分析完成。"},
                step_id="review",
            )
            yield ledger.event(
                "step.started",
                {
                    "title": "写回 Word 修订",
                    "detail": "将审校修订直接写回当前 DOCX 文件。",
                },
                step_id="write",
            )
            write_started = True
            continue

        if stage == "applying":
            if not write_started:
                if not review_finished:
                    review_finished = True
                    yield ledger.event(
                        "step.finished",
                        {"summary": "原文对照分析完成，开始写回当前 DOCX。"},
                        step_id="review",
                    )
                yield ledger.event(
                    "step.started",
                    {
                        "title": "写回 Word 修订",
                        "detail": detail
                        or message
                        or "将审校修订直接写回当前 DOCX 文件。",
                    },
                    step_id="write",
                )
                write_started = True
            yield ledger.event(
                "step_progress",
                _build_live_write_progress_payload(
                    progress_event, default_path=target_docx
                ),
                step_id="write",
            )
            continue

        if stage == "complete":
            result = progress_event.get("result")
            if isinstance(result, dict):
                final_result = result
            break

        if stage == "cancelled":
            yield _cancelled_run_event(
                ledger,
                summary=message or detail or "译稿审校任务已取消。",
                step_id="write" if write_started else "review",
            )
            return

        if stage == "error":
            yield _failed_run_event(
                ledger,
                summary=message or detail or "译稿审校失败。",
                code="DOC_ANNOTATE_FAILED",
                phase="write" if write_started else "review",
                status="model_error",
                step_id="write" if write_started else "review",
            )
            return

    revised_file = str(final_result.get("revised_file") or "").strip()
    applied = int(final_result.get("applied") or 0)
    passed = bool(final_result.get("success") and revised_file and applied > 0)

    if write_started:
        write_summary = (
            f"已将 {applied} 条修订写回 {os.path.basename(revised_file)}。"
            if passed
            else (
                str(final_result.get("message") or "")
                or "未写回任何 Word 修订，请重新生成可定位的审校建议。"
            )
        )
        yield ledger.event(
            "step.finished",
            {"summary": write_summary},
            step_id="write",
        )

    if passed:
        yield ledger.event(
            "file.changed",
            {
                "operation": "annotate_file",
                "path": revised_file,
                "file_path": revised_file,
                "summary": f"已将修订写回 {os.path.basename(revised_file)}。",
                "annotations_added": applied,
                "source_path": os.path.basename(source_pdf),
                "output_path": revised_file,
                "supported": True,
            },
            step_id="write",
        )

    yield ledger.event(
        "check.started",
        {"title": "核验原文写回"},
        step_id="check",
    )
    yield ledger.event(
        "check.finished",
        {
            "passed": passed,
            "status": "verified" if passed else "failed",
            "summary": (
                f"已更新可打开的 DOCX 原文 {os.path.basename(revised_file)}。"
                if passed
                else (
                    str(final_result.get("message") or "")
                    or "未写回任何 Word 修订，请重新生成可定位的审校建议。"
                )
            ),
        },
        step_id="check",
    )

    if (
        passed
        and batch_state.get("has_next_batch")
        and isinstance(large_file_plan, dict)
    ):
        next_batch_index = int(batch_state.get("next_batch_index") or 0)
        next_target_docx = revised_file or target_docx
        yield ledger.event(
            "run.finished",
            {
                "summary": f"第 {current_batch_index}/{total_batches} 批已完成，当前 DOCX 已写入阶段性修订 {os.path.basename(next_target_docx)}，等待确认继续下一批。",
                "completed_task": False,
                "mode": "doc_annotate_bridge",
                "source_path": source_pdf,
                "target_path": target_docx,
                "revised_file": next_target_docx,
                "annotations_added": applied,
                "awaiting_confirmation": True,
                "batch_index": current_batch_index,
                "total_batches": total_batches,
                "runtime": _runtime_payload("awaiting_confirmation"),
                "next_action_artifact": _build_batch_confirmation_artifact(
                    request,
                    source_pdf=source_pdf,
                    target_docx=next_target_docx,
                    large_file_plan=large_file_plan,
                    batch_index=next_batch_index,
                ),
            },
            step_id="run",
        )
        return

    summary = (
        f"已将 {applied} 条修订写回 {os.path.basename(revised_file)}。"
        if passed
        else (
            str(final_result.get("message") or "")
            or "PDF 原文对照审校未完成：未写回任何 Word 修订。"
        )
    )
    yield ledger.event(
        "run.finished",
        {
            "summary": summary,
            "completed_task": passed,
            "mode": "doc_annotate_bridge",
            "source_path": source_pdf,
            "target_path": target_docx,
            "revised_file": revised_file,
            "annotations_added": applied,
            "batch_index": current_batch_index,
            "total_batches": total_batches,
            "runtime": _runtime_payload(
                "verified" if passed else "quality_gate_failed"
            ),
        },
        step_id="run",
    )


def _normalized_path_key(path: Any) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    return os.path.normcase(os.path.normpath(text))


def _build_request_path_aliases(
    request: FileTaskRequest, workspace_root: str
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    seen: set[str] = set()
    for file_info in _request_files(request):
        raw_path = str(file_info.path or file_info.name or "").strip()
        if not raw_path:
            continue
        if raw_path not in seen:
            seen.add(raw_path)
            aliases[_normalized_path_key(raw_path)] = raw_path
        resolved_path = _resolve_existing_path(raw_path, workspace_root)
        if resolved_path:
            aliases[_normalized_path_key(resolved_path)] = raw_path

    target_path = str(request.target_path or "").strip()
    if target_path:
        aliases[_normalized_path_key(target_path)] = target_path
        resolved_target = _resolve_existing_path(target_path, workspace_root)
        if resolved_target:
            aliases[_normalized_path_key(resolved_target)] = target_path
    return aliases


def _rewrite_tool_payload_paths(
    payload: dict[str, Any], aliases: dict[str, str]
) -> dict[str, Any]:
    rewritten = dict(payload or {})
    for key in (
        "path",
        "file_path",
        "source_path",
        "target_path",
        "revised_file",
        "output_path",
    ):
        value = str(rewritten.get(key) or "").strip()
        if not value:
            continue
        alias = aliases.get(_normalized_path_key(value))
        if alias:
            rewritten[key] = alias
    return rewritten


def stream_request_as_tool(
    request: FileTaskRequest,
    *,
    workspace_root: str = "",
    gemini_client: Any = None,
) -> FileTaskToolStreamResult:
    def _chunks():
        path_aliases = _build_request_path_aliases(request, workspace_root)
        last_change: Optional[dict[str, Any]] = None
        for event in stream_request(
            request,
            workspace_root=workspace_root,
            gemini_client=gemini_client,
        ):
            if event.type in {"step_progress", "plan.confirmed"}:
                payload = dict(event.payload or {})
                if event.type == "step_progress":
                    payload = _rewrite_tool_payload_paths(payload, path_aliases)
                yield FileTaskToolStreamChunk(
                    kind="event", event_type=event.type, payload=payload
                )
                continue
            if event.type == "file.changed" and isinstance(event.payload, dict):
                last_change = _rewrite_tool_payload_paths(
                    dict(event.payload), path_aliases
                )
                continue
            if event.type == "run.cancelled":
                text = (
                    str(event.payload.get("summary") or "文档审校任务已取消。")
                    if isinstance(event.payload, dict)
                    else "文档审校任务已取消。"
                )
                yield FileTaskToolStreamChunk(
                    kind="result", payload={"error": text, "cancelled": True}
                )
                return
            if event.type == "run.finished" and isinstance(event.payload, dict):
                payload = _tool_result_from_bridge_payload(
                    dict(event.payload), last_change=last_change
                )
                payload = _rewrite_tool_payload_paths(payload, path_aliases)
                yield FileTaskToolStreamChunk(
                    kind="result",
                    payload=payload,
                )
                return

        yield FileTaskToolStreamChunk(
            kind="result", payload={"error": "文档审校流程未返回结束事件。"}
        )

    return FileTaskToolStreamResult(chunks=_chunks())


def _request_files(request: FileTaskRequest) -> list[FileTaskFile]:
    files: list[FileTaskFile] = []
    if isinstance(request.current_file, FileTaskFile):
        files.append(request.current_file)
    files.extend(file for file in request.files if isinstance(file, FileTaskFile))
    return files


def _file_type(file_info: FileTaskFile) -> str:
    explicit = str(file_info.type or "").strip().lower().lstrip(".")
    if explicit:
        return explicit
    suffix = (
        Path(str(file_info.path or file_info.name or "")).suffix.lower().lstrip(".")
    )
    return suffix


def _find_pdf_file(request: FileTaskRequest) -> Optional[str]:
    for file_info in _request_files(request):
        if _file_type(file_info) == "pdf":
            return file_info.path or file_info.name
    return None


def _find_target_docx_path(request: FileTaskRequest) -> Optional[str]:
    target_path = str(request.target_path or "").strip()
    if target_path.lower().endswith(".docx"):
        return target_path

    for file_info in _request_files(request):
        if _file_type(file_info) != "docx":
            continue
        if file_info.target:
            return file_info.path or file_info.name

    for file_info in _request_files(request):
        if _file_type(file_info) == "docx":
            return file_info.path or file_info.name
    return None


def _resolve_existing_path(raw_path: Optional[str], workspace_root: str) -> str:
    text = str(raw_path or "").strip()
    if not text:
        return ""
    if os.path.isabs(text):
        return text
    if workspace_root:
        candidate = os.path.join(workspace_root, text)
        if os.path.exists(candidate):
            return candidate
    return text


def _merged_followup_requirement(request: FileTaskRequest) -> str:
    task_text = str(request.task or "").strip()
    if not isinstance(request.options, dict):
        return task_text

    followup_context = request.options.get("followup_context")
    if not isinstance(followup_context, dict):
        return task_text
    if str(followup_context.get("kind") or "").strip() != "review_last_task":
        return task_text
    if str(followup_context.get("followup_action") or "").strip().lower() != "improve":
        return task_text

    previous_request = str(followup_context.get("previous_task_request") or "").strip()
    user_feedback = str(followup_context.get("user_feedback") or task_text).strip()
    if not previous_request:
        return task_text

    return (
        f"上一轮任务要求：{previous_request}\n"
        f"当前追加反馈：{user_feedback}\n"
        "请把这次处理视为上一轮任务的继续优化，保持原有审校目标、范围和约束。"
    )


def _build_pdf_reference_windows(
    pdf_path: str,
    *,
    window_pages: int = 4,
    per_window_chars: int = 8000,
    max_windows: Optional[int] = None,
) -> tuple[list[str], dict[str, int]]:
    from app.core.file.file_parser import parse_pdf

    parsed = parse_pdf(pdf_path, uuid.uuid4().hex[:12])
    page_count = int((parsed or {}).get("page_count") or 0)
    pages = (parsed or {}).get("pages") or []
    windows: list[str] = []
    pages_with_text = 0
    window_limit = max(0, int(max_windows or 0))

    if isinstance(pages, list) and pages:
        current: list[str] = []
        for page in pages:
            page_no = int((page or {}).get("page") or 0)
            page_text = str((page or {}).get("text") or "").strip()
            if not page_text:
                continue
            pages_with_text += 1
            current.append(f"[Page {page_no}]\n{page_text}")
            if len(current) >= window_pages:
                windows.append("\n\n".join(current)[:per_window_chars])
                current = []
                if window_limit and len(windows) >= window_limit:
                    break
        if current and (not window_limit or len(windows) < window_limit):
            windows.append("\n\n".join(current)[:per_window_chars])
    else:
        text = str((parsed or {}).get("text") or "").strip()
        if text:
            limit = (
                len(text)
                if not window_limit
                else min(len(text), per_window_chars * window_limit)
            )
            for offset in range(0, limit, per_window_chars):
                windows.append(text[offset : offset + per_window_chars])
            pages_with_text = page_count

    meta = {
        "page_count": page_count,
        "pages_with_text": pages_with_text,
        "window_count": len(windows),
        "window_pages": window_pages,
    }
    return windows, meta


def _reference_preview(reference_windows: Sequence[str]) -> str:
    if not reference_windows:
        return ""
    preview = str(reference_windows[0] or "").strip()
    if len(preview) > 500:
        preview = preview[:497] + "..."
    return preview


def _prepare_docx_chunk_source(formatted_content: str) -> str:
    marker = "## 文档内容"
    marker_pos = formatted_content.find(marker)
    if marker_pos == -1:
        return formatted_content
    line_end = formatted_content.find("\n", marker_pos)
    if line_end == -1:
        return formatted_content
    return formatted_content[line_end + 1 :].lstrip("\n")


def _review_chunk_size(feedback: Any) -> int:
    if getattr(feedback, "client", None) and os.getenv("KOTO_DISABLE_AI") != "1":
        return 4000
    return 10000


def _inspect_docx_review_workload(target_docx: str, feedback: Any) -> dict[str, Any]:
    try:
        reader = getattr(feedback, "reader", None)
        if reader is None:
            from web.document_reader import DocumentReader

            reader = DocumentReader()

        doc_data = reader.read_document(target_docx)
        if not doc_data.get("success"):
            return {}

        formatted_content = reader.format_for_ai(doc_data)
        chunk_source = _prepare_docx_chunk_source(formatted_content)
        chunk_size = _review_chunk_size(feedback)
        splitter = getattr(feedback, "_split_into_chunks_by_paragraphs", None)
        if callable(splitter):
            chunks = splitter(chunk_source, chunk_size)
        else:
            chunks = [chunk_source] if chunk_source else []
        chunk_char_counts = [len(str(chunk or "")) for chunk in chunks]

        return {
            "paragraph_count": len(doc_data.get("paragraphs") or []),
            "table_count": len(doc_data.get("tables") or []),
            "formatted_chars": len(formatted_content),
            "content_chars": len(chunk_source),
            "chunk_size": chunk_size,
            "chunk_count": len(chunks),
            "chunk_char_counts": chunk_char_counts,
        }
    except Exception as exc:
        logger.warning("[DocAnnotateBridge] inspect docx workload failed: %s", exc)
        return {}


def _format_large_count(value: int, unit: str) -> str:
    normalized = max(0, int(value or 0))
    if normalized >= 10000:
        return f"约 {normalized / 10000:.1f} 万{unit}"
    return f"{normalized} {unit}"


def _partition_ranges(total: int, groups: int) -> list[tuple[int, int]]:
    normalized_total = max(0, int(total or 0))
    if normalized_total <= 0:
        return []

    normalized_groups = max(1, min(int(groups or 1), normalized_total))
    base, extra = divmod(normalized_total, normalized_groups)

    ranges: list[tuple[int, int]] = []
    start = 1
    for idx in range(normalized_groups):
        size = base + (1 if idx < extra else 0)
        end = start + size - 1
        ranges.append((start, end))
        start = end + 1
    return ranges


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name) or default))
    except (TypeError, ValueError):
        return max(1, int(default or 1))


def _doc_review_batch_budget(
    model_mode: str, *, chunk_size: int = 0
) -> dict[str, int | str]:
    normalized_model_mode = str(model_mode or "deepseek").strip().lower() or "deepseek"
    is_local_mode = normalized_model_mode == "local"

    if is_local_mode:
        target_minutes = _positive_int_env(
            "KOTO_DOC_REVIEW_LOCAL_BATCH_TARGET_MINUTES", 5
        )
        approx_chars_per_minute = _positive_int_env(
            "KOTO_DOC_REVIEW_LOCAL_BATCH_CHARS_PER_MINUTE", 2400
        )
        max_chunks_per_batch = 3
        max_windows_per_batch = 12
        mode_label = "本地模型"
    else:
        target_minutes = _positive_int_env(
            "KOTO_DOC_REVIEW_CLOUD_BATCH_TARGET_MINUTES", 6
        )
        approx_chars_per_minute = _positive_int_env(
            "KOTO_DOC_REVIEW_CLOUD_BATCH_CHARS_PER_MINUTE", 4000
        )
        max_chunks_per_batch = 6
        max_windows_per_batch = 20
        mode_label = "云端模型"

    target_chars_per_batch = max(
        max(1, int(chunk_size or 0)),
        target_minutes * approx_chars_per_minute,
    )
    return {
        "mode_label": mode_label,
        "target_minutes": target_minutes,
        "approx_chars_per_minute": approx_chars_per_minute,
        "target_chars_per_batch": target_chars_per_batch,
        "max_chunks_per_batch": max_chunks_per_batch,
        "max_windows_per_batch": max_windows_per_batch,
    }


def _normalized_chunk_char_counts(review_stats: dict[str, Any]) -> list[int]:
    chunk_count = max(0, int(review_stats.get("chunk_count") or 0))
    if chunk_count <= 0:
        return []

    raw_counts = review_stats.get("chunk_char_counts")
    counts: list[int] = []
    if isinstance(raw_counts, Sequence) and not isinstance(raw_counts, (str, bytes)):
        try:
            counts = [max(1, int(value or 0)) for value in raw_counts]
        except (TypeError, ValueError):
            counts = []

    if len(counts) != chunk_count:
        content_chars = max(1, int(review_stats.get("content_chars") or 0))
        average_chars = max(1, math.ceil(content_chars / max(1, chunk_count)))
        counts = [average_chars] * chunk_count

    return counts[:chunk_count]


def _chunk_ranges_for_char_budget(
    chunk_char_counts: Sequence[int],
    *,
    target_chars_per_batch: int,
    max_chunks_per_batch: int,
) -> tuple[list[tuple[int, int]], list[int]]:
    normalized_counts = [max(1, int(value or 0)) for value in chunk_char_counts]
    if not normalized_counts:
        return [], []

    target_chars = max(1, int(target_chars_per_batch or 0))
    max_chunks = max(1, int(max_chunks_per_batch or 0))

    ranges: list[tuple[int, int]] = []
    batch_char_counts: list[int] = []
    start_index = 1
    current_chars = 0
    current_chunk_count = 0

    for index, chunk_chars in enumerate(normalized_counts, start=1):
        exceeds_char_budget = (
            current_chunk_count > 0 and (current_chars + chunk_chars) > target_chars
        )
        exceeds_chunk_budget = current_chunk_count >= max_chunks
        if exceeds_char_budget or exceeds_chunk_budget:
            ranges.append((start_index, index - 1))
            batch_char_counts.append(current_chars)
            start_index = index
            current_chars = 0
            current_chunk_count = 0

        current_chars += chunk_chars
        current_chunk_count += 1

    if current_chunk_count > 0:
        ranges.append((start_index, len(normalized_counts)))
        batch_char_counts.append(current_chars)

    return ranges, batch_char_counts


def _window_ranges_for_batch_loads(
    window_count: int, batch_char_counts: Sequence[int]
) -> list[tuple[int, int]]:
    normalized_window_count = max(0, int(window_count or 0))
    if normalized_window_count <= 0 or not batch_char_counts:
        return []

    weights = [max(1, int(value or 0)) for value in batch_char_counts]
    total_weight = sum(weights)
    start = 1
    consumed_weight = 0
    ranges: list[tuple[int, int]] = []

    for index, weight in enumerate(weights):
        remaining_batches = len(weights) - index - 1
        if index == len(weights) - 1 or total_weight <= 0:
            end = normalized_window_count
        else:
            consumed_weight += weight
            proportional_end = int(
                round((consumed_weight / total_weight) * normalized_window_count)
            )
            min_end = start
            max_end = max(min_end, normalized_window_count - remaining_batches)
            end = max(min_end, min(max_end, proportional_end))

        ranges.append((start, end))
        start = end + 1
        if start > normalized_window_count:
            start = normalized_window_count

    return ranges


def _build_large_file_plan(
    reference_meta: dict[str, int],
    review_stats: dict[str, Any],
    *,
    model_mode: str = "deepseek",
) -> Optional[dict[str, Any]]:
    chunk_count = int(review_stats.get("chunk_count") or 0)
    window_count = int(reference_meta.get("window_count") or 0)
    page_count = int(reference_meta.get("page_count") or 0)
    pages_with_text = int(reference_meta.get("pages_with_text") or page_count)
    content_chars = int(review_stats.get("content_chars") or 0)
    normalized_model_mode = str(model_mode or "deepseek").strip().lower() or "deepseek"
    is_local_mode = normalized_model_mode == "local"
    chunk_size = int(review_stats.get("chunk_size") or 0)

    is_large = (
        chunk_count >= 12
        or window_count >= 24
        or pages_with_text >= 120
        or content_chars >= 50000
    )
    if not is_large:
        return None

    batch_budget = _doc_review_batch_budget(model_mode, chunk_size=chunk_size)
    target_minutes = int(batch_budget.get("target_minutes") or 0)
    approx_chars_per_minute = int(batch_budget.get("approx_chars_per_minute") or 0)
    target_chars_per_batch = int(batch_budget.get("target_chars_per_batch") or 0)
    max_chunks_per_batch = int(batch_budget.get("max_chunks_per_batch") or 0)
    max_windows_per_batch = int(batch_budget.get("max_windows_per_batch") or 0)
    mode_label = str(batch_budget.get("mode_label") or "模型")

    chunk_char_counts = _normalized_chunk_char_counts(review_stats)
    batch_count = max(
        2,
        math.ceil(max(1, content_chars) / max(1, target_chars_per_batch)),
        math.ceil(max(1, chunk_count) / max(1, max_chunks_per_batch)),
        math.ceil(max(1, window_count) / max(1, max_windows_per_batch)),
    )
    chunk_ranges, batch_char_counts = _chunk_ranges_for_char_budget(
        chunk_char_counts,
        target_chars_per_batch=target_chars_per_batch,
        max_chunks_per_batch=max_chunks_per_batch,
    )
    if not chunk_ranges:
        chunk_ranges = _partition_ranges(chunk_count, batch_count)
        batch_char_counts = [
            math.ceil(max(1, content_chars) / max(1, len(chunk_ranges)))
        ] * len(chunk_ranges)

    window_ranges = _window_ranges_for_batch_loads(window_count, batch_char_counts)
    window_pages = max(1, int(reference_meta.get("window_pages") or 4))

    steps: list[dict[str, str]] = []
    batches: list[dict[str, Any]] = []
    for idx, chunk_range in enumerate(chunk_ranges):
        chunk_start, chunk_end = chunk_range
        batch_chars = batch_char_counts[idx] if idx < len(batch_char_counts) else 0
        batch_chars_label = _format_large_count(batch_chars, "字")
        estimated_minutes = max(
            1, math.ceil(batch_chars / max(1, approx_chars_per_minute))
        )
        description_parts = [
            f"处理译稿分段 {chunk_start}-{chunk_end}/{chunk_count}",
            batch_chars_label,
            f"预计用时约 {estimated_minutes} 分钟",
        ]
        window_start = 0
        window_end = 0
        approx_page_start = 0
        approx_page_end = 0
        if idx < len(window_ranges):
            window_start, window_end = window_ranges[idx]
            approx_page_start = ((window_start - 1) * window_pages) + 1
            approx_page_end = min(pages_with_text, window_end * window_pages)
            description_parts.append(
                f"对照 PDF 窗口 {window_start}-{window_end}/{window_count}（约第 {approx_page_start}-{approx_page_end} 页正文）"
            )
        description = "，".join(description_parts) + "。"
        steps.append(
            {
                "id": f"batch_{idx + 1}",
                "title": f"第 {idx + 1} 批：分段 {chunk_start}-{chunk_end}",
                "description": description,
            }
        )
        batches.append(
            {
                "id": f"batch_{idx + 1}",
                "title": f"第 {idx + 1} 批：分段 {chunk_start}-{chunk_end}",
                "description": description,
                "chunk_start": chunk_start,
                "chunk_end": chunk_end,
                "char_count": batch_chars,
                "estimated_minutes": estimated_minutes,
                "window_start": window_start,
                "window_end": window_end,
                "page_start": approx_page_start,
                "page_end": approx_page_end,
            }
        )

    steps.extend(
        [
            {
                "id": "write",
                "title": "汇总并写回修订",
                "description": f"合并前面 {len(chunk_ranges)} 批的审校建议，统一写入当前 DOCX 审校稿。",
            },
            {
                "id": "check",
                "title": "核验输出",
                "description": "确认审校稿已生成、可打开，并保留修订结构。",
            },
        ]
    )

    paragraph_count = int(review_stats.get("paragraph_count") or 0)
    table_count = int(review_stats.get("table_count") or 0)
    note = (
        f"原文 PDF 共 {page_count} 页，其中 {pages_with_text} 页含正文，约 {_format_large_count(int(reference_meta.get('window_count', 0) or 0) * int(reference_meta.get('window_pages') or 4), '页窗口容量')}；"
        f"译稿 DOCX 共 {paragraph_count} 段、{table_count} 个表格，约 {_format_large_count(content_chars, '字')}，"
        f"内部将按 {chunk_count} 个审校分段顺序处理。"
    )
    note += (
        f" 当前按 {mode_label} {_format_large_count(target_chars_per_batch, '字/批')} 规划，"
        f"目标单批约 {target_minutes} 分钟；实际耗时会随模型响应和段落复杂度波动。"
    )
    summary = (
        f"文件较大，将按 {len(chunk_ranges)} 批执行：{chunk_count} 个译稿分段，对照 {window_count} 个 PDF 原文窗口。"
        f" 当前按 {_format_large_count(target_chars_per_batch, '字/批')} 分批。"
    )
    return {
        "summary": summary,
        "note": note,
        "steps": steps,
        "batches": batches,
        "execution_policy": "confirm_each_batch",
        "planning_basis": {
            "model_mode": normalized_model_mode,
            "target_minutes": target_minutes,
            "target_chars_per_batch": target_chars_per_batch,
            "approx_chars_per_minute": approx_chars_per_minute,
        },
    }
