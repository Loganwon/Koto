"""Model preflight policy for streaming document-feedback analysis."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class AnalysisPreflight:
    model_id: str
    chunk_size: int
    events: List[Dict[str, Any]]


def prepare_analysis_preflight(system: Any, model_id: str) -> AnalysisPreflight:
    """Pick chunk sizing and report an optional safe model fallback."""
    ai_enabled = bool(system.client) and os.getenv("KOTO_DISABLE_AI") != "1"
    if not ai_enabled:
        return AnalysisPreflight(model_id=model_id, chunk_size=10_000, events=[])

    chunk_size = (
        system._env_int("KOTO_DOC_REVIEW_LOCAL_CHUNK_SIZE", 2400, minimum=1200)
        if system._is_local_client()
        else 4000
    )
    probed_model = system._probe_working_model(model_id)
    if probed_model is None:
        return AnalysisPreflight(
            model_id=model_id,
            chunk_size=chunk_size,
            events=[
                {
                    "stage": "warning",
                    "progress": 16,
                    "message": "⚠️ AI API 暂时全部不可用，将使用本地规则兜底（质量有限）",
                    "detail": "建议稍后重试",
                }
            ],
        )
    if probed_model != model_id:
        return AnalysisPreflight(
            model_id=probed_model,
            chunk_size=chunk_size,
            events=[
                {
                    "stage": "info",
                    "progress": 16,
                    "message": f"🔄 {model_id} 当前负载过高，已自动切换到 {probed_model}",
                    "detail": "系统自动选择可用模型继续任务",
                }
            ],
        )
    return AnalysisPreflight(model_id=model_id, chunk_size=chunk_size, events=[])
