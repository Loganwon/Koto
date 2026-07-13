# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
import logging
import re
import time
from typing import Optional

from app.core.routing.routing_config import (
    TASK_CORPUS,
    TRIVIAL_GREETINGS,
    TRIVIAL_IDENTITY,
    TRIVIAL_EXCLUDE,
)

logger = logging.getLogger(__name__)

# 延迟导入 - 这些模块仅在运行时方法调用时加载，减少启动耗时。
# from app.core.routing.local_model_router import LocalModelRouter


def _get_local_model_router():
    from app.core.routing.local_model_router import LocalModelRouter

    return LocalModelRouter


def _get_task_classifier():
    from app.core.routing.task_classifier import TaskClassifier

    return TaskClassifier


from app.core.routing.rule_router import RuleRouter  # noqa: E402


class SmartDispatcher:
    """
    混合智能路由算法。

    外层只负责把请求分到稳定任务类型；文件任务的细粒度意图、计划
    和监督由 FileTaskRuntime 内部白盒链路负责，避免旧多步规划器干扰。
    """

    # 依赖注入容器
    _dependencies = {
        "LocalExecutor": None,
        "ContextAnalyzer": None,
        "WebSearcher": None,
        "MODEL_MAP": {},
        "client": None,
    }

    # LRU result cache: keyed by MD5(user_input), stores full analyze() return tuple.
    # Routing is deterministic for same text, so no TTL needed.
    _route_cache: "OrderedDict" = None
    _route_cache_max = 128
    _route_cache_lock = None

    @classmethod
    def _get_route_cache(cls):
        if cls._route_cache is None:
            import threading as _threading
            from collections import OrderedDict

            cls._route_cache = OrderedDict()
            cls._route_cache_lock = _threading.Lock()
        return cls._route_cache, cls._route_cache_lock

    @classmethod
    def configure(
        cls, local_executor, context_analyzer, web_searcher, model_map, client
    ):
        """配置外部依赖"""
        cls._dependencies["LocalExecutor"] = local_executor
        cls._dependencies["ContextAnalyzer"] = context_analyzer
        cls._dependencies["WebSearcher"] = web_searcher
        cls._dependencies["MODEL_MAP"] = model_map
        cls._dependencies["client"] = client

    # 任务语料库 - 从 routing_config 导入，此处保留引用方便子类覆盖
    TASK_CORPUS = TASK_CORPUS

    # 预计算特征 (字符级 n-gram)
    _features = None
    _task_vectors = None

    @classmethod
    def _init_features(cls):
        """初始化特征向量 (懒加载)"""
        if cls._features is not None:
            return

        all_ngrams = set()
        for corpus in cls.TASK_CORPUS.values():
            for text in corpus:
                ngrams = cls._extract_ngrams(text)
                all_ngrams.update(ngrams)

        cls._features = list(all_ngrams)

        cls._task_vectors = {}
        for task, corpus in cls.TASK_CORPUS.items():
            vectors = [cls._text_to_vector(text) for text in corpus]
            avg_vector = [
                sum(v[i] for v in vectors) / len(vectors)
                for i in range(len(cls._features))
            ]
            cls._task_vectors[task] = avg_vector

    @classmethod
    def _compute_similarity_scores(
        cls, user_input: str, task_candidates: Optional[list] = None
    ) -> dict:
        """Compute semantic similarity using TaskClassifier embeddings (ML fallback)."""
        if not user_input or not user_input.strip():
            return {}
        scores = {}
        try:
            from app.core.routing.task_classifier import TaskClassifier

            emb_scores = TaskClassifier.compute_similarities(user_input.strip())
            if emb_scores:
                scores = {k: v for k, v in emb_scores.items() if k in cls.TASK_CORPUS}
        except Exception:
            logger.warning(
                "[SmartDispatcher] Silenced exception caught while computing ML similarity",
                exc_info=True,
            )
        # Fill gaps with n-gram fallback for any TASK_CORPUS tasks not covered
        if not scores or set(scores.keys()) != set(cls.TASK_CORPUS.keys()):
            if cls._features is None or cls._task_vectors is None:
                cls._init_features()
            user_vector = cls._text_to_vector(user_input)
            ngram_scores = {
                task: cls._cosine_similarity(user_vector, task_vector)
                for task, task_vector in cls._task_vectors.items()
            }
            for task, score in ngram_scores.items():
                if task not in scores:
                    scores[task] = score
        return scores

    @classmethod
    def _build_routing_list(
        cls, scores: dict, boosts: dict = None, reasons: dict = None, top_k: int = 6
    ) -> list:
        """构建路由分配列表（用于可视化展示）"""
        boosts = boosts or {}
        reasons = reasons or {}
        routing = []
        for task, score in scores.items():
            final_score = max(score, boosts.get(task, 0))
            reason_list = reasons.get(task, [])
            if not reason_list:
                reason_list = ["similarity"]
            routing.append(
                {
                    "task": task,
                    "score": float(final_score),
                    "reason": " + ".join(reason_list),
                }
            )
        routing.sort(key=lambda x: x["score"], reverse=True)
        return routing[:top_k]

    # ──────────────────────────────────────────────────────────────
    # 极简快速通道：无需任何 AI 分类器即可确认的简单输入
    # ──────────────────────────────────────────────────────────────
    # 从 routing_config 导入，此处保留引用以兼容外部测试和子类覆盖
    _TRIVIAL_GREETINGS = TRIVIAL_GREETINGS
    _TRIVIAL_IDENTITY = TRIVIAL_IDENTITY
    _TRIVIAL_EXCLUDE = TRIVIAL_EXCLUDE

    @classmethod
    def _is_trivial_input(cls, user_input: str) -> bool:
        """
        判断是否为极简输入，可不经任何 AI 分类器、直接路由到 CHAT + 本地模型。
        条件：
          1. 是已知问候/致谢/确认词，或
          2. 是简短身份询问（≤20字），或
          3. 长度 ≤15 字且不含复杂任务关键词
        Delegates to RuleRouter.is_trivial().
        """
        return RuleRouter.is_trivial(user_input)

    @classmethod
    def get_trivial_reply(cls, user_input: str) -> str:
        """
        为极简输入返回内置快速响应（本地模型不可用时使用，避免调用云端）。
        匹配顺序：精确问候词 > 感谢 > 告别 > 确认 > 通用兜底。
        Delegates to RuleRouter.get_trivial_reply().
        """
        return RuleRouter.get_trivial_reply(user_input)

    @staticmethod
    def _extract_ngrams(text, n=2):
        """提取字符级 n-gram"""
        text = text.lower().strip()
        ngrams = set()
        for char in text:
            if char.strip():
                ngrams.add(char)
        for i in range(len(text) - 1):
            if text[i : i + 2].strip():
                ngrams.add(text[i : i + 2])
        return ngrams

    @classmethod
    def _quick_task_hint(cls, user_input: str) -> str:
        """Delegates to RuleRouter.quick_task_hint()."""
        return RuleRouter.quick_task_hint(user_input)

    @classmethod
    def _text_to_vector(cls, text):
        if cls._features is None:
            cls._init_features()
        ngrams = cls._extract_ngrams(text)
        vector = [1 if f in ngrams else 0 for f in cls._features]
        return vector

    @staticmethod
    def _cosine_similarity(v1, v2):
        dot_product = sum(a * b for a, b in zip(v1, v2))
        norm1 = sum(a * a for a in v1) ** 0.5
        norm2 = sum(b * b for b in v2) ** 0.5
        if norm1 == 0 or norm2 == 0:
            return 0
        return dot_product / (norm1 * norm2)

    @classmethod
    def _get_dep(cls, name):
        """Helper to get dependency safely"""
        return cls._dependencies.get(name)

    @staticmethod
    def _should_use_annotation_system(user_input, has_file=False):
        """Delegates to RuleRouter.should_use_annotation_system()."""
        return RuleRouter.should_use_annotation_system(user_input, has_file)

    @classmethod
    def _apply_routing_safety(
        cls,
        task_type: str,
        user_input: str,
        user_lower: str,
        file_context,
        LocalExecutor,
        WebSearcher,
    ) -> str:
        """对模型输出应用强规则安全覆写，避免模型分类器误判边界情况。
        Delegates to RuleRouter.apply_safety().
        """
        return RuleRouter.apply_safety(
            task_type, user_input, user_lower, file_context, LocalExecutor, WebSearcher
        )

    @staticmethod
    def _confidence_float(value) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            match = re.search(r"(\d+(?:\.\d+)?)", value)
            if match:
                try:
                    parsed = float(match.group(1))
                    return parsed / 100.0 if parsed > 1.0 else parsed
                except ValueError:
                    return 0.0
        return 0.0

    @classmethod
    def _model_primary_route(
        cls,
        user_input: str,
        user_lower: str,
        file_context,
        LocalExecutor,
        WebSearcher,
        similarity_scores,
        *,
        threshold: float = 0.72,
    ):
        """ML model route for inputs not handled by deterministic rules."""
        early_model_result = None

        # --- Cloud AI Router (primary, fastest cloud model) ---
        _use_airouter = True
        if cls._dependencies and cls._dependencies.get("client") and _use_airouter:
            from app.core.routing.ai_router import AIRouter

            try:
                _ai_type, _ai_conf, _ai_source = AIRouter.classify(
                    cls._dependencies["client"],
                    user_input,
                    timeout=2.0,
                )
                if _ai_type and _ai_conf:
                    _ai_type = cls._apply_routing_safety(
                        _ai_type,
                        user_input,
                        user_lower,
                        file_context,
                        LocalExecutor,
                        WebSearcher,
                    )
                    _ai_conf_label = f"{_ai_conf} ({_ai_source})"
                    logger.info(
                        "[SmartDispatcher] ☁️ AIRouter PRIMARY → %s (%s)",
                        _ai_type,
                        _ai_conf_label,
                    )
                    return ((_ai_type, _ai_conf_label, {}), None)
            except Exception as _air_err:
                logger.warning("[SmartDispatcher] ⚠️ AIRouter skipped: %s", _air_err)

        try:
            task_classifier = _get_task_classifier()
            if task_classifier.is_available():
                task, confidence = task_classifier.classify(user_input)
                confidence_value = cls._confidence_float(confidence)
                if task and confidence_value >= threshold:
                    task = cls._apply_routing_safety(
                        task,
                        user_input,
                        user_lower,
                        file_context,
                        LocalExecutor,
                        WebSearcher,
                    )
                    context_info = {
                        "routing_list": cls._build_routing_list(
                            similarity_scores,
                            boosts={task: confidence_value},
                            reasons={task: ["model_primary:task_classifier"]},
                        ),
                        "router_policy": "model_primary",
                    }
                    logger.info(
                        "[SmartDispatcher] 🚀 模型主判(TaskClassifier): '%s' → %s (%.2f)",
                        user_input[:30],
                        task,
                        confidence_value,
                    )
                    return (
                        task,
                        f"🚀 ModelPrimary(TaskClassifier) {confidence_value:.2f}",
                        context_info,
                    ), early_model_result
        except Exception as exc:
            logger.warning(
                "[SmartDispatcher] ⚠️ 模型主判 TaskClassifier 异常（跳过）: %s", exc
            )

        try:
            local_model_router = _get_local_model_router()
            if local_model_router.is_ollama_available():
                task, confidence_text, _, hint, complexity = (
                    local_model_router.classify_with_hint(user_input, timeout=3.5)
                )
                confidence_value = cls._confidence_float(confidence_text)
                early_model_result = (
                    task,
                    confidence_value,
                    confidence_text,
                    hint,
                    complexity,
                )
                if task and confidence_value >= threshold:
                    task = cls._apply_routing_safety(
                        task,
                        user_input,
                        user_lower,
                        file_context,
                        LocalExecutor,
                        WebSearcher,
                    )
                    context_info = {
                        "routing_list": cls._build_routing_list(
                            similarity_scores,
                            boosts={task: confidence_value},
                            reasons={task: ["model_primary:local_model"]},
                        ),
                        "router_policy": "model_primary",
                    }
                    if hint:
                        context_info["skill_prompt"] = hint
                    if complexity == "complex" and task != "CHAT":
                        context_info["complexity"] = "complex"
                    logger.info(
                        "[SmartDispatcher] 🤖 模型主判(Local): '%s' → %s (%.2f)",
                        user_input[:30],
                        task,
                        confidence_value,
                    )
                    return (
                        task,
                        f"🤖 ModelPrimary(Local) {confidence_value:.2f}",
                        context_info,
                    ), early_model_result
        except Exception as exc:
            logger.warning("[SmartDispatcher] ⚠️ 模型主判本地模型异常（跳过）: %s", exc)

        return None, early_model_result

    @classmethod
    def analyze(cls, user_input: str, history=None, file_context=None):
        """
        智能分析用户输入，返回最匹配的任务类型。

        优先级：ML模型主判 → 可组合规则链 → 关键词兜底 → 相似度 → CHAT默认

        返回: (task_type, confidence_info, context_info)
        """
        import hashlib as _hashlib

        start_time = time.time()

        # Cache lookup — skip for requests with file_context (state may differ)
        if not file_context:
            cache_key = _hashlib.md5(
                user_input.encode(), usedforsecurity=False
            ).hexdigest()[:16]
            cache, lock = cls._get_route_cache()
            with lock:
                if cache_key in cache:
                    cache.move_to_end(cache_key)
                    return cache[cache_key]
        else:
            cache_key = None
            cache = None
            lock = None

        LocalExecutor = cls._get_dep("LocalExecutor")
        ContextAnalyzer = cls._get_dep("ContextAnalyzer")
        WebSearcher = cls._get_dep("WebSearcher")

        cls._init_features()

        user_lower = user_input.lower().strip()
        context_info = None
        similarity_scores = cls._compute_similarity_scores(user_input)
        base_routing_list = cls._build_routing_list(similarity_scores)

        _input_for_trivial = re.sub(
            r"^\[FILE_ATTACHED:[^\]]+\]\s*", "", user_input
        ).strip()

        # ── 0. Force Plan Mode ──────────────────────────────────────────────
        from app.core.routing.routing_config import FORCE_PLAN_TRIGGERS

        if user_input.strip().startswith("/plan ") or any(
            t in user_input for t in FORCE_PLAN_TRIGGERS
        ):
            context_info = {"complexity": "complex", "is_multi_step_task": True}
            context_info["multi_step_info"] = {
                "pattern": "forced_plan",
                "description": "User forced planning mode",
            }
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"MULTI_STEP": 1.0},
                reasons={"MULTI_STEP": ["user_forced"]},
            )
            return "MULTI_STEP", "🛠️ Forced-Plan", context_info

        # ── 1. Trivial Chat Fast Path ───────────────────────────────────────
        if (
            not file_context
            and cls._is_trivial_input(_input_for_trivial)
            and cls._quick_task_hint(_input_for_trivial) == "CHAT"
        ):
            context_info = {
                "router_policy": "trivial_fast_path",
                "local_reply": cls.get_trivial_reply(_input_for_trivial),
                "routing_list": cls._build_routing_list(
                    similarity_scores,
                    boosts={"CHAT": 1.0},
                    reasons={"CHAT": ["rule:trivial_fast_path"]},
                ),
            }
            result = ("CHAT", "💬 Trivial-Quick", context_info)
            if cache_key and cache is not None and lock is not None:
                with lock:
                    cache[cache_key] = result
                    cache.move_to_end(cache_key)
                    while len(cache) > cls._route_cache_max:
                        cache.popitem(last=False)
            logger.info(
                "[SmartDispatcher] 💬 极简输入快速通道: '%s' → CHAT",
                _input_for_trivial[:30],
            )
            return result

        # ── 2. Capability / How-To Query ────────────────────────────────────
        if RuleRouter.is_capability_or_howto_query(user_input):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"CHAT": 1.0},
                reasons={"CHAT": ["rule:capability_or_howto_query"]},
            )
            logger.info(
                "[SmartDispatcher] 💬 能力/方法询问快速通道: '%s' → CHAT",
                user_input[:30],
            )
            return "CHAT", "💬 Capability/HowTo-Query", context_info

        # ── 3. Composable Rule Chain ───────────────────────────────────────
        from app.core.routing.routing_rule_chain import RuleContext, build_rule_chain

        chain = build_rule_chain(cls)
        rule_ctx = RuleContext(
            user_input=user_input,
            user_lower=user_lower,
            file_context=file_context,
            similarity_scores=similarity_scores,
            LocalExecutor=LocalExecutor,
            ContextAnalyzer=ContextAnalyzer,
            WebSearcher=WebSearcher,
            history=history,
        )
        chain_result = chain.run(rule_ctx)
        if chain_result:
            task, label, info = chain_result
            if info is None:
                info = {}
            if not file_context and cache is not None and lock is not None:
                with lock:
                    cache[cache_key] = (task, label, info)
                    cache.move_to_end(cache_key)
                    while len(cache) > cls._route_cache_max:
                        cache.popitem(last=False)
            return task, label, info

        # ── 4. ML Model Primary Route ───────────────────────────────────────
        _early_model_result = None
        if not file_context:
            primary_model_route, _early_model_result = cls._model_primary_route(
                user_input,
                user_lower,
                file_context,
                LocalExecutor,
                WebSearcher,
                similarity_scores,
            )
            if primary_model_route:
                if cache is not None and lock is not None:
                    with lock:
                        cache[cache_key] = primary_model_route
                        cache.move_to_end(cache_key)
                        while len(cache) > cls._route_cache_max:
                            cache.popitem(last=False)
                return primary_model_route

        # ── 5. Model Second-Chance (threshold 0.62) ─────────────────────────
        _SEC_THRESH = 0.62
        try:
            _TC2 = _get_task_classifier()
            if _TC2.is_available():
                _tc2_task, _tc2_conf = _TC2.classify(user_input)
                if _tc2_conf >= _SEC_THRESH:
                    _tc2_task = cls._apply_routing_safety(
                        _tc2_task,
                        user_input,
                        user_lower,
                        file_context,
                        LocalExecutor,
                        WebSearcher,
                    )
                    context_info = context_info or {}
                    context_info["routing_list"] = cls._build_routing_list(
                        similarity_scores,
                        boosts={_tc2_task: _tc2_conf},
                        reasons={_tc2_task: ["tc_2nd_chance"]},
                    )
                    logger.info(
                        "[SmartDispatcher] 🚀 TC二次兜底: '%s' → %s (%.2f)",
                        user_input[:30],
                        _tc2_task,
                        _tc2_conf,
                    )
                    return (
                        _tc2_task,
                        f"🚀 TaskClassifier(2) {_tc2_conf:.2f}",
                        context_info,
                    )
        except Exception:
            logger.warning(
                "[SmartDispatcher] TaskClassifier 2nd chance failed", exc_info=True
            )

        if _early_model_result is not None:
            _em_task, _em_conf, _em_cs, _em_hint, _em_cplx = _early_model_result
            if _em_task and _em_conf >= _SEC_THRESH:
                _em_task = cls._apply_routing_safety(
                    _em_task,
                    user_input,
                    user_lower,
                    file_context,
                    LocalExecutor,
                    WebSearcher,
                )
                context_info = context_info or {}
                context_info["routing_list"] = cls._build_routing_list(
                    similarity_scores,
                    boosts={_em_task: _em_conf},
                    reasons={_em_task: ["local_model_2nd_chance"]},
                )
                if _em_hint:
                    context_info["skill_prompt"] = _em_hint
                if _em_cplx == "complex" and _em_task != "CHAT":
                    context_info["complexity"] = "complex"
                logger.info(
                    "[SmartDispatcher] 🤖 Ollama二次兜底: '%s' → %s (%.2f)",
                    user_input[:30],
                    _em_task,
                    _em_conf,
                )
                return _em_task, f"🤖 LocalModel(2) {_em_conf:.2f}", context_info
        else:
            try:
                _lmr2 = _get_local_model_router()
                if _lmr2.is_ollama_available():
                    _r2_task, _r2_cs, _, _r2_hint, _r2_cplx = _lmr2.classify_with_hint(
                        user_input, timeout=4.5
                    )
                    _r2_conf = 0.0
                    if isinstance(_r2_cs, str):
                        _mm2 = re.search(r"(\d+\.\d+)", _r2_cs)
                        if _mm2:
                            _r2_conf = float(_mm2.group(1))
                    if _r2_task and _r2_conf >= _SEC_THRESH:
                        _r2_task = cls._apply_routing_safety(
                            _r2_task,
                            user_input,
                            user_lower,
                            file_context,
                            LocalExecutor,
                            WebSearcher,
                        )
                        context_info = context_info or {}
                        context_info["routing_list"] = cls._build_routing_list(
                            similarity_scores,
                            boosts={_r2_task: _r2_conf},
                            reasons={_r2_task: ["local_model_late"]},
                        )
                        if _r2_hint:
                            context_info["skill_prompt"] = _r2_hint
                        if _r2_cplx == "complex" and _r2_task != "CHAT":
                            context_info["complexity"] = "complex"
                        logger.info(
                            "[SmartDispatcher] 🤖 Ollama延迟起动: '%s' → %s (%.2f)",
                            user_input[:30],
                            _r2_task,
                            _r2_conf,
                        )
                        return (
                            _r2_task,
                            f"🤖 LocalModel(late) {_r2_conf:.2f}",
                            context_info,
                        )
            except Exception:
                logger.warning(
                    "[SmartDispatcher] Ollama late retry failed", exc_info=True
                )

        # ── 5. Keyword Fallback Rules (all models failed) ────────────────────
        logger.debug(
            "[SmartDispatcher] ⚠️ 模型均未达阈值，回退关键词兜底: '%s'", user_input[:30]
        )

        # Cache keyword-fallback results (deterministic for same input + file context)
        _kw_key = "kw:" + (cache_key or "")
        if not file_context and cache is not None and lock is not None:
            with lock:
                if _kw_key in cache:
                    cache.move_to_end(_kw_key)
                    return cache[_kw_key]

        _kw_result = None

        if _kw_result:
            pass
        elif file_context and file_context.get("has_file"):
            _fc_ext = file_context.get("file_type", "")
            if _fc_ext in (".doc", ".docx"):
                try:
                    if cls._should_use_annotation_system(user_input, has_file=True):
                        context_info = {"complexity": "complex"}
                        context_info["routing_list"] = cls._build_routing_list(
                            similarity_scores,
                            boosts={"DOC_ANNOTATE": 1.0},
                            reasons={"DOC_ANNOTATE": ["fallback:annotation_with_file"]},
                        )
                        _kw_result = (
                            "DOC_ANNOTATE",
                            "📄 Fallback-Annotation",
                            context_info,
                        )
                except Exception:
                    logger.warning(
                        "[SmartDispatcher] annotation fallback failed", exc_info=True
                    )

        # PPT / DocGen / FileSearch / System / MultiStep / Compound / RAG / WebSearch

        # PPT direct
        from app.core.routing.routing_config import (
            PPT_DIRECT_KEYWORDS,
            PPT_ACTION_WORDS,
            PPT_QUESTION_GUARDS,
            DOC_GEN_OUTPUT_KEYWORDS,
            DOC_GEN_ACTION_KEYWORDS,
            DOC_GEN_QUESTION_GUARDS,
            FILE_SEARCH_PATTERNS,
        )

        if _kw_result is None and (
            any(k in user_lower for k in PPT_DIRECT_KEYWORDS)
            and any(a in user_lower for a in PPT_ACTION_WORDS)
            and not any(q in user_lower for q in PPT_QUESTION_GUARDS)
        ):
            context_info = {"complexity": "complex"}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"FILE_GEN": 1.0},
                reasons={"FILE_GEN": ["fallback:ppt_direct"]},
            )
            logger.info("[SmartDispatcher] 🎯 PPT 请求直通 FILE_GEN")
            _kw_result = ("FILE_GEN", "📄 PPT-Direct", context_info)

        # Document generation
        if _kw_result is None and (
            any(k in user_lower for k in DOC_GEN_OUTPUT_KEYWORDS)
            and any(a in user_lower for a in DOC_GEN_ACTION_KEYWORDS)
            and not any(q in user_lower for q in DOC_GEN_QUESTION_GUARDS)
        ):
            context_info = context_info or {}
            context_info["complexity"] = "complex"
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"FILE_GEN": 1.0},
                reasons={"FILE_GEN": ["fallback:doc_gen_direct"]},
            )
            logger.info("[SmartDispatcher] 📄 文档生成请求直通 FILE_GEN")
            _kw_result = ("FILE_GEN", "📄 DocGen-Direct", context_info)

        # File search (global)
        if _kw_result is None and any(
            re.search(p, user_input) for p in FILE_SEARCH_PATTERNS
        ):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"FILE_SEARCH": 1.0},
                reasons={"FILE_SEARCH": ["rule:disk_file_search"]},
            )
            logger.info("[SmartDispatcher] 🔍 文件搜索/全盘扫描直通 FILE_SEARCH")
            _kw_result = ("FILE_SEARCH", "🔍 FileSearch-Direct", context_info)

        # System command
        if (
            _kw_result is None
            and LocalExecutor
            and LocalExecutor.is_system_command(user_input)
        ):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"SYSTEM": 0.9},
                reasons={"SYSTEM": ["fallback:system"]},
            )
            _kw_result = ("SYSTEM", "🖥️ Fallback-System", context_info)

        # RAG context continuation
        if _kw_result is None and history and len(history) >= 2 and ContextAnalyzer:
            context_info = ContextAnalyzer.analyze_context(user_input, history)
            if (
                context_info.get("is_continuation")
                and context_info.get("related_task") == "WEB_SEARCH"
            ):
                from app.core.routing.routing_config import SEARCH_FOLLOWUP_VERBS

                if any(v in user_lower for v in SEARCH_FOLLOWUP_VERBS):
                    context_info["routing_list"] = cls._build_routing_list(
                        similarity_scores,
                        boosts={"WEB_SEARCH": 0.9},
                        reasons={"WEB_SEARCH": ["fallback:search_followup"]},
                    )
                    _kw_result = (
                        "WEB_SEARCH",
                        "🌐 Fallback-SearchFollowup",
                        context_info,
                    )

        # Web search detection
        if (
            _kw_result is None
            and WebSearcher
            and WebSearcher.needs_web_search(user_input)
        ):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"WEB_SEARCH": 0.9},
                reasons={"WEB_SEARCH": ["fallback:web_search"]},
            )
            _kw_result = ("WEB_SEARCH", "🌐 Fallback-WebSearch", context_info)

        # RAG history continuation
        if _kw_result is None and history and len(history) >= 2 and ContextAnalyzer:
            context_info = ContextAnalyzer.analyze_context(user_input, history)
            if (
                context_info.get("is_continuation")
                and context_info.get("confidence", 0) > 0.7
            ):
                related_task = context_info.get("related_task")
                continuation_type = context_info.get("continuation_type", "unknown")
                if related_task:
                    context_info["routing_list"] = cls._build_routing_list(
                        similarity_scores,
                        boosts={related_task: 0.88},
                        reasons={related_task: [f"fallback:rag_{continuation_type}"]},
                    )
                    _kw_result = (
                        related_task,
                        f"🔗 Fallback-RAG-{continuation_type}",
                        context_info,
                    )

        if _kw_result:
            if not file_context and cache is not None and lock is not None:
                with lock:
                    cache[_kw_key] = _kw_result
                    cache.move_to_end(_kw_key)
                    while len(cache) > cls._route_cache_max:
                        cache.popitem(last=False)
            return _kw_result

        # ── 7. Final default: ML similarity → CHAT ───────────────────────────
        scores = similarity_scores
        best_task = max(scores, key=scores.get)
        best_score = scores[best_task]
        latency = (time.time() - start_time) * 1000

        from app.core.routing.routing_config import GENERIC_QUESTION_WORDS

        if best_score > 0.45:
            is_q = any(qw in user_lower for qw in GENERIC_QUESTION_WORDS)
            if is_q and best_score < 0.6 and best_task != "CHAT":
                pass
            else:
                confidence = f"🧠 ML ({best_score:.0%}, {latency:.1f}ms)"
                context_info = context_info or {}
                context_info["routing_list"] = cls._build_routing_list(
                    similarity_scores,
                    boosts={best_task: best_score},
                    reasons={best_task: ["similarity_best"]},
                )
                return best_task, confidence, context_info

        context_info = context_info or {}
        context_info["routing_list"] = base_routing_list
        result = ("CHAT", f"💬 Default ({latency:.1f}ms)", context_info)
        if cache_key and cache is not None and lock is not None:
            with lock:
                cache[cache_key] = result
                cache.move_to_end(cache_key)
                if len(cache) > cls._route_cache_max:
                    cache.popitem(last=False)
        return result

    @classmethod
    def get_model_for_task(cls, task_type, has_image=False, complexity="normal"):
        """根据任务类型获取最优模型（自动跳过当前不可用的模型）"""
        MODEL_MAP = cls._get_dep("MODEL_MAP")
        if not MODEL_MAP:
            MODEL_MAP = {"CHAT": "deepseek-chat"}

        # ── 咨询 ModelFallbackExecutor：若首选模型当前不可用，直接返回备选 ──
        try:
            from app.core.llm.model_fallback import get_fallback_executor

            _fbe = get_fallback_executor()
        except Exception:
            _fbe = None

        def _avail(preferred: str, fb_task: str = task_type) -> str:
            """若 preferred 当前可用则直接返回；否则从降级链取第一个可用模型。"""
            if _fbe and not _fbe.is_available(preferred):
                alt = _fbe.get_best_available(task_type=fb_task, preferred=preferred)
                if alt and alt != preferred:
                    import logging as _log

                    _log.getLogger(__name__).warning(
                        "[Dispatcher] 模型 %s 当前不可用，改用 %s (task=%s)",
                        preferred,
                        alt,
                        task_type,
                    )
                    return alt
            return preferred

        if task_type == "FILE_GEN":
            if complexity == "complex":
                return MODEL_MAP.get("COMPLEX", MODEL_MAP.get("CODER", "deepseek-chat"))
            return MODEL_MAP.get("FILE_GEN", "deepseek-chat")

        if task_type == "DOC_ANNOTATE":
            if complexity == "complex":
                return MODEL_MAP.get("COMPLEX", MODEL_MAP.get("CODER", "deepseek-chat"))
            return MODEL_MAP.get("DOC_ANNOTATE", "deepseek-chat")

        if task_type == "RESEARCH":
            return MODEL_MAP.get("RESEARCH", "deepseek-chat")

        if task_type == "CODER":
            return MODEL_MAP.get("CODER", "deepseek-chat")

        # 多步复杂任务 → Pro 模型确保执行质量
        if task_type == "MULTI_STEP":
            return MODEL_MAP.get("MULTI_STEP", MODEL_MAP.get("CODER", "deepseek-chat"))

        # CHAT 任务使用当前配置的 CHAT 模型；可用性由 _avail 统一处理。
        if task_type == "CHAT":
            _chat_candidate = MODEL_MAP.get("CHAT", "deepseek-chat")
            return _avail(_chat_candidate)

        # 通用复杂度升级：非 CHAT 任务标记为 complex 时使用较强模型
        if complexity == "complex":
            return MODEL_MAP.get("COMPLEX", "deepseek-chat")

        if has_image and task_type != "PAINTER":
            return _avail(
                MODEL_MAP.get("VISION", MODEL_MAP.get("CHAT", "deepseek-chat")),
                "VISION",
            )

        return _avail(MODEL_MAP.get(task_type, MODEL_MAP.get("CHAT", "deepseek-chat")))

    # ── LangGraph 工作流集成 ────────────────────────────────────────────────
    @staticmethod
    def normalize_workflow_route(route: str) -> str:
        normalized = str(route or "").strip()
        return "standard" if normalized in ("", "legacy") else normalized

    @classmethod
    def resolve_workflow(
        cls, task_type: str, user_input: str, has_file: bool = False
    ) -> str:
        """
        根据 dispatch() 返回的 task_type 决定是否使用 LangGraph 多步工作流。

        Args:
            has_file: 请求是否附带已上传文件。为 True 时跳过 LangGraph 工作流，
                      因为工作流没有文件字节上下文，强制使用标准文件分析流。

        返回值:
            "langgraph_react"          → 使用 LangGraphAgent（单 Agent ReAct）
            "langgraph_research_doc"   → 使用 WorkflowEngine: research_and_document
            "langgraph_multi_agent_ppt"→ 使用 WorkflowEngine: multi_agent_ppt
            "standard"                 → 使用标准非 LangGraph 路径

        集成方式（在 web/app.py 或对应处理函数中）:
            task_type, conf, ctx = SmartDispatcher.dispatch(user_input, ...)
            wf = SmartDispatcher.resolve_workflow(task_type, user_input, has_file=has_file)
            if wf.startswith("langgraph_"):
                # 使用 LangGraph 路径
                ...
        """
        try:
            from app.core.workflow.langgraph_workflow import WorkflowEngine

            detected = WorkflowEngine.detect_workflow(
                task_type, user_input, has_file=has_file
            )
            if detected == "multi_agent_ppt":
                return "langgraph_multi_agent_ppt"
            elif detected == "research_and_document":
                return "langgraph_research_doc"
            elif task_type == "MULTI_STEP" and not has_file:
                # 通用多步任务 → LangGraphAgent ReAct（有文件时不走 LangGraph）
                return "langgraph_react"
            else:
                return "standard"
        except ImportError:
            # langgraph 未安装 → 回退到标准路径
            return "standard"
