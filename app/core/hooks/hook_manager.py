# -*- coding: utf-8 -*-
"""
Koto HookManager — 用户生命周期钩子系统
==========================================
任何人都可以在 config/hooks/ 目录下放置 Python 脚本，定义函数来拦截
Koto 的处理管线（无需修改核心代码）。

支持的钩子函数签名（文件里只需定义你关心的那几个）：

  def pre_message(text: str, ctx: HookContext) -> str | None:
      \"\"\"在用户消息发往 LLM 前调用。返回新的文本字符串即可替换原始输入；返回 None 则不替换。\"\"\"

  def post_response(text: str, ctx: HookContext) -> str | None:
      \"\"\"在 AI 回答返回用户前调用。返回新的文本替换回复；返回 None 则不替换。\"\"\"

  def on_skill_change(skill_id: str, enabled: bool, ctx: HookContext) -> None:
      \"\"\"Skill 被启用/禁用时调用（无返回值）。\"\"\"

  def on_session_start(session_id: str, ctx: HookContext) -> None:
      \"\"\"新会话被创建时调用（无返回值）。\"\"\"

  def on_tool_result(tool_name: str, result: str, ctx: HookContext) -> str | None:
      \"\"\"每次工具调用完成后调用。返回新字符串可替换工具结果；返回 None 则不替换。\"\"\"

示例 config/hooks/logger_hook.py：

    import logging
    logger = logging.getLogger("my_hook")

    def pre_message(text, ctx):
        logger.info(f"[HOOK] 收到消息 ({ctx.task_type}): {text[:80]}")

    def post_response(text, ctx):
        logger.info(f"[HOOK] AI 回复: {text[:80]}")

关键特性：
  - 所有钩子出错都被静默捕获，永远不会影响主管线
  - 钩子文件热重载：每次 SkillManager.reload() 时自动重新加载钩子文件
  - HookContext 包含：session_id、task_type、skill_id、active_skills、extra（可扩展字典）

@version 2026-05-26
"""

from __future__ import annotations

import logging
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_HOOKS_DIR = Path(__file__).parent.parent.parent.parent / "config" / "hooks"

# 钩子点枚举
HOOK_PRE_MESSAGE      = "pre_message"
HOOK_POST_RESPONSE    = "post_response"
HOOK_ON_SKILL_CHANGE  = "on_skill_change"
HOOK_ON_SESSION_START = "on_session_start"
HOOK_ON_TOOL_RESULT   = "on_tool_result"

_KNOWN_HOOKS = {
    HOOK_PRE_MESSAGE,
    HOOK_POST_RESPONSE,
    HOOK_ON_SKILL_CHANGE,
    HOOK_ON_SESSION_START,
    HOOK_ON_TOOL_RESULT,
}


@dataclass
class HookContext:
    """传入所有钩子函数的上下文对象（只读，按需扩展）。"""

    session_id: str = ""
    task_type: str = ""
    skill_id: str = ""
    active_skills: List[str] = field(default_factory=list)
    # 可自由读写的扩展字典（钩子之间可通过此字段传递临时状态）
    extra: Dict[str, Any] = field(default_factory=dict)


