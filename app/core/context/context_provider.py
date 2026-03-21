# -*- coding: utf-8 -*-
"""
Koto ContextProvider — 用户自定义上下文注入系统
================================================
用户在 config/context/ 目录下放置 JSON 文件，即可向 AI 的系统提示中
持久注入自定义上下文（无需修改任何代码）。

每个 JSON 文件就是一个「上下文块」，格式如下：

    {
      "id": "my_projects",
      "name": "我的项目背景",
      "content": "我目前正在开发一个 Python 的 Flask Web 应用，叫做 Koto...",
      "enabled": true,
      "priority": 50,
      "task_types": [],
      "inject_mode": "system",
      "template_vars": {}
    }

字段说明：
  id          : 唯一标识符（小写+下划线，必填）
  name        : 显示名称（可选，用于日志）
  content     : 要注入的文本（支持 {variable} 模板，使用 template_vars 或 user_profile 中的字段）
  enabled     : true/false，是否启用（默认 true）
  priority    : 整数，越小越先注入（默认 50）
  task_types  : 生效的任务类型列表（[] 或省略 = 所有任务）
  inject_mode : "system"（追加到系统提示，默认）
                "header"（插在系统提示开头）

示例 — config/context/my_background.json：
    {
      "id": "my_background",
      "name": "个人背景",
      "content": "用户是一名后端工程师，主要使用 Python 和 Go，公司用 K8s 部署。回答问题时优先考虑这个技术栈。",
      "enabled": true,
      "priority": 10
    }

更多示例见 config/context/_EXAMPLES/ 目录。

与 Skills 的区别：
  - Skills 改变 AI 的行为方式（如：步骤化输出、严谨模式）
  - ContextProvider 注入背景知识（如：项目信息、用户偏好、领域背景）

@version 2026-05-26
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CONTEXT_DIR = Path(__file__).parent.parent.parent.parent / "config" / "context"
_USER_PROFILE_PATH = Path(__file__).parent.parent.parent.parent / "config" / "user_profile.json"


class ContextBlock:
    """单个上下文块的内存表示。"""

    __slots__ = ("id", "name", "content", "enabled", "priority", "task_types",
                 "inject_mode", "template_vars")

    def __init__(self, data: Dict[str, Any]) -> None:
        self.id:            str       = data.get("id", "")
        self.name:          str       = data.get("name", self.id)
        self.content:       str       = data.get("content", "")
        self.enabled:       bool      = data.get("enabled", True)
        self.priority:      int       = int(data.get("priority", 50))
        self.task_types:    List[str] = [t.upper() for t in data.get("task_types", [])]
        self.inject_mode:   str       = data.get("inject_mode", "system")  # system | header
        self.template_vars: Dict      = data.get("template_vars", {})

    def matches(self, task_type: Optional[str]) -> bool:
        if not self.enabled:
            return False
        if not self.task_types:
            return True
        if task_type and task_type.upper() in self.task_types:
            return True
        return False


class ContextProvider:
    """
    单例上下文注入器。

    用法：
        from app.core.context.context_provider import get_context_provider
        provider = get_context_provider()
        extra = provider.build_injection(task_type="CHAT")
        # extra 是一个 dict with keys "header" and "system"
    """

    _instance: Optional["ContextProvider"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._blocks: List[ContextBlock] = []
        self._user_profile: Dict[str, Any] = {}
        self._load_user_profile()
        self._load()

    # ── 单例 ──────────────────────────────────────────────────────────────────

    @classmethod
    def instance(cls) -> "ContextProvider":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reload(cls) -> None:
        """重新加载所有上下文文件（热更新）。"""
        with cls._lock:
            cls._instance = cls()
        logger.info("[ContextProvider] 上下文文件已热重载")

    # ── 加载 ──────────────────────────────────────────────────────────────────

    def _load_user_profile(self) -> None:
        try:
            if _USER_PROFILE_PATH.exists():
                self._user_profile = json.loads(_USER_PROFILE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug(f"[ContextProvider] 加载 user_profile 失败: {e}")

    def _load(self) -> None:
        ctx_dir = _CONTEXT_DIR
        if not ctx_dir.is_dir():
            logger.debug("[ContextProvider] config/context/ 不存在，跳过加载")
            return

        loaded = 0
        for json_file in sorted(ctx_dir.glob("*.json")):
            if json_file.name.startswith("_"):
                continue
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if not data.get("id"):
                    data["id"] = json_file.stem
                block = ContextBlock(data)
                self._blocks.append(block)
                loaded += 1
                logger.debug(f"[ContextProvider] 加载上下文块: {block.id} (priority {block.priority})")
            except Exception as e:
                logger.warning(f"[ContextProvider] 加载 {json_file.name} 失败: {e}")

        # 按优先级排序
        self._blocks.sort(key=lambda b: b.priority)

        if loaded > 0:
            logger.info(f"[ContextProvider] 已加载 {loaded} 个上下文块")

    # ── 构建注入文本 ──────────────────────────────────────────────────────────

    def _render(self, block: ContextBlock) -> str:
        """渲染模板变量替换。"""
        content = block.content
        if "{" not in content:
            return content

        # 合并：block 自身的 template_vars 优先，不够再从 user_profile 补
        vars_map: Dict[str, Any] = dict(self._user_profile)
        vars_map.update(block.template_vars)

        try:
            return content.format_map(_SafeFormatMap(vars_map))
        except Exception as e:
            logger.debug(f"[ContextProvider] 模板渲染失败 ({block.id}): {e}")
            return content

    def build_injection(
        self,
        task_type: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        返回经过过滤和渲染的上下文注入文本。

        Returns:
            {
              "header": str,  # 应插入系统提示开头的文字（inject_mode=header）
              "system": str,  # 应追加到系统提示末尾的文字（inject_mode=system）
            }
        """
        header_parts: List[str] = []
        system_parts: List[str] = []

        for block in self._blocks:
            if not block.matches(task_type):
                continue
            rendered = self._render(block).strip()
            if not rendered:
                continue

            wrapped = (
                f"\n\n## 📌 {block.name}\n{rendered}"
                if block.name and block.name != block.id
                else f"\n\n{rendered}"
            )

            if block.inject_mode == "header":
                header_parts.append(wrapped)
            else:
                system_parts.append(wrapped)

        return {
            "header": "".join(header_parts),
            "system": "".join(system_parts),
        }

    def inject_into_prompt(
        self,
        system_prompt: str,
        task_type: Optional[str] = None,
    ) -> str:
        """
        将匹配的上下文块注入到系统提示中。

        Args:
            system_prompt: 当前系统提示（Skills 注入后的版本）
            task_type:     当前任务类型

        Returns:
            注入后的系统提示字符串
        """
        injection = self.build_injection(task_type)
        result = system_prompt

        if injection["header"]:
            result = injection["header"] + "\n\n" + result

        if injection["system"]:
            result = result + injection["system"]

        return result

    def list_blocks(self) -> List[Dict[str, Any]]:
        """列出所有上下文块（用于 API/UI 展示）。"""
        return [
            {
                "id":          b.id,
                "name":        b.name,
                "enabled":     b.enabled,
                "priority":    b.priority,
                "task_types":  b.task_types,
                "inject_mode": b.inject_mode,
                "preview":     b.content[:120] + ("…" if len(b.content) > 120 else ""),
            }
            for b in self._blocks
        ]


class _SafeFormatMap(dict):
    """对于找不到的键，保留原始 {key} 占位符而不抛出 KeyError。"""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def get_context_provider() -> ContextProvider:
    """获取 ContextProvider 单例（推荐使用方式）。"""
    return ContextProvider.instance()
