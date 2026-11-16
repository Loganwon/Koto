from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.core.agent.file_task_classification_finalizer import build_final_classification
from app.core.agent.file_task_classification_policy import resolve_classification_policy
from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskExecutionContext,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
    FileTaskRequirementSet,
)
from app.core.agent.file_task_execution_messaging import (
    intent_plan_guidance as _execution_messaging_intent_plan_guidance,
)
from app.core.agent.file_task_execution_messaging import (
    output_mode_guidance as _execution_messaging_output_mode_guidance,
)
from app.core.agent.file_task_execution_messaging import (
    output_mode_label as _execution_messaging_output_mode_label,
)
from app.core.agent.file_task_intent_adjudication import (
    classification_task_text as _intent_adjudication_classification_task_text,
)
from app.core.agent.file_task_intent_adjudication import (
    request_with_task as _intent_adjudication_request_with_task,
)
from app.core.agent.file_task_runtime_utils import _preview
from app.core.agent.file_task_validation import (
    build_file_task_requirements,
    validate_file_task_plan,
)
from app.core.agent.file_task_workflow_state import workflow_resume_control
from app.core.agent.tool_design_protocol import TOOL_DESIGN_PROTOCOL

logger = logging.getLogger(__name__)


class _FileTaskRuntimePart2:
    def _classify_request(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        known_tool_gap: Optional[Dict[str, Any]] = None,
    ) -> FileTaskClassification:
        followup_context = self._followup_context(request)
        resume_control = workflow_resume_control(request)
        classification_task = self._classification_task_text(request, resume_control)
        classification_request = self._request_with_task(request, classification_task)
        planner_policy, planner_reason, planner_backend = self._planner_classification(
            request
        )
        classification_policy = resolve_classification_policy(
            classification_task=classification_task,
            classification_request=classification_request,
            files=files,
            followup_context=followup_context,
            resume_control=resume_control,
            explicit_output_mode=self._explicit_output_mode(request),
            planner_policy=planner_policy,
            planner_backend=planner_backend,
            known_tool_gap=known_tool_gap,
        )
        raw_write_signal = classification_policy.raw_write_signal
        diagnostic_request = classification_policy.diagnostic_request
        request_kind = classification_policy.request_kind
        execution_mode = classification_policy.execution_mode
        reason_codes = classification_policy.reason_codes
        known_gap_name = classification_policy.known_gap_name

        return build_final_classification(
            request=request,
            files=files,
            request_kind=request_kind,
            task_family=classification_policy.task_family,
            operation_kind=classification_policy.operation_kind,
            execution_mode=execution_mode,
            output_mode=classification_policy.output_mode,
            write_authorized=classification_policy.write_authorized,
            write_required=classification_policy.write_required,
            diagnostic_request=diagnostic_request,
            raw_write_signal=raw_write_signal,
            planner_policy=planner_policy,
            planner_reason=planner_reason,
            planner_backend=planner_backend,
            known_gap_name=known_gap_name,
            reason_codes=reason_codes,
        )

    def _effective_planner_classification(
        self, request: FileTaskRequest
    ) -> tuple[str, str, str]:
        return self._planner_classification(request)

    def _classification_task_text(
        self, request: FileTaskRequest, resume_control: Dict[str, Any]
    ) -> str:
        return _intent_adjudication_classification_task_text(
            request,
            resume_control,
        )

    def _request_with_task(
        self, request: FileTaskRequest, task_text: str
    ) -> FileTaskRequest:
        return _intent_adjudication_request_with_task(
            request,
            task_text,
        )

    def _build_execution_context(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        *,
        known_tool_gap: Optional[Dict[str, Any]] = None,
        classification: Optional[FileTaskClassification] = None,
        intent_plan: Optional[FileTaskIntentPlan] = None,
        intent_adjudication: Optional[Dict[str, Any]] = None,
        quick_action_mode: str = "",
    ) -> FileTaskExecutionContext:
        resolved_known_tool_gap = (
            known_tool_gap if isinstance(known_tool_gap, dict) else None
        )
        resolved_classification = classification or self._classify_request(
            request, files, resolved_known_tool_gap
        )
        resolved_intent_plan = self._resolve_intent_plan(
            request,
            files,
            known_tool_gap=resolved_known_tool_gap,
            classification=resolved_classification,
            intent_plan=intent_plan,
        )
        requirements = build_file_task_requirements(request, resolved_classification)
        plan_check = validate_file_task_plan(
            requirements, resolved_classification, resolved_intent_plan
        )
        (
            effective_planner_policy,
            effective_planner_reason,
            effective_planner_backend,
        ) = self._effective_planner_classification(request)
        resolved_quick_action_mode = (
            str(quick_action_mode or self._quick_action_mode(request)).strip().lower()
        )
        return FileTaskExecutionContext(
            classification=resolved_classification,
            intent_plan=resolved_intent_plan,
            requirements=requirements,
            plan_check=plan_check,
            known_tool_gap=resolved_known_tool_gap,
            intent_adjudication=dict(intent_adjudication or {}),
            effective_planner_policy=effective_planner_policy,
            effective_planner_reason=effective_planner_reason,
            effective_planner_backend=effective_planner_backend,
            quick_action_mode=resolved_quick_action_mode,
            simple_quick_action=resolved_quick_action_mode == "simple",
        )

    def _constraint_audit(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
        intent_plan: FileTaskIntentPlan,
        requirements: FileTaskRequirementSet,
        recipe_skeleton: Dict[str, Any],
    ) -> Dict[str, Any]:
        from app.core.agent.file_task_preflight_policy import (
            build_preflight_constraint_audit,
        )

        return build_preflight_constraint_audit(
            request=request,
            files=files,
            classification=classification,
            intent_plan=intent_plan,
            requirements=requirements,
            recipe_skeleton=recipe_skeleton,
        )

    def _planner_classification(self, request: FileTaskRequest) -> tuple[str, str, str]:
        return "native_only", "file_task_native_only", "native"

    def _sanitize_planner_options(self, options: Dict[str, Any]) -> Dict[str, Any]:
        return {
            str(key): value
            for key, value in dict(options or {}).items()
            if "planner" not in str(key)
        }

    def _clone_request_with_options(
        self, request: FileTaskRequest, options: Dict[str, Any]
    ) -> FileTaskRequest:
        return FileTaskRequest(
            task=request.task,
            task_id=request.task_id,
            run_id=request.run_id,
            session_id=request.session_id,
            files=list(request.files),
            current_file=request.current_file,
            selection=request.selection,
            selection_source=request.selection_source,
            target_path=request.target_path,
            model_mode=request.model_mode,
            model_id=request.model_id,
            history=list(request.history),
            options=dict(options),
            routing_decision=request.routing_decision,
        )

    def _build_plan(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        write_intent: bool,
        output_mode: str,
        known_tool_gap: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        context_parts = []
        if files:
            context_parts.append(f"{len(files)} 个文件")
        if request.selection:
            context_parts.append("1 段选区")
        context_detail = "和".join(context_parts)
        steps = [
            {
                "id": "context",
                "title": "读取显式上下文",
                "description": (
                    f"读取 {context_detail}，并保留来源引用。"
                    if context_detail
                    else "检查是否有选区、附件或明确当前文件。"
                ),
            },
            {
                "id": "execute",
                "title": "执行任务",
                "description": self._execute_plan_description(
                    write_intent, output_mode, known_tool_gap
                ),
            },
            {
                "id": "check",
                "title": "核验结果",
                "description": "输出检查结论和剩余动作，避免静默失败。",
            },
        ]
        return steps

    def _resolve_intent_plan(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        *,
        known_tool_gap: Optional[Dict[str, Any]] = None,
        classification: Optional[FileTaskClassification] = None,
        intent_plan: Optional[FileTaskIntentPlan] = None,
    ) -> FileTaskIntentPlan:
        resolved_classification = classification or self._classify_request(
            request, files, known_tool_gap
        )
        if isinstance(intent_plan, FileTaskIntentPlan):
            planned = intent_plan
        else:
            try:
                planned = self._intent_planner.plan(
                    request,
                    files,
                    resolved_classification,
                    known_tool_gap=known_tool_gap,
                )
            except Exception as exc:
                logger.warning("[FileTaskRuntime] intent planner failed: %s", exc)
                planned = self._fallback_intent_plan(
                    request, files, resolved_classification, known_tool_gap
                )
            if not isinstance(planned, FileTaskIntentPlan):
                planned = self._fallback_intent_plan(
                    request, files, resolved_classification, known_tool_gap
                )

        planned.intent_type = (
            str(
                planned.intent_type or resolved_classification.task_family or "analyze"
            ).strip()
            or "analyze"
        )
        planned.output_mode = (
            str(resolved_classification.output_mode or planned.output_mode or "answer")
            .strip()
            .lower()
            or "answer"
        )
        planned.confidence = float(
            resolved_classification.confidence
            if resolved_classification.confidence is not None
            else planned.confidence or 0.0
        )
        planned.write_authorized = bool(resolved_classification.write_authorized)
        planned.write_required = bool(resolved_classification.write_required)
        if not str(planned.goal_statement or "").strip():
            planned.goal_statement = self._fallback_intent_goal_statement(
                request, resolved_classification, known_tool_gap
            )
        if not planned.dynamic_steps:
            planned.dynamic_steps = self._build_plan(
                request,
                files,
                resolved_classification.write_required,
                planned.output_mode,
                known_tool_gap,
            )
        if not planned.reason_codes:
            planned.reason_codes = [
                item for item in resolved_classification.reason_codes if item
            ]
        return planned

    def _fallback_intent_plan(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
        known_tool_gap: Optional[Dict[str, Any]] = None,
    ) -> FileTaskIntentPlan:
        output_mode = (
            str(classification.output_mode or "answer").strip().lower() or "answer"
        )
        requires_confirmation = (
            output_mode == "hybrid"
            and self._fallback_requires_explicit_confirmation(request)
        )
        recommended_strategy = self._fallback_intent_strategy(
            classification,
            output_mode,
            known_tool_gap,
            requires_confirmation=requires_confirmation,
        )
        can_apply = output_mode in {
            "write",
            "hybrid",
        } and self._fallback_intent_has_apply_target(request, files)
        reason_codes = [item for item in classification.reason_codes if item]
        reason_codes.extend(
            [
                "intent_plan:fallback",
                f"intent_type:{classification.task_family or 'analyze'}",
                f"strategy:{recommended_strategy}",
            ]
        )
        if can_apply:
            reason_codes.append("can_apply")
        if requires_confirmation:
            reason_codes.append("requires_confirmation")
        return FileTaskIntentPlan(
            intent_type=classification.task_family or "analyze",
            goal_statement=self._fallback_intent_goal_statement(
                request, classification, known_tool_gap
            ),
            output_mode=output_mode,
            confidence=float(classification.confidence or 0.0),
            write_authorized=bool(classification.write_authorized),
            write_required=bool(classification.write_required),
            can_apply=can_apply,
            requires_confirmation=requires_confirmation,
            recommended_strategy=recommended_strategy,
            dynamic_steps=self._build_plan(
                request,
                files,
                classification.write_required,
                output_mode,
                known_tool_gap,
            ),
            reason_codes=reason_codes,
        )

    def _fallback_intent_goal_statement(
        self,
        request: FileTaskRequest,
        classification: FileTaskClassification,
        known_tool_gap: Optional[Dict[str, Any]] = None,
    ) -> str:
        task_text = _preview(request.task, 180) or "当前文件任务"
        output_mode = (
            str(classification.output_mode or "answer").strip().lower() or "answer"
        )
        if known_tool_gap:
            return f"识别缺失原生能力并输出可落地工具设计：{task_text}"
        if classification.request_kind == "resume":
            return f"延续上一轮待确认的文件任务：{task_text}"
        if output_mode == "write":
            return f"完成真实文件修改并交付结果：{task_text}"
        if output_mode == "hybrid":
            if self._fallback_requires_explicit_confirmation(request):
                return f"先分析并整理可应用建议，再等待确认：{task_text}"
            return f"先分析并整理可应用建议，后续可按用户要求应用：{task_text}"
        return f"基于显式上下文给出结论或答复：{task_text}"

    def _fallback_intent_strategy(
        self,
        classification: FileTaskClassification,
        output_mode: str,
        known_tool_gap: Optional[Dict[str, Any]] = None,
        *,
        requires_confirmation: bool = False,
    ) -> str:
        if known_tool_gap:
            return "design_new_tool"
        if classification.request_kind == "resume":
            return "resume_previous_plan"
        if output_mode == "write":
            return "write_through"
        if output_mode == "hybrid":
            return (
                "analyze_then_confirm"
                if requires_confirmation
                else "analyze_then_optional_apply"
            )
        return "answer_only"

    def _fallback_requires_explicit_confirmation(
        self, request: FileTaskRequest
    ) -> bool:
        task_text = str(request.task or "").strip()
        if re.search(
            r"(?:确认后|等(?:我|用户)?确认|等待(?:我|用户)?确认|我确认后|用户确认后|"
            r"确认(?:了|完)?再|先.{0,24}(?:等|等待).{0,12}确认|"
            r"等(?:我|用户)?(?:说)?继续|回复继续|说继续|"
            r"wait for (?:my |user )?confirmation|confirm(?:ation)? before (?:apply|applying|write|writing))",
            task_text,
            re.IGNORECASE,
        ):
            return True
        options = request.options if isinstance(request.options, dict) else {}
        return bool(
            options.get("requires_confirmation") or options.get("confirm_before_apply")
        )

    def _fallback_intent_has_apply_target(
        self, request: FileTaskRequest, files: List[FileTaskFile]
    ) -> bool:
        if str(request.target_path or "").strip():
            return True
        if request.selection:
            return True
        return any(
            file_info.target or file_info.path or file_info.name for file_info in files
        )

    def _execute_plan_description(
        self,
        write_intent: bool,
        output_mode: str,
        known_tool_gap: Optional[Dict[str, Any]],
    ) -> str:
        if known_tool_gap:
            capability = str(
                known_tool_gap.get("missing_capability") or "缺失能力"
            ).strip()
            return f"当前任务触发 Koto 原生能力缺口：{capability}；模型需要产出 {TOOL_DESIGN_PROTOCOL} 工具规格，不调用未注册工具。"
        if write_intent:
            return "模型在 Koto allowlist 工具目录内规划并执行，写入后产生 file.changed 事件。"
        if output_mode == "hybrid":
            return "模型先读取文件并给出可应用的分析建议；当前轮不默认直接写入原文件。"
        return "模型可读取文件、调用分析工具并生成可审计答复。"

    def _output_mode_label(self, output_mode: str) -> str:
        return _execution_messaging_output_mode_label(output_mode)

    def _output_mode_guidance(self, classification: FileTaskClassification) -> str:
        return _execution_messaging_output_mode_guidance(classification)

    def _intent_plan_guidance(self, intent_plan: FileTaskIntentPlan) -> str:
        return _execution_messaging_intent_plan_guidance(intent_plan)
