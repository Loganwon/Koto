from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
)
from app.core.agent.file_task_recipes import select_task_recipe


def _preview(value: Any, limit: int = 180) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


_EXPLICIT_CONFIRMATION_PATTERN = re.compile(
    r"(?:确认后|等(?:我|用户)?确认|等待(?:我|用户)?确认|我确认后|用户确认后|"
    r"确认(?:了|完)?再|先.{0,24}(?:等|等待).{0,12}确认|"
    r"等(?:我|用户)?(?:说)?继续|回复继续|说继续|"
    r"wait for (?:my |user )?confirmation|confirm(?:ation)? before (?:apply|applying|write|writing))",
    re.IGNORECASE,
)


def _requires_explicit_confirmation(request: FileTaskRequest) -> bool:
    task_text = str(request.task or "").strip()
    if _EXPLICIT_CONFIRMATION_PATTERN.search(task_text):
        return True
    options = request.options if isinstance(request.options, dict) else {}
    return bool(
        options.get("requires_confirmation") or options.get("confirm_before_apply")
    )


class FileTaskIntentPlanner:
    def plan(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
        *,
        known_tool_gap: Optional[Dict[str, Any]] = None,
    ) -> FileTaskIntentPlan:
        output_mode = (
            str(classification.output_mode or "answer").strip().lower() or "answer"
        )
        recipe_match = select_task_recipe(
            request, files, write_intent=bool(classification.write_intent)
        )
        requires_confirmation = (
            output_mode == "hybrid" and _requires_explicit_confirmation(request)
        )
        recommended_strategy = self._recommended_strategy(
            classification,
            output_mode,
            known_tool_gap,
            requires_confirmation=requires_confirmation,
        )
        can_apply = output_mode in {"write", "hybrid"} and self._has_apply_target(
            request, files
        )
        reason_codes = [item for item in classification.reason_codes if item]
        reason_codes.extend(
            [
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
            goal_statement=self._goal_statement(
                request, classification, output_mode, known_tool_gap
            ),
            output_mode=output_mode,
            confidence=float(classification.confidence or 0.0),
            write_intent=bool(classification.write_intent),
            can_apply=can_apply,
            requires_confirmation=requires_confirmation,
            recommended_strategy=recommended_strategy,
            dynamic_steps=self._dynamic_steps(
                request,
                files,
                write_intent=bool(classification.write_intent),
                output_mode=output_mode,
                known_tool_gap=known_tool_gap,
                recipe_match=recipe_match,
            ),
            reason_codes=reason_codes,
        )

    def _goal_statement(
        self,
        request: FileTaskRequest,
        classification: FileTaskClassification,
        output_mode: str,
        known_tool_gap: Optional[Dict[str, Any]],
    ) -> str:
        task_text = _preview(request.task, 180) or "当前文件任务"
        if known_tool_gap:
            return f"识别缺失原生能力并输出可落地工具设计：{task_text}"
        if classification.request_kind == "resume":
            return f"延续上一轮待确认的文件任务：{task_text}"
        if classification.diagnostic_request:
            return f"解释上一轮结果或失败原因，并给出下一步建议：{task_text}"
        if output_mode == "write":
            return f"完成真实文件修改并交付结果：{task_text}"
        if output_mode == "hybrid":
            if _requires_explicit_confirmation(request):
                return f"先分析并整理可应用建议，再等待确认：{task_text}"
            return f"先分析并整理可应用建议，后续可按用户要求应用：{task_text}"
        return f"基于显式上下文给出结论或答复：{task_text}"

    def _recommended_strategy(
        self,
        classification: FileTaskClassification,
        output_mode: str,
        known_tool_gap: Optional[Dict[str, Any]],
        *,
        requires_confirmation: bool = False,
    ) -> str:
        if known_tool_gap:
            return "design_new_tool"
        if classification.request_kind == "resume":
            return "resume_previous_plan"
        if classification.diagnostic_request:
            return "diagnose_then_answer"
        if output_mode == "write":
            return "write_through"
        if output_mode == "hybrid":
            return (
                "analyze_then_confirm"
                if requires_confirmation
                else "analyze_then_optional_apply"
            )
        return "answer_only"

    def _has_apply_target(
        self, request: FileTaskRequest, files: List[FileTaskFile]
    ) -> bool:
        if str(request.target_path or "").strip():
            return True
        for file_info in files:
            if file_info.target:
                return True
            path = str(file_info.path or file_info.name or "").strip()
            if path and Path(path).suffix:
                return True
        return bool(request.selection)

    def _dynamic_steps(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        *,
        write_intent: bool,
        output_mode: str,
        known_tool_gap: Optional[Dict[str, Any]],
        recipe_match: Any = None,
    ) -> List[Dict[str, Any]]:
        if (
            recipe_match
            and getattr(recipe_match, "recipe", None)
            and recipe_match.recipe.plan_steps
        ):
            return [dict(step) for step in recipe_match.recipe.plan_steps]
        context_parts: List[str] = []
        if files:
            context_parts.append(f"{len(files)} 个文件")
        if request.selection:
            context_parts.append("1 段选区")
        context_detail = "和".join(context_parts)
        return [
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
                "description": self._execute_step_description(
                    write_intent, output_mode, known_tool_gap
                ),
            },
            {
                "id": "check",
                "title": "核验结果",
                "description": "输出检查结论和剩余动作，避免静默失败。",
            },
        ]

    def _execute_step_description(
        self,
        write_intent: bool,
        output_mode: str,
        known_tool_gap: Optional[Dict[str, Any]],
    ) -> str:
        if known_tool_gap:
            capability = str(
                known_tool_gap.get("missing_capability") or "缺失能力"
            ).strip()
            return f"当前任务触发 Koto 原生能力缺口：{capability}；模型需要产出 tool_design_v1 工具规格，不调用未注册工具。"
        if write_intent:
            return "模型在 Koto allowlist 工具目录内规划并执行，写入后产生 file.changed 事件。"
        if output_mode == "hybrid":
            return "模型先读取文件并给出可应用的分析建议；当前轮不默认直接写入原文件。"
        return "模型可读取文件、调用分析工具并生成可审计答复。"
