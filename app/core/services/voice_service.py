# -*- coding: utf-8 -*-
"""
app/core/services/voice_service.py
===================================
语音服务适配层 — 将 `web/voice_engine.py` 的功能暴露为 app/core 内的服务接口。

使用方式：
    from app.core.services.voice_service import VoiceService

    # 获取引擎状态
    status = VoiceService.get_status()

    # 流式识别（SSE 场景）
    for event in VoiceService.recognize_stream():
        ...

    # 停止识别
    VoiceService.request_stop()

设计原则
────────
- **零副作用导入**：导入本模块不会触发模型加载。
- **向后兼容**：`web/voice_engine.py` 保持不变，双路可用。
- **懒加载**：所有 `web.voice_engine` 函数在首次调用时才会被导入。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Generator

logger = logging.getLogger(__name__)


class VoiceService:
    """
    语音服务门面（Facade）。

    所有方法均为静态方法，调用方无需实例化。
    内部将调用委托给 `web.voice_engine` 中对应的函数。
    """

    @staticmethod
    def get_status() -> Dict[str, Any]:
        """
        返回当前语音引擎的就绪状态。

        返回格式（同 web/voice_engine.get_status()）：
            {
                "available": bool,
                "model_loaded": bool,
                "engine": "vosk" | "whisper" | "unavailable",
                "label": str,
                "model_path": str,
                "whisper_available": bool,
            }
        """
        try:
            from web.voice_engine import get_status
            return get_status()
        except ImportError as exc:
            logger.warning("[VoiceService] voice_engine 导入失败: %s", exc)
            return {
                "available": False,
                "model_loaded": False,
                "engine": "unavailable",
                "label": "语音模块未安装",
                "model_path": "",
                "whisper_available": False,
            }

    @staticmethod
    def request_stop() -> None:
        """请求中止当前正在运行的识别流。"""
        try:
            from web.voice_engine import request_stop
            request_stop()
        except ImportError as exc:
            logger.warning("[VoiceService] voice_engine 导入失败（request_stop）: %s", exc)

    @staticmethod
    def preload() -> None:
        """
        预加载语音模型（可在应用启动时调用以减少首次识别延迟）。
        """
        try:
            from web.voice_engine import preload
            preload()
        except ImportError as exc:
            logger.warning("[VoiceService] voice_engine 导入失败（preload）: %s", exc)

    @staticmethod
    def recognize_stream(
        max_wait: float = 8.0,
        max_speech: float = 30.0,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        流式语音识别生成器（供 Flask SSE 路由直接迭代）。

        Args:
            max_wait:   等待用户开口的最长时间（秒）
            max_speech: 整段录音的最大时长（秒）

        Yields:
            {'type': 'ping',    'elapsed': float}
            {'type': 'partial', 'text': str}
            {'type': 'final',   'text': str, 'engine': str}
            {'type': 'error',   'message': str}
        """
        try:
            from web.voice_engine import recognize_stream
            yield from recognize_stream(max_wait=max_wait, max_speech=max_speech)
        except ImportError as exc:
            logger.warning("[VoiceService] voice_engine 导入失败（recognize_stream）: %s", exc)
            yield {"type": "error", "message": f"语音模块不可用: {exc}"}
        except Exception as exc:
            logger.error("[VoiceService] recognize_stream 异常: %s", exc, exc_info=True)
            yield {"type": "error", "message": str(exc)}
