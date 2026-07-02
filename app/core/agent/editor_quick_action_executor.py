from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Optional

from app.core.agent import llm_provider_helpers
from app.core.agent.lifecycle import (
    AgentEvent,
    AgentRequest,
    RunMetadata,
    RunState,
    evt_error,
    evt_lifecycle_end,
    evt_lifecycle_error,
    evt_lifecycle_start,
    evt_phase,
    evt_plan,
    evt_status_message,
    evt_step_done,
    evt_step_error,
    evt_step_progress,
    evt_step_start,
    evt_stream_chunk,
    evt_task_complete,
)
from app.core.agent.request_validator import RequestValidator
from app.core.llm.model_mode import normalize_model_mode
from app.core.shared.tool_parser import parse_tool_calls

logger = logging.getLogger(__name__)


class EditorQuickActionExecutor:
    """Lightweight text executor for editor SSE quick actions."""

    @staticmethod
    def supports(request: AgentRequest) -> bool:
        return request.language not in {"python", "r"}

    def iter_events(self, request: AgentRequest) -> Iterator[AgentEvent]:
        meta = RunMetadata(session_id=request.session_id)
        meta.start()
        yield evt_lifecycle_start(meta.run_id, meta.session_id)

        try:
            yield from self._run_inner(request, meta)
        except Exception as exc:
            logger.exception("[EditorQuickActionExecutor] failed: %s", exc)
            meta.finish(RunState.FAILED, str(exc))
            yield evt_lifecycle_error(meta.run_id, str(exc))
            yield evt_task_complete(error=f"内部错误：{exc}")
            return

        if not meta.state.is_terminal:
            meta.finish(RunState.SUCCEEDED)
        yield evt_lifecycle_end(meta.run_id, meta.state)

    def _run_inner(
        self,
        request: AgentRequest,
        meta: RunMetadata,
    ) -> Iterator[AgentEvent]:
        if not request.prompt:
            yield evt_error("请输入内容")
            meta.finish(RunState.FAILED, "empty prompt")
            return

        phases = self._resolve_phases(request)
        phase_steps = [
            {
                "id": phase.get("id") or f"step_{idx + 1}",
                "description": phase.get("label") or phase.get("id") or f"步骤 {idx + 1}",
            }
            for idx, phase in enumerate(phases)
        ]
        if phase_steps:
            yield evt_plan(phase_steps)

        analyze_phase = phases[0] if phases else {"id": "understand", "label": "理解需求"}
        analyze_step_id = analyze_phase.get("id", "understand")
        analyze_label = analyze_phase.get("label", "理解需求")

        yield evt_step_start(analyze_step_id, analyze_label)
        yield evt_phase(phases, analyze_step_id, "running")
        yield evt_step_progress(analyze_step_id, "正在分析上下文…")
        yield evt_status_message("正在分析上下文…")

        prompt = self._apply_rag_chunking(request, request.prompt)
        system_instruction = RequestValidator.build_system_instruction(request)
        full_prompt = RequestValidator.assemble_prompt(request, prompt)
        use_local = self._should_use_local(request)
        meta.model = self._pick_model(use_local, request)

        yield evt_step_done(analyze_step_id, f"{analyze_label}完成")
        yield evt_phase(phases, analyze_step_id, "done")

        gen_phase = phases[-1]["id"] if len(phases) <= 2 else phases[1]["id"]
        gen_label = next(
            (phase.get("label", gen_phase) for phase in phases if phase.get("id") == gen_phase),
            gen_phase,
        )
        yield evt_step_start(gen_phase, gen_label)
        yield evt_phase(phases, gen_phase, "running")
        yield evt_step_progress(gen_phase, "正在生成回复…")
        yield evt_status_message("正在生成回复…")

        result_text = yield from self._stream_llm(
            full_prompt,
            system_instruction,
            use_local,
            request,
        )
        if result_text is None:
            meta.finish(RunState.FAILED, "LLM returned empty")
            yield evt_step_error(gen_phase, "未能生成有效回复")
            yield evt_error(self._build_model_unavailable_error(request, use_local))
            return

        yield evt_step_done(gen_phase, f"{gen_label}完成")

        clean_text, _tool_calls = parse_tool_calls(result_text)
        for phase in phases:
            yield evt_phase(phases, phase["id"], "done")
        yield evt_status_message("")
        yield evt_task_complete(result=clean_text)
        meta.finish(RunState.SUCCEEDED)

    def _stream_llm(
        self,
        full_prompt: str,
        system_instruction: str,
        use_local: bool,
        request: AgentRequest,
    ) -> Iterator[AgentEvent]:
        result_text: Optional[str] = None
        if use_local:
            try:
                result_text = yield from self._try_local(full_prompt, system_instruction, request)
            except Exception as exc:
                logger.warning("[EditorQuickActionExecutor] local failed: %s: %s", type(exc).__name__, exc)
                result_text = None
            return result_text

        try:
            result_text = yield from self._try_online(full_prompt, system_instruction, request)
        except Exception as exc:
            logger.warning("[EditorQuickActionExecutor] online failed: %s: %s", type(exc).__name__, exc)
            if not llm_provider_helpers.is_online_failure(exc):
                raise
            result_text = None

        if result_text:
            return result_text

        yield evt_status_message(
            "⚠️ 云端 AI 暂时不可用，已自动切换到本地模型 (Ollama)，响应速度可能较慢。"
        )
        try:
            return (yield from self._try_local(full_prompt, system_instruction, request))
        except Exception as exc:
            logger.error("[EditorQuickActionExecutor] local fallback failed: %s", exc)
            return None

    def _try_online(
        self,
        full_prompt: str,
        system_instruction: str,
        request: AgentRequest,
    ) -> Iterator[AgentEvent]:
        model = self._pick_model(False, request)
        provider = llm_provider_helpers.get_provider(model=model, model_mode=request.model_mode)
        gen = provider.generate_content(
            prompt=full_prompt,
            model=model,
            system_instruction=system_instruction,
            stream=True,
        )
        parts: list[str] = []
        for chunk in gen:
            part = chunk.get("content", "") if isinstance(chunk, dict) else str(chunk)
            if part:
                parts.append(part)
                yield evt_stream_chunk(part, live_doc=request.live_doc, live_mode=request.live_mode)
        return "".join(parts) or None

    def _try_local(
        self,
        full_prompt: str,
        system_instruction: str,
        request: AgentRequest,
    ) -> Iterator[AgentEvent]:
        if not llm_provider_helpers.is_ollama_alive():
            return None
        local = llm_provider_helpers.get_local_provider(self._pick_local_model(request))
        local_prompt = f"[系统指令]\n{system_instruction}\n\n{full_prompt}"
        gen = local.generate_content(prompt=local_prompt, stream=True)
        parts: list[str] = []
        for chunk in gen:
            part = chunk.get("content", "") if isinstance(chunk, dict) else str(chunk)
            if part:
                parts.append(part)
                yield evt_stream_chunk(part, live_doc=request.live_doc, live_mode=request.live_mode)
        return "".join(parts) or None

    def _resolve_phases(self, request: AgentRequest) -> list[dict[str, str]]:
        try:
            from app.core.editor_skills import get_phases

            action_hint = request.action_type or ""
            return get_phases(action_hint) if action_hint else get_phases("")
        except Exception:
            return [
                {"id": "understand", "label": "理解需求"},
                {"id": "generate", "label": "生成回复"},
            ]

    def _apply_rag_chunking(self, request: AgentRequest, prompt: str) -> str:
        context = request.context
        if not context:
            return prompt

        try:
            from app.core.file.doc_chunker import DocChunker

            if len(context) > DocChunker.CHUNK_THRESHOLD:
                chunks = DocChunker.chunk(context)
                query = request.selection if request.selection else prompt
                retrieved = DocChunker.retrieve(chunks, query=query, top_k=4)
                dc_context = "\n\n---\n\n".join(retrieved)
                return (
                    f"[文档内容（RAG检索片段，共{len(chunks)}段，"
                    f"已检索最相关{len(retrieved)}段）]\n"
                    f"{dc_context}\n[用户请求]: {prompt}"
                )
            return f"{context}\n[用户请求]: {prompt}"
        except Exception:
            return f"{context}\n[用户请求]: {prompt}"

    def _should_use_local(self, request: AgentRequest) -> bool:
        normalized_mode = normalize_model_mode(request.model_mode, default="auto")
        if normalized_mode == "local":
            return True
        if normalized_mode == "cloud":
            return False
        try:
            from web.settings import SettingsManager

            return bool(SettingsManager().get("ai", "use_local_only"))
        except Exception:
            return False

    def _pick_model(self, use_local: bool, request: AgentRequest) -> str:
        if use_local:
            return "ollama-local"
        preferred_model = ""
        if isinstance(request.extra, dict):
            preferred_model = str(request.extra.get("preferred_model") or "").strip()
            if preferred_model.lower() in {"auto", "local"}:
                preferred_model = ""
        return preferred_model or llm_provider_helpers.pick_online_model()

    def _pick_local_model(self, request: AgentRequest) -> str:
        if isinstance(request.extra, dict):
            preferred_model = str(request.extra.get("local_model") or "").strip()
            if preferred_model.lower() in {"auto", "cloud", "local"}:
                return ""
            if preferred_model.lower().startswith("gemini"):
                return ""
            return preferred_model
        return ""

    def _build_model_unavailable_error(self, request: AgentRequest, use_local: bool) -> str:
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
