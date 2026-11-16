from __future__ import annotations

import datetime as _dt
import json
import logging
from typing import Any, Dict, List, Optional

from app.core.agent._file_task_stepwise_helpers import (
    stepwise_docx_content_quality_block_message as _stepwise_docx_content_quality_block_message,
)
from app.core.agent._file_task_stepwise_helpers import (
    stepwise_docx_write_block_message as _stepwise_docx_write_block_message,
)
from app.core.agent._file_task_stepwise_helpers import (
    stepwise_pdf_fallback_insights as _stepwise_pdf_fallback_insights,
)
from app.core.agent._file_task_stepwise_helpers import (
    stepwise_pdf_fallback_paragraphs as _stepwise_pdf_fallback_paragraphs,
)
from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskExecutionContext,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
)
from app.core.agent.file_task_followup_context import (
    followup_context as _build_followup_context,
)
from app.core.agent.file_task_message_payload import build_file_task_runtime_messages
from app.core.agent.file_task_quality_gate import (
    evaluate_task_quality_gate as _quality_evaluate_task_quality_gate,
)
from app.core.agent.file_task_quality_gate import (
    quality_gate_result as _quality_gate_result,
)
from app.core.agent.file_task_result_markers import (
    KOTO_CREATED_RESULT_MARKER,
    KOTO_MODIFIED_RESULT_MARKER,
)
from app.core.agent.file_task_runtime_utils import _json_payload
from app.core.agent.file_task_supervisor_prompts import (
    file_types as _supervisor_file_types,
)
from app.core.agent.file_task_system_prompt_builder import (
    build_file_task_runtime_system_prompt,
)
from app.core.agent.file_task_tool_feedback import (
    extract_file_changes as _feedback_extract_file_changes,
)
from app.core.agent.file_task_tool_feedback import (
    extract_tool_runtime_outcome as _feedback_extract_tool_runtime_outcome,
)
from app.core.agent.file_task_tool_feedback import (
    tool_artifacts as _feedback_tool_artifacts,
)
from app.core.agent.file_task_tool_feedback import (
    tool_runtime_status as _feedback_tool_runtime_status,
)
from app.core.agent.file_task_tool_gateway import ToolExecutor
from app.core.agent.file_task_verification import (
    verification_precheck as _verification_precheck,
)
from app.core.agent.kernel import ModelResponse
from app.core.agent.toolkits.foundation.catalog import file_states_for_changes

logger = logging.getLogger(__name__)


