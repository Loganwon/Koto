"""Presentation-neutral Ollama compatibility gate for the model installer."""

from __future__ import annotations

from collections.abc import Callable

try:
    from src.ollama_compat import inspect_model_compatibility
except ImportError:
    from ollama_compat import inspect_model_compatibility


def reject_incompatible_model(
    tag: str,
    *,
    set_error: Callable[[], None],
    log: Callable[[str], None],
    schedule: Callable[[Callable[[], None]], None],
    show_error: Callable[[str, str], None],
    restore_actions: Callable[[], None],
) -> bool:
    compatibility = inspect_model_compatibility(tag)
    if compatibility.get("compatible") is not False:
        return False

    current = compatibility.get("current_version") or "未知"
    required = compatibility.get("required_version") or "最新版"
    set_error()
    log(
        f"❌ 模型已下载，但 Ollama {current} 无法加载；"
        f"该模型要求 Ollama {required} 或更高版本"
    )
    schedule(
        lambda: show_error(
            "需要升级 Ollama",
            f"模型 {tag} 要求 Ollama {required} 或更高版本。\n"
            f"当前版本：{current}\n\n请先更新 Ollama，再重新验证模型。",
        )
    )
    schedule(restore_actions)
    return True
