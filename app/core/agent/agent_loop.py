# ══════════════════════════════════════════════════════════════
# agent_loop.py — Koto Unified Agent Loop
#
# Inspired by OpenClaw's single-entry agent architecture.
# This module provides ONE entry point for all file-assistant
# AI requests:
#
#   KotoAgentLoop.run(request: AgentRequest) → Generator[AgentEvent]
#
# Internal flow:
#   1. Validate & classify request
#   2. Fire BEFORE_PROMPT_BUILD hooks (PII filter, memory, skill injection)
#   3. Resolve model (online → local fallback)
#   4. Execute (single-shot streaming OR ReAct tool loop)
#   5. Fire BEFORE_REPLY hooks (PII restore, output validation)
#   6. Parse tool calls from response
#   7. Fire AGENT_END hooks (metrics, cleanup)
#   8. Yield lifecycle_end event
#
# The loop itself is transport-agnostic: it yields AgentEvent
# objects. Callers (socket_handler, SSE endpoints) map events
# to their own wire format.
# ══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from app.core.agent.hooks import HookContext, HookPoint, HookRegistry, get_default_registry
from app.core.llm.model_mode import normalize_model_mode
from app.core.shared.tool_parser import parse_tool_calls, stringify_tool_result
from app.core.shared.llm_helpers import is_online_failure, is_ollama_alive, get_local_provider
from app.core.agent.request_validator import RequestValidator
from app.core.agent.tool_executor import ToolExecutor
from app.core.agent.response_formatter import ResponseFormatter
from app.core.agent.lifecycle import (
    AgentEvent,
    AgentRequest,
    EventType,
    RunMetadata,
    RunState,
    evt_code_result,
    evt_doc_tool_call,
    evt_error,
    evt_lifecycle_end,
    evt_lifecycle_error,
    evt_lifecycle_start,
    evt_phase,
    evt_proposal,
    evt_rag_info,
    evt_skill_suggestions,
    evt_plan,
    evt_step_done,
    evt_step_error,
    evt_step_progress,
    evt_step_start,
    evt_status_message,
    evt_stream_block,
    evt_stream_chunk,
    evt_task_complete,
    evt_live_doc_commit,
    evt_thought,
    evt_tool_call,
    evt_tool_result,
)

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

MAX_HISTORY_TURNS = 10
MAX_TASK_ROUNDS = 20
MAX_TASK_CONSECUTIVE_ERRORS = 3
_TASK_FILE_CONTEXT_PREVIEW_LIMIT = 8_000
_TASK_TOOL_RESULT_CONTEXT_LIMIT = 24_000
_KOTO_CREATED_MARKER = "__koto_created__:"


def _extract_koto_created_paths(result_str: str) -> List[str]:
    """Parse __koto_created__:[...] marker appended by run_python_in_sandbox."""
    idx = result_str.rfind(_KOTO_CREATED_MARKER)
    if idx == -1:
        return []
    try:
        return json.loads(result_str[idx + len(_KOTO_CREATED_MARKER):])
    except Exception:
        return []


def _sample_task_context_text(text: Any, limit: int) -> str:
    content = str(text or "")
    if len(content) <= limit:
        return content
    head = max(int(limit * 0.7), 1)
    tail = max(limit - head - 48, 0)
    marker = "\n\n...[中间内容已省略]...\n\n"
    if tail <= 0:
        return content[:limit]
    return content[:head] + marker + content[-tail:]


_TASK_SYSTEM_PROMPT = """你是 Koto 文件任务助手。用户会描述一个涉及文件操作的任务，你需要理解任务、制定计划、使用工具执行。

## 工作模式

1. 理解：分析用户任务和提供的文件上下文
2. 计划：制定清晰的分步执行计划
3. 执行：逐步调用工具完成任务
4. 交付：汇报结果

## 可用工具

你可以调用以下工具来完成任务：

文件读取：
- `read_sheet_data(path, sheet_name?, max_rows?)` — 读取 Excel 表格数据（结构化 JSON）
- `read_docx_content(path, max_chars?)` — 读取 Word 文档段落
- `parse_file_to_text(path, max_chars?, start_page?, end_page?)` — 将任意文件解析为纯文本；PDF 可按页窗口读取
- `list_workspace_files(path?, recursive?)` — 列出工作区文件

文件写入：
- `write_sheet_data(path, sheet_name?, updates)` — 写入 Excel 单元格（自动备份）
- `create_file(path, content)` — 创建新文件
- `copy_file(source, destination)` — 复制文件

AI 处理：
- `llm_extract(text, fields, instructions?)` — 从文本中提取结构化数据
- `llm_transform(text, instruction)` — 按指令转换文本

代码执行：
- `run_python_code(code, timeout?)` — 在沙盒中执行 Python 代码
- 当前任务文件会自动复制到沙盒当前目录，可直接按文件名访问；绝对路径见 `TASK_FILE_PATHS`

## 规则

1. 在执行文件写入操作前，先读取目标文件确认当前状态
2. `write_sheet_data` 的 `updates` 参数必须是 JSON 字符串格式
3. 对于复杂数据处理，优先使用 `run_python_code` 而非多次调用 `llm_extract`
4. 工具调用失败时，分析错误原因，尝试修复后重试（最多重试 2 次）
5. 每一步都给用户清晰的进展说明
6. 如果任务不明确，先用已有工具探索文件内容，再决定具体做法"""

# Insert-at-cursor trigger phrases (Chinese)
_INSERT_TRIGGERS = (
    "在光标处插入", "插入文档", "插入到文档", "请插入", "插入内容", "写入文档",
)