class HookManager:
    """
    单例管理器，负责加载 config/hooks/*.py 并在生命周期各处触发钩子。

    取得单例：from app.core.hooks.hook_manager import get_hook_manager
    """

    _instance: Optional["HookManager"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        # hook_name → List[Callable]
        self._hooks: Dict[str, List[Callable]] = {k: [] for k in _KNOWN_HOOKS}
        self._loaded_files: List[str] = []
        self._load()

    # ── 单例 ──────────────────────────────────────────────────────────────────

    @classmethod
    def instance(cls) -> "HookManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reload(cls) -> None:
        """重新加载所有钩子文件（热更新，不重启）。"""
        with cls._lock:
            cls._instance = cls()
        logger.info("[HookManager] 钩子文件已热重载")

    # ── 加载 ──────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        hooks_dir = _HOOKS_DIR
        if not hooks_dir.is_dir():
            logger.debug("[HookManager] config/hooks/ 不存在，跳过加载")
            return

        # 确保 hooks_dir 在 sys.path 中，以便钩子脚本能导入彼此
        hooks_str = str(hooks_dir)
        if hooks_str not in sys.path:
            sys.path.insert(0, hooks_str)

        py_files = sorted(hooks_dir.glob("*.py"))
        for py_file in py_files:
            if py_file.name.startswith("_"):
                continue
            self._load_file(py_file)

        if self._loaded_files:
            logger.info(
                f"[HookManager] 已加载 {len(self._loaded_files)} 个钩子文件: "
                f"{[Path(f).name for f in self._loaded_files]}"
            )

    def _load_file(self, py_file: Path) -> None:
        module_name = f"_koto_hook_{py_file.stem}"
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                return
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            registered_count = 0
            for hook_name in _KNOWN_HOOKS:
                fn = getattr(mod, hook_name, None)
                if callable(fn):
                    self._hooks[hook_name].append(fn)
                    registered_count += 1

            if registered_count > 0:
                self._loaded_files.append(str(py_file))
                logger.debug(
                    f"[HookManager] {py_file.name}: 注册了 {registered_count} 个钩子函数"
                )
            else:
                logger.debug(
                    f"[HookManager] {py_file.name}: 未找到已知钩子函数，跳过"
                )
        except Exception as e:
            logger.warning(f"[HookManager] 加载 {py_file.name} 失败: {e}")

    # ── 触发器 ────────────────────────────────────────────────────────────────

    def fire_pre_message(self, text: str, ctx: HookContext) -> str:
        """触发 pre_message 钩子链。返回（可能被修改过的）文本。"""
        result = text
        for fn in self._hooks[HOOK_PRE_MESSAGE]:
            try:
                ret = fn(result, ctx)
                if isinstance(ret, str):
                    result = ret
            except Exception as e:
                logger.warning(f"[HookManager] pre_message 钩子异常: {e}")
        return result

    def fire_post_response(self, text: str, ctx: HookContext) -> str:
        """触发 post_response 钩子链。返回（可能被修改过的）回复文本。"""
        result = text
        for fn in self._hooks[HOOK_POST_RESPONSE]:
            try:
                ret = fn(result, ctx)
                if isinstance(ret, str):
                    result = ret
            except Exception as e:
                logger.warning(f"[HookManager] post_response 钩子异常: {e}")
        return result

    def fire_on_skill_change(
        self, skill_id: str, enabled: bool, ctx: Optional[HookContext] = None
    ) -> None:
        """触发 on_skill_change 钩子（无返回值）。"""
        _ctx = ctx or HookContext()
        for fn in self._hooks[HOOK_ON_SKILL_CHANGE]:
            try:
                fn(skill_id, enabled, _ctx)
            except Exception as e:
                logger.warning(f"[HookManager] on_skill_change 钩子异常: {e}")

    def fire_on_session_start(self, session_id: str, ctx: Optional[HookContext] = None) -> None:
        """触发 on_session_start 钩子（无返回值）。"""
        _ctx = ctx or HookContext(session_id=session_id)
        for fn in self._hooks[HOOK_ON_SESSION_START]:
            try:
                fn(session_id, _ctx)
            except Exception as e:
                logger.warning(f"[HookManager] on_session_start 钩子异常: {e}")

    def fire_on_tool_result(
        self, tool_name: str, result: str, ctx: HookContext
    ) -> str:
        """触发 on_tool_result 钩子链。返回（可能被修改过的）工具结果。"""
        current = result
        for fn in self._hooks[HOOK_ON_TOOL_RESULT]:
            try:
                ret = fn(tool_name, current, ctx)
                if isinstance(ret, str):
                    current = ret
            except Exception as e:
                logger.warning(f"[HookManager] on_tool_result 钩子异常: {e}")
        return current

    def has_hooks(self, hook_name: str) -> bool:
        """是否有任何钩子注册到某个钩子点。"""
        return len(self._hooks.get(hook_name, [])) > 0

    def summary(self) -> Dict[str, int]:
        """返回各钩子点注册的函数数量（用于调试）。"""
        return {k: len(v) for k, v in self._hooks.items() if v}


def get_hook_manager() -> HookManager:
    """获取 HookManager 单例（推荐使用方式）。"""
    return HookManager.instance()
