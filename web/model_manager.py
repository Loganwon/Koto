# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
动态模型管理器 (Dynamic Model Manager)
========================================
自动发现 API 可用模型，根据任务类型智能匹配最佳模型。
支持 Gemini 及未来其他 Provider 扩展。

核心能力：
- 调用 client.models.list() 自动发现 API 可用模型列表
- 基于能力矩阵为每个任务类型评分，选择最优模型
- TTL 缓存（默认 6 小时），避免频繁 API 调用
- 新模型加入 API 后自动感知并路由，无需手动维护
- 优雅降级：API 不可用时使用静态默认值
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.llm.model_capabilities import (
    get_interactions_only_model_set as _get_interactions_only_model_set,
)
from app.core.llm.model_capabilities import (
    get_model_blocklist_from_env,
    is_interactions_only_model,
    normalize_model_id,
)

logger = logging.getLogger(__name__)

# ─── 任务能力需求权重表 ────────────────────────────────────────────────────
# 每个任务所看重的能力维度及权重，权重之和不必等于 1。
# 必须能力 (required=True) 的维度：模型不满足则直接排除。
TASK_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    # CHAT 极度优先 speed，确保 Flash 始终胜出 Pro 模型（Pro score≈19 < Flash score≈23.8）
    "CHAT": {
        "speed": 14,  # 提高速度权重：Flash(speed=9)≈23.8 > Pro(speed=4)≈21.4
        "quality": 6,
        "context": 4,
        "reasoning": 4,
        "multimodal": False,  # 不强制要求
        "image_gen": False,
        "grounding": False,
        "function_calling": False,
    },
    "CODER": {
        "speed": 4,
        "quality": 9,
        "reasoning": 9,
        "context": 8,
        "function_calling": True,  # 必须支持
        "multimodal": False,
        "image_gen": False,
        "grounding": False,
    },
    "WEB_SEARCH": {
        "speed": 7,
        "quality": 6,
        "grounding": True,  # 必须支持
        "multimodal": False,
        "image_gen": False,
        "function_calling": False,
    },
    "VISION": {
        "speed": 7,
        "quality": 7,
        "multimodal": True,  # 必须支持
        "image_gen": False,
        "grounding": False,
        "function_calling": False,
    },
    "RESEARCH": {
        "speed": 1,
        "quality": 10,
        "reasoning": 10,
        "context": 10,
        "grounding": True,
        "function_calling": False,
        "image_gen": False,
        "multimodal": False,
    },
    "FILE_GEN": {
        "speed": 5,
        "quality": 8,
        "context": 8,
        "function_calling": True,
        "multimodal": False,
        "image_gen": False,
        "grounding": False,
    },
    "FILE_TASK": {
        "speed": 3,
        "quality": 9,
        "reasoning": 9,
        "context": 10,
        "function_calling": True,
        "multimodal": False,
        "image_gen": False,
        "grounding": False,
    },
    "PAINTER": {
        "image_gen": True,  # 必须支持
        "quality": 8,
        "speed": 5,
        "multimodal": False,
        "grounding": False,
        "function_calling": False,
    },
    "AGENT": {
        "speed": 7,
        "function_calling": True,  # 必须支持
        "reasoning": 8,
        "multimodal": True,
        "context": 6,
        "image_gen": False,
        "grounding": False,
    },
}

# ─── 任务级已验证偏好 ────────────────────────────────────────────────────────
# 基于当前线上可用性与实时探测结果的显式偏好：
# - 轻量交互和文件任务优先 DeepSeek
# - Gemini 保留为视觉/图片生成，以及显式选择 Gemini 时的备选
_TASK_MODEL_PREFERENCES: Dict[str, List[str]] = {
    "CHAT": [
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ],
    "WEB_SEARCH": [
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ],
    "VISION": [
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ],
    "CODER": [
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "gemini-3.1-pro-preview",
        "gemini-2.5-pro",
        "gemini-3-pro-preview",
        "gemini-2.5-flash",
        "gemini-3-flash-preview",
    ],
    "RESEARCH": [
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "gemini-3.1-pro-preview",
        "gemini-2.5-pro",
        "gemini-3-pro-preview",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
    ],
    "FILE_GEN": [
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "gemini-3.1-pro-preview",
        "gemini-2.5-pro",
        "gemini-3-pro-preview",
        "gemini-2.5-flash",
        "gemini-3-flash-preview",
    ],
    "FILE_TASK": [
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "gemini-3.1-pro-preview",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-3-flash-preview",
        "gemini-3-pro-preview",
    ],
    "AGENT": [
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "gemini-3.1-pro-preview",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-3-flash-preview",
        "gemini-3-pro-preview",
    ],
    "PAINTER": [
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image",
    ],
}