class KotoAgentLoop:
    """
    Unified agent loop for the Koto file assistant.

    Usage:
        loop = KotoAgentLoop()
        for event in loop.run(request):
            # map event to WS/SSE
            ...
    """

    def __init__(
        self,
        hook_registry: Optional[HookRegistry] = None,
        socketio=None,
    ) -> None:
        self._hooks = hook_registry or get_default_registry()
        self._socketio = socketio
        # Live-doc streaming state (reset per run)
        self._live_doc: bool = False
        self._live_mode: str = "replace"
        self._live_request_id: str = ""

    # ══════════════════════════════════════════════════════════════
    # Public entry point
    # ══════════════════════════════════════════════════════════════

    def run(self, request: AgentRequest) -> Generator[AgentEvent, None, None]:
        """
        Run the agent loop for a single request.
        Yields AgentEvent objects as the run progresses.
        """
        meta = RunMetadata(session_id=request.session_id)
        meta.start()
        # Capture live-doc flags for this run
        self._live_doc = getattr(request, 'live_doc', False)
        self._live_mode = getattr(request, 'live_mode', 'replace')
        self._live_request_id = meta.run_id
        yield evt_lifecycle_start(meta.run_id, meta.session_id)

        try:
            yield from self._run_inner(request, meta)
        except Exception as exc:
            logger.exception("[AgentLoop] Unhandled error: %s", exc)
            meta.finish(RunState.FAILED, str(exc))
            yield evt_lifecycle_error(meta.run_id, str(exc))
            yield evt_task_complete(error=f"内部错误：{exc}")
            return

        # Fire AGENT_END hooks
        end_ctx = HookContext(request=request, metadata={"run": meta})
        self._hooks.fire(HookPoint.AGENT_END, end_ctx)

        if not meta.state.is_terminal:
            meta.finish(RunState.SUCCEEDED)
        yield evt_lifecycle_end(meta.run_id, meta.state)

    # ══════════════════════════════════════════════════════════════
    # Inner run logic
    # ══════════════════════════════════════════════════════════════

    def _run_inner(
        self, request: AgentRequest, meta: RunMetadata
    ) -> Generator[AgentEvent, None, None]:
        if not request.prompt:
            yield evt_error("请输入内容")
            meta.finish(RunState.FAILED, "empty prompt")
            return

        # ── Phase 1: Analyse context ──────────────────────────────────
        phases = self._resolve_phases(request)
        phase_steps = [
            {
                "id": p.get("id") or f"step_{idx + 1}",
                "description": p.get("label") or p.get("id") or f"步骤 {idx + 1}",
            }
            for idx, p in enumerate(phases)
        ]
        if phase_steps:
            yield evt_plan(phase_steps)

        analyze_phase = phases[0] if phases else {"id": "understand", "label": "理解需求"}
        analyze_step_id = analyze_phase.get("id", "understand")

        yield evt_step_start(analyze_step_id, analyze_phase.get("label", "理解需求"))
        yield evt_phase(phases, analyze_step_id, "running")
        yield evt_step_progress(analyze_step_id, "正在分析上下文…")
        yield evt_status_message("正在分析上下文…")

        # ── RAG chunking for long documents ───────────────────────────
        prompt = request.prompt
        prompt = self._apply_rag_chunking(request, prompt)

        # ── Code execution mode (chart generation) ────────────────────
        if request.language in ("python", "r"):
            yield from self._run_code_mode(request, prompt, meta)
            return

        # ── Build system instruction ──────────────────────────────────
        system_instruction = self._build_system_instruction(request)

        # ── Fire BEFORE_PROMPT_BUILD hooks (PII, memory, skills) ──────
        hook_ctx = HookContext(
            messages=[],
            request=request,
            metadata={
                "system_instruction": system_instruction,
                "prompt": prompt,
                "history": request.history,
            },
        )
        self._hooks.fire(HookPoint.BEFORE_PROMPT_BUILD, hook_ctx)

        if hook_ctx.abort_reason:
            yield evt_error(hook_ctx.abort_reason)
            meta.finish(RunState.FAILED, hook_ctx.abort_reason)
            return

        # Apply hook mutations
        system_instruction = hook_ctx.metadata.get("system_instruction", system_instruction)
        prompt = hook_ctx.metadata.get("prompt", prompt)
        pipeline_skill_ids = hook_ctx.metadata.get("skill_ids", [])
        pipeline_mask_result = hook_ctx.metadata.get("mask_result")
        pipeline_force_local = hook_ctx.metadata.get("force_local", False)

        # ── Build full prompt with history ────────────────────────────
        full_prompt = self._assemble_prompt(request, prompt)

        # ── Resolve model ─────────────────────────────────────────────
        use_local = self._should_use_local(request, pipeline_force_local)
        model_name = self._pick_model(use_local, request)
        meta.model = model_name

        if request.action_type == "ai_task":
            yield from self._run_task_mode(
                request,
                prompt,
                system_instruction,
                use_local,
                meta,
                phases,
                pipeline_skill_ids,
                pipeline_mask_result,
            )
            return

        # ── Phase transition: generating ──────────────────────────────
        yield evt_step_done(analyze_step_id, f"{analyze_phase.get('label', '理解需求')}完成")
        yield evt_phase(phases, analyze_step_id, "done")
        gen_phase = phases[-1]["id"] if len(phases) <= 2 else phases[1]["id"]
        gen_label = next((p.get("label", gen_phase) for p in phases if p.get("id") == gen_phase), gen_phase)
        yield evt_step_start(gen_phase, gen_label)
        yield evt_phase(phases, gen_phase, "running")
        yield evt_step_progress(gen_phase, "正在生成回复…")
        yield evt_status_message("正在生成回复…")

        # ── Stream LLM response ───────────────────────────────────────
        result_text = yield from self._stream_llm(
            full_prompt, system_instruction, use_local, meta,
        )

        if result_text is None:
            meta.finish(RunState.FAILED, "LLM returned empty")
            yield evt_step_error(gen_phase, "未能生成有效回复")
            yield evt_task_complete(error=(
                "在线 AI 不可用，本地 Ollama 也未运行。\n"
                "请执行: ollama serve，或在 config/gemini_config.env 配置 API 密钥。"
            ))
            return

        yield evt_step_done(gen_phase, f"{gen_label}完成")

        # ── Fire BEFORE_REPLY hooks (PII restore, output validation) ──
        reply_ctx = HookContext(
            reply_text=result_text,
            request=request,
            metadata={
                "mask_result": pipeline_mask_result,
                "skill_ids": pipeline_skill_ids,
                "raw_prompt": request.prompt,
                "file_type": request.file_type,
            },
        )
        self._hooks.fire(HookPoint.BEFORE_REPLY, reply_ctx)

        if reply_ctx.abort_reason:
            yield evt_task_complete(result=reply_ctx.reply_text)
            meta.finish(RunState.SUCCEEDED)
            return

        result_text = reply_ctx.reply_text

        # Emit skill suggestions from hook
        suggestions = reply_ctx.metadata.get("suggestions", [])
        if suggestions:
            yield evt_skill_suggestions(suggestions)

        # If output was BLOCKED by validation
        if reply_ctx.metadata.get("validation_action") == "BLOCK":
            yield evt_task_complete(result=result_text)
            meta.finish(RunState.SUCCEEDED)
            return

        # ── Parse tool calls from response ────────────────────────────
        clean_text, tool_calls = _parse_tool_calls(result_text)

        # ── Insert-at-cursor fallback ─────────────────────────────────
        tool_calls = self._insert_fallback(request, tool_calls, clean_text)

        # ── Emit proposals or tool calls ──────────────────────────────
        has_proposals = False
        if request.output_mode != "chat":
            if request.selection and tool_calls:
                proposals = self._build_proposals(request.selection, tool_calls, clean_text)
                if proposals:
                    proposal_summary = proposals[0].get("rationale", "")
                    has_proposals = True
                    proposal_step_id = "prepare_proposals"
                    yield evt_step_start(proposal_step_id, "生成修改建议")
                    yield evt_step_progress(proposal_step_id, "正在准备修改建议…")
                    yield evt_status_message("正在准备修改建议…")
                    yield evt_proposal(proposals, proposal_summary)
                    yield evt_step_done(proposal_step_id, "修改建议已生成")
            else:
                doc_tool_step_open = False
                for tc in tool_calls:
                    if not doc_tool_step_open:
                        yield evt_step_start("prepare_doc_tool_calls", "生成文档变更指令")
                        doc_tool_step_open = True
                    yield evt_doc_tool_call(tc)
                if doc_tool_step_open:
                    yield evt_step_done("prepare_doc_tool_calls", "文档变更指令已生成")

        # ── Mark all phases done ──────────────────────────────────────
        for p in phases:
            yield evt_phase(phases, p["id"], "done")
        yield evt_status_message("")

        # ── Final result ──────────────────────────────────────────────
        # If streaming directly to document, emit commit event before task_complete
        if self._live_doc and clean_text and not has_proposals:
            yield evt_live_doc_commit(
                full_text=clean_text,
                live_mode=self._live_mode,
                original_selection=request.selection,
                request_id=self._live_request_id,
            )
        yield evt_task_complete(result=clean_text, has_proposals=has_proposals)
        meta.finish(RunState.SUCCEEDED)

    def _run_task_mode(
        self,
        request: AgentRequest,
        prompt: str,
        system_instruction: str,
        use_local: bool,
        meta: RunMetadata,
        phases: List[Dict[str, str]],
        pipeline_skill_ids: List[str],
        pipeline_mask_result: Any,
    ) -> Generator[AgentEvent, None, None]:
        """Execute provider-native task/tool rounds for ai_task requests."""
        analyze_phase = phases[0] if phases else {"id": "understand", "label": "理解需求"}
        analyze_step_id = analyze_phase.get("id", "understand")
        gen_phase = phases[-1]["id"] if len(phases) <= 2 else phases[1]["id"]
        gen_label = next((p.get("label", gen_phase) for p in phases if p.get("id") == gen_phase), gen_phase)

        yield evt_step_done(analyze_step_id, f"{analyze_phase.get('label', '理解需求')}完成")
        yield evt_phase(phases, analyze_step_id, "done")
        yield evt_step_start(gen_phase, gen_label)
        yield evt_phase(phases, gen_phase, "running")
        yield evt_step_progress(gen_phase, "正在规划并执行任务…")
        yield evt_status_message("正在规划并执行任务…")

        task_files = self._get_task_files(request)
        file_context = self._build_task_file_context(task_files)
        messages = self._build_task_messages(request, prompt, file_context)
        # Always build registry and tool_defs — OllamaLLMProvider supports native
        # tool calling for compatible models (qwen3, llama3.1+, mistral-nemo…)
        registry = self._build_task_registry(task_files)
        tool_defs = registry.get_definitions()

        rounds = 0
        consecutive_errors = 0
        active_use_local = use_local
        final_text = ""
        # Cross-round write dedup: tracks (tool_name, canonical_target_path) → success count
        completed_write_ops: Dict[str, int] = {}
        # Stage verification state
        file_states: List[Dict[str, Any]] = []
        _MODIFIER_TOOL_NAMES = {
            "write_sheet_data", "write_docx_content", "create_file",
            "copy_file", "extract_to_file", "insert_excel_as_docx_table",
        }
        _MAX_WRITE_OPS_PER_FILE = 3

        while rounds < MAX_TASK_ROUNDS:
            rounds += 1
            response: Optional[Dict[str, Any]] = None
            try:
                response = self._call_task_llm(
                    messages,
                    system_instruction,
                    tool_defs,
                    active_use_local,
                    request,
                )
            except Exception as exc:
                logger.warning("[AgentLoop] Task LLM call failed: %s", exc, exc_info=True)
                if not active_use_local and _is_online_failure(exc):
                    yield evt_status_message(
                        "⚠️ 云端 AI 暂时不可用，已自动切换到本地模型 (Ollama)，响应速度可能较慢。"
                    )
                    active_use_local = True
                    meta.model = self._pick_model(True, request)
                    try:
                        response = self._call_task_llm(
                            messages,
                            system_instruction,
                            tool_defs,
                            active_use_local,
                            request,
                        )
                    except Exception as local_exc:
                        logger.warning("[AgentLoop] Local task fallback failed: %s", local_exc, exc_info=True)
                        exc = local_exc
                        response = None

                if response is None:
                    consecutive_errors += 1
                    if consecutive_errors >= MAX_TASK_CONSECUTIVE_ERRORS:
                        yield evt_step_error(gen_phase, f"LLM 连续调用失败：{exc}")
                        yield evt_status_message("")
                        yield evt_task_complete(error=f"任务执行失败：{exc}")
                        meta.finish(RunState.FAILED, str(exc))
                        return
                    yield evt_thought(f"LLM 调用出错，正在重试…（{exc}）")
                    continue

            consecutive_errors = 0

            content_text = str((response or {}).get("content") or "")
            tool_calls = (response or {}).get("tool_calls") or []
            if content_text.strip():
                yield evt_thought(content_text.strip())

            model_msg: Dict[str, Any] = {"role": "model", "content": content_text}
            if tool_calls:
                # Ensure every tool call has an id for proper multi-turn tracking
                for _tc in tool_calls:
                    if not _tc.get("id"):
                        _tc["id"] = uuid.uuid4().hex[:8]
                model_msg["tool_calls"] = tool_calls
            raw_parts = (response or {}).get("_raw_parts")
            if raw_parts:
                model_msg["parts"] = raw_parts
            messages.append(model_msg)

            if not tool_calls:
                final_text = content_text.strip() or "任务已完成。"
                break

            for index, raw_tool_call in enumerate(tool_calls, start=1):
                tool_call = raw_tool_call if isinstance(raw_tool_call, dict) else {}
                tool_name = str(tool_call.get("name") or "").strip()
                tool_args = tool_call.get("args") or {}
                if not isinstance(tool_args, dict):
                    tool_args = {}
                tool_call_id = tool_call.get("id") or uuid.uuid4().hex[:8]
                step_id = f"{tool_name or 'tool'}_{rounds}_{index}"

                hook_ctx = HookContext(
                    tool_call={
                        "id": tool_call.get("id") or uuid.uuid4().hex[:8],
                        "name": tool_name,
                        "args": tool_args,
                    },
                    request=request,
                    metadata={"round": rounds, "step_id": step_id},
                )
                self._hooks.fire(HookPoint.BEFORE_TOOL_CALL, hook_ctx)
                if hook_ctx.abort_reason:
                    yield evt_step_error(step_id, hook_ctx.abort_reason)
                    yield evt_status_message("")
                    yield evt_task_complete(error=hook_ctx.abort_reason)
                    meta.finish(RunState.FAILED, hook_ctx.abort_reason)
                    return
                if hook_ctx.skip:
                    yield evt_step_done(step_id, f"{tool_name or '工具'} 已跳过")
                    continue
                tool_call = hook_ctx.tool_call or tool_call
                tool_name = str(tool_call.get("name") or tool_name or "").strip()
                tool_args = tool_call.get("args") or tool_args
                if not isinstance(tool_args, dict):
                    tool_args = {}

                if not tool_name:
                    err = "模型返回了无效的工具调用"
                    yield evt_step_error(step_id, err)
                    messages.append({
                        "role": "function",
                        "name": "invalid_tool_call",
                        "content": err,
                    })
                    continue

                # Cross-round write dedup: prevent repeated writes to the same file
                if tool_name in _MODIFIER_TOOL_NAMES:
                    _target_path = (
                        tool_args.get("path") or tool_args.get("target_path")
                        or tool_args.get("destination") or ""
                    )
                    _canonical = (
                        os.path.normcase(os.path.abspath(str(_target_path)))
                        if _target_path else "__unknown__"
                    )
                    # Do NOT include sheet_name for insert_excel_as_docx_table —
                    # all sheet insertions to the same DOCX share a single write cap.
                    _write_key = f"{tool_name}::{_canonical}"
                    _prior_count = completed_write_ops.get(_write_key, 0)
                    if _prior_count >= _MAX_WRITE_OPS_PER_FILE:
                        _skip_msg = (
                            f"⚠️ 写入工具 `{tool_name}` 已对目标文件成功执行 {_prior_count} 次，"
                            "本次调用被跳过以防止重复写入。如需修复问题，请使用 run_python_code。"
                        )
                        yield evt_thought(_skip_msg)
                        yield evt_step_done(step_id, f"{tool_name} 跳过重复写入")
                        messages.append({
                            "role": "function",
                            "name": tool_name,
                            "content": _skip_msg,
                        })
                        continue

                yield evt_step_start(step_id, f"调用 {tool_name}")
                yield evt_tool_call({
                    "id": tool_call.get("id") or uuid.uuid4().hex[:8],
                    "name": tool_name,
                    "args": tool_args,
                })

                try:
                    result = registry.execute(tool_name, tool_args) if registry else None
                    result_str = _stringify_tool_result(result)
                except Exception as exc:
                    logger.warning("[AgentLoop] Tool %s failed: %s", tool_name, exc, exc_info=True)
                    result_str = f"Error: {exc}"
                    yield evt_step_error(step_id, str(exc))

                after_ctx = HookContext(
                    tool_call=tool_call,
                    tool_result=result_str,
                    request=request,
                    metadata={"round": rounds, "step_id": step_id},
                )
                self._hooks.fire(HookPoint.AFTER_TOOL_CALL, after_ctx)
                if after_ctx.abort_reason:
                    yield evt_step_error(step_id, after_ctx.abort_reason)
                    yield evt_status_message("")
                    yield evt_task_complete(error=after_ctx.abort_reason)
                    meta.finish(RunState.FAILED, after_ctx.abort_reason)
                    return
                if after_ctx.tool_result is not None:
                    result_str = after_ctx.tool_result

                yield evt_tool_result(tool_name, result_str)
                yield evt_step_done(step_id, f"{tool_name} 完成")

                # Track successful write ops for cross-round dedup
                if tool_name in _MODIFIER_TOOL_NAMES and not result_str.startswith("Error:"):
                    completed_write_ops[_write_key] = completed_write_ops.get(_write_key, 0) + 1  # type: ignore[name-defined]
                    # Track file change for stage verification
                    try:
                        _payload = json.loads(result_str)
                        if isinstance(_payload, dict) and not _payload.get("error"):
                            _fc_path = (
                                _payload.get("path") or _payload.get("file_path")
                                or tool_args.get("path") or tool_args.get("target_path") or ""
                            )
                            if _fc_path:
                                _fc_preview = str(_payload.get("preview") or "")[:200]
                                file_states = _merge_file_states_loop(file_states, [{
                                    "path": str(_fc_path),
                                    "file_type": str(_payload.get("file_type") or ""),
                                    "summary": str(_payload.get("summary") or f"{tool_name} 完成"),
                                    "preview": _fc_preview,
                                    "change_type": str(_payload.get("change_type") or "modify"),
                                }])
                    except Exception:
                        pass

                # run_python_code may modify/create workspace files — detect KOTO_CREATED markers
                if tool_name == "run_python_code" and not result_str.startswith("Error:"):
                    for _created_path in _extract_koto_created_paths(result_str):
                        _ext = Path(_created_path).suffix.lstrip(".").lower()
                        file_states = _merge_file_states_loop(file_states, [{
                            "path": _created_path,
                            "file_type": _ext,
                            "summary": f"Python 代码修改了 {os.path.basename(_created_path)}",
                            "preview": "",
                            "change_type": "modify",
                        }])
                        _py_write_key = f"run_python_code::{os.path.normcase(_created_path)}"
                        completed_write_ops[_py_write_key] = completed_write_ops.get(_py_write_key, 0) + 1

                messages.append({
                    "role": "function",
                    "name": tool_name,
                    "tool_call_id": tool_call_id,
                    "content": _sample_task_context_text(result_str, _TASK_TOOL_RESULT_CONTEXT_LIMIT),
                })

            # ── Stage verification after each batch of write tool calls ──────
            if file_states and not final_text:
                _verify_result = _run_task_stage_verify(prompt, file_states, completed_write_ops, request)
                if _verify_result:
                    _v_completed = _verify_result.get("completed") is True
                    _v_summary = str(_verify_result.get("summary") or "")
                    _v_remaining = _verify_result.get("remaining_steps") or []
                    _verify_step_id = f"verify_{rounds}"
                    yield evt_step_start(_verify_step_id, "阶段检测")
                    if _v_completed:
                        yield evt_step_done(_verify_step_id, _v_summary or "阶段检测通过，任务完成")
                        final_text = _v_summary or "任务已完成。"
                        messages.append({
                            "role": "function",
                            "name": "verify_task_completion",
                            "content": json.dumps(_verify_result, ensure_ascii=False),
                        })
                        break
                    else:
                        _v_msg = _v_summary
                        if _v_remaining:
                            _v_msg += "；待完成：" + "；".join(str(s) for s in _v_remaining[:3])
                        yield evt_thought(f"阶段检测：{_v_msg}")
                        yield evt_step_done(_verify_step_id, _v_msg or "阶段检测完成")
                        # Inject warning about already-completed write ops
                        _done_writes = list(dict.fromkeys(
                            k.split("::")[0] for k in completed_write_ops if completed_write_ops[k] >= 1
                        ))
                        _v_inject = json.dumps(_verify_result, ensure_ascii=False)
                        if _done_writes:
                            _warn = (
                                f"⚠️ 已执行的写入工具：{', '.join(_done_writes)}。"
                                "请勿重复调用这些工具，改用 run_python_code 修复剩余问题。"
                            )
                            _v_inject = _v_inject[:-1] + f', "_dedup_warning": {json.dumps(_warn, ensure_ascii=False)}}}'
                        messages.append({
                            "role": "function",
                            "name": "verify_task_completion",
                            "content": _sample_task_context_text(_v_inject, 4_000),
                        })

        if not final_text:
            err = "任务达到最大执行轮次，请缩小范围后重试。"
            yield evt_step_error(gen_phase, err)
            yield evt_status_message("")
            yield evt_task_complete(error=err)
            meta.finish(RunState.FAILED, err)
            return

        yield evt_step_done(gen_phase, f"{gen_label}完成")

        reply_ctx = HookContext(
            reply_text=final_text,
            request=request,
            metadata={
                "mask_result": pipeline_mask_result,
                "skill_ids": pipeline_skill_ids,
                "raw_prompt": request.prompt,
                "file_type": request.file_type,
            },
        )
        self._hooks.fire(HookPoint.BEFORE_REPLY, reply_ctx)
        final_text = reply_ctx.reply_text or final_text

        suggestions = reply_ctx.metadata.get("suggestions", [])
        if suggestions:
            yield evt_skill_suggestions(suggestions)

        for p in phases:
            yield evt_phase(phases, p["id"], "done")
        yield evt_status_message("")

        # Stream final answer to chat bubble (fake streaming)
        # CJK text has no spaces → split at sentence punctuation; Latin → word chunks.
        if final_text:
            import re as _re
            _CJK = bool(_re.search(r'[\u4e00-\u9fff\u3040-\u30ff]', final_text[:80]))
            if _CJK:
                # Split at sentence-ending punctuation, keeping the delimiter attached
                _parts = _re.split(r'(?<=[。！？\n；])', final_text)
                _parts = [p for p in _parts if p]
                # If no sentence breaks, fall back to 30-char chunks
                if len(_parts) <= 1:
                    _parts = [final_text[i:i + 30] for i in range(0, len(final_text), 30)]
            else:
                _words = final_text.split()
                _parts = [" ".join(_words[i:i + 8]) for i in range(0, len(_words), 8)]
                # Re-add trailing spaces for interior chunks
                _parts = [
                    p + " " if idx < len(_parts) - 1 else p
                    for idx, p in enumerate(_parts)
                ]
            for _c in _parts:
                yield evt_stream_chunk(
                    _c,
                    live_doc=self._live_doc,
                    live_mode=self._live_mode,
                    request_id=self._live_request_id,
                )
            # Emit live-doc commit when docx is active
            if self._live_doc:
                yield evt_live_doc_commit(
                    full_text=final_text,
                    live_mode=self._live_mode,
                    original_selection=getattr(request, "selection", ""),
                    request_id=self._live_request_id,
                )

        yield evt_task_complete(result=final_text)
        meta.finish(RunState.SUCCEEDED)

    # ══════════════════════════════════════════════════════════════
    # Code execution mode (chart generation)
    # ══════════════════════════════════════════════════════════════

    def _run_code_mode(
        self, request: AgentRequest, prompt: str, meta: RunMetadata
    ) -> Generator[AgentEvent, None, None]:
        """Handle Python/R code generation + sandbox execution."""
        try:
            from app.core.sandbox import run_python, run_r
        except ImportError as e:
            yield evt_code_result({
                "error": f"Sandbox 模块加载失败: {e}",
                "stdout": "", "stderr": "", "files": {},
            })
            meta.finish(RunState.FAILED, str(e))
            return

        lang_label = "Python (matplotlib/pandas)" if request.language == "python" else "R (ggplot2)"
        gen_prompt = (
            f"请根据以下任务，编写一段可以直接运行的 {lang_label} 代码。\n"
            "要求：\n"
            "1. 使用 matplotlib 或 pandas 绘图（Python）/ ggplot2（R）\n"
            "2. 将生成的图表保存为当前目录下的 chart.png 文件\n"
            "3. 对于 Python：使用 plt.savefig('chart.png', dpi=150, bbox_inches='tight')\n"
            "4. 对于 R：使用 ggsave('chart.png', dpi=150)\n"
            "5. 不要用 plt.show() 或任何 GUI 调用\n"
            "6. 只输出代码，不要任何 markdown 代码块标记（不要 ```）\n\n"
            f"任务描述：{prompt}\n"
        )
        if request.csv_data:
            gen_prompt += f"\n表格数据（CSV 格式）：\n{request.csv_data}\n"

        yield evt_stream_chunk(f"🤖 正在为你生成 {request.language.upper()} 代码…\n")

        code = _call_llm_sync(gen_prompt, use_local_only=(request.model_mode == "local"))
        if not code:
            yield evt_code_result({
                "error": "AI 代码生成失败，请检查 API Key 配置。",
                "stdout": "", "stderr": "", "files": {},
            })
            meta.finish(RunState.FAILED, "code gen failed")
            return

        # Strip markdown fences
        code = re.sub(r"^```[a-z]*\n?", "", code.strip(), flags=re.MULTILINE)
        code = code.strip().strip("`")

        yield evt_stream_chunk(f"\n```{request.language}\n{code}\n```\n\n▶ 正在执行…\n")

        if request.language == "python":
            result = run_python(code)
        else:
            result = run_r(code)

        yield evt_code_result(result)
        meta.finish(RunState.SUCCEEDED)

    # ══════════════════════════════════════════════════════════════
    # LLM streaming
    # ══════════════════════════════════════════════════════════════

    def _stream_llm(
        self,
        full_prompt: str,
        system_instruction: str,
        use_local: bool,
        meta: RunMetadata,
    ) -> Generator[AgentEvent, None, Optional[str]]:
        """
        Stream LLM response. Yields stream_chunk events.
        Returns the full concatenated text, or None on total failure.

        Uses Python generator send() to return the result text
        while still yielding events.
        """
        result_text: Optional[str] = None

        if use_local:
            result_text = yield from self._try_local(full_prompt, system_instruction)
            if not result_text:
                return None
        else:
            # Try online first, fall back to local
            try:
                result_text = yield from self._try_online(full_prompt, system_instruction)
            except Exception as exc:
                logger.warning("[AgentLoop] Online LLM failed: %s: %s", type(exc).__name__, exc)
                if _is_online_failure(exc):
                    result_text = None
                else:
                    raise

            if not result_text:
                logger.warning("[AgentLoop] Online returned empty, trying local…")
                yield evt_status_message(
                    "⚠️ 云端 AI 暂时不可用，已自动切换到本地模型 (Ollama)，响应速度可能较慢。"
                )
                try:
                    result_text = yield from self._try_local(full_prompt, system_instruction)
                except Exception as exc2:
                    logger.error("[AgentLoop] Local fallback failed: %s", exc2)
                    result_text = None

        return result_text

    def _try_online(
        self, full_prompt: str, system_instruction: str
    ) -> Generator[AgentEvent, None, Optional[str]]:
        """Stream from online provider. Yields stream_chunk events."""
        provider = _get_provider()
        model = _pick_online_model()
        gen = provider.generate_content(
            prompt=full_prompt,
            model=model,
            system_instruction=system_instruction,
            stream=True,
        )
        parts: List[str] = []
        for chunk in gen:
            part = chunk.get("content", "") if isinstance(chunk, dict) else str(chunk)
            if part:
                parts.append(part)
                yield evt_stream_chunk(part, live_doc=self._live_doc,
                                       live_mode=self._live_mode,
                                       request_id=self._live_request_id)
        return "".join(parts) or None

    def _try_local(
        self, full_prompt: str, system_instruction: str
    ) -> Generator[AgentEvent, None, Optional[str]]:
        """Stream from local Ollama. Yields stream_chunk events."""
        if not _is_ollama_alive():
            return None
        local = _get_local_provider()
        local_prompt = f"[系统指令]\n{system_instruction}\n\n{full_prompt}"
        gen = local.generate_content(prompt=local_prompt, stream=True)
        parts: List[str] = []
        for chunk in gen:
            part = chunk.get("content", "") if isinstance(chunk, dict) else str(chunk)
            if part:
                parts.append(part)
                yield evt_stream_chunk(part, live_doc=self._live_doc,
                                       live_mode=self._live_mode,
                                       request_id=self._live_request_id)
        return "".join(parts) or None

    # ══════════════════════════════════════════════════════════════
    # Prompt building helpers
    # ══════════════════════════════════════════════════════════════

    def _resolve_phases(self, request: AgentRequest) -> List[Dict[str, str]]:
        """Resolve UI phase indicators for the action type."""
        try:
            from app.core.editor_skills import get_phases
            action_hint = request.action_type or ""
            return get_phases(action_hint) if action_hint else get_phases("")
        except Exception:
            return [
                {"id": "understand", "label": "理解需求"},
                {"id": "generate", "label": "生成回复"},
            ]

    def _apply_rag_chunking(
        self, request: AgentRequest, prompt: str
    ) -> str:
        """Apply RAG chunking if document context is long."""
        context = request.context
        if not context:
            return prompt

        try:
            from app.core.file.doc_chunker import DocChunker as _DC
            if len(context) > _DC.CHUNK_THRESHOLD:
                chunks = _DC.chunk(context)
                query = request.selection if request.selection else prompt
                retrieved = _DC.retrieve(chunks, query=query, top_k=4)
                dc_context = "\n\n---\n\n".join(retrieved)
                return (
                    f"[文档内容（RAG检索片段，共{len(chunks)}段，"
                    f"已检索最相关{len(retrieved)}段）]\n"
                    f"{dc_context}\n[用户请求]: {prompt}"
                )
            else:
                return f"{context}\n[用户请求]: {prompt}"
        except Exception:
            return f"{context}\n[用户请求]: {prompt}"

    def _build_system_instruction(self, request: AgentRequest) -> str:
        """Build the system instruction based on file type and mode."""
        return RequestValidator.build_system_instruction(request, self._hooks)

    def _assemble_prompt(self, request: AgentRequest, prompt: str) -> str:
        """Assemble the full prompt with history, selection, CSV data."""
        return RequestValidator.assemble_prompt(request, prompt)

    def _get_task_files(self, request: AgentRequest) -> List[Dict[str, str]]:
        """Normalise task file metadata carried in AgentRequest.extra."""
        files = request.extra.get("files") if isinstance(request.extra, dict) else []
        normalized: List[Dict[str, str]] = []
        if isinstance(files, list):
            for item in files:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path") or "").strip()
                name = str(item.get("name") or "").strip() or (os.path.basename(path) if path else "")
                file_type = str(item.get("type") or "").strip().lower() or request.file_type
                preview = str(item.get("content_preview") or "").strip()
                normalized.append({
                    "path": path or request.file_name or request.session_id or "current_document",
                    "name": name or request.file_name or "current_document",
                    "type": file_type,
                    "content_preview": _sample_task_context_text(preview or request.context, _TASK_FILE_CONTEXT_PREVIEW_LIMIT),
                })

        if normalized:
            return normalized

        if request.file_name or request.file_type or request.context:
            inferred_name = request.file_name or "current_document"
            inferred_type = request.file_type or os.path.splitext(inferred_name)[1].lstrip(".").lower()
            return [{
                "path": request.file_name or request.session_id or inferred_name,
                "name": inferred_name,
                "type": inferred_type,
                "content_preview": _sample_task_context_text(request.context, _TASK_FILE_CONTEXT_PREVIEW_LIMIT),
            }]

        return []

    def _build_task_file_context(self, files: List[Dict[str, str]]) -> str:
        """Build a file-context block for task-mode prompts."""
        if not files:
            return ""

        parts = ["## 当前文件上下文", ""]
        for item in files:
            path = item.get("path", "")
            name = item.get("name", os.path.basename(path) if path else "current_document")
            item_type = item.get("type", os.path.splitext(path)[1].lstrip(".").lower() if path else "")
            preview = item.get("content_preview", "")

            parts.append(f"### 文件: {name}")
            parts.append(f"- 路径: {path}")
            parts.append(f"- 类型: {item_type or 'unknown'}")
            if preview:
                parts.append(f"- 内容预览:\n```\n{_sample_task_context_text(preview, _TASK_FILE_CONTEXT_PREVIEW_LIMIT)}\n```")
            parts.append("")

        return "\n".join(parts).strip()

    def _build_task_messages(
        self,
        request: AgentRequest,
        prompt: str,
        file_context: str,
    ) -> List[Dict[str, Any]]:
        """Convert chat history + current task into provider chat messages."""
        messages: List[Dict[str, Any]] = []
        history = request.history or []
        recent = history[-MAX_HISTORY_TURNS * 2:] if history else []
        for turn in recent:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role") or "").strip().lower()
            content = str(turn.get("content") or "")
            if not content:
                continue
            if role == "user":
                messages.append({"role": "user", "content": content})
            elif role in {"assistant", "model"}:
                messages.append({"role": "model", "content": content})

        user_message = self._build_task_user_message(prompt, file_context)
        messages.append({"role": "user", "content": user_message})
        return messages

    def _build_task_user_message(self, task: str, file_context: str) -> str:
        """Compose the user message for task-mode execution."""
        parts = [f"## 任务\n\n{task}"]
        if file_context:
            parts.append(file_context)
        return "\n\n".join(parts)

    def _build_task_registry(self, task_files: Optional[List[Dict[str, str]]] = None):
        """Build a ToolRegistry backed by task tools."""
        return ToolExecutor.build_registry(task_files, socketio=self._socketio)

    def _call_task_llm(
        self,
        messages: List[Dict[str, Any]],
        system_instruction: str,
        tool_defs: List[Dict[str, Any]],
        use_local: bool,
        request: AgentRequest,
    ) -> Dict[str, Any]:
        """Call the LLM in non-streaming mode with provider-native tool support."""
        if use_local:
            if not _is_ollama_alive():
                raise RuntimeError("本地 Ollama 未运行")
            local_provider = _get_local_provider()
            # Pass tools through — OllamaLLMProvider supports native tool calling
            # for compatible models (qwen3, llama3.1+, mistral-nemo, etc.)
            response = local_provider.generate_content(
                prompt=messages,
                system_instruction=system_instruction,
                tools=tool_defs or None,
                stream=False,
            )
        else:
            provider = _get_provider()
            model_name = self._pick_model(False, request)
            try:
                from app.core.llm.model_fallback import get_fallback_executor

                executor = get_fallback_executor()
                response = executor.generate_with_fallback(
                    provider=provider,
                    prompt=messages,
                    preferred_model=model_name,
                    task_type="FILE_TASK",
                    system_instruction=system_instruction,
                    tools=tool_defs or None,
                    stream=False,
                )
            except ImportError:
                response = provider.generate_content(
                    prompt=messages,
                    model=model_name,
                    system_instruction=system_instruction,
                    tools=tool_defs or None,
                    stream=False,
                )

        if isinstance(response, dict):
            return response
        return {"content": str(response or ""), "tool_calls": []}

    def _should_use_local(self, request: AgentRequest, force_local: bool = False) -> bool:
        """Determine whether to use local model."""
        normalized_mode = normalize_model_mode(request.model_mode, default="auto")
        if normalized_mode == "local":
            return True
        if normalized_mode == "cloud":
            return False
        if force_local:
            return True
        try:
            from web.settings import SettingsManager as _SM
            if bool(_SM().get("ai", "use_local_only")):
                return True
        except Exception:
            pass
        return False

    def _pick_model(self, use_local: bool, request: Optional[AgentRequest] = None) -> str:
        if use_local:
            return "ollama-local"
        preferred_model = ""
        if request and isinstance(request.extra, dict):
            preferred_model = str(request.extra.get("preferred_model") or "").strip()
            if preferred_model.lower() in {"auto", "local"}:
                preferred_model = ""
        if preferred_model:
            return preferred_model
        return _pick_online_model()

    def _insert_fallback(
        self,
        request: AgentRequest,
        tool_calls: List[Dict[str, Any]],
        clean_text: str,
    ) -> List[Dict[str, Any]]:
        """Synthesise a set_html when AI failed to produce one for insert requests."""
        if tool_calls:
            return tool_calls
        if request.file_type not in ("docx", "pptx"):
            return tool_calls
        if not any(t in request.prompt for t in _INSERT_TRIGGERS):
            return tool_calls

        # Find last assistant turn with substantive content
        import html as _html
        last_ai = ""
        for turn in reversed(request.history or []):
            if turn.get("role") == "assistant":
                c = turn.get("content", "").strip()
                c_clean = re.sub(r"<TOOL>.*?</TOOL>", "", c, flags=re.DOTALL).strip()
                if len(c_clean) > 10:
                    last_ai = c_clean
                    break

        if last_ai:
            paragraphs = [p.strip() for p in last_ai.split("\n") if p.strip()]
            html_val = "".join(f"<p>{_html.escape(p)}</p>" for p in paragraphs)
            logger.info("[AgentLoop] Synthesised set_html from last assistant turn")
            return [{"type": "set_html", "value": html_val}]

        return tool_calls

    def _build_proposals(
        self,
        selection: str,
        tool_calls: List[Dict[str, Any]],
        clean_text: str,
    ) -> List[Dict[str, Any]]:
        """Build proposal dicts from tool calls + selection."""
        return ResponseFormatter.build_proposals(selection, tool_calls, clean_text)


