"""Proxy candidate discovery kept independent from Flask application wiring."""

from __future__ import annotations

import os
import socket
import sys
from typing import Any, Callable, Iterable
from urllib.parse import urlparse


def extract_system_proxy_candidates(
    *,
    settings_manager: Any,
    normalize_proxy_url: Callable[[str], str],
    proxy_options: Iterable[str],
) -> list[str]:
    """Return configured, environment, system, and local proxy candidates."""
    candidates: list[str] = []

    try:
        enabled = settings_manager.get("proxy", "enabled")
        manual_proxy = settings_manager.get("proxy", "manual_proxy") or ""
        if enabled is not False and manual_proxy.strip():
            candidates.append(normalize_proxy_url(manual_proxy.strip()))
    except Exception:
        pass

    environment_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if environment_proxy:
        candidates.append(normalize_proxy_url(environment_proxy))

    if sys.platform.startswith("win"):
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                proxy_enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
                if proxy_enabled:
                    proxy_server = str(
                        winreg.QueryValueEx(key, "ProxyServer")[0]
                    ).strip()
                    if "=" in proxy_server and ";" in proxy_server:
                        proxy_map = {
                            protocol.strip().lower(): value.strip()
                            for pair in proxy_server.split(";")
                            if "=" in pair
                            for protocol, value in [pair.split("=", 1)]
                        }
                        for protocol in ("https", "http", "socks", "socks5"):
                            if proxy_map.get(protocol):
                                candidates.append(
                                    normalize_proxy_url(proxy_map[protocol])
                                )
                    elif proxy_server:
                        candidates.append(normalize_proxy_url(proxy_server))
        except Exception:
            pass

    candidates.extend(proxy_options)
    deduplicated: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        key = candidate.lower()
        if key not in seen:
            seen.add(key)
            deduplicated.append(candidate)
    return deduplicated


def configure_proxy(
    *,
    force_proxy: str,
    settings_manager: Any,
    normalize_proxy_url: Callable[[str], str],
    proxy_options: Iterable[str],
    logger: Any,
) -> str | None:
    """Select a reachable proxy and update the process proxy environment."""
    if force_proxy and force_proxy.lower() not in {"auto", "system"}:
        os.environ["HTTPS_PROXY"] = force_proxy
        os.environ["HTTP_PROXY"] = force_proxy
        logger.info("🔧 使用强制代理: %s", force_proxy)
        return force_proxy

    try:
        if settings_manager.get("proxy", "enabled") is False:
            os.environ.pop("HTTPS_PROXY", None)
            os.environ.pop("HTTP_PROXY", None)
            logger.info("🔧 用户已禁用代理")
            return None
    except Exception:
        pass

    for proxy in extract_system_proxy_candidates(
        settings_manager=settings_manager,
        normalize_proxy_url=normalize_proxy_url,
        proxy_options=proxy_options,
    ):
        try:
            parsed = urlparse(proxy)
            if not parsed.hostname or not parsed.port:
                continue
            with socket.create_connection((parsed.hostname, parsed.port), timeout=0.1):
                os.environ["HTTPS_PROXY"] = proxy
                os.environ["HTTP_PROXY"] = proxy
                logger.info("✅ 自动匹配系统代理: %s", proxy)
                return proxy
        except Exception:
            continue
    return None
