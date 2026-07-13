#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
"""Koto unified entry point — delegates to the correct app mode."""

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

from launcher import bootstrap, health
from src.startup_diagnostics import run_startup_diagnostics

logger = logging.getLogger("koto.launcher.entry")


def setup_logging(level: str = "INFO") -> None:
    """Configure launcher logging."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="[%(asctime)s] %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def launch_desktop(root: Path, port: int) -> int:
    """Launch Koto in desktop (pywebview) mode."""
    entry = bootstrap.find_entry_script("desktop")
    if not entry:
        logger.error("No desktop entry script found. Run 'python -m launcher --server' for Flask mode.")
        return 1

    # ``port`` may have been changed after resolving a conflict.  Keeping an
    # inherited value here makes the launcher report one port and start another.
    os.environ["KOTO_PORT"] = str(port)
    os.chdir(str(root))

    logger.info("Starting desktop mode: %s (port %d)", entry, port)
    return subprocess.call([sys.executable, entry])


def launch_server(root: Path, port: int) -> int:
    """Launch Koto in Flask server mode."""
    entry = bootstrap.find_entry_script("server")
    if not entry:
        logger.error("No server entry script found.")
        return 1

    os.environ["KOTO_PORT"] = str(port)
    os.chdir(str(root))

    logger.info("Starting server mode: %s (port %d)", entry, port)
    logger.info("Open http://localhost:%d in your browser.", port)
    return subprocess.call([sys.executable, entry])


def main() -> int:
    parser = argparse.ArgumentParser(description="Koto Unified Launcher")
    parser.add_argument(
        "--mode", "-m",
        choices=["desktop", "server"],
        default="desktop",
        help="Launch mode (default: desktop)",
    )
    parser.add_argument(
        "--server", "-s",
        action="store_true",
        help="Shortcut for --mode server",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Run environment health check and exit",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=None,
        help=f"Port to use (default: {health.DEFAULT_PORT})",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level",
    )

    args = parser.parse_args()
    setup_logging(args.log_level)
    root = Path(__file__).resolve().parent.parent

    # Health check mode
    if args.health:
        ok = bootstrap.run_health_report()
        ready = health.check_runtime_readiness()
        for name, status in ready.items():
            logger.info("  %-20s %s", name, "OK" if status else "MISSING")
        report = run_startup_diagnostics(root, include_import_check=True)
        logger.info("Startup self-check: %s", report["summary"])
        for check in report["checks"]:
            if check["level"] != "ok":
                logger.warning("  %-24s %s", check["name"], check["message"])
        return 0 if ok and report["status"] != "blocked" else 1

    mode = "server" if args.server else args.mode

    # Port resolution
    port = args.port or int(os.environ.get("KOTO_PORT", health.DEFAULT_PORT))
    if not health.is_port_available(port):
        alt = health.find_available_port(port + 1)
        logger.warning("Port %d in use, using %d instead.", port, alt)
        port = alt

    if mode == "desktop":
        return launch_desktop(root, port)
    else:
        return launch_server(root, port)


if __name__ == "__main__":
    sys.exit(main())