# ══════════════════════════════════════════════════════════════
# Module-level helpers (delegated to app.core.shared)
# ══════════════════════════════════════════════════════════════

# Aliases so any in-file references continue to work unchanged
_parse_tool_calls = parse_tool_calls
_stringify_tool_result = stringify_tool_result
_is_online_failure = is_online_failure
_is_ollama_alive = is_ollama_alive
_get_local_provider = get_local_provider


# ── LLM helpers (delegate to existing provider infrastructure) ─────────

def _pick_online_model() -> str:
    try:
        from web.app import MODEL_MAP
        m = MODEL_MAP.get("CHAT", "")
        if m:
            return m
    except Exception:
        pass
    return "gemini-2.5-flash"


def _get_provider():
    from app.core.llm.provider_factory import get_llm_provider
    return get_llm_provider(provider="gemini", allow_local_fallback=False)


def _call_llm_sync(prompt: str, use_local_only: bool = False) -> Optional[str]:
    """Synchronous (non-streaming) LLM call. Returns text or None."""
    if use_local_only:
        if not _is_ollama_alive():
            return None
        try:
            local = _get_local_provider()
            gen = local.generate_content(prompt=prompt, stream=False)
            if isinstance(gen, dict):
                return gen.get("content", "")
            return str(gen) if gen else None
        except Exception:
            return None

    try:
        provider = _get_provider()
        model = _pick_online_model()
        gen = provider.generate_content(prompt=prompt, model=model, stream=False)
        if isinstance(gen, dict):
            return gen.get("content", "")
        return str(gen) if gen else None
    except Exception:
        if _is_ollama_alive():
            try:
                local = _get_local_provider()
                gen = local.generate_content(prompt=prompt, stream=False)
                if isinstance(gen, dict):
                    return gen.get("content", "")
                return str(gen) if gen else None
            except Exception:
                pass
        return None


