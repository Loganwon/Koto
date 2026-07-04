# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_system_prompts_limit_app_control_to_whitelisted_launches():
    sources = [
        _read("web/chat_system_instruction.py"),
        _read("web/context_injector.py"),
    ]

    for source in sources:
        assert "联动本地应用" not in source
        assert "可以解释本地应用、路径和快捷键相关操作" in source
        assert "可以执行 Koto 白名单内的简单应用启动" in source
        assert "不发送消息、不截图、不代替用户操作应用内容" in source

    assert "把无法直接执行的系统或应用控制请求伪装成已完成" in sources[0]


def test_agent_handler_uses_shared_local_model_helpers():
    source = _read("web/services/chat_stream/agent_handler.py")

    assert "from app.core.shared.llm_helpers import (" in source
    assert "get_local_provider as _get_local_provider" in source
    assert "is_ollama_alive as _is_ollama_alive" in source
    assert "from app.core.socket_handler import _is_ollama_alive, _get_local_provider" not in source
