# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto UserToolLoader — 用户自定义工具脚本加载器
===============================================
在 config/tools/ 目录下放置 Python 脚本，用 @koto_tool 装饰器即可将
普通函数注册为 AI 可调用的工具（无需修改任何核心代码）。

快速上手示例 — config/tools/my_tools.py：

    from app.core.tools.user_tool_loader import koto_tool

    @koto_tool(
        description="在我的个人笔记中搜索内容",
        parameters={
            "query": {"type": "STRING", "description": "搜索关键词"},
        },
        required=["query"],
    )
    def search_my_notes(query: str) -> str:
        import os
        notes_dir = os.path.expanduser("~/notes")
        results = []
        for fname in os.listdir(notes_dir):
            path = os.path.join(notes_dir, fname)
            text = open(path).read()
            if query.lower() in text.lower():
                results.append(f"[{fname}]: {text[:200]}")
        return "\\n".join(results) if results else "未找到相关笔记"

    @koto_tool(description="获取今日待办清单")
    def get_today_todos() -> str:
        return "1. 完成季报\\n2. 回复邮件\\n3. 开周会"

参数说明：
  description   : 工具用途（AI 读这个来决定何时调用，要写得精确）
  parameters    : 参数 schema 字典（key = 参数名, value = {"type": "STRING", "description": "..."}）
                  支持类型: STRING | INTEGER | NUMBER | BOOLEAN | ARRAY | OBJECT
  required      : 必填参数名列表（默认为空）
  name          : 工具名称（默认使用函数名）
  returns_type  : 返回值说明（可选，方便 AI 理解输出）

工具函数规则：
  - 返回值必须是 str（或可被 str() 转换的类型）
  - 抛出的异常会被捕获并作为错误字符串返回给 AI
  - 函数可以导入任意标准库和已安装的第三方包
  - 首次执行时加载，之后缓存（热重载需重启）

@version 2026-05-26
"""

from __future__ import annotations

import functools
import importlib.util
import logging
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_TOOLS_DIR = Path(__file__).parent.parent.parent.parent / "config" / "tools"

# 全局注册表：被 @koto_tool 装饰后自动注册到这里
_REGISTERED_TOOLS: List[Dict[str, Any]] = []
_REGISTRY_LOCK = threading.Lock()


# ── @koto_tool 装饰器 ─────────────────────────────────────────────────────────


def koto_tool(
    description: str = "",
    parameters: Optional[Dict[str, Dict]] = None,
    required: Optional[List[str]] = None,
    name: Optional[str] = None,
    returns_type: Optional[str] = None,
) -> Callable:
    """
    将函数注册为 Koto 可调用工具的装饰器。

    用法：
        @koto_tool("用途描述", parameters={"key": {"type": "STRING", "description": "..."}})
        def my_fn(key: str) -> str:
            ...

    也可直接作为无参数装饰器（工具无参数时）：
        @koto_tool("获取当前时间")
        def get_time() -> str:
            ...
    """

    def decorator(fn: Callable) -> Callable:
        tool_name = name or fn.__name__

        # 构造参数 schema
        props: Dict[str, Dict] = {}
        if parameters:
            for k, v in parameters.items():
                props[k] = {
                    "type": v.get("type", "STRING"),
                    "description": v.get("description", ""),
                }

        tool_def = {
            "name": tool_name,
            "description": description or (fn.__doc__ or "").strip().split("\n")[0],
            "func": _safe_wrapper(fn),
            "parameters": {
                "type": "OBJECT",
                "properties": props,
                "required": required or [],
            },
        }
        if returns_type:
            tool_def["returns_type"] = returns_type

        with _REGISTRY_LOCK:
            # 覆盖同名工具
            existing = next(
                (i for i, t in enumerate(_REGISTERED_TOOLS) if t["name"] == tool_name),
                None,
            )
            if existing is not None:
                _REGISTERED_TOOLS[existing] = tool_def
            else:
                _REGISTERED_TOOLS.append(tool_def)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def _safe_wrapper(fn: Callable) -> Callable:
    """包装函数以捕获异常并返回错误字符串（工具调用不应炸掉整个管线）。"""

    @functools.wraps(fn)
    def wrapped(*args, **kwargs) -> str:
        try:
            result = fn(*args, **kwargs)
            return str(result) if result is not None else ""
        except Exception as e:
            logger.warning(f"[UserTool:{fn.__name__}] 执行出错: {e}")
            return f"[工具执行错误] {fn.__name__}: {e}"

    return wrapped


# ── 加载器 ────────────────────────────────────────────────────────────────────


def load_user_tools() -> int:
    """
    扫描 config/tools/*.py 并执行（触发 @koto_tool 注册）。

    Returns:
        成功加载的文件数量
    """
    tools_dir = _TOOLS_DIR
    if not tools_dir.is_dir():
        logger.debug("[UserToolLoader] config/tools/ 不存在，跳过")
        return 0

    # 确保 tools_dir 在 sys.path 中，以便脚本互相导入
    tools_str = str(tools_dir)
    if tools_str not in sys.path:
        sys.path.insert(0, tools_str)

    loaded = 0
    before = len(_REGISTERED_TOOLS)

    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        module_name = f"_koto_usertool_{py_file.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            loaded += 1
            logger.debug(f"[UserToolLoader] 已执行: {py_file.name}")
        except Exception as e:
            logger.warning(f"[UserToolLoader] 加载 {py_file.name} 失败: {e}")

    new_tools = len(_REGISTERED_TOOLS) - before
    if new_tools > 0:
        tool_names = [t["name"] for t in _REGISTERED_TOOLS[before:]]
        logger.info(
            f"[UserToolLoader] 从 {loaded} 个文件注册了 {new_tools} 个用户工具: "
            f"{tool_names}"
        )

    return loaded


def get_registered_tools() -> List[Dict[str, Any]]:
    """获取当前已注册的所有用户自定义工具定义（只读副本）。"""
    with _REGISTRY_LOCK:
        return list(_REGISTERED_TOOLS)


# ── AgentPlugin 适配器 ────────────────────────────────────────────────────────


class UserDefinedPlugin:
    """
    将用户自定义工具包装成标准 AgentPlugin 接口，以便注册到 ToolRegistry。

    此类不严格继承 AgentPlugin ABC，以避免在工具脚本加载失败时引起导入错误。
    ToolRegistry 只需要 get_tools() 方法。
    """

    @property
    def name(self) -> str:
        return "UserDefinedTools"

    @property
    def description(self) -> str:
        return "User-defined custom tools from config/tools/"

    def get_tools(self) -> List[Dict[str, Any]]:
        return get_registered_tools()

    def __repr__(self) -> str:
        return f"<UserDefinedPlugin: {len(get_registered_tools())} tools>"
