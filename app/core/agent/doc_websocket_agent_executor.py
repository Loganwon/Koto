from __future__ import annotations

import logging
import html
import re
from collections.abc import Iterator
from typing import Any, Optional

from app.core.agent import llm_provider_helpers
from app.core.agent.editor_code_action_executor import EditorCodeActionExecutor
from app.core.agent.hooks import HookContext, HookPoint, HookRegistry
from app.core.agent.lifecycle import (
    AgentEvent,
    AgentRequest,
    RunMetadata,
    RunState,
    evt_doc_tool_call,
    evt_error,
    evt_lifecycle_end,
    evt_lifecycle_error,
    evt_lifecycle_start,
    evt_live_doc_commit,
    evt_phase,
    evt_plan,
    evt_proposal,
    evt_status_message,
    evt_step_done,
    evt_step_error,
    evt_step_progress,
    evt_step_start,
    evt_stream_chunk,
    evt_task_complete,
)
from app.core.agent.pipeline_hooks import register_pipeline_hooks
from app.core.agent.request_validator import RequestValidator
from app.core.agent.response_formatter import ResponseFormatter
from app.core.llm.model_mode import normalize_model_mode
from app.core.shared.tool_parser import parse_tool_calls

logger = logging.getLogger(__name__)

_INSERT_TRIGGERS = (
    "在光标处插入", "插入文档", "插入到文档", "请插入", "插入内容", "写入文档",
)


