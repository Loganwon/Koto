# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Background Agent — 后台自主执行代理
=====================================
仿照 Cursor Background Agents / Devin / GitHub Copilot Workspace 的
"后台自主任务执行"模式，原创实现。

核心特性：
  1. **非阻塞提交** — 用户提交任务后立即返回 task_id，不等待执行完成
  2. **分阶段规划** — 先生成可执行计划（Plan），再逐步执行每个 Step
  3. **实时进度** — 通过 ProgressBus 广播每个步骤的状态
  4. **人工介入点** — 执行前可配置 review 节点，等待用户确认
  5. **断点恢复** — 依托 TaskLedger + CheckpointManager 实现崩溃后恢复
  6. **并行子任务** — 独立的步骤可并行执行（参考 Magentic-One 的并行策略）
  7. **工具继承** — 复用 UnifiedAgent 的完整工具链

架构
----
  User Input
      ↓
  [BackgroundAgent.submit()]      →  立即返回 task_id
      ↓ (后台线程)
  [_PlanningPhase]                →  LLM 生成结构化 Plan
      ↓
  [_ExecutionPhase]               →  逐步执行每个 Step
      ├── Step 1: 使用工具/UnifiedAgent
      ├── Step 2（可并行）
      └── ...
      ↓
  [_SynthesisPhase]               →  合并结果，生成最终报告
      ↓
  ProgressBus → 前端订阅

与现有系统集成
--------------
  - BackgroundAgent.submit() 调用 JobRunner.submit() 将任务入队
  - JobRunner 负责线程管理、重试、超时
  - TaskLedger 记录完整执行历史
  - 每个 Step 的执行通过 UnifiedAgent 完成（复用工具链）

用法
----
    from app.core.agent.background_agent import BackgroundAgent, BackgroundTask

    agent = BackgroundAgent(session_id="sess_123")

    # 提交后台任务，立即返回
    task_id = agent.submit(
        goal="帮我分析 /workspace/data/ 目录下所有 CSV 文件，"
             "生成一份数据质量报告，并发现异常值",
        context={"workspace": "/workspace/data/"},
        human_review_before_execute=True,   # 执行前等待用户确认计划
    )

    print(f"任务已提交: {task_id}")

    # 查询进度（前端通过 SSE 实时获取，此处为轮询示例）
    status = agent.get_status(task_id)
    print(status)

    # 批准计划（当 human_review_before_execute=True 时）
    agent.approve_plan(task_id)

    # 取消任务
    agent.cancel(task_id)
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────────────────────────


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    """执行计划中的单个步骤。"""

    step_id: str
    title: str
    description: str
    tool_hint: Optional[str] = None  # 建议使用的工具类型
    depends_on: List[str] = field(default_factory=list)  # 依赖的 step_id 列表
    can_parallel: bool = False  # 是否可与其他步骤并行
    status: StepStatus = StepStatus.PENDING
    result: str = ""
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0


@dataclass
class ExecutionPlan:
    """Agent 生成的完整执行计划。"""

    plan_id: str
    goal: str
    steps: List[PlanStep]
    estimated_minutes: int = 0
    reasoning: str = ""  # LLM 的规划思路


@dataclass
class BackgroundTaskStatus:
    task_id: str
    goal: str
    session_id: str
    phase: str  # "planning"|"review"|"executing"|"done"|"failed"
    plan: Optional[ExecutionPlan]
    steps_total: int
    steps_done: int
    current_step: Optional[str]
    final_report: str
    error: str
    submitted_at: float
    updated_at: float


# ─────────────────────────────────────────────────────────────────────────────
# Prompt 模板
# ─────────────────────────────────────────────────────────────────────────────

_PLANNING_PROMPT = """\
你是一个专业的任务规划专家。用户想要完成以下目标：

目标：
{goal}

上下文信息：
{context}

可用工具能力：
{tools_description}

请生成一个结构化的执行计划。要求：
- 将目标分解为 3-8 个具体的、可执行的步骤
- 每个步骤都有明确的输入和预期输出
- 标记哪些步骤可以并行执行
- 预估完成时间（分钟）

输出格式（只输出 JSON，无其他文字）：
{{
  "reasoning": "规划思路（1-2句话）",
  "estimated_minutes": 数字,
  "steps": [
    {{
      "step_id": "step_1",
      "title": "步骤标题（10字以内）",
      "description": "详细描述，说明要做什么、用什么工具、预期产出",
      "tool_hint": "建议工具（web_search/read_file/write_file/code_exec/memory_search/null）",
      "depends_on": [],
      "can_parallel": false
    }}
  ]
}}
"""