def _merge_file_states_loop(
    file_states: List[Dict[str, Any]],
    file_changes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge new file change records into the running file_states list."""
    state_by_path: Dict[str, Dict[str, Any]] = {}
    for item in file_states:
        path = str(item.get("path") or "").strip()
        if path:
            state_by_path[path] = dict(item)
    for change in file_changes:
        path = str(change.get("path") or "").strip()
        if not path:
            continue
        state = state_by_path.get(path, {"path": path})
        state.update({
            "path": path,
            "exists": True,
            "modified": change.get("change_type") != "none",
            "preview": str(change.get("preview") or ""),
            "summary": str(change.get("summary") or state.get("summary") or ""),
            "file_type": str(change.get("file_type") or state.get("file_type") or ""),
        })
        state_by_path[path] = state
    return list(state_by_path.values())


def _run_task_stage_verify(
    task: str,
    file_states: List[Dict[str, Any]],
    completed_write_ops: Dict[str, int],
    request: Any,
) -> Optional[Dict[str, Any]]:
    """Run stage verification for agent_loop task mode.

    Returns verification dict or None if verification is not applicable/failed.

    Uses a heuristic approach instead of a separate LLM call: if all tracked
    files are marked as modified and at least one write op succeeded, we treat
    the task as complete.  An extra LLM round-trip cannot reliably verify DOCX
    content (it never reads the file), and when it falsely returns
    completed=false it injects a dedup warning that causes the main LLM to
    produce confusing "没有执行" final messages.
    """
    # Only run verification when there are actual file changes to evaluate
    if not file_states:
        return None
    # Only run if there have been successful write operations
    if not any(v >= 1 for v in completed_write_ops.values()):
        return None

    # Heuristic: all tracked files modified → task is done.
    all_modified = all(s.get("modified") for s in file_states)
    if not all_modified:
        return None  # Some files not yet modified; let the loop continue

    modified_names = [
        os.path.basename(str(s.get("path") or "")) for s in file_states
    ]
    summary = "文件已成功修改：" + "、".join(n for n in modified_names if n)
    return {"completed": True, "confidence": 1.0, "summary": summary, "remaining_steps": []}
