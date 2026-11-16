#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
"""Koto launcher health utilities ? port checks and runtime readiness.

These helpers back ``python -m launcher --health`` and port auto-resolution
for desktop/server mode. Kept intentionally dependency-light.
"""

from __future__ import annotations

import logging
import socket
from typing import Dict

logger = logging.getLogger("koto.launcher.health")

DEFAULT_PORT = 5000

_MAX_SCAN_PORTS = 20


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Return True when the TCP port can be bound on the given host."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
        return True
    except OSError:
        return False


def find_available_port(start_port: int, max_attempts: int = _MAX_SCAN_PORTS) -> int:
    """Return the first available port at or above ``start_port``.

    Falls back to ``start_port`` when the scan window is exhausted.
    """
    for candidate in range(start_port, start_port + max_attempts):
        if is_port_available(candidate):
            return candidate
    logger.warning("No available port found in range, falling back to %d", start_port)
    return start_port


def check_runtime_readiness() -> Dict[str, bool]:
    """Report lightweight runtime readiness for the launcher health check.

    Returns a dict of check-name ? boolean. Keep each probe cheap and
    non-blocking (no network calls).
    """
    from launcher.bootstrap import check_core_dependencies

    deps = check_core_dependencies()
    results: Dict[str, bool] = {}
    for name, available in deps.items():
        results[f"dependency:{name}"] = available

    results["port:5000"] = is_port_available(DEFAULT_PORT)
    return results
