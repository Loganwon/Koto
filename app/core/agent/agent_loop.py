# ══════════════════════════════════════════════════════════════
# agent_loop.py — Koto Unified Agent Loop
#
# Inspired by OpenClaw's single-entry agent architecture.
# This module provides the text/quick-action agent loop for editor AI requests:
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

import logging
import re
from typing import Any, Dict, Generator, List, Optional

from app.core.agent.hooks import HookContext, HookPoint, HookRegistry, get_default_registry
from app.core.llm.model_mode import normalize_model_mode
from app.core.shared.tool_parser import parse_tool_calls
from app.core.shared.llm_helpers import is_online_failure, is_ollama_alive, get_local_provider
from app.core.agent.request_validator import RequestValidator
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
)

logger = logging.getLogger(__name__)

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
            full_prompt, system_instruction, use_local, meta, request,
        )

        if result_text is None:
            meta.finish(RunState.FAILED, "LLM returned empty")
            yield evt_step_error(gen_phase, "未能生成有效回复")
            yield evt_task_complete(error=self._build_model_unavailable_error(request, use_local))
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
            "3. 对于 Python：在代码开头设置 matplotlib.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','Noto Sans CJK SC','WenQuanYi Micro Hei','DejaVu Sans'] 和 matplotlib.rcParams['axes.unicode_minus']=False\n"
            "4. 对于 Python：使用 plt.savefig('chart.png', dpi=220, bbox_inches='tight')\n"
            "5. 对于 R：使用 ggsave('chart.png', dpi=220)\n"
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
        request: AgentRequest,
    ) -> Generator[AgentEvent, None, Optional[str]]:
        """
        Stream LLM response. Yields stream_chunk events.
        Returns the full concatenated text, or None on total failure.

        Uses Python generator send() to return the result text
        while still yielding events.
        """
        result_text: Optional[str] = None

        if use_local:
            try:
                result_text = yield from self._try_local(full_prompt, system_instruction, request)
            except Exception as exc:
                logger.warning("[AgentLoop] Local LLM failed: %s: %s", type(exc).__name__, exc)
                result_text = None
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
                    result_text = yield from self._try_local(full_prompt, system_instruction, request)
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
        self, full_prompt: str, system_instruction: str, request: Optional[AgentRequest] = None
    ) -> Generator[AgentEvent, None, Optional[str]]:
        """Stream from local Ollama. Yields stream_chunk events."""
        if not _is_ollama_alive():
            return None
        local = _get_local_provider(self._pick_local_model(request))
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

    def _pick_local_model(self, request: Optional[AgentRequest] = None) -> str:
        if request and isinstance(request.extra, dict):
            preferred_model = str(request.extra.get("local_model") or "").strip()
            if preferred_model.lower() in {"auto", "cloud", "local"} or preferred_model.lower().startswith("gemini"):
                return ""
            return preferred_model
        return ""

    def _build_model_unavailable_error(self, request: AgentRequest, use_local: bool) -> str:
        """Return an availability error that matches the request's routing mode."""
        normalized_mode = normalize_model_mode(request.model_mode, default="auto")
        if use_local or normalized_mode == "local":
            local_model = self._pick_local_model(request)
            model_hint = f"（当前模型：{local_model}）" if local_model else ""
            return (
                f"本地模式已启用，但 Ollama 未运行或所选本地模型不可用{model_hint}。\n"
                "请检查：\n"
                "1. 执行 ollama serve\n"
                "2. 执行 ollama list 确认所选模型已下载\n"
                "3. 或切换到云端模式"
            )
        return (
            "在线 AI 不可用，本地 Ollama 也未运行。\n"
            "请执行: ollama serve，或在 config/gemini_config.env 配置 API 密钥。"
        )

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


