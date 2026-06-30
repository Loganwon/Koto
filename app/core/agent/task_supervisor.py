# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class SupervisionResult:
    passed: bool
    stage: str
    score: float = 0.0
    report: str = ""
    issues: list[str] = field(default_factory=list)
    fix_suggestions: list[str] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0


@dataclass
class StepTrace:
    step_id: str
    tool: str
    status: str
    duration_ms: float
    summary: str
    error: str = ""


class TaskSupervisor:
    def __init__(self, llm_call: Callable[..., Any] | None = None) -> None:
        self.llm_call = llm_call

    def _check_integrity(
        self,
        plan: dict[str, Any],
        results: list[dict[str, Any]],
    ) -> SupervisionResult:
        issues: list[str] = []
        for index, step in enumerate(plan.get("steps") or []):
            step_id = step.get("id") or step.get("step_id") or f"step_{index}"
            result = next(
                (item for item in results if item.get("step_id") == step_id),
                None,
            )
            if not result:
                issues.append(f"Step {step_id}: missing")
                continue
            status = str(result.get("status", "")).lower()
            if status not in {"completed", "done", "success"}:
                issues.append(f"Step {step_id}: {result.get('status', '?')}")

        passed = not issues
        score = 1.0 if passed else max(0.0, 1.0 - len(issues) * 0.2)
        return SupervisionResult(
            passed=passed,
            stage="integrity",
            score=score,
            issues=issues,
        )

    def verify(
        self,
        plan: dict[str, Any],
        step_results: list[dict[str, Any]],
        completion_criteria: dict[str, Any] | None = None,
        output_text: str = "",
    ) -> SupervisionResult:
        started_at = time.time()
        integrity_result = self._check_integrity(plan, step_results)
        integrity_result.trace = {
            "completion_criteria": completion_criteria or {},
            "output_text_length": len(output_text or ""),
        }
        integrity_result.elapsed_ms = (time.time() - started_at) * 1000
        if not integrity_result.passed:
            return integrity_result
        integrity_result.stage = "delivery"
        integrity_result.report = "Passed integrity. Quality check needs LLM provider."
        return integrity_result
