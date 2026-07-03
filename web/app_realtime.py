from __future__ import annotations

from collections.abc import Callable
from logging import Logger

from flask import Flask, request


def init_socketio(
    app: Flask,
    logger: Logger,
    cors_origins,
    *,
    has_socketio: bool,
    socketio_cls,
):
    """Initialize Flask-SocketIO when the optional dependency is available."""
    socketio = None
    if has_socketio and socketio_cls is not None:
        socketio = socketio_cls(
            app,
            cors_allowed_origins=cors_origins,
            async_mode="threading",
            logger=False,
            engineio_logger=False,
            ping_timeout=120,
            ping_interval=30,
        )
        try:
            from app.core.socket_handler import register_socket_events

            register_socket_events(socketio)
            logger.info("[WebSocket] Flask-SocketIO 初始化完成，文件助手 AI 通道就绪")
        except Exception as exc:
            logger.warning("[WebSocket] socket_handler 注册失败: %s", exc)
    return socketio


def init_notification_socket(
    app: Flask,
    logger: Logger,
    sock_cls,
    notification_manager_factory: Callable[[], object],
):
    """Initialize the optional flask-sock notifications channel."""
    sock = None
    if sock_cls:
        sock = sock_cls(app)
    else:
        logger.warning("[WebSocket] ⚠️ flask-sock 未安装，使用轮询作为通知兜底")

    if not sock:
        return None

    @sock.route("/ws/notifications")
    def ws_notifications(ws):
        user_id = request.args.get("user_id", "default")
        manager = notification_manager_factory()
        manager.register_connection(user_id, ws)
        try:
            while True:
                message = ws.receive()
                if message is None:
                    break
                if isinstance(message, str) and message.lower() == "ping":
                    ws.send("pong")
        finally:
            manager.unregister_connection(user_id, ws)

    try:
        from web.mcp_ws import register_mcp_ws

        register_mcp_ws(sock)
        logger.info("[WebSocket] MCP endpoint registered at /ws/mcp")
    except Exception as exc:
        logger.warning("[WebSocket] MCP endpoint registration failed: %s", exc)

    return sock
