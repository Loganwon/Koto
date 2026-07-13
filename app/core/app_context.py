# -*- coding: utf-8 -*-
"""
Koto AppContext — 集中式服务容器（依赖注入）
=============================================

所有需要在模块间共享的「有状态单例」统一在此注册和获取。
取代散落在各文件的 module-level globals + 散乱的 get_xxx() 函数，
提供 **线程安全、延迟初始化、可测试** 的服务管理。

用法
----
    from app.core.app_context import ctx

    # 获取服务（首次访问时自动创建）
    mem_mgr = ctx.memory_manager
    cfg     = ctx.config_manager
    kb      = ctx.knowledge_base

    # 在测试中替换实例
    ctx.override("memory_manager", mock_manager)
    ctx.reset()  # 测试结束后恢复
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class _ServiceSlot:
    """单个服务的懒加载容器。"""

    __slots__ = ("factory", "instance", "lock")

    def __init__(self, factory: Callable[[], Any]):
        self.factory = factory
        self.instance: Any = None
        self.lock = threading.Lock()

    def get(self) -> Any:
        """Double-checked locking lazy init."""
        if self.instance is not None:
            return self.instance
        with self.lock:
            if self.instance is None:
                self.instance = self.factory()
        return self.instance

    def reset(self):
        with self.lock:
            self.instance = None

    def override(self, inst: Any):
        with self.lock:
            self.instance = inst


class AppContext:
    """
    集中式服务容器 — Koto 的依赖注入核心。

    所有注册的服务都通过 property 暴露，首次访问时延迟初始化，
    线程安全。
    """

    def __init__(self):
        self._slots: Dict[str, _ServiceSlot] = {}
        self._overrides: Dict[str, Any] = {}
        self._global_lock = threading.Lock()
        self._register_defaults()

    # ── 注册默认工厂 ──────────────────────────────────────────────────────────

    def _register_defaults(self):
        """注册所有核心服务的工厂函数（惰性导入，避免循环依赖和启动开销）。"""

        # ── ConfigurationManager ──
        self._register("config_manager", lambda: _make_config_manager())

        # ── SettingsManager ──
        self._register("settings_manager", lambda: _make_settings_manager())

        # ── EnhancedMemoryManager ──
        self._register("memory_manager", lambda: _make_memory_manager())

        # ── KnowledgeBase (RAG) ──
        self._register("knowledge_base", lambda: _make_knowledge_base())

        # ── FileRegistry ──
        self._register("file_registry", lambda: _make_file_registry())

        # ── TaskLedger ──
        self._register("task_ledger", lambda: _make_task_ledger())

        # ── SystemEventMonitor ──
        self._register("system_monitor", lambda: _make_system_monitor())

        # ── NotificationManager ──
        self._register("notification_manager", lambda: _make_notification_manager())

        # ── CheckpointManager ──
        self._register("checkpointer", lambda: _make_checkpointer())

        # ── ModelManager ──
        self._register("model_manager", lambda: _make_model_manager())

        # ── UnifiedAgent (主 Agent 实例) ──
        self._register("agent", lambda: _make_agent())

        # ── TokenTracker ──
        self._register("token_tracker", lambda: _make_token_tracker())

    # ── 通用注册 / 获取 ──────────────────────────────────────────────────────

    def _register(self, name: str, factory: Callable[[], Any]):
        self._slots[name] = _ServiceSlot(factory)

    def get(self, name: str) -> Any:
        """按名称获取服务（推荐使用 property）。"""
        with self._global_lock:
            if name in self._overrides:
                return self._overrides[name]
        slot = self._slots.get(name)
        if slot is None:
            raise KeyError(f"[AppContext] 未注册的服务: {name}")
        return slot.get()

    def override(self, name: str, instance: Any):
        """测试时替换服务实例。"""
        with self._global_lock:
            self._overrides[name] = instance

    def reset(self, name: Optional[str] = None):
        """
        重置服务实例（测试 teardown 使用）。

        Args:
            name: 指定服务名则只重置该服务；None 则全部重置。
        """
        slots_to_reset = []
        with self._global_lock:
            if name:
                self._overrides.pop(name, None)
                slot = self._slots.get(name)
                if slot:
                    slots_to_reset.append(slot)
            else:
                self._overrides.clear()
                slots_to_reset = list(self._slots.values())
        for slot in slots_to_reset:
            slot.reset()

    def shutdown(self):
        """优雅关闭所有服务（释放连接、线程等资源）。

        按注册逆序调用每个服务的 close()/shutdown()/dispose() 方法，
        安全重启或进程退出时调用。
        """
        with self._global_lock:
            names = reversed(list(self._slots.keys()))
        for name in names:
            slot = self._slots.get(name)
            if slot is None:
                continue
            inst = None
            with slot.lock:
                if slot.instance is not None:
                    inst = slot.instance
                    slot.instance = None
            if inst is not None:
                for method_name in ("close", "shutdown", "dispose", "cleanup"):
                    method = getattr(inst, method_name, None)
                    if callable(method):
                        try:
                            method()
                        except Exception as e:
                            logger.debug(
                                "[AppContext] %s.%s() 失败: %s", name, method_name, e
                            )
                        break

    def register_custom(self, name: str, factory: Callable[[], Any]):
        """运行时注册自定义服务（插件扩展用）。"""
        with self._global_lock:
            self._register(name, factory)

    # ── 类型化 Property 访问（IDE 补全友好）────────────────────────────────

    @property
    def config_manager(self):
        """app.core.config.configuration_manager.ConfigurationManager"""
        return self.get("config_manager")

    @property
    def settings_manager(self):
        """app.core.config.user_settings.SettingsManager"""
        return self.get("settings_manager")

    @property
    def memory_manager(self):
        """app.core.services.memory_manager.EnhancedMemoryManager"""
        return self.get("memory_manager")

    @property
    def knowledge_base(self):
        """Knowledge base (RAG service)"""
        return self.get("knowledge_base")

    @property
    def file_registry(self):
        """app.core.file.file_registry.FileRegistry"""
        return self.get("file_registry")

    @property
    def task_ledger(self):
        """app.core.tasks.task_ledger.TaskLedger"""
        return self.get("task_ledger")

    @property
    def system_monitor(self):
        """app.core.monitoring.system_event_monitor.SystemEventMonitor"""
        return self.get("system_monitor")

    @property
    def notification_manager(self):
        """app.core.services.notification_manager.NotificationManager"""
        return self.get("notification_manager")

    @property
    def checkpointer(self):
        """Checkpoint saver (Sqlite/Memory)"""
        return self.get("checkpointer")

    @property
    def model_manager(self):
        """Model discovery manager"""
        return self.get("model_manager")

    @property
    def agent(self):
        """app.core.agent.unified_agent.UnifiedAgent"""
        return self.get("agent")

    @property
    def token_tracker(self):
        """app.core.analytics.token_tracker module-level functions proxy"""
        return self.get("token_tracker")


# ══════════════════════════════════════════════════════════════════════════════
# Factory functions — 延迟导入，避免启动时循环依赖
# ══════════════════════════════════════════════════════════════════════════════


def _make_config_manager():
    from app.core.config.configuration_manager import ConfigurationManager

    logger.debug("[AppContext] 创建 ConfigurationManager")
    return ConfigurationManager()


def _make_settings_manager():
    try:
        from settings import SettingsManager
    except ImportError:
        from app.core.config.user_settings import SettingsManager
    logger.debug("[AppContext] 创建 SettingsManager")
    return SettingsManager()


def _make_memory_manager():
    from app.core.services.memory_manager import EnhancedMemoryManager

    logger.debug("[AppContext] 创建 EnhancedMemoryManager")
    return EnhancedMemoryManager()


def _make_knowledge_base():
    try:
        from app.core.services.knowledge_base import get_knowledge_base

        logger.debug("[AppContext] 创建 KnowledgeBase")
        return get_knowledge_base()
    except Exception as e:
        logger.debug(f"[AppContext] KnowledgeBase 创建失败: {e}")
        return None


def _make_file_registry():
    from app.core.file.file_registry import FileRegistry

    logger.debug("[AppContext] 创建 FileRegistry")
    return FileRegistry()


def _make_task_ledger():
    import os
    import sys

    from app.core.tasks.task_ledger import TaskLedger

    if getattr(sys, "frozen", False):
        root = os.path.dirname(sys.executable)
    else:
        root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
    db_path = os.path.join(root, "config", "task_ledger.sqlite")
    logger.debug("[AppContext] 创建 TaskLedger")
    return TaskLedger(db_path)


def _make_system_monitor():
    from app.core.monitoring.system_event_monitor import SystemEventMonitor

    logger.debug("[AppContext] 创建 SystemEventMonitor")
    return SystemEventMonitor()


def _make_notification_manager():
    import os
    import sys

    if getattr(sys, "frozen", False):
        root = os.path.dirname(sys.executable)
    else:
        root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
    db_path = os.path.join(root, "config", "notifications.sqlite")
    try:
        from app.core.services.notification_manager import NotificationManager

        logger.debug("[AppContext] 创建 NotificationManager")
        return NotificationManager(db_path)
    except Exception as e:
        logger.debug(f"[AppContext] NotificationManager 创建失败: {e}")
        return None


def _make_checkpointer():
    import os
    import sys

    if getattr(sys, "frozen", False):
        root = os.path.dirname(sys.executable)
    else:
        root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
    db_path = os.path.join(root, "config", "koto_checkpoints.sqlite")
    try:
        from app.core.agent.checkpoint_manager import get_checkpointer

        logger.debug("[AppContext] 创建 Checkpointer")
        return get_checkpointer(db_path)
    except Exception as e:
        logger.debug(f"[AppContext] Checkpointer 创建失败: {e}")
        return None


def _make_model_manager():
    try:
        from app.core.services.model_manager import ModelManager

        logger.debug("[AppContext] 创建 ModelManager")
        return ModelManager()
    except Exception as e:
        logger.debug(f"[AppContext] ModelManager 创建失败: {e}")
        return None


def _make_agent():
    try:
        from app.core.agent.factory import create_agent

        logger.debug("[AppContext] 创建 UnifiedAgent")
        return create_agent()
    except Exception as e:
        logger.debug(f"[AppContext] Agent 创建失败: {e}")
        return None


def _make_token_tracker():
    try:
        import app.core.analytics.token_tracker as tt

        logger.debug("[AppContext] 加载 TokenTracker 模块")
        return tt
    except Exception as e:
        logger.debug(f"[AppContext] TokenTracker 加载失败: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Global singleton
# ══════════════════════════════════════════════════════════════════════════════

ctx = AppContext()
