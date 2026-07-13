#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
"""Koto launcher health checks — port availability and runtime readiness."""

import logging
import socket
import time
from pathlib import Path

logger = logging.getLogger("koto.launcher.health")

DEFAULT_PORT = 5000


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is free to bind."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def find_available_port(start: int = DEFAULT_PORT, max_attempts: int = 10) -> int:
    """Find the first available port starting from `start`."""
    for port in range(start, start + max_attempts):
        if is_port_available(port):
            return port
    raise RuntimeError(f"No available port found in range {start}-{start + max_attempts}")


def wait_for_port(port: int, timeout: float = 10.0, host: str = "127.0.0.1") -> bool:
    """Wait until a port becomes available (after a process has released it)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_port_available(port, host):
            return True
        time.sleep(0.5)
    return False


def check_runtime_readiness() -> dict:
    """Check common runtime prerequisites."""
    root = Path(__file__).resolve().parent.parent

    checks = {
        "config_dir": (root / "config").is_dir(),
        "web_app": (root / "web" / "app.py").exists(),
        "desktop_app": (root / "src" / "koto_app.py").exists(),
        "requirements": (root / "config" / "requirements.txt").exists(),
    }

    return checks
