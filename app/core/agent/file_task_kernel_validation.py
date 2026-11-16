"""Final-answer evidence policy for file tasks running in the Agent Kernel."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from app.core.agent.file_task_completion_gates import source_coverage_guard_message
from app.core.agent.file_task_evidence_policy import requires_readonly_source_coverage
from app.core.agent.file_task_evidence_validation import (
    missing_readonly_source_coverage,
)
from app.core.agent.kernel import AgentRequest, ValidationOutcome


class FileTaskKernelValidator:
    """Reject final answers that do not yet satisfy observable task evidence."""

    def __init__(
        self,
        *,
        task: str,
        files: Sequence[Any],
        readonly_tool_outputs: List[Dict[str, Any]],
        write_required: bool,
        file_changes: List[Dict[str, Any]] | None = None,
        write_tool_names: Sequence[str] = (),
        mutation_failures: List[Dict[str, Any]] | None = None,
    ) -> None:
        self._task = str(task or "")
        self._files = list(files or [])
        self._outputs = readonly_tool_outputs
        self._write_required = bool(write_required)
        self._file_changes = file_changes if file_changes is not None else []
        self._write_tool_names = tuple(
            dict.fromkeys(
                str(name).strip() for name in write_tool_names if str(name).strip()
            )
        )
        self.last_instruction = ""
        self._mutation_failures = (
            mutation_failures if mutation_failures is not None else []
        )

    def validate(self, content: str, request: AgentRequest) -> ValidationOutcome:
        self.last_instruction = ""
        if self._mutation_failures:
            if any(item.get("policy_denied") for item in self._mutation_failures):
                self.last_instruction = (
                    "文件写入被当前授权范围阻止。已执行操作保留，受阻操作尚未完成。"
                )
                return ValidationOutcome.block(
                    self.last_instruction, reasons=("mutation_policy_denied",)
                )
            self.last_instruction = (
                "文件写入失败，尚未观察到同一目标的成功提交。"
                "请修正实际失败原因后完成写入，不能仅回复已经完成。"
            )
            return ValidationOutcome.retry(
                content, self.last_instruction, reasons=("mutation_not_committed",)
            )
        if self._write_required:
            if self._file_changes:
                return ValidationOutcome.accept(content)
            tools = "、".join(self._write_tool_names)
            instruction = (
                "当前任务明确要求写入文件，但尚未观察到任何 file.changed。"
                "不要只回复已完成；请继续调用可产生真实文件变更的工具"
                f"（{tools}）。"
                if tools
                else "当前任务明确要求写入文件，但尚未观察到任何 file.changed。"
                "不要只回复已完成；请继续调用可产生真实文件变更的工具。"
            )
            self.last_instruction = instruction
            return ValidationOutcome.retry(
                content,
                instruction,
                reasons=("write_evidence_missing",),
            )

        missing: List[str] = []
        instruction = ""
        reason = ""
        if requires_readonly_source_coverage(self._task, self._files):
            missing = missing_readonly_source_coverage(self._files, self._outputs)
            if missing:
                reason = "readonly_source_coverage_missing"
                instruction = source_coverage_guard_message(
                    task=self._task, missing=missing
                )

        if not instruction:
            return ValidationOutcome.accept(content)
        self.last_instruction = instruction
        return ValidationOutcome.retry(
            content,
            instruction,
            reasons=(reason, *tuple(missing)),
        )


__all__ = ["FileTaskKernelValidator"]
