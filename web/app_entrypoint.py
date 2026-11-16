"""Executable-server lifecycle kept separate from the Flask application module."""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any


def run_web_server(
    *,
    app: Any,
    socketio: Any,
    local_dispatcher: Any,
    chat_dir: str,
    workspace_dir: str,
) -> None:
    """Run the executable-only startup and shutdown lifecycle for Koto."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    debug_mode = os.environ.get("KOTO_DEBUG", "false").lower() == "true"
    port = int(os.environ.get("KOTO_PORT", "5000"))
    deploy_mode = os.environ.get("KOTO_DEPLOY_MODE", "local").strip().lower()
    default_host = (
        "0.0.0.0"
        if deploy_mode in {"cloud", "production", "prod"}
        else "127.0.0.1"
    )
    bind_host = os.environ.get("KOTO_BIND_HOST", default_host).strip() or default_host

    from src.runtime_bootstrap import validate_startup_config_or_raise

    validate_startup_config_or_raise()

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

    if socketio is not None:
        socketio.run(
            app,
            debug=debug_mode,
            host=bind_host,
            port=port,
            allow_unsafe_werkzeug=True,
        )
    else:
        app.run(debug=debug_mode, host=bind_host, port=port, threaded=True)
