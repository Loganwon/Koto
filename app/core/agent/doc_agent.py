# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
DocAgent — OpenClaw-style Document AI Agent
============================================

A unified agent for document processing tasks that follows the
plan → execute → verify loop. Integrates TaskPlanner's DAG framework
with streaming execution and real-time change tracking.

Features:
  - LLM-driven task planning with multi-file context
  - Step-by-step execution with progress streaming
  - File change tracking for frontend highlighting
  - Dynamic replanning on errors or discoveries
  - Task completion verification by model
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional, Set

logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================


class DocEventType(str, Enum):
    """Event types emitted by DocAgent during execution."""
    PLAN_START = "plan_start"
    PLAN_CREATED = "plan_created"
    STEP_START = "step_start"
    STEP_PROGRESS = "step_progress"
    STEP_DONE = "step_done"
    STEP_ERROR = "step_error"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FILE_CHANGE = "file_change"
    HIGHLIGHT = "highlight"
    USER_CONFIRM = "user_confirm"
    REPLAN = "replan"
    THOUGHT = "thought"
    STREAM_CHUNK = "stream_chunk"
    VERIFICATION = "verification"
    TASK_COMPLETE = "task_complete"
    ERROR = "error"


@dataclass
class FileHandle:
    """Reference to a file being processed."""
    path: str
    file_type: str = ""              # docx/xlsx/pptx/pdf/txt
    content_snapshot: str = ""       # Current content for diff comparison
    selection: Optional[str] = None  # User-selected text
    cursor_position: int = 0

    def __post_init__(self):
        if not self.file_type and self.path:
            self.file_type = Path(self.path).suffix.lstrip(".").lower()

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if self.file_type:
            data.setdefault("type", self.file_type)
        return data


@dataclass
class FileChange:
    """Represents a change made to a file."""
    file_path: str
    change_type: str           # add/modify/delete
    range_start: int           # Character offset start
    range_end: int             # Character offset end
    original: str              # Original content
    modified: str              # New content
    timestamp: float = field(default_factory=time.time)
    step_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "change_type": self.change_type,
            "range": [self.range_start, self.range_end],
            "original": self.original[:500],  # Truncate for transport
            "modified": self.modified[:500],
            "timestamp": self.timestamp,
            "step_id": self.step_id,
        }


@dataclass
class DocTask:
    """A document processing task."""
    id: str
    prompt: str
    files: List[FileHandle] = field(default_factory=list)
    permissions: Set[str] = field(default_factory=lambda: {"read", "write"})
    session_id: str = ""
    history: List[Dict[str, Any]] = field(default_factory=list)
    options: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:8]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "files": [f.to_dict() for f in self.files],
            "permissions": list(self.permissions),
            "session_id": self.session_id,
        }


@dataclass
class DocEvent:
    """Event emitted by DocAgent during execution."""
    event_type: DocEventType
    task_id: str = ""
    step_id: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.event_type.value,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "data": self.data,
            "timestamp": self.timestamp,
        }


# ============================================================================
# DocAgent
# ============================================================================

# Execution limits
MAX_STEPS = 20
MAX_TOOL_CALLS_PER_STEP = 10
MAX_CONSECUTIVE_ERRORS = 3


