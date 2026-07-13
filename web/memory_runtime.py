# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

try:
    from app.core.llm.provider_compat import types
except Exception:  # pragma: no cover - depends on optional SDK install
    types = None

logger = logging.getLogger("koto.app")

def _get_client() -> Any:
    from web.runtime_context import get_client_proxy

    return get_client_proxy()


def get_memory_manager() -> Any:
    """Return the application-owned memory service.

    The web layer supplies LLM adapters, but it never creates a second memory
    store or silently falls back to the deprecated JSON implementation.  A
    single manager instance is essential: otherwise chat, agent tools and the
    memory API can read and write different histories in the same process.
    """
    from app.core.app_context import ctx

    manager = ctx.memory_manager
    _inject_memory_adapters(manager)
    return manager


def _generate_config(*, temperature: float, max_output_tokens: int) -> Any:
    if types is None:
        return None
    return types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )


def _inject_memory_adapters(mgr: Any) -> None:
    try:
        import hashlib

        def _memory_generate(
            prompt: str, temperature: float = 0.2, max_tokens: int = 300
        ) -> str:
            kwargs = {
                "model": "deepseek-chat",
                "contents": prompt,
            }
            config = _generate_config(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
            if config is not None:
                kwargs["config"] = config
            resp = _get_client().models.generate_content(**kwargs)
            return resp.text or ""

        def _memory_embed(texts: list) -> list:
            # Deterministic local feature hashing keeps memory retrieval usable
            # without crossing the archived cloud-embedding boundary.
            vectors = []
            for text in texts:
                vector = [0.0] * 256
                for token in str(text or "")[:4000].lower().split():
                    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
                    slot = int.from_bytes(digest, "big") % len(vector)
                    vector[slot] += 1.0
                magnitude = sum(value * value for value in vector) ** 0.5 or 1.0
                vectors.append([value / magnitude for value in vector])
            return vectors

        if hasattr(mgr, "set_llm_adapters"):
            mgr.set_llm_adapters(
                generate_fn=_memory_generate,
                embedding_fn=_memory_embed,
            )
    except Exception as exc:
        logger.warning("[MemoryRuntime] Memory adapter injection failed: %s", exc)


def _llm_sync(prompt: str, *, model: str, temperature: float, max_tokens: int) -> str:
    try:
        kwargs = {
            "model": model,
            "contents": prompt,
        }
        config = _generate_config(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if config is not None:
            kwargs["config"] = config
        resp = _get_client().models.generate_content(**kwargs)
        return resp.text or ""
    except Exception:
        return ""


def _start_memory_extraction(
    user_msg: str,
    ai_msg: str,
    history=None,
    task_type: str = "CHAT",
    session_name: str = "default",
) -> None:
    try:
        from web.memory_integration import MemoryIntegration
    except ImportError:
        MemoryIntegration = None

    def _reflection_llm(prompt: str) -> str:
        return _llm_sync(
            prompt,
            model="deepseek-chat",
            temperature=0.1,
            max_tokens=600,
        )

    def _quality_llm(prompt: str) -> str:
        quality_models = ["deepseek-chat"]
        model = quality_models[0]
        try:
            from app.core.llm.model_fallback import get_fallback_executor

            fallback_executor = get_fallback_executor()
            model = next(
                (item for item in quality_models if fallback_executor.is_available(item)),
                quality_models[-1],
            )
        except Exception:
            logger.warning("[MemoryRuntime] Model fallback lookup failed", exc_info=True)
        result = _llm_sync(
            prompt,
            model=model,
            temperature=0.15,
            max_tokens=800,
        )
        return result or _reflection_llm(prompt)

    def _worker() -> None:
        if MemoryIntegration and MemoryIntegration.should_extract(user_msg, ai_msg):
            try:
                memory_mgr = get_memory_manager()

                class _LLMAdapter:
                    async def generate(self, prompt, temperature=0.1, max_tokens=500):
                        return _reflection_llm(prompt)

                result = asyncio.run(
                    MemoryIntegration.extract_and_apply(
                        memory_mgr,
                        user_msg,
                        ai_msg,
                        _LLMAdapter(),
                        history,
                    )
                )
                if result.get("success"):
                    logger.info("[MemoryIntegration] automatic extraction completed")
                else:
                    logger.warning(
                        "[MemoryIntegration] extraction failed: %s",
                        result.get("error"),
                    )
            except Exception as exc:
                logger.error("[MemoryIntegration] extraction error: %s", exc)

        try:
            from app.core.memory.memory_reflector import MemoryReflector

            MemoryReflector.reflect_async(
                user_msg=user_msg,
                ai_msg=ai_msg,
                task_type=task_type,
                session_name=session_name,
                get_memory_fn=get_memory_manager,
                llm_fn=_reflection_llm,
            )
        except Exception as exc:
            logger.warning("[MemoryReflector] start failed: %s", exc)

        try:
            pm_mgr = get_memory_manager()
            if pm_mgr and hasattr(pm_mgr, "update_personality_async"):
                pm_mgr.update_personality_async(user_msg, ai_msg, _quality_llm)
        except Exception as exc:
            logger.warning("[PersonalityMatrix] update start failed: %s", exc)

        try:
            from app.core.monitoring.shadow_watcher import ShadowWatcher

            ShadowWatcher.observe(user_msg, ai_msg, session_name)
        except Exception as exc:
            logger.warning("[ShadowWatcher] observe failed: %s", exc)

        try:
            from app.core.learning.rating_store import RatingStore
            from app.core.learning.response_evaluator import ResponseEvaluator

            eval_msg_id = RatingStore.make_msg_id(session_name, user_msg)
            ResponseEvaluator.evaluate_async(
                msg_id=eval_msg_id,
                user_input=user_msg,
                ai_response=ai_msg,
                task_type=task_type,
                session_name=session_name,
                llm_fn=_reflection_llm,
            )
        except Exception as exc:
            logger.warning("[ResponseEvaluator] start failed: %s", exc)

        try:
            from app.core.monitoring.macro_recorder import MacroRecorder

            MacroRecorder.record_turn(user_msg, task_type or "CHAT", session_name)
        except Exception as exc:
            logger.warning("[MacroRecorder] record failed: %s", exc)

    threading.Thread(target=_worker, daemon=True).start()


def get_knowledge_base() -> Any:
    """Return the AppContext-owned knowledge base used by memory features."""
    from app.core.app_context import ctx

    return ctx.knowledge_base