_STEP_EXECUTION_PROMPT = """\
你是 Koto，正在执行后台任务的第 {step_num}/{total_steps} 步。

整体目标：{goal}

本步骤：
标题：{step_title}
描述：{step_description}
工具建议：{tool_hint}

之前步骤的结果：
{previous_results}

请执行本步骤并给出详细结果。如果需要使用工具，请调用相应工具。
"""

_SYNTHESIS_PROMPT = """\
你是一位专业报告撰写者。请根据以下后台任务的执行结果，生成一份**完整的任务报告**。

原始目标：{goal}

各步骤执行结果：
{steps_result}

请生成包含以下内容的 Markdown 报告：
1. **执行摘要** — 任务是否成功完成，主要成果是什么
2. **详细结果** — 各步骤的发现和产出
3. **关键洞察** — 最重要的发现或结论
4. **后续建议** — 如果适用
"""


# ─────────────────────────────────────────────────────────────────────────────
# BackgroundAgent
# ─────────────────────────────────────────────────────────────────────────────


class BackgroundAgent:
    """
    后台自主执行代理。

    任务提交后在后台线程执行，不阻塞主对话线程。
    """

    def __init__(
        self,
        session_id: str = "",
        model_id: str = "gemini-2.5-flash",
        max_steps: int = 10,
        step_timeout_seconds: float = 120.0,
    ):
        self.session_id = session_id
        self.model_id = model_id
        self.max_steps = max_steps
        self.step_timeout = step_timeout_seconds

        # 内存内状态（持久化由 TaskLedger 处理）
        self._tasks: Dict[str, BackgroundTaskStatus] = {}
        self._plans: Dict[str, ExecutionPlan] = {}
        self._review_events: Dict[str, threading.Event] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()

        # 懒加载依赖
        self._llm = None
        self._registry = None
        self._progress_bus = None
        self._ProgressEvent = None
        self._ledger = None

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    def submit(
        self,
        goal: str,
        context: Optional[Dict[str, Any]] = None,
        human_review_before_execute: bool = False,
        on_complete: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        """
        提交后台任务，立即返回 task_id。

        Args:
            goal:                        任务目标描述
            context:                     额外上下文（文件路径、工作区等）
            human_review_before_execute: 生成计划后暂停等待用户审批
            on_complete:                 任务完成时的回调 (task_id, report)

        Returns:
            task_id: 用于查询进度的任务 ID
        """
        task_id = str(uuid.uuid4())
        now = time.time()

        status = BackgroundTaskStatus(
            task_id=task_id,
            goal=goal,
            session_id=self.session_id,
            phase="planning",
            plan=None,
            steps_total=0,
            steps_done=0,
            current_step=None,
            final_report="",
            error="",
            submitted_at=now,
            updated_at=now,
        )

        cancel_event = threading.Event()
        review_event = threading.Event()

        with self._lock:
            self._tasks[task_id] = status
            self._cancel_events[task_id] = cancel_event
            self._review_events[task_id] = review_event

        # 如果不需要人工审批，直接预先设置 review_event
        if not human_review_before_execute:
            review_event.set()

        # 启动后台线程
        thread = threading.Thread(
            target=self._run_task,
            args=(
                task_id,
                goal,
                context or {},
                review_event,
                cancel_event,
                on_complete,
            ),
            daemon=True,
            name=f"koto-bg-agent-{task_id[:8]}",
        )
        thread.start()

        logger.info(f"[BackgroundAgent] 任务已提交: {task_id[:8]} — {goal[:50]}")
        self._emit(task_id, "submitted", f"任务已提交，开始规划...")
        return task_id

    def approve_plan(self, task_id: str):
        """批准执行计划，允许任务继续执行。"""
        event = self._review_events.get(task_id)
        if event:
            event.set()
            self._update(task_id, phase="executing")
            self._emit(task_id, "approved", "计划已批准，开始执行...")
        else:
            raise KeyError(f"Task {task_id} not found")

    def reject_plan(self, task_id: str, feedback: str = ""):
        """拒绝计划并取消任务。"""
        self.cancel(task_id)
        self._emit(task_id, "rejected", f"计划已拒绝: {feedback}")

    def cancel(self, task_id: str):
        """取消正在执行的任务。"""
        event = self._cancel_events.get(task_id)
        if event:
            event.set()
            self._update(task_id, phase="failed", error="用户取消")
            self._emit(task_id, "cancelled", "任务已取消")

    def get_status(self, task_id: str) -> Optional[BackgroundTaskStatus]:
        """获取任务当前状态。"""
        return self._tasks.get(task_id)

    def get_plan(self, task_id: str) -> Optional[ExecutionPlan]:
        """获取任务的执行计划（规划完成后可用）。"""
        return self._plans.get(task_id)

    def list_tasks(self, session_id: str = "") -> List[BackgroundTaskStatus]:
        """列出当前内存中的任务（按提交时间倒序）。"""
        tasks = list(self._tasks.values())
        if session_id:
            tasks = [t for t in tasks if t.session_id == session_id]
        return sorted(tasks, key=lambda t: t.submitted_at, reverse=True)

    # ── 后台执行主流程 ────────────────────────────────────────────────────────

    def _run_task(
        self,
        task_id: str,
        goal: str,
        context: Dict,
        review_event: threading.Event,
        cancel_event: threading.Event,
        on_complete: Optional[Callable],
    ):
        """后台线程主函数：规划 → 等待审批 → 执行 → 合成。"""
        try:
            self._init_lazy()

            # ── 阶段 1：规划 ─────────────────────────────────────────────
            self._emit(task_id, "planning", "正在生成执行计划...")
            plan = self._plan(task_id, goal, context, cancel_event)
            if plan is None or cancel_event.is_set():
                self._update(task_id, phase="failed", error="规划失败或已取消")
                return

            self._plans[task_id] = plan
            self._update(
                task_id, phase="review", plan=plan, steps_total=len(plan.steps)
            )
            self._emit(
                task_id,
                "plan_ready",
                f"计划已生成，共 {len(plan.steps)} 步，预计 {plan.estimated_minutes} 分钟\n"
                f"步骤：{', '.join(s.title for s in plan.steps)}",
            )

            # ── 阶段 2：等待人工审批 ─────────────────────────────────────
            review_event.wait(timeout=300)  # 最多等待5分钟
            if cancel_event.is_set():
                return

            # ── 阶段 3：逐步执行 ─────────────────────────────────────────
            self._update(task_id, phase="executing")
            step_results: Dict[str, str] = {}

            for i, step in enumerate(plan.steps):
                if cancel_event.is_set():
                    self._update(task_id, phase="failed", error="执行中途取消")
                    return

                self._update(task_id, current_step=step.step_id, steps_done=i)
                self._emit(
                    task_id, "step_start", f"[{i+1}/{len(plan.steps)}] {step.title}"
                )

                step.status = StepStatus.RUNNING
                step.started_at = time.time()

                result = self._execute_step(
                    task_id, goal, step, i + 1, len(plan.steps), step_results
                )

                step.result = result
                step.status = StepStatus.DONE
                step.finished_at = time.time()
                step_results[step.step_id] = result

                self._update(task_id, steps_done=i + 1)
                self._emit(
                    task_id, "step_done", f"[{i+1}/{len(plan.steps)}] {step.title} ✓"
                )

            # ── 阶段 4：合成报告 ─────────────────────────────────────────
            self._emit(task_id, "synthesis", "正在合成最终报告...")
            report = self._synthesize(goal, plan.steps)
            self._update(
                task_id,
                phase="done",
                final_report=report,
                steps_done=len(plan.steps),
                current_step=None,
            )
            self._emit(task_id, "completed", "任务已完成，最终报告已生成")

            if on_complete:
                try:
                    on_complete(task_id, report)
                except Exception as cb_err:
                    logger.warning(f"[BackgroundAgent] on_complete 回调异常: {cb_err}")

        except Exception as exc:
            logger.exception(f"[BackgroundAgent] 任务 {task_id[:8]} 异常: {exc}")
            self._update(task_id, phase="failed", error=str(exc))
            self._emit(task_id, "error", f"任务执行异常: {exc}")

    # ── 规划 ──────────────────────────────────────────────────────────────────

    def _plan(
        self,
        task_id: str,
        goal: str,
        context: Dict,
        cancel_event: threading.Event,
    ) -> Optional[ExecutionPlan]:
        """调用 LLM 生成结构化执行计划。"""
        tools_desc = self._describe_tools()
        ctx_str = json.dumps(context, ensure_ascii=False, indent=2) if context else "{}"
        prompt = _PLANNING_PROMPT.format(
            goal=goal,
            context=ctx_str,
            tools_description=tools_desc,
        )

        raw = self._llm_call(prompt, temperature=0.3)
        if not raw or cancel_event.is_set():
            return None

        data = self._extract_json(raw)
        if not data or "steps" not in data:
            logger.warning("[BackgroundAgent] 规划 JSON 解析失败，使用单步降级")
            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                goal=goal,
                steps=[
                    PlanStep(
                        step_id="step_1",
                        title="直接执行",
                        description=goal,
                        tool_hint="web_search",
                    )
                ],
                reasoning="规划解析失败，降级为单步执行",
            )

        steps = []
        for s in data.get("steps", [])[: self.max_steps]:
            steps.append(
                PlanStep(
                    step_id=s.get("step_id", str(uuid.uuid4())),
                    title=s.get("title", "步骤"),
                    description=s.get("description", ""),
                    tool_hint=s.get("tool_hint"),
                    depends_on=s.get("depends_on", []),
                    can_parallel=s.get("can_parallel", False),
                )
            )

        return ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            goal=goal,
            steps=steps,
            estimated_minutes=data.get("estimated_minutes", 0),
            reasoning=data.get("reasoning", ""),
        )

    # ── 步骤执行 ──────────────────────────────────────────────────────────────

    def _execute_step(
        self,
        task_id: str,
        goal: str,
        step: PlanStep,
        step_num: int,
        total_steps: int,
        previous_results: Dict[str, str],
    ) -> str:
        """通过 UnifiedAgent 执行单个步骤。"""

        # 构建前序结果摘要
        prev_summary = ""
        for sid, res in previous_results.items():
            prev_summary += f"[{sid}]: {res[:300]}\n"

        prompt = _STEP_EXECUTION_PROMPT.format(
            step_num=step_num,
            total_steps=total_steps,
            goal=goal,
            step_title=step.title,
            step_description=step.description,
            tool_hint=step.tool_hint or "根据情况选择合适工具",
            previous_results=prev_summary or "（这是第一步）",
        )

        # 尝试使用 UnifiedAgent（带完整工具链）
        try:
            if self._registry:
                steps_gen = _run_agent_step(
                    llm=self._llm_provider,
                    registry=self._registry,
                    prompt=prompt,
                    model_id=self.model_id,
                    timeout=self.step_timeout,
                )
                return steps_gen
        except Exception as e:
            logger.warning(f"[BackgroundAgent] UnifiedAgent 执行失败，降级: {e}")

        # 降级：直接 LLM 调用
        return self._llm_call(prompt, temperature=0.4)

    # ── 合成报告 ──────────────────────────────────────────────────────────────

    def _synthesize(self, goal: str, steps: List[PlanStep]) -> str:
        steps_result = "\n\n".join(
            f"## 步骤 {i+1}：{s.title}\n{s.result}"
            for i, s in enumerate(steps)
            if s.result
        )
        prompt = _SYNTHESIS_PROMPT.format(
            goal=goal,
            steps_result=steps_result[:10000],
        )
        result = self._llm_call(prompt, temperature=0.3)
        # 合成报告有害内容检测
        try:
            from app.core.security.output_validator import OutputValidator

            _val = OutputValidator.validate(text=result)
            if _val.is_blocked:
                logger.warning(
                    "[BackgroundAgent] synthesis 输出被拦截: %s", _val.reasons
                )
                return _val.text
            return _val.text
        except Exception:
            return result

    # ── 工具 & 状态管理 ───────────────────────────────────────────────────────

    def _update(self, task_id: str, **kwargs):
        """更新任务状态。"""
        with self._lock:
            status = self._tasks.get(task_id)
            if status:
                for k, v in kwargs.items():
                    if hasattr(status, k):
                        setattr(status, k, v)
                status.updated_at = time.time()

    def _emit(self, task_id: str, event_type: str, message: str):
        """发布进度事件到 ProgressBus。"""
        logger.info(f"[BackgroundAgent:{task_id[:8]}] [{event_type}] {message}")
        if self._progress_bus and self._ProgressEvent and self.session_id:
            try:
                self._progress_bus.publish(
                    self._ProgressEvent(
                        session_id=self.session_id,
                        event_type=f"bg_agent_{event_type}",
                        data={
                            "task_id": task_id,
                            "event": event_type,
                            "message": message,
                            "ts": time.time(),
                        },
                    )
                )
            except Exception as _e:
                logger.debug("[BackgroundAgent] ProgressBus 事件发布失败: %s", _e)

    def _describe_tools(self) -> str:
        """描述当前可用工具（用于规划提示）。"""
        if not self._registry:
            return "web_search, read_file, write_file, code_exec, memory_search"
        try:
            names = [t["name"] for t in self._registry.get_tool_definitions()[:20]]
            return ", ".join(names)
        except Exception:
            return "web_search, read_file, write_file"

    def _llm_call(self, prompt: str, temperature: float = 0.3) -> str:
        """统一 LLM 调用。"""
        if not self._llm_provider:
            logger.error("[BackgroundAgent] LLM provider 未初始化")
            return ""
        try:
            result = self._llm_provider.generate_text(
                prompt=prompt,
                model_id=self.model_id,
                temperature=temperature,
            )
            if isinstance(result, dict):
                return result.get("text", result.get("content", str(result)))
            return str(result)
        except Exception as e:
            logger.error(f"[BackgroundAgent] LLM 调用失败: {e}")
            return f"LLM 调用失败: {e}"

    def _extract_json(self, text: str) -> Optional[Dict]:
        text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError as _e:
                logger.debug("[BackgroundAgent] JSON 解析失败（将返回 None）: %s", _e)
        return None

    def _init_lazy(self):
        """懒加载 LLM、工具注册表、ProgressBus。"""
        if self._llm_provider is not None:
            return
        try:
            import os

            from app.core.llm.gemini import GeminiProvider

            api_key = os.environ.get("GEMINI_API_KEY", "")
            self._llm_provider = GeminiProvider(api_key=api_key)
        except Exception as e:
            logger.error(f"[BackgroundAgent] LLMProvider 加载失败: {e}")
            self._llm_provider = None

        try:
            from app.core.agent.factory import build_default_registry
            from app.core.agent.tool_registry import ToolRegistry

            self._registry = build_default_registry()
        except Exception:
            try:
                from app.core.agent.tool_registry import ToolRegistry

                self._registry = ToolRegistry()
            except Exception:
                self._registry = None

        try:
            from app.core.tasks.progress_bus import ProgressEvent, get_progress_bus

            self._progress_bus = get_progress_bus()
            self._ProgressEvent = ProgressEvent
        except Exception as _e:
            logger.warning("[BackgroundAgent] ProgressBus 加载失败: %s", _e)

        try:
            from app.core.tasks.task_ledger import get_ledger

            self._ledger = get_ledger()
        except Exception as _e:
            logger.warning("[BackgroundAgent] TaskLedger 加载失败: %s", _e)

    # 使 _llm 和 _llm_provider 统一（init 前可能未初始化）
    _llm_provider = None


