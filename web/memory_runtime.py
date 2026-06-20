# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

try:
    from google.genai import types
except Exception:  # pragma: no cover - depends on optional SDK install
    types = None

logger = logging.getLogger("koto.app")

_memory_manager: Any = None
_kb: Any = None


def _get_client() -> Any:
    from web.runtime_context import get_client_proxy

    return get_client_proxy()


def get_memory_manager() -> Any:
    global _memory_manager
    if _memory_manager is not None:
        return _memory_manager

    try:
        from app.core.app_context import ctx

        mgr = ctx.memory_manager
        if mgr is not None:
            _memory_manager = mgr
            _inject_memory_adapters(_memory_manager)
            return _memory_manager
    except Exception:
        logger.warning("[MemoryRuntime] AppContext memory manager unavailable", exc_info=True)

    try:
        from enhanced_memory_manager import EnhancedMemoryManager

        _memory_manager = EnhancedMemoryManager()
        logger.info("[MemoryRuntime] Enhanced memory manager initialized")
    except ImportError:
        try:
            from web.enhanced_memory_manager import EnhancedMemoryManager

            _memory_manager = EnhancedMemoryManager()
            logger.info("[MemoryRuntime] Enhanced memory manager initialized")
        except ImportError:
            try:
                from memory_manager import MemoryManager
            except ImportError:
                from web.memory_manager import MemoryManager

            _memory_manager = MemoryManager()
            logger.warning("[MemoryRuntime] Basic memory manager initialized")

    _inject_memory_adapters(_memory_manager)
    return _memory_manager


def _generate_config(*, temperature: float, max_output_tokens: int) -> Any:
    if types is None:
        return None
    return types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )


def _inject_memory_adapters(mgr: Any) -> None:
    try:
        from app.core.llm.embedding_model_selector import (
            resolve_gemini_embedding_model,
        )

        memory_embedding_model = resolve_gemini_embedding_model()

        def _memory_generate(
            prompt: str, temperature: float = 0.2, max_tokens: int = 300
        ) -> str:
            kwargs = {
                "model": "gemini-2.5-flash-lite",
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
            safe_texts = [(t or "")[:1000] for t in texts]
            resp = _get_client().models.embed_content(
                model=memory_embedding_model,
                contents=safe_texts,
            )
            embeddings = []
            if hasattr(resp, "embeddings"):
                for item in resp.embeddings:
                    if hasattr(item, "values"):
                        embeddings.append(list(item.values))
                    elif hasattr(item, "embedding"):
                        embeddings.append(list(item.embedding))
                    elif isinstance(item, dict):
                        embeddings.append(
                            list(item.get("values") or item.get("embedding") or [])
                        )
            elif hasattr(resp, "embedding"):
                embeddings.append(list(resp.embedding))
            elif isinstance(resp, dict) and "embeddings" in resp:
                for item in resp.get("embeddings", []):
                    embeddings.append(
                        list(item.get("values") or item.get("embedding") or [])
                    )
            return embeddings

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
        from memory_integration import MemoryIntegration
    except ImportError:
        try:
            from web.memory_integration import MemoryIntegration
        except ImportError:
            MemoryIntegration = None

    def _reflection_llm(prompt: str) -> str:
        return _llm_sync(
            prompt,
            model="gemini-2.5-flash-lite",
            temperature=0.1,
            max_tokens=600,
        )

    def _quality_llm(prompt: str) -> str:
        quality_models = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
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
    global _kb
    if _kb is None:
        try:
            from knowledge_base import KnowledgeBase
        except ImportError:
            from web.knowledge_base import KnowledgeBase
        _kb = KnowledgeBase()
        logger.info("[MemoryRuntime] Knowledge base initialized")
    return _kb