# ─── 本地执行任务（无需 API 模型）────────────────────────────────────────────
LOCAL_EXECUTOR_TASKS = {"SYSTEM", "FILE_OP"}

# ─── 已知模型能力注册表 ───────────────────────────────────────────────────────
# 预填已知模型的能力；未知模型通过名称规则自动推断。
# provider: "gemini" | "openai" | "anthropic" | ...（预留扩展）
# tier: 综合能力等级（1-10），同任务需求下优先选高 tier
# interactions_only: True 表示必须走 Interactions API（而非 generate_content）
KNOWN_MODEL_REGISTRY: Dict[str, Dict[str, Any]] = {
    # ── DeepSeek primary cloud stack ─────────────────────────────
    "deepseek-v4-pro": {
        "provider": "deepseek",
        "tier": 10,
        "speed": 7,
        "quality": 10,
        "reasoning": 10,
        "context": 10,
        "multimodal": False,
        "function_calling": True,
        "grounding": True,
        "image_gen": False,
        "interactions_only": False,
        "display": "DeepSeek V4 Pro",
        "strengths": ["推理", "代码", "工具调用", "复杂文件任务"],
    },
    "deepseek-v4-flash": {
        "provider": "deepseek",
        "tier": 8,
        "speed": 9,
        "quality": 8,
        "reasoning": 8,
        "context": 8,
        "multimodal": False,
        "function_calling": True,
        "grounding": True,
        "image_gen": False,
        "interactions_only": False,
        "display": "DeepSeek V4 Flash",
        "strengths": ["快速", "对话", "代码", "工具调用"],
    },
    # ── Gemini 3.x preview (preferred text stack) ──────────────────
    "gemini-3.1-pro-preview": {
        "provider": "gemini",
        "tier": 10,
        "speed": 9,
        "quality": 10,
        "reasoning": 10,
        "context": 10,
        "multimodal": True,
        "function_calling": True,
        "grounding": True,
        "image_gen": False,
        "interactions_only": False,
        "display": "Gemini 3.1 Pro Preview 🚀",
        "strengths": ["推理", "代码", "工具调用", "复杂任务"],
    },
    "gemini-3-pro-preview": {
        "provider": "gemini",
        "tier": 10,
        "speed": 6,
        "quality": 10,
        "reasoning": 10,
        "context": 10,
        "multimodal": True,
        "function_calling": True,
        "grounding": True,
        "image_gen": False,
        "interactions_only": False,
        "display": "Gemini 3 Pro Preview 🚀",
        "strengths": ["推理", "代码", "分析", "复杂任务"],
    },
    "gemini-3-flash-preview": {
        "provider": "gemini",
        "tier": 8,
        "speed": 10,
        "quality": 8,
        "reasoning": 8,
        "context": 8,
        "multimodal": True,
        "function_calling": True,
        "grounding": True,
        "image_gen": False,
        "interactions_only": False,
        "display": "Gemini 3 Flash Preview ⚡",
        "strengths": ["快速", "对话", "多模态", "联网搜索"],
    },
    # ── Gemini 2.5 (primary) ────────────────────────────────────
    "gemini-2.5-pro": {
        "provider": "gemini",
        "tier": 9,
        "speed": 4,
        "quality": 10,
        "reasoning": 10,
        "context": 10,
        "multimodal": True,
        "function_calling": True,
        "grounding": True,
        "image_gen": False,
        "interactions_only": False,
        "display": "Gemini 2.5 Pro 🚀",
        "strengths": ["推理", "代码", "分析", "复杂任务"],
    },
    "gemini-2.5-flash": {
        "provider": "gemini",
        "tier": 7,
        "speed": 9,
        "quality": 7,
        "reasoning": 7,
        "context": 7,
        "multimodal": True,
        "function_calling": True,
        "grounding": True,
        "image_gen": False,
        "interactions_only": False,
        "display": "Gemini 2.5 Flash ⚡",
        "strengths": ["快速", "对话", "多模态", "联网搜索"],
    },
    "gemini-2.5-flash-lite": {
        "provider": "gemini",
        "tier": 5,
        "speed": 10,
        "quality": 5,
        "reasoning": 5,
        "context": 6,
        "multimodal": True,
        "function_calling": True,
        "grounding": True,
        "image_gen": False,
        "interactions_only": False,
        "display": "Gemini 2.5 Flash Lite ⚡",
        "strengths": ["快速", "经济", "轻量"],
    },
    # ── Image generation ─────────────────────────────────────────
    "gemini-3.1-flash-image-preview": {
        "provider": "gemini",
        "tier": 7,
        "speed": 7,
        "quality": 8,
        "reasoning": 5,
        "context": 5,
        "multimodal": True,
        "function_calling": False,
        "grounding": False,
        "image_gen": True,
        "interactions_only": False,
        "display": "Gemini 3.1 Flash Image 🎨",
        "strengths": ["图像生成", "多模态"],
    },
    "gemini-2.5-flash-image": {
        "provider": "gemini",
        "tier": 5,
        "speed": 8,
        "quality": 6,
        "reasoning": 4,
        "context": 5,
        "multimodal": True,
        "function_calling": False,
        "grounding": False,
        "image_gen": True,
        "interactions_only": False,
        "display": "Gemini 2.5 Flash Image 🎨",
        "strengths": ["图像生成", "多模态"],
    },
    # ── Deep Research ────────────────────────────────────────────
    "deep-research-pro-preview-12-2025": {
        "provider": "gemini",
        "tier": 10,
        "speed": 1,
        "quality": 10,
        "reasoning": 10,
        "context": 10,
        "multimodal": False,
        "function_calling": False,
        "grounding": True,
        "image_gen": False,
        "interactions_only": True,
        "display": "Deep Research Pro 🔬",
        "strengths": ["深度研究", "学术分析", "综合报告"],
    },
}