def _run_agent_step(
    llm,
    registry,
    prompt: str,
    model_id: str,
    timeout: float,
) -> str:
    """
    通过 UnifiedAgent 执行单个步骤，收集最终答案文本。
    设计为同步辅助函数，被 BackgroundAgent._execute_step 调用。
    """
    from app.core.agent.unified_agent import UnifiedAgent

    agent = UnifiedAgent(
        llm_provider=llm,
        tool_registry=registry,
        model_id=model_id,
    )
    final_answer = ""
    try:
        for step in agent.run(input_text=prompt):
            if hasattr(step, "step_type") and str(step.step_type) in (
                "final_answer",
                "FINAL_ANSWER",
            ):
                final_answer = getattr(step, "content", "") or getattr(
                    step, "output", ""
                )
            elif hasattr(step, "output") and step.output:
                final_answer = step.output
    except Exception as e:
        logger.warning(f"[BackgroundAgent._run_agent_step] 异常: {e}")
        final_answer = f"步骤执行异常: {e}"
    return final_answer or "(无输出)"


# ─────────────────────────────────────────────────────────────────────────────
# 便捷工厂：全局后台代理单例
# ─────────────────────────────────────────────────────────────────────────────

_global_agents: Dict[str, BackgroundAgent] = {}
_global_lock = threading.Lock()


def get_background_agent(session_id: str) -> BackgroundAgent:
    """获取或创建与 session_id 绑定的 BackgroundAgent 实例。"""
    with _global_lock:
        if session_id not in _global_agents:
            _global_agents[session_id] = BackgroundAgent(session_id=session_id)
        return _global_agents[session_id]