class DocAgent:
    """
    OpenClaw-style Document AI Agent.

    Orchestrates document processing tasks through:
    1. Planning: LLM generates a step-by-step execution plan
    2. Execution: Steps are executed with tool calls, tracking changes
    3. Verification: LLM verifies task completion

    Events are emitted throughout for frontend streaming.
    """

    def __init__(
        self,
        emitter: Optional["DocEventEmitter"] = None,
        model_id: str = "gemini-3.1-pro-preview",
        api_key: Optional[str] = None,
    ):
        self._emitter = emitter
        self._model_id = model_id
        self._api_key = api_key
        self._provider_mode = "cloud"
        self._change_log: List[FileChange] = []
        self._cancelled = False

    def cancel(self):
        """Request cancellation of current execution."""
        self._cancelled = True

    # ── Main Entry Point ───────────────────────────────────────────────────

    def run(self, task: DocTask) -> Iterator[DocEvent]:
        """
        Execute a document task. Yields DocEvent objects.

        This is a synchronous generator for compatibility with
        Flask-SocketIO. For async contexts, use run_async().
        """
        self._cancelled = False
        self._change_log = []
        start_time = time.time()

        # Emit plan start
        yield DocEvent(
            DocEventType.PLAN_START,
            task_id=task.id,
            data={"prompt": task.prompt, "file_count": len(task.files)},
        )

        # Get LLM provider
        provider = self._get_provider(task.options)
        if not provider:
            yield DocEvent(
                DocEventType.ERROR,
                task_id=task.id,
                data={"message": "无法初始化 LLM 服务（请检查 API Key 配置）"},
            )
            return

        # Build tool registry
        registry = self._build_registry()
        tool_defs = registry.get_definitions()

        # Phase 1: Planning
        yield DocEvent(
            DocEventType.THOUGHT,
            task_id=task.id,
            data={"text": "正在分析任务并制定执行计划..."},
        )

        plan = self._create_plan(task, provider, tool_defs)

        yield DocEvent(
            DocEventType.PLAN_CREATED,
            task_id=task.id,
            data={
                "plan": plan.to_dict() if hasattr(plan, "to_dict") else {"steps": []},
                "estimated_steps": len(plan.steps) if hasattr(plan, "steps") else 1,
            },
        )

        # Phase 2: Execution
        yield from self._execute_plan(task, plan, registry, provider)

        # Phase 3: Verification
        if not self._cancelled:
            verification = self._verify_completion(task, provider)
            yield DocEvent(
                DocEventType.VERIFICATION,
                task_id=task.id,
                data=verification,
            )

        # Done
        elapsed = round(time.time() - start_time, 1)
        yield DocEvent(
            DocEventType.TASK_COMPLETE,
            task_id=task.id,
            data={
                "elapsed_seconds": elapsed,
                "changes_made": len(self._change_log),
                "summary": f"任务完成，耗时 {elapsed}s",
            },
        )

    async def run_async(self, task: DocTask) -> AsyncIterator[DocEvent]:
        """Async version of run() for async contexts."""
        for event in self.run(task):
            yield event
            await asyncio.sleep(0)  # Yield control

    # ── Planning ───────────────────────────────────────────────────────────

    def _create_plan(
        self,
        task: DocTask,
        provider: Any,
        tool_defs: List[Dict],
    ):
        """Create an execution plan using TaskPlanner."""
        try:
            from app.core.tasks.task_planner import TaskPlanner

            planner = TaskPlanner()

            # Extract tool names for planning
            tool_names = [t.get("name", "") for t in tool_defs if t.get("name")]

            # Build file context for planning
            file_context = self._build_file_context(task.files)

            # Combine prompt with file context
            full_prompt = task.prompt
            if file_context:
                full_prompt = f"{task.prompt}\n\n{file_context}"

            # Generate plan
            plan = planner.plan_with_llm(
                task_id=task.id,
                user_input=full_prompt,
                llm_provider=provider,
                model_id=self._model_id,
                available_tools=tool_names,
                session_context=self._build_history_context(task.history),
            )

            logger.info(
                "[DocAgent] Plan created: %d steps for task %s",
                len(plan.steps), task.id
            )
            return plan

        except Exception as e:
            logger.warning("[DocAgent] Planning failed, using direct execution: %s", e)
            # Fallback: create a simple single-step plan
            return self._create_direct_plan(task)

    def _create_direct_plan(self, task: DocTask):
        """Create a simple single-step plan when LLM planning fails."""
        from app.core.tasks.task_planner import Plan, PlanStep

        plan = Plan(task_id=task.id, original_request=task.prompt)
        plan.add_step(PlanStep(
            name="execute",
            description="直接执行用户请求",
            step_type="llm",
            executor_prompt=task.prompt,
        ))
        return plan

    # ── Execution ──────────────────────────────────────────────────────────

    def _execute_plan(
        self,
        task: DocTask,
        plan: Any,
        registry: Any,
        provider: Any,
    ) -> Iterator[DocEvent]:
        """Execute the plan step by step."""
        from app.core.tasks.task_planner import StepStatus

        consecutive_errors = 0

        for step in plan.steps:
            if self._cancelled:
                yield DocEvent(
                    DocEventType.ERROR,
                    task_id=task.id,
                    step_id=step.step_id if hasattr(step, "step_id") else "",
                    data={"message": "任务已取消"},
                )
                return

            step_id = getattr(step, "step_id", step.name if hasattr(step, "name") else str(uuid.uuid4())[:8])

            yield DocEvent(
                DocEventType.STEP_START,
                task_id=task.id,
                step_id=step_id,
                data={
                    "name": step.name if hasattr(step, "name") else "execute",
                    "description": step.description if hasattr(step, "description") else "",
                    "progress": 0,
                },
            )

            try:
                # Execute the step with tool calls
                yield from self._execute_step(task, step, registry, provider, step_id)

                step.status = StepStatus.COMPLETED
                consecutive_errors = 0

                yield DocEvent(
                    DocEventType.STEP_DONE,
                    task_id=task.id,
                    step_id=step_id,
                    data={
                        "name": step.name if hasattr(step, "name") else "execute",
                        "summary": f"步骤完成",
                        "progress": 100,
                    },
                )

            except Exception as e:
                consecutive_errors += 1
                logger.error("[DocAgent] Step failed: %s", e, exc_info=True)

                yield DocEvent(
                    DocEventType.STEP_ERROR,
                    task_id=task.id,
                    step_id=step_id,
                    data={"error": str(e)},
                )

                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    yield DocEvent(
                        DocEventType.ERROR,
                        task_id=task.id,
                        data={"message": f"连续 {consecutive_errors} 次错误，任务中止"},
                    )
                    return

    def _execute_step(
        self,
        task: DocTask,
        step: Any,
        registry: Any,
        provider: Any,
        step_id: str,
    ) -> Iterator[DocEvent]:
        """Execute a single step with LLM-driven tool calls."""
        # Build the execution prompt
        exec_prompt = getattr(step, "executor_prompt", "") or getattr(step, "description", "")
        if not exec_prompt:
            exec_prompt = task.prompt

        # Build system prompt
        system = self._build_system_prompt()

        # Build file context
        file_context = self._build_file_context(task.files)

        # Construct messages
        user_message = f"## 当前任务\n\n{exec_prompt}"
        if file_context:
            user_message += f"\n\n{file_context}"

        messages = [{"role": "user", "content": user_message}]

        # Get tool definitions
        tool_defs = registry.get_definitions()

        # LLM loop for this step
        tool_calls_count = 0

        while tool_calls_count < MAX_TOOL_CALLS_PER_STEP:
            if self._cancelled:
                return

            # Call LLM
            response = self._call_llm(provider, messages, system, tool_defs)

            content_text = response.get("content", "")
            tool_calls = response.get("tool_calls", [])

            # Emit thought
            if content_text:
                yield DocEvent(
                    DocEventType.THOUGHT,
                    task_id=task.id,
                    step_id=step_id,
                    data={"text": content_text},
                )

            # Append model response to messages
            model_msg: Dict[str, Any] = {"role": "model", "content": content_text or ""}
            if tool_calls:
                model_msg["tool_calls"] = tool_calls
            raw_parts = response.get("_raw_parts")
            if raw_parts:
                model_msg["parts"] = raw_parts
            messages.append(model_msg)

            # No tool calls means step is complete
            if not tool_calls:
                break

            # Execute tool calls
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})

                yield DocEvent(
                    DocEventType.TOOL_CALL,
                    task_id=task.id,
                    step_id=step_id,
                    data={"tool_name": tool_name, "tool_args": tool_args},
                )

                # Execute the tool
                try:
                    result = registry.execute(tool_name, tool_args)
                    result_str = str(result) if result is not None else "(no output)"

                    # Track file changes if applicable
                    change = self._detect_file_change(tool_name, tool_args, result_str)
                    if change:
                        change.step_id = step_id
                        self._change_log.append(change)
                        yield DocEvent(
                            DocEventType.FILE_CHANGE,
                            task_id=task.id,
                            step_id=step_id,
                            data=change.to_dict(),
                        )

                except Exception as e:
                    result_str = f"Error: {e}"
                    logger.warning("[DocAgent] Tool %s failed: %s", tool_name, e)

                yield DocEvent(
                    DocEventType.TOOL_RESULT,
                    task_id=task.id,
                    step_id=step_id,
                    data={
                        "tool_name": tool_name,
                        "result_preview": result_str[:500],
                    },
                )

                # Append function response
                messages.append({
                    "role": "function",
                    "name": tool_name,
                    "content": result_str[:4000],
                })

                tool_calls_count += 1

            # Update progress
            progress = min(90, int(tool_calls_count / MAX_TOOL_CALLS_PER_STEP * 100))
            yield DocEvent(
                DocEventType.STEP_PROGRESS,
                task_id=task.id,
                step_id=step_id,
                data={"progress": progress},
            )

    def _detect_file_change(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: str,
    ) -> Optional[FileChange]:
        """Detect if a tool call resulted in a file change."""
        write_tools = {
            "write_sheet_data",
            "create_file",
            "copy_file",
            "editor_live_update",
        }

        if tool_name not in write_tools:
            return None

        try:
            result_data = json.loads(result)
            if not result_data.get("success", False) and "error" in result_data:
                return None
        except (json.JSONDecodeError, TypeError):
            pass

        file_path = tool_args.get("path", tool_args.get("destination", ""))
        if not file_path:
            return None

        return FileChange(
            file_path=file_path,
            change_type="modify" if tool_name == "write_sheet_data" else "add",
            range_start=0,
            range_end=0,
            original="",
            modified=str(tool_args.get("updates", tool_args.get("content", "")))[:500],
        )

    # ── Verification ───────────────────────────────────────────────────────

    def _verify_completion(
        self,
        task: DocTask,
        provider: Any,
    ) -> Dict[str, Any]:
        """Ask the model to verify if the task was completed successfully."""
        prompt = f"""请验证以下任务是否已成功完成：

## 原始任务
{task.prompt}

## 执行的变更
{json.dumps([c.to_dict() for c in self._change_log], ensure_ascii=False, indent=2) if self._change_log else "无文件变更记录"}

## 请回答
1. 任务是否完成？(completed/partial/failed)
2. 简要说明完成情况

以 JSON 格式输出：{{"status": "completed|partial|failed", "summary": "说明"}}"""

        try:
            verify_model = self._local_model_id() if self._provider_mode == "local" else self._model_id
            response = provider.generate_content(
                prompt=[{"role": "user", "content": prompt}],
                model=verify_model or None,
                stream=False,
                call_timeout=30,
            )
            content = response.get("content", "")

            # Try to parse JSON
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])

            return {"status": "completed", "summary": content[:200]}

        except Exception as e:
            logger.warning("[DocAgent] Verification failed: %s", e)
            error_text = str(e)
            if "timed out" in error_text.lower():
                return {"status": "unknown", "summary": "结果已生成，状态检查超时，未影响本次执行结果"}
            return {"status": "unknown", "summary": "结果已生成，状态检查暂不可用"}

    # ── Helpers ────────────────────────────────────────────────────────────

    def _get_provider(self, options: Optional[Dict[str, Any]] = None):
        """Get LLM provider instance."""
        try:
            model_mode = str((options or {}).get("model_mode") or "").strip().lower()
            if model_mode == "local":
                from app.core.llm.ollama_llm_provider import OllamaLLMProvider

                self._provider_mode = "local"
                return OllamaLLMProvider(model=self._local_model_id() or None)

            from app.core.llm.gemini import GeminiProvider
            self._provider_mode = "cloud"

            api_key = self._api_key
            provider = GeminiProvider(api_key=api_key)
            if not provider.api_key:
                logger.error("[DocAgent] No API key available")
                return None
            return provider
        except Exception as e:
            logger.error("[DocAgent] Failed to init LLM provider: %s", e)
            return None

    def _build_registry(self):
        """Build a ToolRegistry with all document tools."""
        from app.core.agent.tool_registry import ToolRegistry
        from app.core.agent.task_tools import TaskToolsPlugin

        registry = ToolRegistry()
        registry.register_plugin(TaskToolsPlugin())
        return registry

    def _call_llm(
        self,
        provider: Any,
        messages: List[Dict],
        system: str,
        tool_defs: List[Dict],
    ) -> Dict[str, Any]:
        """Call the LLM with messages and tools."""
        if self._provider_mode == "local":
            return provider.generate_content(
                prompt=messages,
                model=self._local_model_id() or None,
                system_instruction=system,
                tools=tool_defs if tool_defs else None,
                stream=False,
            )

        try:
            from app.core.llm.model_fallback import get_fallback_executor
            executor = get_fallback_executor()
            return executor.generate_with_fallback(
                provider=provider,
                prompt=messages,
                preferred_model=self._model_id,
                task_type="FILE_TASK",
                system_instruction=system,
                tools=tool_defs if tool_defs else None,
                stream=False,
            )
        except ImportError:
            return provider.generate_content(
                prompt=messages,
                model=self._model_id,
                system_instruction=system,
                tools=tool_defs if tool_defs else None,
                stream=False,
            )

    def _local_model_id(self) -> str:
        target_model = str(self._model_id or "").strip()
        if target_model.lower() in {"", "local", "ollama", "auto"} or target_model.lower().startswith("gemini"):
            return ""
        return target_model

    def _build_system_prompt(self) -> str:
        """Build the system prompt for execution."""
        return """你是 Koto 文件任务助手。你正在执行一个分步任务。

## 规则
1. 在执行文件写入前，先读取目标文件确认当前状态
2. 工具调用失败时，分析错误原因，尝试修复后重试
3. 每一步给用户清晰的进展说明
4. 完成后简要汇报结果

## 可用工具
你可以使用各种文件读写工具来完成任务。"""

    def _build_file_context(self, files: List[FileHandle]) -> str:
        """Build file context string for LLM."""
        if not files:
            return ""

        parts = ["## 当前文件上下文\n"]
        for f in files:
            parts.append(f"### 文件: {Path(f.path).name}")
            parts.append(f"- 路径: {f.path}")
            parts.append(f"- 类型: {f.file_type}")
            if f.selection:
                parts.append(f"- 选中文本: {f.selection[:500]}")
            if f.content_snapshot:
                parts.append(f"- 内容预览:\n```\n{f.content_snapshot[:2000]}\n```")
            parts.append("")

        return "\n".join(parts)

    def _build_history_context(self, history: List[Dict]) -> str:
        """Build conversation history context."""
        if not history:
            return ""

        relevant = [
            m for m in history
            if m.get("role") in ("user", "model") and m.get("content")
        ][-8:]

        if not relevant:
            return ""

        return "\n".join(
            f"[{m['role']}] {str(m['content'])[:200]}"
            for m in relevant
        )


# ============================================================================
# Factory function
# ============================================================================


def create_doc_agent(
    emitter: Optional["DocEventEmitter"] = None,
    model_id: str = "gemini-3.1-pro-preview",
    api_key: Optional[str] = None,
) -> DocAgent:
    """Factory function to create a DocAgent instance."""
    return DocAgent(emitter=emitter, model_id=model_id, api_key=api_key)
