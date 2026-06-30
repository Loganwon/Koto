#!/usr/bin/env python3
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto Server Mode - 纯 Web 服务（无桌面窗口）
用于云部署 / Docker / Railway / VPS

用法:
  python server.py                    # 开发模式
  gunicorn -w 2 -b 0.0.0.0:5000 server:app  # 生产模式

环境变量:
  KOTO_PORT=5000               服务端口
  KOTO_AUTH_ENABLED=true       启用认证（SaaS 模式）
  KOTO_JWT_SECRET=xxx          JWT 签名密钥
  KOTO_MAX_DAILY_REQUESTS=100  每用户每日请求上限
  GEMINI_API_KEY=xxx           Gemini API 密钥

  # LangSmith 可观测性追踪（可选）
  LANGCHAIN_TRACING_V2=true
  LANGCHAIN_API_KEY=lsv2_...   # https://smith.langchain.com
  LANGCHAIN_PROJECT=Koto
"""

import atexit
import logging
import os
import signal
import sys
from pathlib import Path

try:
    from src.runtime_bootstrap import (
        configure_process_environment,
        init_optional_langsmith,
        load_optional_gemini_env,
        resolve_runtime_roots,
        validate_startup_config_or_raise,
    )
except ImportError:
    from runtime_bootstrap import (
        configure_process_environment,
        init_optional_langsmith,
        load_optional_gemini_env,
        resolve_runtime_roots,
        validate_startup_config_or_raise,
    )

# 设置环境
ROOTS = resolve_runtime_roots(__file__)
APP_ROOT = ROOTS.app_root
configure_process_environment(
    ROOTS,
    prepend_paths=(APP_ROOT,),
    append_paths=(APP_ROOT / "web",),
    required_dirs=("logs", "chats", "workspace", "config"),
)

# 初始化集中式日志（在其他模块导入之前）
from app.core.logging_setup import setup_logging  # noqa: E402

setup_logging(log_dir=str(APP_ROOT / "logs"))

# 加载 .env 配置
load_optional_gemini_env()

# 启动时配置验证
try:
    validate_startup_config_or_raise()
except Exception as e:
    print(f"[FATAL] Configuration error: {e}")
    sys.exit(1)

# LangSmith 可观测性初始化（可选，仅当环境变量已设置时激活）
init_optional_langsmith()

# 导入 Flask app
from web.app import app

# 运行模式检测
DEPLOY_MODE = os.environ.get("KOTO_DEPLOY_MODE", "local")  # local / cloud
PORT = int(os.environ.get("KOTO_PORT", os.environ.get("PORT", "5000")))

logger = logging.getLogger(__name__)


def _cleanup():
    """Clean up resources on shutdown."""
    logger.info("Running cleanup...")
    try:
        from web.settings import SettingsManager

        if SettingsManager._instance:
            SettingsManager._instance.flush()
            logger.info("Settings flushed")
    except Exception as e:
        logger.debug("Settings flush failed: %s", e)

    try:
        from app.core.monitoring.event_database import EventDatabase  # noqa: F401

        # Close any open database connections
        logger.info("Cleanup complete")
    except Exception as e:
        logger.debug("DB cleanup failed: %s", e)


def _shutdown_handler(signum, frame):
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    sig_name = (
        signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
    )
    logger.info("Received %s, shutting down gracefully...", sig_name)
    _cleanup()
    raise SystemExit(0)


# Register handlers
signal.signal(signal.SIGINT, _shutdown_handler)
signal.signal(signal.SIGTERM, _shutdown_handler)
atexit.register(_cleanup)


if __name__ == "__main__":
    print(f"""
╔═══════════════════════════════════════╗
║     Koto 言 - AI Assistant Server     ║
║  Mode: {"Cloud (SaaS)" if os.environ.get("KOTO_AUTH_ENABLED") == "true" else "Local (No Auth)":33s} ║
║  Port: {PORT:<33d} ║
╚═══════════════════════════════════════╝
    """)
    # 优先使用 SocketIO 启动（支持文件助手全双工通信）
    try:
        from web.app import socketio as _sio

        if _sio is not None:
            logger.info("[Server] 使用 Flask-SocketIO 启动（WebSocket 支持已启用）")
            _sio.run(
                app, host="0.0.0.0", port=PORT, debug=False, allow_unsafe_werkzeug=True
            )  # nosec B104
        else:
            raise ImportError("socketio is None")
    except (ImportError, AttributeError):
        logger.info("[Server] 使用标准 Flask 启动（无 WebSocket）")
        app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)  # nosec B104
