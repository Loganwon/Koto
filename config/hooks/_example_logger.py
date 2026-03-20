"""
示例 Hook 文件 — 消息日志记录器
将此文件重命名为 example_logger.py（去掉开头的 _）即可激活。

这个示例展示了如何使用 pre_message 和 post_response 钩子
将 Koto 的对话记录到本地日志文件。
"""
import os
import logging
from datetime import datetime

# 日志文件路径（相对于 Koto 根目录）
_LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "chat_history.log")
_logger = logging.getLogger("koto.hooks.logger")


def _write_log(tag: str, text: str, session_id: str = "") -> None:
    try:
        os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{tag}] <{session_id}> {text[:500]}\n")
    except Exception as e:
        _logger.debug("Hook logger write failed: %s", e)


def pre_message(text: str, ctx) -> None:
    """记录用户发送的消息（在 AI 处理之前）"""
    _write_log("USER", text, ctx.session_id if ctx else "")
    return None  # 不修改消息内容


def post_response(text: str, ctx) -> None:
    """记录 AI 回复的消息"""
    _write_log("KOTO", text, ctx.session_id if ctx else "")
    return None  # 不修改回复内容


def on_skill_change(skill_id: str, enabled: bool, ctx) -> None:
    """记录 Skill 切换事件"""
    state = "启用" if enabled else "禁用"
    _write_log("SKILL", f"'{skill_id}' 已{state}", ctx.session_id if ctx else "")