# ─── 名称推断规则 (越靠前优先级越高) ──────────────────────────────────────────
# 用于从未见过的新模型名称中推断能力
_INFER_RULES: List[Tuple[str, Dict[str, Any]]] = [
    # 图像生成类
    (
        r"imagen",
        {
            "image_gen": True,
            "multimodal": True,
            "grounding": False,
            "function_calling": False,
        },
    ),
    (r"image.*gen|gen.*image", {"image_gen": True}),
    (r"image.*preview|flash.*image", {"image_gen": True, "multimodal": True}),
    # 深度研究（仅支持 Interactions API）
    (
        r"deep.?research",
        {
            "grounding": True,
            "reasoning": 10,
            "context": 10,
            "speed": 1,
            "tier_bonus": 3,
            "interactions_only": True,
        },
    ),
    # Pro 系列能力更强
    (
        r"\bpro\b",
        {"quality": 9, "reasoning": 9, "context": 9, "speed": 4, "tier_bonus": 2},
    ),
    # Flash 系列速度优先
    (r"\bflash\b", {"speed": 9, "quality": 6, "tier_bonus": 0}),
    # Ultra 最高能力
    (
        r"\bultra\b",
        {"quality": 10, "reasoning": 10, "context": 10, "speed": 3, "tier_bonus": 4},
    ),
    # Nano/Micro 轻量
    (
        r"\bnano\b|\bmicro\b",
        {"speed": 10, "quality": 4, "reasoning": 3, "tier_bonus": -2},
    ),
    # 多模态
    (r"vision|multimodal", {"multimodal": True}),
    # 联网
    (r"grounding|search", {"grounding": True}),
    # 实验版本
    (r"\bexp\b|\bexperimental\b", {"tier_bonus": -1}),
    # Preview
    (r"\bpreview\b", {"tier_bonus": 1}),
]


