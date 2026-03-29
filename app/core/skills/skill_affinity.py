# -*- coding: utf-8 -*-
"""
Koto SkillAffinityTracker — 用户技能亲和度学习引擎
===================================================

跟踪用户对各种 Skill 的偏好行为，构建个性化的技能推荐排名附加信号。

核心数据：
- 每次用户手动启用、接受推荐、或点击某个 Skill → 记录一次正向信号
- 每 30 天旧信号自动衰减（exponential decay），避免历史偏好主导
- 提供 `get_affinity_scores()` 接口，返回 skill_id → 0.0~1.0 的亲和度

数据存储：config/skill_affinity.json
{
    "skill_id": {
        "activations": 5,
        "last_used": "2026-03-22T10:00:00",
        "decay_score": 0.82
    }
}
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 衰减半衰期（天）：超过此天数的使用记录贡献减半
_DECAY_HALF_LIFE_DAYS = 30.0
# 最大归一化激活次数（用于 score 归一化到 0~1）
_MAX_ACTIVATIONS_FOR_NORM = 20
# 保存节流：每 N 次记录后才写盘
_SAVE_THROTTLE = 3


def _get_affinity_path() -> Path:
    if getattr(sys, "frozen", False):
        root = Path(os.path.dirname(sys.executable))
    else:
        root = Path(__file__).resolve().parents[3]
    return root / "config" / "skill_affinity.json"


class SkillAffinityTracker:
    """追踪用户 Skill 使用偏好的单例。"""

    _instance: Optional["SkillAffinityTracker"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._path = _get_affinity_path()
        self._data: Dict[str, dict] = {}
        self._dirty_count = 0
        self._data_lock = threading.Lock()
        self._load()

    @classmethod
    def get_instance(cls) -> "SkillAffinityTracker":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── 公开 API ──────────────────────────────────────────────────────────────

    def record_activation(self, skill_id: str):
        """记录一次 Skill 激活（用户手动启用 / 接受推荐 / 临时注入被使用）。"""
        now = datetime.now().isoformat()
        with self._data_lock:
            entry = self._data.get(skill_id)
            if entry is None:
                entry = {"activations": 0, "last_used": now, "decay_score": 0.0}
                self._data[skill_id] = entry
            entry["activations"] = entry.get("activations", 0) + 1
            entry["last_used"] = now
            self._dirty_count += 1
            if self._dirty_count >= _SAVE_THROTTLE:
                self._save()
                self._dirty_count = 0

    def get_affinity_scores(self) -> Dict[str, float]:
        """
        返回所有已知 Skill 的亲和度分数（0.0~1.0）。

        Score = normalized_activations * recency_decay
        """
        now = datetime.now()
        decay_lambda = math.log(2) / max(_DECAY_HALF_LIFE_DAYS, 1.0)
        scores: Dict[str, float] = {}

        with self._data_lock:
            for skill_id, entry in self._data.items():
                activations = entry.get("activations", 0)
                last_used = entry.get("last_used", "")

                # Normalize activations (0~1)
                norm_act = min(activations / _MAX_ACTIVATIONS_FOR_NORM, 1.0)

                # Recency decay
                recency = 0.5
                if last_used:
                    try:
                        dt = datetime.fromisoformat(last_used)
                        age_days = max((now - dt).total_seconds() / 86400.0, 0.0)
                        recency = math.exp(-decay_lambda * age_days)
                    except (ValueError, TypeError):
                        pass

                scores[skill_id] = round(norm_act * recency, 4)

        return scores

    def get_top_skills(self, n: int = 5) -> list:
        """返回亲和度最高的 N 个 skill_id。"""
        scores = self.get_affinity_scores()
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [sid for sid, _ in ranked[:n]]

    def flush(self):
        """强制写盘（应用关闭时调用）。"""
        with self._data_lock:
            self._save()
            self._dirty_count = 0

    # ── 内部方法 ──────────────────────────────────────────────────────────────

    def _load(self):
        try:
            if self._path.exists():
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._data = raw
                    logger.debug(f"[SkillAffinity] 加载 {len(self._data)} 条亲和度记录")
        except Exception as e:
            logger.debug(f"[SkillAffinity] 加载失败: {e}")
            self._data = {}

    def _save(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug(f"[SkillAffinity] 保存失败: {e}")
