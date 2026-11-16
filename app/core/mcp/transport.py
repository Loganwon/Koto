# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Transport abstraction layer for MCP protocol.

Supports three transports:
  - stdio: Subprocess-based, JSON-RPC over stdin/stdout
  - WebSocket: Bidirectional WebSocket connection
  - SSE: Server-Sent Events with HTTP POST for requests
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)

# SSE → httpx
try:
    import httpx

    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

# WebSocket → websocket-client
try:
    import websocket

    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False


# ── Abstract Transport Interface ────────────────────────────────────────────


class Transport(ABC):
    """Abstract base for MCP transports."""

    kind: str = ""

    @abstractmethod
    def connect(self) -> None:
        """Establish the transport connection."""

    @abstractmethod
    def disconnect(self) -> None:
        """Tear down the transport connection."""

    @abstractmethod
    def send(self, payload: bytes) -> None:
        """Send raw bytes over the transport."""

    @abstractmethod
    def receive(self, timeout: float = 30.0) -> Optional[bytes]:
        """Receive a raw message. Returns None on timeout/EOF."""

    @property
    @abstractmethod
    def connected(self) -> bool:
        """Whether the transport is currently connected."""


class AsyncTransport(ABC):
    """Abstract base for async MCP transports."""

    kind: str = ""

    @abstractmethod
    async def connect(self) -> None:
        """Establish the transport connection."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Tear down the transport connection."""

    @abstractmethod
    async def send(self, payload: bytes) -> None:
        """Send raw bytes over the transport."""

    @abstractmethod
    async def receive(self, timeout: float = 30.0) -> Optional[bytes]:
        """Receive a raw message. Returns None on timeout/EOF."""

    @property
    @abstractmethod
    def connected(self) -> bool:
        """Whether the transport is currently connected."""


# ── Stdio Transport ─────────────────────────────────────────────────────────


class StdioTransport(Transport):
    """MCP transport via subprocess stdin/stdout with JSON-RPC framing."""

    kind = "stdio"

    def __init__(
        self,
        command: List[str],
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        startup_timeout: float = 10.0,
    ):
        self.command = command
        self.env = env
        self.cwd = cwd
        self.startup_timeout = startup_timeout
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()
        self._closed = False

    def connect(self) -> None:
        with self._lock:
            if self._process is not None:
                return
            merged_env = os.environ.copy()
            if self.env:
                merged_env.update(self.env)
            try:
                self._process = subprocess.Popen(
                    self.command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=merged_env,
                    cwd=self.cwd,
                    text=False,
                )
                self._closed = False
                logger.debug(
                    "[StdioTransport] started %s (pid=%s)",
                    self.command,
                    self._process.pid,
                )
            except Exception:
                self._process = None
                raise

    def disconnect(self) -> None:
        with self._lock:
            self._closed = True
            proc = self._process
            self._process = None
        if proc is not None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.stdout.close()
            except Exception:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def send(self, payload: bytes) -> None:
        with self._lock:
            if self._process is None or self._closed:
                raise RuntimeError("StdioTransport not connected")
            try:
                self._process.stdin.write(payload)
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                self._closed = True
                raise RuntimeError(f"StdioTransport write failed: {e}") from e

    def receive(self, timeout: float = 30.0) -> Optional[bytes]:
        proc = self._process
        if proc is None or self._closed:
            return None
        stdout = proc.stdout
        if stdout is None:
            return None

        deadline = time.time() + timeout
        line_buf = []

        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None

            # Non-blocking read with polling
            if hasattr(stdout, "read1"):
                chunk = stdout.read1(4096)
            else:
                chunk = stdout.read(4096)

            if not chunk:
                self._closed = True
                return None

            # Accumulate and split on newlines
            line_buf.append(chunk)
            raw = b"".join(line_buf)

            if b"\n" in raw:
                # Extract the first complete line
                idx = raw.index(b"\n")
                line = raw[:idx]
                remainder = raw[idx + 1 :]
                # Push remainder back? Not easily done with pipes, so buffer locally.
                # For simplicity, we return the line and the caller handles batching.
                return line

        return None

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._process is not None and not self._closed


# ── WebSocket Transport ─────────────────────────────────────────────────────