# 版本号 → tier 基底分
def _version_to_tier_base(model_name: str) -> int:
    """从模型名中提取大版本号，用于基础 tier 分计算。"""
    m = re.search(r"gemini[- ]?(\d+)(?:\.(\d+))?", model_name)
    if m:
        major = int(m.group(1))
        minor = float(m.group(2) or 0) / 10
        return min(9, 2 + major + round(minor))
    return 4  # 未知模型的保守默认值


def infer_capabilities(model_id: str) -> Dict[str, Any]:
    """
    对于注册表中未记录的新模型，从名称推断能力。
    返回与 KNOWN_MODEL_REGISTRY 格式兼容的 dict。
    """
    name = model_id.lower()
    caps: Dict[str, Any] = {
        "provider": "gemini" if "gemini" in name or "palm" in name else "unknown",
        "tier": _version_to_tier_base(name),
        "speed": 7,
        "quality": 7,
        "reasoning": 7,
        "context": 7,
        "multimodal": False,
        "function_calling": True,
        "grounding": False,
        "image_gen": False,
        "interactions_only": False,
        "display": model_id,
        "strengths": [],
        "_inferred": True,  # 标记为自动推断
    }
    tier_bonus = 0
    for pattern, updates in _INFER_RULES:
        if re.search(pattern, name):
            bonus = updates.get("tier_bonus", 0)
            tier_bonus += bonus
            for key, value in updates.items():
                if key != "tier_bonus":
                    caps[key] = value
    if is_interactions_only_model(model_id):
        caps["interactions_only"] = True
    caps["tier"] = max(1, min(10, caps["tier"] + tier_bonus))
    return caps


# ─── 核心评分函数 ─────────────────────────────────────────────────────────────
def score_model_for_task(caps: Dict[str, Any], task: str) -> float:
    """
    给模型对特定任务进行打分。
    - 布尔型必要能力不满足 → 返回 -1（排除）
    - 否则加权求和，加上 tier 奖励
    """
    reqs = TASK_REQUIREMENTS.get(task, {})
    if not reqs:
        return 0.0

    score = 0.0
    for dim, requirement in reqs.items():
        model_val = caps.get(dim)
        if isinstance(requirement, bool):
            if requirement and not model_val:
                return -1.0  # 硬性排除
            # 不需要该能力 → 不加分也不扣分
        elif isinstance(requirement, (int, float)):
            # 数值型：越接近需求，评分越高；超出上限不额外加分
            val = float(model_val or 0)
            score += requirement * (val / 10.0)

    # tier 贡献（最高加 2 分，避免完全覆盖任务匹配度）
    score += caps.get("tier", 5) * 0.2
    return round(score, 4)


