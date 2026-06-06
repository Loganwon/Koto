from __future__ import annotations

import os
import threading
import time
from logging import Logger
from pathlib import Path


_runtime_lock = threading.Lock()
_runtime_thread: threading.Thread | None = None
_runtime_started = False


def initialize_background_runtime(
    logger: Logger,
    get_workspace_root,
) -> None:
    """Warm up long-running subsystems so jobs, triggers, and ops are live after startup."""
    try:
        time.sleep(1)

        from app.core.jobs.job_runner import get_job_runner
        from app.core.jobs.trigger_registry import get_trigger_registry
        from app.core.ops.ops_event_bus import get_ops_bus
        from app.core.skills.skill_trigger_binding import get_skill_binding_manager

        get_ops_bus()
        runner = get_job_runner()
        registry = get_trigger_registry()
        bindings = get_skill_binding_manager()

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
            from web.work_file_library import get_work_file_library

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
            f"job_runner={runner is not None}, "
            f"triggers={len(registry.list_all())}, "
            f"bindings={len(bindings.list_bindings())}"
        )

        try:
            from app.core.learning.distill_manager import DistillManager
            from app.core.learning.shadow_tracer import ShadowTracer, TraceEvent

            def _on_training_ready(event: str, skill_id: str, count: int):
                if event == TraceEvent.TRAINING_READY:
                    logger.debug(
                        f"[Flywheel] 🚀 skill={skill_id} 已积累 {count} 条优质记录，自动提交 LoRA 训练..."
                    )
                    try:
                        job_id = DistillManager.instance().submit(skill_id)
                        logger.info(
                            f"[Flywheel] ✅ 训练任务已提交 job_id={job_id} skill={skill_id}"
                        )
                    except Exception as submit_exc:
                        logger.warning(f"[Flywheel] ⚠️ 自动提交训练失败: {submit_exc}")

            ShadowTracer.add_listener(_on_training_ready)
            logger.info("[Flywheel] ✅ 数据飞轮监听器已注册（ShadowTracer → DistillManager）")
        except Exception as exc:
            logger.warning(f"[Flywheel] ⚠️ 飞轮监听器注册失败（非致命）: {exc}")

        try:
            from web.telegram_bot import get_telegram_bot

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


def preload_audio_stt(logger: Logger) -> None:
    """Deprecated no-op kept for startup compatibility."""
    logger.debug("[startup] legacy microphone voice engine preload removed")
