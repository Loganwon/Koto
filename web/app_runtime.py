from __future__ import annotations

import os
import threading
import time
from logging import Logger
from pathlib import Path


_runtime_lock = threading.Lock()
_runtime_thread: threading.Thread | None = None
_runtime_started = False
_model_runtime_lock = threading.Lock()
_model_runtime_threads: tuple[threading.Thread, ...] = ()
_model_runtime_started = False
_proxy_warmup_lock = threading.Lock()
_proxy_warmup_thread: threading.Thread | None = None


def _background_runtime_disabled() -> bool:
    return os.environ.get("KOTO_SKIP_BACKGROUND_RUNTIME", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _run_model_runtime(logger: Logger, initialize, refresh) -> None:
    """Initialize model state before entering its long-running refresh loop."""
    try:
        initialize()
    except Exception:
        logger.exception("[ModelManager] initialization failed")
    try:
        refresh()
    except Exception:
        logger.exception("[ModelManager] refresh loop stopped unexpectedly")


def start_model_runtime(
    logger: Logger,
    initialize_model_manager,
    refresh_model_manager,
) -> tuple[threading.Thread, ...]:
    """Start model discovery/refresh once, unless this is a safe import probe."""
    global _model_runtime_started, _model_runtime_threads

    with _model_runtime_lock:
        if _model_runtime_started:
            return _model_runtime_threads
        _model_runtime_started = True
        if _background_runtime_disabled():
            logger.info("[ModelManager] 后台模型运行时已按安全导入配置跳过")
            return ()

        thread = threading.Thread(
            target=_run_model_runtime,
            args=(logger, initialize_model_manager, refresh_model_manager),
            name="ModelManagerRuntime",
            daemon=True,
        )
        thread.start()
        _model_runtime_threads = (thread,)
        return _model_runtime_threads


def start_proxy_warmup(logger: Logger, warmup) -> threading.Thread | None:
    """Warm proxy discovery once without polluting safe application imports."""
    global _proxy_warmup_thread

    with _proxy_warmup_lock:
        if _proxy_warmup_thread is not None:
            return _proxy_warmup_thread
        if _background_runtime_disabled():
            logger.info("[Proxy] 后台代理预热已按安全导入配置跳过")
            return None
        thread = threading.Thread(
            target=warmup,
            name="ProxyWarmup",
            daemon=True,
        )
        thread.start()
        _proxy_warmup_thread = thread
        return thread


def _start_managed_services(logger: Logger) -> dict[str, str]:
    """Start executable services under the shared runtime lifecycle.

    Every component is isolated and reported so one optional integration
    cannot prevent the core application from becoming available.
    """
    state: dict[str, str] = {}
    starters = (
        (
            "clipboard",
            lambda: __import__(
                "app.core.services.clipboard_manager", fromlist=["get_clipboard_manager"]
            ).get_clipboard_manager().start_monitoring(),
        ),
    )
    for name, starter in starters:
        try:
            starter()
            state[name] = "running"
        except Exception as exc:
            state[name] = f"degraded: {exc}"
            logger.warning("[Runtime:%s] startup degraded: %s", name, exc)

    try:
        module = __import__(
            "app.core.services.auto_catalog_scheduler", fromlist=["get_auto_catalog_scheduler"]
        )
        auto_catalog = module.get_auto_catalog_scheduler()
        if auto_catalog.is_auto_catalog_enabled():
            auto_catalog._register_scheduled_task()
            state["auto_catalog"] = "running"
        else:
            state["auto_catalog"] = "disabled"
    except Exception as exc:
        state["auto_catalog"] = f"degraded: {exc}"
        logger.warning("[Runtime:auto_catalog] startup degraded: %s", exc)
    return state


def initialize_background_runtime(
    logger: Logger,
    get_workspace_root,
) -> None:
    """Warm up supported long-running subsystems after startup."""
    try:
        time.sleep(1)

        managed_services = _start_managed_services(logger)
        logger.info("[Runtime] managed services: %s", managed_services)

        from app.core.jobs.job_runner import get_job_runner
        from app.core.ops.ops_event_bus import get_ops_bus
        get_ops_bus()
        runner = get_job_runner()

        try:
            from app.core.goal.goal_job_handler import register_goal_handler
            from app.core.goal.goal_manager import get_goal_manager

            goal_manager = get_goal_manager()
            register_goal_handler(runner)
            logger.info(
                f"[GoalManager] ✅ 长期目标管理器已启动 (活跃目标: {goal_manager.count()} 条)"
            )
        except Exception as exc:
            logger.warning(f"[GoalManager] ⚠️ 初始化失败（非致命）: {exc}")

        try:
            from app.core.file.file_registry import get_file_registry
            from app.core.file.file_watcher import get_file_watcher

            file_registry = get_file_registry()
            file_watcher = get_file_watcher()
            workspace_dir = get_workspace_root()
            watcher_started = False
            if file_watcher.enabled and workspace_dir and Path(workspace_dir).is_dir():
                file_watcher.add_dir(workspace_dir)
                threading.Thread(
                    target=file_watcher.scan_once,
                    args=(workspace_dir,),
                    daemon=True,
                    name="koto-init-scan",
                ).start()
            if file_watcher.enabled:
                file_watcher.start()
                watcher_started = True
            else:
                logger.info(
                    "[FileHub] ℹ️ 文件监控默认关闭，跳过 workspace 全量扫描和后台轮询"
                )
            if watcher_started:
                logger.info(
                    f"[FileHub] ✅ 文件注册表已启动 (已收录: {file_registry.count()} 个文件，监控目录: {len(file_watcher.watch_dirs)} 个)"
                )
            else:
                logger.info(
                    f"[FileHub] ✅ 文件注册表已启动 (已收录: {file_registry.count()} 个文件，文件监控: disabled)"
                )
        except Exception as exc:
            logger.warning(f"[FileHub] ⚠️ 文件模块初始化失败（非致命）: {exc}")

        try:
            from web.files.work_file_library import get_work_file_library

            work_file_library = get_work_file_library()
            if not work_file_library.is_indexed():
                work_file_library.scan_locations()
                logger.debug("[WorkFileLibrary] 🚀 工作文件库后台扫描已启动（桌面/文档/下载）")
            else:
                logger.info(
                    f"[WorkFileLibrary] ✅ 工作文件库已加载: {work_file_library.count()} 个工作文件"
                )
        except Exception as exc:
            logger.warning(f"[WorkFileLibrary] ⚠️ 初始化失败（非致命）: {exc}")

        logger.info(
            "[Runtime] ✅ 后台运行时已启动: "
            f"job_runner={runner is not None}"
        )

        try:
            from app.core.services.telegram_bot import get_telegram_bot

            tg_bot = get_telegram_bot()
            if tg_bot:
                tg_bot.start()
                logger.info("[Telegram] ✅ Telegram Bot 已启动")
            else:
                logger.info("[Telegram] ℹ️ 未配置 TELEGRAM_BOT_TOKEN，Bot 不启动")
        except Exception as exc:
            logger.warning(f"[Telegram] ⚠️ Bot 启动失败（非致命）: {exc}")

        try:
            from app.core.services.morning_brief import get_morning_brief_service

            get_morning_brief_service().start_scheduler()
            logger.info("[MorningBrief] ✅ 晨间简报调度器已启动")
        except Exception as exc:
            logger.warning(f"[MorningBrief] ⚠️ 调度器启动失败（非致命）: {exc}")

        try:
            from app.core.memory.contact_manager import get_contact_manager

            contact_manager = get_contact_manager()
            logger.info(
                f"[ContactCRM] ✅ 联系人 CRM 已就绪 (已收录: {contact_manager.count()} 位)"
            )
        except Exception as exc:
            logger.warning(f"[ContactCRM] ⚠️ 联系人 CRM 初始化失败（非致命）: {exc}")

    except Exception as exc:
        logger.warning(f"[Runtime] ⚠️ 后台运行时初始化失败: {exc}")


def start_background_runtime(logger: Logger, get_workspace_root) -> threading.Thread:
    """Start background runtime warmup in a daemon thread."""
    global _runtime_started, _runtime_thread

    with _runtime_lock:
        if _runtime_started and _runtime_thread is not None:
            logger.debug("[Runtime] 后台运行时已请求启动，跳过重复启动")
            return _runtime_thread

        if _background_runtime_disabled():
            # Import and diagnostic probes must not start watchers, schedulers,
            # or external integrations merely to verify that the app imports.
            thread = threading.Thread(
                target=lambda: None,
                name="RuntimeBootstrapSkipped",
                daemon=True,
            )
            _runtime_started = True
            _runtime_thread = thread
            logger.info("[Runtime] 后台运行时已按 KOTO_SKIP_BACKGROUND_RUNTIME 跳过")
            return thread

        thread = threading.Thread(
            target=initialize_background_runtime,
            args=(logger, get_workspace_root),
            name="RuntimeBootstrap",
            daemon=True,
        )
        _runtime_started = True
        _runtime_thread = thread
        thread.start()
        return thread
