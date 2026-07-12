"""Executable-server lifecycle kept separate from the Flask application module."""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any, Callable


def _start_compat_background_services() -> None:
    """Start services still owned by the executable compatibility path.

    The normal runtime bootstrap owns jobs, triggers, and integrations.  These
    services have not migrated yet, so keep their startup here but use their
    canonical package paths and isolate each optional service.  A clipboard
    issue must not prevent the task queue or the auto-catalog scheduler from
    starting.
    """
    import logging

    logger = logging.getLogger("koto.app_entrypoint")

    try:
        from app.core.services.clipboard_manager import get_clipboard_manager

        get_clipboard_manager().start_monitoring()
    except Exception as exc:
        logger.warning("[Clipboard] compatibility startup failed: %s", exc)

    try:
        from web.task_scheduler import get_task_scheduler

        get_task_scheduler().start()
    except Exception as exc:
        logger.warning("[TaskScheduler] compatibility startup failed: %s", exc)

    try:
        from web.task_queue import task_queue

        task_queue.start()
    except Exception as exc:
        logger.warning("[TaskQueue] compatibility startup failed: %s", exc)

    try:
        from web.auto_catalog_scheduler import get_auto_catalog_scheduler

        auto_catalog = get_auto_catalog_scheduler()
        if auto_catalog.is_auto_catalog_enabled():
            auto_catalog._register_scheduled_task()
    except Exception as exc:
        logger.warning("[AutoCatalog] compatibility startup failed: %s", exc)


def run_web_server(
    *,
    app: Any,
    socketio: Any,
    local_dispatcher: Any,
    parallel_system_enabled: bool,
    stop_dispatcher: Callable[[], None],
    chat_dir: str,
    workspace_dir: str,
) -> None:
    """Run the executable-only startup and shutdown lifecycle for Koto."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    debug_mode = os.environ.get("KOTO_DEBUG", "false").lower() == "true"
    port = int(os.environ.get("KOTO_PORT", "5000"))

    print("\nKoto Web Server Starting...")
    print(f"Chat Directory: {os.path.abspath(chat_dir)}")
    print(f"Workspace: {os.path.abspath(workspace_dir)}")

    def check_ollama_async() -> None:
        time.sleep(2)
        if os.environ.get("KOTO_DEPLOY_MODE") == "cloud":
            print("Ollama: Disabled (cloud mode - using DeepSeek API)")
            return
        print("Ollama: Running" if local_dispatcher.is_ollama_running() else "Ollama: Not Running")

    threading.Thread(target=check_ollama_async, daemon=True).start()
    print("Koto AI services are starting")
    print(f"\nOpen http://localhost:{port} in your browser\n")

    def start_compat_background_services() -> None:
        time.sleep(1)
        _start_compat_background_services()

    threading.Thread(target=start_compat_background_services, daemon=True).start()
    try:
        if socketio is not None:
            socketio.run(
                app,
                debug=debug_mode,
                host="0.0.0.0",
                port=port,
                allow_unsafe_werkzeug=True,
            )
        else:
            app.run(debug=debug_mode, host="0.0.0.0", port=port, threaded=True)
    finally:
        if parallel_system_enabled:
            print("[PARALLEL] Shutting down parallel execution system...")
            stop_dispatcher()
            print("[PARALLEL] Parallel execution system shut down")
