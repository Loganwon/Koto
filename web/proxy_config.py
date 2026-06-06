from __future__ import annotations

import logging
import os
import sys
from typing import List, Optional

from app.core.utils.proxy_utils import (
    collect_proxy_candidates,
    detect_live_proxy,
    get_default_proxy_candidates,
    normalize_proxy_url,
    set_env_proxy,
)

logger = logging.getLogger(__name__)

PROXY_OPTIONS = get_default_proxy_candidates()


def _get_configured_proxy_from_settings(settings_manager) -> Optional[str]:
    try:
        enabled = settings_manager.get("proxy", "enabled")
        manual = settings_manager.get("proxy", "manual_proxy") or ""
        if enabled is not False and manual.strip():
            return normalize_proxy_url(manual.strip())
    except Exception as exc:
        logger.debug("Failed to read proxy from settings: %s", exc)
    return None


def extract_system_proxy_candidates(settings_manager=None) -> List[str]:
    candidates: List[str] = []

    if settings_manager is not None:
        manual = _get_configured_proxy_from_settings(settings_manager)
        if manual:
            candidates.append(manual)

    candidates.extend(collect_proxy_candidates(include_defaults=True))
    return candidates


def setup_proxy(settings_manager=None, force_proxy: str = "") -> Optional[str]:
    if force_proxy and force_proxy.lower() not in ("auto", "system"):
        set_env_proxy(force_proxy)
        return force_proxy

    if settings_manager is not None:
        try:
            if settings_manager.get("proxy", "enabled") is False:
                os.environ.pop("HTTPS_PROXY", None)
                os.environ.pop("HTTP_PROXY", None)
                logger.info("Proxy disabled by user")
                return None
        except Exception as exc:
            logger.debug("Failed to check proxy setting: %s", exc)

    proxy_candidates = extract_system_proxy_candidates(settings_manager)
    live = detect_live_proxy(proxy_candidates, timeout=0.1)
    if live:
        set_env_proxy(live)
    return live