class ModelManager:
    """
    动态模型管理器。

    用法：
        manager = ModelManager(client)
        model_map = manager.get_model_map()     # 得到任务 → 模型ID 的映射
        model_id  = manager.get_model_for_task("CODER")
        manager.refresh()                       # 手动刷新

    get_model_map() 会在第一次调用（或缓存过期）时查询 API，
    后续调用直接返回缓存，直到 TTL 到期。
    """

    DEFAULT_CACHE_TTL = 6 * 3600  # 6 小时
    FAST_RETRY_AFTER = 300  # API 失败后 5 分钟内不重试

    def __init__(self, client, cache_ttl: int = DEFAULT_CACHE_TTL):
        self._client = client
        self._cache_ttl = cache_ttl
        self._cached_map: Optional[Dict[str, str]] = None
        self._cached_caps: Dict[str, Dict[str, Any]] = {}  # model_id → caps
        self._available_ids: List[str] = []
        self._last_refresh = 0.0
        self._last_fail_ts = 0.0

    # ── 公共接口 ─────────────────────────────────────────────────────────────

    def get_model_for_task(self, task: str) -> Optional[str]:
        """返回指定任务的最佳模型 ID；本地任务返回 'local-executor'。"""
        if task in LOCAL_EXECUTOR_TASKS:
            return "local-executor"
        return self.get_model_map().get(task)

    def get_model_map(self) -> Dict[str, str]:
        """
        返回完整任务 → 模型ID 映射。
        优先读缓存，过期后自动刷新；API 失败则保留上次缓存或使用静态默认值。
        """
        now = time.time()
        if (
            self._cached_map is not None
            and (now - self._last_refresh) < self._cache_ttl
        ):
            return self._cached_map
        # 失败冷却期内不重试
        if self._last_fail_ts and (now - self._last_fail_ts) < self.FAST_RETRY_AFTER:
            return self._cached_map or self._static_default_map()
        self._rebuild()
        return self._cached_map or self._static_default_map()

    def get_available_models(self) -> List[Dict[str, Any]]:
        """
        返回当前可用模型列表，每个元素包含 id / display / tier / caps 等信息。
        供前端展示或调试用。
        """
        self.get_model_map()  # 触发一次刷新（如有必要）
        result = []
        for mid in self._available_ids:
            caps = self._cached_caps.get(mid, {})
            result.append(
                {
                    "id": mid,
                    "display": caps.get("display", mid),
                    "tier": caps.get("tier", 5),
                    "provider": caps.get("provider", "gemini"),
                    "strengths": caps.get("strengths", []),
                    "capabilities": {
                        "multimodal": caps.get("multimodal", False),
                        "image_gen": caps.get("image_gen", False),
                        "grounding": caps.get("grounding", False),
                        "function_calling": caps.get("function_calling", False),
                        "interactions_only": caps.get("interactions_only", False),
                        "_inferred": caps.get("_inferred", False),
                    },
                }
            )
        return sorted(result, key=lambda x: x["tier"], reverse=True)

    def get_model_map_with_scores(self) -> Dict[str, Dict[str, Any]]:
        """
        返回带有评分明细的路由结果，供调试/API 展示用。
        """
        model_map = self.get_model_map()
        out = {}
        for task, model_id in model_map.items():
            caps = self._cached_caps.get(model_id, {})
            out[task] = {
                "model_id": model_id,
                "display": caps.get("display", model_id),
                "tier": caps.get("tier", 0),
                "score": score_model_for_task(caps, task) if caps else 0,
                "provider": caps.get(
                    "provider", "local" if model_id == "local-executor" else "gemini"
                ),
                "_inferred": caps.get("_inferred", False),
            }
        return out

    def get_interactions_only_models(self) -> Set[str]:
        """返回必须走 Interactions API 的模型集合。"""
        self.get_model_map()
        detected = {
            mid
            for mid, caps in self._cached_caps.items()
            if caps.get("interactions_only", False)
        }
        return _get_interactions_only_model_set(detected)

    def get_fallback_model(self) -> str:
        """返回最适合做通用降级的模型（支持 generate_content，速度快、稳定可用）。"""
        self.get_model_map()
        # 优先选用已知稳定的 Flash 模型，避免 pro-preview 等访问受限的模型
        _PREFERRED_FALLBACKS = [
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.5-pro",
            "gemini-3-pro-preview",
        ]
        for mid in _PREFERRED_FALLBACKS:
            caps = self._cached_caps.get(mid)
            if (
                caps
                and not caps.get("interactions_only", False)
                and not caps.get("image_gen", False)
            ):
                return mid
        # 兜底：按速度/质量/tier 综合排序，不再硬编码排除 preview 系列。
        # 实际可用性由运行时超时+降级链保证，避免静态限制阻断新模型。
        candidates = [
            (mid, caps)
            for mid, caps in self._cached_caps.items()
            if not caps.get("interactions_only", False)
            and not caps.get("image_gen", False)
            and mid != "local-executor"
        ]
        if not candidates:
            return "gemini-2.5-flash"
        best = max(
            candidates,
            key=lambda x: (
                x[1].get("speed", 0) * 0.6
                + x[1].get("quality", 0) * 0.3
                + x[1].get("tier", 0) * 0.1
            ),
        )
        return best[0]

    def refresh(self) -> Dict[str, str]:
        """强制刷新模型列表，返回新的 model_map。"""
        self._last_refresh = 0.0
        self._last_fail_ts = 0.0
        return self.get_model_map()

    # ── 私有方法 ─────────────────────────────────────────────────────────────

    def _rebuild(self):
        """从 API 获取可用模型列表，重新构建 model_map 和 capabilities 缓存。"""
        try:
            discovered = self._fetch_available_model_ids()
        except Exception as exc:
            logger.warning(f"[ModelManager] 模型列表获取失败: {exc}")
            self._last_fail_ts = time.time()
            # 如无缓存，使用静态默认
            if self._cached_map is None:
                self._cached_map = self._static_default_map()
                self._preload_static_caps()
            return

        try:
            from app.core.llm.model_selection import (
                get_configured_cloud_model,
                get_configured_cloud_provider,
            )

            cloud_provider = get_configured_cloud_provider()
            if cloud_provider != "gemini":
                for task in ("CHAT", "CODER", "FILE_TASK", "AGENT"):
                    configured_model = get_configured_cloud_model(task_type=task, provider=cloud_provider)
                    if configured_model:
                        discovered.append(configured_model)
                if cloud_provider == "deepseek":
                    discovered.extend(["deepseek-v4-pro", "deepseek-v4-flash"])
        except Exception as exc:
            logger.debug("[ModelManager] configured cloud model injection skipped: %s", exc)

        # 路由使用 Gemini API 发现结果 + 当前配置的非 Gemini 云端主模型。
        self._available_ids = list(dict.fromkeys(discovered))  # 去重保序

        # 构建能力缓存：API 发现的模型优先用注册表补充能力，否则自动推断
        for mid in self._available_ids:
            if mid not in self._cached_caps:
                if mid in KNOWN_MODEL_REGISTRY:
                    caps = KNOWN_MODEL_REGISTRY[mid].copy()
                else:
                    caps = infer_capabilities(mid)
                if is_interactions_only_model(mid):
                    caps["interactions_only"] = True
                self._cached_caps[mid] = caps

        # 额外预加载注册表（用于 get_interactions_only_models 等能力查询，不影响路由评分）
        for mid, caps in KNOWN_MODEL_REGISTRY.items():
            if mid not in self._cached_caps:
                preload_caps = caps.copy()
                if is_interactions_only_model(mid):
                    preload_caps["interactions_only"] = True
                self._cached_caps[mid] = preload_caps

        # 为每个任务类型选择最优模型（仅从 API 实际发现的模型中选，跳过 interactions_only）
        new_map: Dict[str, str] = {}
        static_defaults = self._static_default_map()
        for task in TASK_REQUIREMENTS:
            best = self._select_best(task, self._available_ids)
            if best:
                new_map[task] = best
            elif task in static_defaults:
                new_map[task] = static_defaults[task]
        for task in LOCAL_EXECUTOR_TASKS:
            new_map[task] = "local-executor"

        self._cached_map = new_map
        self._last_refresh = time.time()
        self._last_fail_ts = 0.0

        logger.info(
            f"[ModelManager] 刷新完成 — 发现 {len(discovered)} 个可用模型，"
            f"路由 {len(new_map)} 个任务"
        )
        self._log_routing_summary(new_map)

    def _fetch_available_model_ids(self) -> List[str]:
        """
        调用 Gemini API 列出可用模型，返回 model ID 列表（去掉 'models/' 前缀）。
        过滤掉 embedding、音频等纯特殊用途模型。
        """
        exclude_keywords = {"embedding", "aqa", "tts", "speech", "whisper"}
        configured_blocklist = get_model_blocklist_from_env()
        include_actions = {
            "generateContent",
            "generate_content",
            "streamGenerateContent",
            "generateImages",
        }

        include_actions_normalized = {
            re.sub(r"[^a-z]", "", action.lower()) for action in include_actions
        }

        def _supports_generation(model: Any) -> bool:
            supported_actions = getattr(model, "supported_actions", None) or []
            if not supported_actions:
                return True
            normalized_actions = {
                re.sub(r"[^a-z]", "", str(action).lower())
                for action in supported_actions
                if action
            }
            return bool(normalized_actions & include_actions_normalized)

        def _append_model(model: Any, collector: List[str]) -> None:
            raw_name = getattr(model, "name", "") or ""
            mid = normalize_model_id(raw_name)
            if not mid:
                return
            mid_lower = mid.lower()
            if any(kw in mid_lower for kw in exclude_keywords):
                return
            if mid in configured_blocklist:
                return
            if not _supports_generation(model):
                return
            collector.append(mid)

        def _coerce_list_response(page: Any) -> List[Any]:
            if page is None:
                return []
            try:
                return list(page)
            except TypeError as exc:
                raise RuntimeError("client.models.list() returned a non-iterable response") from exc

        model_ids: List[str] = []
        try:
            # google-genai SDK: client.models.list() 返回 Model 对象的迭代器
            page = self._client.models.list(config={"page_size": 200})
            for model in _coerce_list_response(page):
                _append_model(model, model_ids)
        except TypeError:
            # 部分 SDK 版本 list() 不接受 config 参数
            for model in _coerce_list_response(self._client.models.list()):
                _append_model(model, model_ids)

        logger.info(f"[ModelManager] API 返回 {len(model_ids)} 个可用模型")
        return model_ids

    def _merge_with_registry(self, discovered: List[str]) -> List[str]:
        """
        （保留接口供外部调用，_rebuild 已不使用此方法进行路由。）
        仅返回 API 发现的模型列表，不再强制追加注册表中未被 API 返回的模型，
        避免将已下线或不可用模型混入评分路由池。
        """
        return list(dict.fromkeys(discovered))  # 去重保序

    def _select_best(self, task: str, model_ids: List[str]) -> Optional[str]:
        """从提供的模型列表中，为指定任务选出得分最高的模型。

        路由表可以选择 interactions-only 模型；调用层会按模型能力切到
        Interactions API。只有 get_fallback_model() 这类直接 generate_content
        的稳定兜底路径需要排除它们。
        """
        for preferred_id in _TASK_MODEL_PREFERENCES.get(task, []):
            if preferred_id not in model_ids:
                continue
            caps = self._cached_caps.get(preferred_id)
            if not caps:
                continue
            return preferred_id

        best_id = None
        best_score = -1.0

        for mid in model_ids:
            caps = self._cached_caps.get(mid)
            if not caps:
                continue
            sc = score_model_for_task(caps, task)
            if sc < 0:
                continue
            if sc > best_score:
                best_score = sc
                best_id = mid
        return best_id

    def _preload_static_caps(self):
        """将注册表的能力描述预加载到缓存，供 API 失败时使用。"""
        for mid, caps in KNOWN_MODEL_REGISTRY.items():
            if mid not in self._cached_caps:
                self._cached_caps[mid] = caps.copy()

    @staticmethod
    def _static_default_map() -> Dict[str, str]:
        """API 不可用时的静态兜底映射。"""
        defaults = {
            "CHAT": "deepseek-v4-pro",
            "CODER": "deepseek-v4-pro",
            "WEB_SEARCH": "deepseek-v4-pro",
            "VISION": "gemini-3-flash-preview",
            "RESEARCH": "deepseek-v4-pro",
            "FILE_GEN": "deepseek-v4-pro",
            "FILE_TASK": "deepseek-v4-pro",
            "DOC_ANNOTATE": "deepseek-v4-pro",
            "MEETING_EXTRACT": "deepseek-v4-pro",
            "PAINTER": "gemini-3.1-flash-image-preview",
            "AGENT": "deepseek-v4-pro",
            "SYSTEM": "local-executor",
            "FILE_OP": "local-executor",
            "COMPLEX": "deepseek-v4-pro",
        }
        return defaults

    @staticmethod
    def _log_routing_summary(model_map: Dict[str, str]):
        lines = ["[ModelManager] 最新路由表:"]
        for task, mid in sorted(model_map.items()):
            lines.append(f"  {task:<12} → {mid}")
        logger.info("\n".join(lines))
