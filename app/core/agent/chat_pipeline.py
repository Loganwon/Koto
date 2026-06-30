# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Generator

from app.core.agent.types import AgentStepType

logger = logging.getLogger(__name__)


class ChatPipeline:
    """Unified chat pipeline used by /chat and /process-stream endpoints.

    Encapsulates the shared flow:
      PII mask → agent.run() stream → 503 local fallback →
      output validation + retry → PII restore → task_final SSE →
      persistence → self-eval → exception→local fallback

    Routes become thin wrappers that prepare context and delegate to this pipeline.
    """

    def __init__(
        self,
        agent: Any,
        pii_filter: Any | None = None,
        output_validator: Any | None = None,
        local_fallback_fn: Callable | None = None,
        is_service_unavailable_fn: Callable | None = None,
        history_saver: Callable | None = None,
        state_saver: Callable | None = None,
        session_state_merger: Callable | None = None,
        tracker: Any | None = None,
        tracker_path: str = "",
        self_eval_fn: Callable | None = None,
        skill_suggester: Any | None = None,
    ):
        self.agent = agent
        self.pii_filter = pii_filter
        self.output_validator = output_validator
        self.local_fallback_fn = local_fallback_fn
        self.is_service_unavailable_fn = is_service_unavailable_fn
        self.history_saver = history_saver
        self.state_saver = state_saver
        self.session_state_merger = session_state_merger
        self.tracker = tracker
        self.tracker_path = tracker_path
        self.self_eval_fn = self_eval_fn
        self.skill_suggester = skill_suggester
        self._collected_steps: list[dict] = []

    # ── Public entry ────────────────────────────────────────────────────────

    def run(
        self,
        message: str,
        history: list[dict],
        *,
        session_id: str = "",
        model_id: str | None = None,
        skill_id: str | None = None,
        task_type: str | None = None,
        system_context: str | None = None,
        user_chose_local: bool = False,
        enable_skill_suggestions: bool = False,
        auto_skill_ids: list[str] | None = None,
    ) -> Generator[str, None, None]:
        self._collected_steps = []
        final_answer = ""
        used_local_fallback = False
        local_fallback_model = None
        local_use_reason = None
        t_start = time.time()

        if model_id and self.agent.model_id != model_id:
            self.agent.model_id = model_id

        # ── Step 1: PII masking ──────────────────────────────────────────
        mask_result = None
        safe_message = message
        try:
            if self.pii_filter:
                mask_result = self.pii_filter.mask(message)
                if mask_result and mask_result.has_pii:
                    safe_message = mask_result.masked_text
                    logger.info("[ChatPipeline] PII masked: %s", mask_result.stats)
        except Exception as e:
            logger.warning("[ChatPipeline] PII filter skipped: %s", e)

        try:
            # ── User explicitly chose local model ────────────────────────
            if user_chose_local:
                logger.info(
                    "[ChatPipeline] User chose local, using local model directly"
                )
                ans, mod = self._do_local_fallback(safe_message, history)
                if ans:
                    used_local_fallback = True
                    local_fallback_model = mod
                    local_use_reason = "user_choice"
                    final_answer = ans
                else:
                    final_answer = (
                        "❌ 本地模型 (Ollama) 未响应。\n\n"
                        "请检查：\n1. Ollama 是否正常运行（`ollama serve`）\n"
                        "2. 所选模型是否已下载（`ollama list`）\n"
                        "3. 或在设置中切换到云端模式"
                    )
            else:
                # ── Step 2: Agent.run() stream ───────────────────────────
                for step in self.agent.run(
                    input_text=safe_message,
                    history=history,
                    session_id=session_id,
                    skill_id=skill_id,
                    task_type=task_type,
                    system_context=system_context,
                ):
                    step_data = step.to_dict()
                    self._collected_steps.append(step_data)
                    if step.step_type == AgentStepType.ANSWER:
                        final_answer = step.content or ""
                    yield self._sse("agent_step", step_data)

                if not final_answer and self._collected_steps:
                    final_answer = self._collected_steps[-1].get("content", "")

            # ── Step 3: 503 → local fallback ────────────────────────────
            (
                final_answer,
                used_local_fallback,
                local_fallback_model,
                local_use_reason,
                fallback_notice,
            ) = self._check_503_fallback(
                safe_message,
                history,
                final_answer,
                used_local_fallback,
                local_fallback_model,
                local_use_reason,
            )
            if fallback_notice:
                yield self._sse("agent_step", fallback_notice)

            # ── Step 4: Output validation + retry ────────────────────────
            validated_answer, validation_action = self._validate_output(
                final_answer,
                skill_id=skill_id,
                original_prompt=message,
                used_local_fallback=used_local_fallback,
                safe_message=safe_message,
                history=history,
                session_id=session_id,
                task_type=task_type,
                system_context=system_context,
            )

            # ── Step 5: PII restore ──────────────────────────────────────
            display_answer = self._restore_pii(validated_answer, mask_result)

            # ── Step 6: Local fallback prefix ────────────────────────────
            if used_local_fallback and local_use_reason == "cloud_fallback":
                lm = local_fallback_model or "本地模型"
                display_answer = (
                    f"🔄 **[本地模型回复]** 云端服务暂时不可用，"
                    f"以下回答由本地 AI（`{lm}`）提供，能力可能弱于云端：\n\n"
                    f"{display_answer}"
                )

            # ── Step 7: Skill suggestions ────────────────────────────────
            if enable_skill_suggestions and display_answer and not used_local_fallback:
                display_answer = self._inject_skill_suggestions(
                    display_answer, message, task_type, skill_id, auto_skill_ids
                )

            # ── Step 8: task_final SSE + persistence ─────────────────────
            latency_ms = int((time.time() - t_start) * 1000)
            task_payload = self._build_task_payload(
                display_answer,
                session_id,
                skill_id,
                auto_skill_ids,
                task_type,
                validation_action,
                mask_result,
                latency_ms,
                model_id,
                local_fallback_model,
                used_local_fallback,
            )
            yield self._sse("task_final", task_payload)

            self._persist(session_id, message, display_answer)

            if self.tracker and self.tracker_path and display_answer:
                self.tracker.update_async(message, display_answer, self.tracker_path)

            self._run_self_eval(
                message, display_answer, task_type, session_id, used_local_fallback
            )

        except Exception as e:
            logger.exception("[ChatPipeline] stream failed")
            err_str = str(e)
            if self.is_service_unavailable_fn and self.is_service_unavailable_fn(
                err_str
            ):
                yield from self._exception_local_fallback(
                    safe_message,
                    history,
                    mask_result,
                    session_id,
                    message,
                    skill_id,
                    task_type,
                )
                return
            yield self._sse("error", {"error": err_str})

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _sse(event_type: str, data: dict) -> str:
        return f"data: {json.dumps({'type': event_type, 'data': data}, ensure_ascii=False)}\n\n"

    def _do_local_fallback(self, message: str, history: list[dict]) -> tuple[str, str]:
        if not self.local_fallback_fn:
            return ("", "")
        try:
            return self.local_fallback_fn(message, history)
        except Exception as e:
            logger.warning("[ChatPipeline] Local fallback failed: %s", e)
            return ("", "")

    def _check_503_fallback(
        self,
        safe_message: str,
        history: list[dict],
        final_answer: str,
        used_local_fallback: bool,
        local_fallback_model: str | None,
        local_use_reason: str | None,
    ) -> tuple[str, bool, str | None, str | None, dict | None]:
        error_steps = [
            s for s in self._collected_steps if s.get("step_type") == "error"
        ]
        is_503 = (
            self.is_service_unavailable_fn
            and error_steps
            and self.is_service_unavailable_fn(error_steps[-1].get("content", ""))
        )
        if not is_503 or used_local_fallback:
            return (
                final_answer,
                used_local_fallback,
                local_fallback_model,
                local_use_reason,
                None,
            )

        logger.warning("[ChatPipeline] 503 detected, trying local fallback")
        notice = {
            "step_type": "thought",
            "content": "⚠️ 云端服务暂时不可用，正在切换到本地模型处理您的请求...",
            "metadata": {"source": "local_fallback"},
        }
        ans, mod = self._do_local_fallback(safe_message, history)
        if ans:
            final_answer = ans
            used_local_fallback = True
            local_fallback_model = mod
            local_use_reason = "cloud_fallback"
            logger.info(
                "[ChatPipeline] Local fallback success (%s), len=%d", mod, len(ans)
            )
        else:
            final_answer = (
                "⚠️ 云端服务暂时不可用（503），本地模型也无法访问，请稍后重试。"
            )
        return (
            final_answer,
            used_local_fallback,
            local_fallback_model,
            local_use_reason,
            notice,
        )

    def _validate_output(
        self,
        final_answer: str,
        *,
        skill_id: str | None,
        original_prompt: str,
        used_local_fallback: bool,
        safe_message: str,
        history: list[dict],
        session_id: str,
        task_type: str | None,
        system_context: str | None,
    ) -> tuple[str, str]:
        validated = final_answer
        action = "PASS"
        if not final_answer or not self.output_validator:
            return validated, action

        try:
            val = self.output_validator.validate(
                text=final_answer,
                skill_id=skill_id if not used_local_fallback else None,
                original_prompt=original_prompt if not used_local_fallback else None,
            )
            action = val.action
            if val.is_blocked:
                logger.warning(
                    "[ChatPipeline] Output blocked (ignored): %s", val.reasons
                )
                validated = final_answer
            elif val.needs_retry and not used_local_fallback:
                logger.warning("[ChatPipeline] Output retry triggered: %s", val.reasons)
                retry_input = val.text if val.text != final_answer else safe_message
                retry_answer = self._run_retry(
                    retry_input,
                    history,
                    session_id,
                    skill_id,
                    task_type,
                    system_context,
                )
                validated = retry_answer or final_answer
                if not retry_answer:
                    logger.warning(
                        "[ChatPipeline] Retry returned empty, keeping original"
                    )
            else:
                validated = val.text
        except Exception as e:
            logger.warning("[ChatPipeline] Output validation skipped: %s", e)

        return validated, action

    def _run_retry(
        self,
        retry_input: str,
        history: list[dict],
        session_id: str,
        skill_id: str | None,
        task_type: str | None,
        system_context: str | None,
    ) -> str:
        retry_steps: list[dict] = []
        retry_answer = ""
        try:
            for step in self.agent.run(
                input_text=retry_input,
                history=history,
                session_id=session_id,
                skill_id=skill_id,
                task_type=task_type,
                system_context=system_context,
            ):
                retry_steps.append(step.to_dict())
                if step.step_type == AgentStepType.ANSWER:
                    retry_answer = step.content or ""
        except Exception as e:
            logger.warning("[ChatPipeline] Retry exception: %s", e)
        if not retry_answer and retry_steps:
            retry_answer = retry_steps[-1].get("content", "")
        if retry_answer:
            self._collected_steps.extend(retry_steps)
            logger.info("[ChatPipeline] Retry success, len=%d", len(retry_answer))
        return retry_answer

    def _restore_pii(self, text: str, mask_result: Any) -> str:
        if not mask_result or not mask_result.has_pii:
            return text
        try:
            return mask_result.restore(text)
        except Exception:
            logger.warning("[ChatPipeline] PII restore failed", exc_info=True)
            return text

    def _inject_skill_suggestions(
        self,
        answer: str,
        message: str,
        task_type: str | None,
        skill_id: str | None,
        auto_skill_ids: list[str] | None,
    ) -> str:
        if not self.skill_suggester:
            return answer
        try:
            suggestions = self.skill_suggester.suggest(
                user_input=message or "",
                task_type=task_type or "CHAT",
                already_active_ids=auto_skill_ids or [],
                answer_text=answer,
            )
            if suggestions:
                answer += self.skill_suggester.format_hint(suggestions)
            all_active = list(
                set((auto_skill_ids or []) + ([skill_id] if skill_id else []))
            )
            already_ids = [s["id"] for s in suggestions] if suggestions else []
            chains = self.skill_suggester.suggest_chains(
                active_skill_ids=all_active,
                already_suggested_ids=already_ids,
            )
            if chains:
                answer += self.skill_suggester.format_chain_hint(chains)
        except Exception as e:
            logger.debug("[ChatPipeline] Skill suggestions skipped: %s", e)
        return answer

    def _build_task_payload(
        self,
        answer: str,
        session_id: str,
        skill_id: str | None,
        auto_skill_ids: list[str] | None,
        task_type: str | None,
        validation_action: str,
        mask_result: Any,
        latency_ms: int,
        model_id: str | None,
        local_model: str | None,
        used_local: bool,
    ) -> dict:
        return {
            "id": f"task_{int(time.time() * 1000)}",
            "status": "success",
            "result": answer,
            "steps": self._collected_steps,
            "meta": {
                "session_id": session_id,
                "skill_id": skill_id,
                "auto_skill_ids": auto_skill_ids,
                "task_type": task_type,
                "validation_action": validation_action,
                "pii_masked": mask_result.has_pii if mask_result else False,
                "latency_ms": latency_ms,
                "model": local_model if used_local else model_id,
                "local_fallback": used_local,
            },
        }

    def _persist(self, session_id: str, message: str, answer: str) -> None:
        if not self.history_saver:
            return
        try:
            self.history_saver(session_id, message, answer or "[Agent task completed]")
        except Exception as e:
            logger.debug("[ChatPipeline] History save failed: %s", e)
        if self.state_saver and self.session_state_merger:
            try:
                merged = self.session_state_merger(None, self._collected_steps)
                self.state_saver(session_id, merged)
            except Exception as e:
                logger.debug("[ChatPipeline] State save failed: %s", e)

    def _run_self_eval(
        self,
        message: str,
        answer: str,
        task_type: str | None,
        session_id: str,
        used_local: bool,
    ) -> None:
        if not answer or used_local or not self.self_eval_fn:
            return
        try:
            self.self_eval_fn(
                user_input=message,
                ai_response=answer,
                task_type=task_type or "CHAT",
                session_name=session_id or "",
            )
        except Exception as e:
            logger.debug("[ChatPipeline] Self-eval failed: %s", e)

    def _exception_local_fallback(
        self,
        safe_message: str,
        history: list[dict],
        mask_result: Any,
        session_id: str,
        original_message: str,
        skill_id: str | None,
        task_type: str | None,
    ):
        logger.warning(
            "[ChatPipeline] Streaming exception with 503, trying local fallback"
        )
        yield self._sse(
            "agent_step",
            {
                "step_type": "thought",
                "content": "⚠️ 云端服务暂时不可用，正在切换到本地模型处理您的请求...",
                "metadata": {"source": "local_fallback"},
            },
        )
        ans, mod = self._do_local_fallback(safe_message, history)
        if ans:
            try:
                if self.output_validator:
                    val = self.output_validator.validate(text=ans)
                    if val.is_blocked:
                        logger.warning(
                            "[ChatPipeline] Local fallback output blocked: %s",
                            val.reasons,
                        )
                    ans = val.text
            except Exception:
                logger.debug(
                    "[ChatPipeline] Local fallback validation skipped", exc_info=True
                )
            ans = self._restore_pii(ans, mask_result)
            lm = mod or "本地模型"
            display = (
                f"🔄 **[本地模型回复]** 云端服务不可用，"
                f"以下由本地 AI（`{lm}`）提供：\n\n{ans}"
            )
            yield self._sse(
                "task_final",
                {
                    "id": f"task_{int(time.time() * 1000)}",
                    "status": "success",
                    "result": display,
                    "steps": self._collected_steps,
                    "meta": {
                        "session_id": session_id,
                        "skill_id": skill_id,
                        "task_type": task_type,
                        "model": lm,
                        "local_fallback": True,
                    },
                },
            )
            self._persist(session_id, original_message, ans)
