from __future__ import annotations

import logging
import sys


def log_exception(
    logger: logging.Logger | None = None,
    msg: str = "Non-critical operation failed",
    level: int = logging.DEBUG,
    exc_info: bool = True,
) -> None:
    if logger is None:
        logger = logging.getLogger(__name__)
    logger.log(level, msg, exc_info=exc_info)


def handle_non_fatal(logger_name: str | None = None):
    """Return a callable that logs an exception and returns a default value.

    Usage:
        result = risky_call() or handle_non_fatal(__name__)()
    """
    logger = logging.getLogger(logger_name or __name__)

    def _handler(exc: BaseException | None = None) -> None:
        logger.debug("Non-fatal error (suppressed): %s", exc, exc_info=exc is not None)

    return _handler
