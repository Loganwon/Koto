"""
Centralized logging configuration for Koto.

Call setup_logging() once at server startup before any other imports that log.
All modules that do `logging.getLogger(__name__)` will inherit this config.
"""

import logging
import logging.handlers
import os
from pathlib import Path

_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
_BACKUP_COUNT = 5


def setup_logging(
    level: int = logging.INFO,
    log_dir: str = "logs",
) -> None:
    """Configure root logger with rotating file + console handlers.

    Args:
        level: Root log level (default INFO). Override with KOTO_LOG_LEVEL env var.
        log_dir: Directory for log files (default "logs").
    """
    env_level = os.environ.get("KOTO_LOG_LEVEL", "").upper()
    if env_level and hasattr(logging, env_level):
        level = getattr(logging, env_level)

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / "koto.log"

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        str(log_file),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    if root.handlers:
        root.handlers.clear()

    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Quieten noisy third-party loggers
    for noisy in ("urllib3", "httpx", "httpcore", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