class DocWebSocketAgentExecutor:
    """Doc WebSocket executor for chat, doc edits, live doc, and code requests."""

    @staticmethod
    def supports(request: AgentRequest) -> bool:
        return True

    def __init__(self, hook_registry: HookRegistry | None = None) -> None:
        self._hooks = hook_registry or HookRegistry()
        if hook_registry is None:
            register_pipeline_hooks(self._hooks)

    def iter_events(self, request: AgentRequest) -> Iterator[AgentEvent]:
        if EditorCodeActionExecutor.supports(request):
            yield from EditorCodeActionExecutor().iter_events(request)
            return

        meta = RunMetadata(session_id=request.session_id)
        meta.start()
        yield evt_lifecycle_start(meta.run_id, meta.session_id)

        try:
            yield from self._run_inner(request, meta)
        except Exception as exc:
            logger.exception("[DocWebSocketAgentExecutor] failed: %s", exc)
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

        phases = [
            {"id": "understand", "label": "理解需求"},
            {"id": "generate", "label": "生成回复"},
        ]
        yield evt_plan([
            {"id": "understand", "description": "理解需求"},
            {"id": "generate", "description": "生成回复"},
        ])

        yield evt_step_start("understand", "理解需求")
        yield evt_phase(phases, "understand", "running")
        yield evt_step_progress("understand", "正在分析上下文…")
        yield evt_status_message("正在分析上下文…")

        prompt = self._apply_context(request, request.prompt)
        system_instruction = RequestValidator.build_system_instruction(request)
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

        system_instruction = hook_ctx.metadata.get("system_instruction", system_instruction)
        prompt = hook_ctx.metadata.get("prompt", prompt)
        pipeline_skill_ids = hook_ctx.metadata.get("skill_ids", [])
        pipeline_mask_result = hook_ctx.metadata.get("mask_result")
        pipeline_force_local = hook_ctx.metadata.get("force_local", False)
        full_prompt = RequestValidator.assemble_prompt(request, prompt)
        use_local = self._should_use_local(request, pipeline_force_local)
        meta.model = self._pick_model(use_local, request)

        yield evt_step_done("understand", "理解需求完成")
        yield evt_phase(phases, "understand", "done")
        yield evt_step_start("generate", "生成回复")
        yield evt_phase(phases, "generate", "running")
        yield evt_step_progress("generate", "正在生成回复…")
        yield evt_status_message("正在生成回复…")

        result_text = yield from self._stream_llm(
            full_prompt,
            system_instruction,
            use_local,
            request,
        )
        if result_text is None:
            meta.finish(RunState.FAILED, "LLM returned empty")
            yield evt_step_error("generate", "未能生成有效回复")
            yield evt_task_complete(error=self._build_model_unavailable_error(request, use_local))
            return

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
        result_text = reply_ctx.reply_text

        yield evt_step_done("generate", "生成回复完成")

        if request.output_mode != "chat":
            clean_text, tool_calls = parse_tool_calls(result_text)
            tool_calls = self._insert_fallback(request, tool_calls, clean_text)
            has_proposals = False

            if request.selection and tool_calls:
                proposals = ResponseFormatter.build_proposals(
                    request.selection,
                    tool_calls,
                    clean_text,
                )
                if proposals:
                    proposal_summary = proposals[0].get("rationale", "")
                    has_proposals = True
                    yield evt_step_start("prepare_proposals", "生成修改建议")
                    yield evt_step_progress("prepare_proposals", "正在准备修改建议…")
                    yield evt_status_message("正在准备修改建议…")
                    yield evt_proposal(proposals, proposal_summary)
                    yield evt_step_done("prepare_proposals", "修改建议已生成")
            else:
                doc_tool_step_open = False
                for tool_call in tool_calls:
                    if not doc_tool_step_open:
                        yield evt_step_start("prepare_doc_tool_calls", "生成文档变更指令")
                        doc_tool_step_open = True
                    yield evt_doc_tool_call(tool_call)
                if doc_tool_step_open:
                    yield evt_step_done("prepare_doc_tool_calls", "文档变更指令已生成")

            yield evt_phase(phases, "generate", "done")
            yield evt_status_message("")
            if request.live_doc and clean_text and not has_proposals:
                yield evt_live_doc_commit(
                    full_text=clean_text,
                    live_mode=request.live_mode,
                    original_selection=request.selection,
                    request_id=meta.run_id,
                )
            yield evt_task_complete(result=clean_text, has_proposals=has_proposals)
            meta.finish(RunState.SUCCEEDED)
            return

        yield evt_phase(phases, "generate", "done")
        yield evt_status_message("")
        if request.live_doc and result_text:
            clean_text, _tool_calls = parse_tool_calls(result_text)
            yield evt_live_doc_commit(
                full_text=clean_text,
                live_mode=request.live_mode,
                original_selection=request.selection,
                request_id=meta.run_id,
            )
            yield evt_task_complete(result=clean_text)
            meta.finish(RunState.SUCCEEDED)
            return
        yield evt_task_complete(result=result_text)
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
                logger.warning("[DocWebSocketAgentExecutor] local failed: %s: %s", type(exc).__name__, exc)
                result_text = None
            return result_text

        try:
            result_text = yield from self._try_online(full_prompt, system_instruction, request)
        except Exception as exc:
            logger.warning("[DocWebSocketAgentExecutor] online failed: %s: %s", type(exc).__name__, exc)
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
            logger.error("[DocWebSocketAgentExecutor] local fallback failed: %s", exc)
            return None

    def _try_online(
        self,
        full_prompt: str,
        system_instruction: str,
        request: AgentRequest,
    ) -> Iterator[AgentEvent]:
        model = self._pick_model(False, request)
        provider = llm_provider_helpers.get_provider(model=model, model_mode=request.model_mode)
        chunks = provider.generate_content(
            prompt=full_prompt,
            model=model,
            system_instruction=system_instruction,
            stream=True,
        )
        parts: list[str] = []
        for chunk in chunks:
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
        chunks = local.generate_content(prompt=local_prompt, stream=True)
        parts: list[str] = []
        for chunk in chunks:
            part = chunk.get("content", "") if isinstance(chunk, dict) else str(chunk)
            if part:
                parts.append(part)
                yield evt_stream_chunk(part, live_doc=request.live_doc, live_mode=request.live_mode)
        return "".join(parts) or None

    def _apply_context(self, request: AgentRequest, prompt: str) -> str:
        if request.context:
            return f"{request.context}\n[用户请求]: {prompt}"
        return prompt

    def _insert_fallback(
        self,
        request: AgentRequest,
        tool_calls: list[dict[str, Any]],
        clean_text: str,
    ) -> list[dict[str, Any]]:
        if tool_calls:
            return tool_calls
        if request.file_type not in ("docx", "pptx"):
            return tool_calls
        if not any(trigger in request.prompt for trigger in _INSERT_TRIGGERS):
            return tool_calls

        last_ai = ""
        for turn in reversed(request.history or []):
            if turn.get("role") != "assistant":
                continue
            content = str(turn.get("content", "")).strip()
            content_clean = re.sub(r"<TOOL>.*?</TOOL>", "", content, flags=re.DOTALL).strip()
            if len(content_clean) > 10:
                last_ai = content_clean
                break

        if not last_ai:
            return tool_calls

        paragraphs = [paragraph.strip() for paragraph in last_ai.split("\n") if paragraph.strip()]
        html_value = "".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in paragraphs)
        logger.info("[DocWebSocketAgentExecutor] Synthesised set_html from last assistant turn")
        return [{"type": "set_html", "value": html_value}]

    def _should_use_local(self, request: AgentRequest, force_local: bool = False) -> bool:
        normalized_mode = normalize_model_mode(request.model_mode, default="auto")
        if normalized_mode == "local":
            return True
        if normalized_mode == "cloud":
            return False
        if force_local:
            return True
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
            "请执行: ollama serve，或在 config/deepseek_config.env 配置 API 密钥。"
        )