class WebSocketTransport(Transport):
    """MCP transport via WebSocket."""

    kind = "websocket"

    def __init__(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        connect_timeout: float = 10.0,
    ):
        self.url = url
        self.headers = headers or {}
        self.connect_timeout = connect_timeout
        self._ws: Any = None
        self._lock = threading.RLock()

    def connect(self) -> None:
        if not _WS_AVAILABLE:
            raise ImportError("websocket-client is required for WebSocket transport")
        with self._lock:
            if self._ws is not None:
                return
            header_list = [f"{k}: {v}" for k, v in self.headers.items()]
            self._ws = websocket.create_connection(
                self.url, timeout=self.connect_timeout, header=header_list
            )

    def disconnect(self) -> None:
        with self._lock:
            ws = self._ws
            self._ws = None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def send(self, payload: bytes) -> None:
        with self._lock:
            if self._ws is None:
                raise RuntimeError("WebSocketTransport not connected")
            self._ws.send(payload if isinstance(payload, str) else payload.decode())

    def receive(self, timeout: float = 30.0) -> Optional[bytes]:
        ws = self._ws
        if ws is None:
            return None
        try:
            ws.settimeout(timeout)
            raw = ws.recv()
            if isinstance(raw, bytes):
                return raw
            return raw.encode("utf-8")
        except Exception:
            return None

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._ws is not None


# ── SSE Transport ───────────────────────────────────────────────────────────


class SSETransport(Transport):
    """MCP transport via SSE (Server-Sent Events) + HTTP POST.

    SSE endpoint is used for receiving messages from the server.
    HTTP POST is used for sending messages (JSON-RPC requests) to the server.
    """

    kind = "sse"

    def __init__(
        self,
        sse_url: str,
        post_url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        connect_timeout: float = 10.0,
    ):
        self.sse_url = sse_url
        self.post_url = post_url or sse_url
        self.headers = headers or {}
        self.connect_timeout = connect_timeout
        self._client: Optional[httpx.Client] = None
        self._connected = False
        self._lock = threading.RLock()

    def connect(self) -> None:
        if not _HTTPX_AVAILABLE:
            raise ImportError("httpx is required for SSE transport")
        with self._lock:
            if self._connected:
                return
            self._client = httpx.Client(
                timeout=httpx.Timeout(
                    self.connect_timeout, connect=self.connect_timeout
                ),
                headers=self.headers,
            )
            # Verify connection with a GET
            resp = self._client.get(self.sse_url)
            resp.raise_for_status()
            self._connected = True

    def disconnect(self) -> None:
        with self._lock:
            client = self._client
            self._client = None
            self._connected = False
        if client is not None:
            client.close()

    def send(self, payload: bytes) -> None:
        with self._lock:
            if self._client is None:
                raise RuntimeError("SSETransport not connected")
            self._client.post(
                self.post_url,
                content=payload,
                headers={"Content-Type": "application/json"},
            )

    def receive(self, timeout: float = 30.0) -> Optional[bytes]:
        # SSE receive would require a streaming connection.
        # For request-response MCP over HTTP, responses come via the POST response.
        # This transport is primarily for sending; the caller reads SSE events separately.
        return None

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected


# ── Transport Factory ───────────────────────────────────────────────────────


def create_transport(
    kind: str,
    command: Optional[List[str]] = None,
    url: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Transport:
    """Create a transport instance based on kind."""
    if kind == "stdio":
        if command is None:
            raise ValueError("command is required for stdio transport")
        return StdioTransport(command=command, env=env, cwd=cwd, **kwargs)
    elif kind == "websocket":
        if url is None:
            raise ValueError("url is required for websocket transport")
        return WebSocketTransport(url=url, headers=headers, **kwargs)
    elif kind == "sse":
        if url is None:
            raise ValueError("url is required for SSE transport")
        return SSETransport(sse_url=url, headers=headers, **kwargs)
    else:
        raise ValueError(f"Unknown transport kind: {kind!r}")


__all__ = [
    "Transport",
    "AsyncTransport",
    "StdioTransport",
    "WebSocketTransport",
    "SSETransport",
    "create_transport",
]