class _FileTaskRuntimePart4:
    def _stepwise_docx_write_block_message(
        self,
        request: FileTaskRequest,
        snippets: List[Dict[str, Any]],
        recipe_skeleton: Dict[str, Any],
        tool_name: str,
        tool_args: Dict[str, Any],
    ) -> str:
        return _stepwise_docx_write_block_message(
            request=request,
            snippets=snippets,
            recipe_skeleton=recipe_skeleton,
            tool_name=tool_name,
            tool_args=tool_args,
        )

    def _stepwise_docx_content_quality_block_message(
        self, snippets: List[Dict[str, Any]], text: str
    ) -> str:
        return _stepwise_docx_content_quality_block_message(snippets, text)

    def _stepwise_pdf_fallback_paragraphs(
        self,
        request: FileTaskRequest,
        pdf_snippet: Dict[str, Any],
        exc: Exception,
    ) -> List[Dict[str, str]]:
        return _stepwise_pdf_fallback_paragraphs(pdf_snippet, exc)

    def _stepwise_pdf_fallback_insights(self, preview: str) -> List[str]:
        return _stepwise_pdf_fallback_insights(preview)

    def _file_types(self, files: List[FileTaskFile]) -> set[str]:
        return _supervisor_file_types(files)

    def _build_system_prompt(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        known_tool_gap: Optional[Dict[str, Any]] = None,
        classification: Optional[FileTaskClassification] = None,
        intent_plan: Optional[FileTaskIntentPlan] = None,
        execution_context: Optional[FileTaskExecutionContext] = None,
        recipe_skeleton: Optional[Dict[str, Any]] = None,
        tool_definitions: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        resolved_context = execution_context or self._build_execution_context(
            request,
            files,
            known_tool_gap=known_tool_gap,
            classification=classification,
            intent_plan=intent_plan,
        )
        return build_file_task_runtime_system_prompt(
            request=request,
            files=files,
            classification=resolved_context.classification,
            intent_plan=resolved_context.intent_plan,
            known_tool_gap=resolved_context.known_tool_gap,
            recipe_skeleton=recipe_skeleton,
            output_mode_guidance=self._output_mode_guidance,
            intent_plan_guidance=self._intent_plan_guidance,
            current_date=_dt.datetime.now().strftime("%Y-%m-%d"),
            tool_definitions=tool_definitions,
        )

    def _build_messages(
        self,
        request: FileTaskRequest,
        snippets: List[Dict[str, Any]],
        files: List[FileTaskFile],
        known_tool_gap: Optional[Dict[str, Any]] = None,
        classification: Optional[FileTaskClassification] = None,
        intent_plan: Optional[FileTaskIntentPlan] = None,
        execution_context: Optional[FileTaskExecutionContext] = None,
        recipe_skeleton: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        resolved_context = execution_context or self._build_execution_context(
            request,
            files,
            known_tool_gap=known_tool_gap,
            classification=classification,
            intent_plan=intent_plan,
        )
        resolved_classification = resolved_context.classification
        resolved_intent_plan = resolved_context.intent_plan
        resolved_known_tool_gap = resolved_context.known_tool_gap
        return build_file_task_runtime_messages(
            request=request,
            snippets=snippets,
            files=files,
            classification=resolved_classification,
            intent_plan=resolved_intent_plan,
            known_tool_gap=resolved_known_tool_gap,
            recipe_skeleton=recipe_skeleton,
        )

    def _followup_context(self, request: FileTaskRequest) -> Dict[str, Any]:
        return _build_followup_context(request)

    def _call_model(
        self,
        *,
        request: FileTaskRequest,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if hasattr(self._model_client, "for_request"):
            gateway = self._model_client.for_request(request)  # type: ignore[union-attr]
            response = gateway.generate(
                messages=messages,
                system=system,
                tools=tools,
                model_id=str(request.model_id or ""),
                options={"task_type": "FILE_TASK"},
            )
            return ModelResponse.from_raw(response, strict=False).to_mapping()
        if hasattr(self._model_client, "call"):
            return self._model_client.call(request=request, messages=messages, system=system, tools=tools)  # type: ignore[union-attr]
        return self._model_client(request=request, messages=messages, system=system, tools=tools)  # type: ignore[misc]

    def _extract_file_changes(
        self, tool_name: str, tool_args: Dict[str, Any], result: Any
    ) -> List[Dict[str, Any]]:
        return _feedback_extract_file_changes(
            tool_name,
            tool_args,
            result,
            created_marker=KOTO_CREATED_RESULT_MARKER,
            modified_marker=KOTO_MODIFIED_RESULT_MARKER,
        )

    def _extract_tool_runtime_outcome(self, result: Any) -> Optional[Dict[str, Any]]:
        return _feedback_extract_tool_runtime_outcome(result)

    def _tool_runtime_status(
        self, tool_runtime_outcome: Optional[Dict[str, Any]]
    ) -> str:
        return _feedback_tool_runtime_status(tool_runtime_outcome)

    def _tool_artifacts(self, tool_name: str, result: Any) -> List[Dict[str, Any]]:
        return _feedback_tool_artifacts(tool_name, result)

    def _quality_gate_result(
        self,
        *,
        criterion: str,
        passed: bool,
        detail: str,
        priority: str = "high",
    ) -> Dict[str, Any]:
        return _quality_gate_result(
            criterion=criterion,
            passed=passed,
            detail=detail,
            priority=priority,
        )

    def _evaluate_task_quality_gate(
        self,
        request: FileTaskRequest,
        file_changes: List[Dict[str, Any]],
        *,
        write_intent: bool,
        output_mode: str,
    ) -> Dict[str, Any]:
        return _quality_evaluate_task_quality_gate(
            request,
            file_changes,
            write_intent=write_intent,
            output_mode=output_mode,
        )

    def _verify_task(
        self,
        request: FileTaskRequest,
        executor: ToolExecutor,
        file_changes: List[Dict[str, Any]],
        write_intent: bool,
        output_mode: str,
        model_failed: bool,
        readonly_fallback_used: bool = False,
        tool_runtime_outcome: Optional[Dict[str, Any]] = None,
        tool_gap: Optional[Dict[str, Any]] = None,
        next_action_artifact: Optional[Dict[str, Any]] = None,
        execution_failure: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        runtime_status = self._tool_runtime_status(tool_runtime_outcome)
        precheck = _verification_precheck(
            request=request,
            file_changes=file_changes,
            write_intent=write_intent,
            model_failed=model_failed,
            execution_failure=execution_failure,
            readonly_fallback_used=readonly_fallback_used,
            runtime_status=runtime_status,
            tool_runtime_outcome=tool_runtime_outcome,
            tool_gap=tool_gap,
            next_action_artifact=next_action_artifact,
            requires_file_change_before_pause=self._requires_file_change_before_pause(
                request
            ),
        )
        if precheck is not None:
            return precheck

        if file_changes:
            verify_target_path = self._verification_target_path(request, file_changes)
            verify_args = {
                "task_description": request.task,
                "file_states": json.dumps(
                    file_states_for_changes(
                        file_changes, workspace_root=self._workspace_root
                    ),
                    ensure_ascii=False,
                ),
                "file_changes": json.dumps(file_changes, ensure_ascii=False),
                "target_path": verify_target_path,
                "model_mode": request.model_mode,
            }
            try:
                result = executor("verify_task_completion", verify_args)
                payload = _json_payload(result)
            except Exception as exc:
                logger.warning(
                    "[FileTaskRuntime] verify_task_completion failed: %s", exc
                )
                payload = {
                    "completed": False,
                    "summary": f"文件已变更，但 AI 核验工具不可用：{exc}",
                }

            if payload.get("error"):
                return {
                    "passed": False,
                    "status": "verify_error",
                    "summary": f"文件已变更，但核验工具返回错误：{payload.get('error')}",
                    "remaining": ["修复模型/核验工具配置后重新核验"],
                    "criteria_results": [
                        {
                            "criterion": "verification_tool_available",
                            "passed": False,
                            "detail": f"核验工具返回错误：{payload.get('error')}",
                            "priority": "critical",
                        }
                    ],
                }

            completed = payload.get("completed")
            passed = bool(completed) if completed is not None else True
            quality_gate = self._evaluate_task_quality_gate(
                request,
                file_changes,
                write_intent=write_intent,
                output_mode=output_mode,
            )
            verification_criteria = payload.get("criteria_results") or []
            combined_criteria = [
                *verification_criteria,
                *quality_gate.get("criteria_results", []),
            ]
            if not quality_gate.get("passed", True):
                remaining = list(quality_gate.get("remaining") or [])
                if payload.get("remaining_steps"):
                    remaining.extend(
                        str(item)
                        for item in payload.get("remaining_steps") or []
                        if str(item or "").strip()
                    )
                summary = "文件已有变更，但未满足本任务的关键质量门禁。"
                if remaining:
                    summary = f"{summary}还需处理：{remaining[0]}"
                return {
                    "passed": False,
                    "status": "quality_gate_failed",
                    "summary": summary,
                    "confidence": payload.get("confidence"),
                    "remaining": remaining or ["补齐任务要求的关键产物后重新核验"],
                    "criteria_results": combined_criteria,
                }
            return {
                "passed": passed,
                "status": "verified" if passed else "quality_gate_failed",
                "summary": str(
                    payload.get("summary")
                    or ("文件变更已记录。" if passed else "核验未通过。")
                ),
                "confidence": payload.get("confidence"),
                "remaining": payload.get("remaining_steps")
                or ([] if passed else ["根据核验结果继续修复"]),
                "criteria_results": combined_criteria,
            }

        return {
            "passed": True,
            "status": "completed" if not model_failed else "context_only",
            "summary": (
                "已完成分析建议，当前未直接写入文件。"
                if output_mode == "hybrid"
                else "已完成只读任务，没有产生文件写入。"
            ),
            "remaining": [],
        }

    def _requires_file_change_before_pause(self, request: FileTaskRequest) -> bool:
        options = request.options if isinstance(request.options, dict) else {}
        return bool(
            options.get("requires_confirmation") or options.get("confirm_before_apply")
        )
