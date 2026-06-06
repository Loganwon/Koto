from __future__ import annotations

import logging
import os
import socket
import sys
from typing import List, Optional
from urllib.parse import urlparse


logger = logging.getLogger(__name__)


def normalize_proxy_url(proxy_value: str) -> str:
    if not proxy_value:
        return ""
    value = proxy_value.strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"
    return value


def get_default_proxy_candidates() -> List[str]:
    custom = os.environ.get("KOTO_PROXY_PORTS", "")
    if custom.strip():
        return [normalize_proxy_url(f"http://127.0.0.1:{p.strip()}") for p in custom.split(",") if p.strip().isdigit()]
    return [
        "http://127.0.0.1:7890",
        "http://127.0.0.1:10809",
        "http://127.0.0.1:1080",
    ]


def get_env_proxy_candidates() -> List[str]:
    candidates: List[str] = []
    env_proxy = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )
    if env_proxy:
        candidates.append(normalize_proxy_url(env_proxy))

    force_proxy = str(os.getenv("FORCE_PROXY") or "").strip()
    if force_proxy and force_proxy.lower() not in {"auto", "system"}:
        candidates.append(normalize_proxy_url(force_proxy))
    return candidates


def get_windows_registry_proxy_candidates() -> List[str]:
    candidates: List[str] = []
    if not sys.platform.startswith("win"):
        return candidates
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            proxy_enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0] or 0)
            if proxy_enabled:
                proxy_server = str(
                    winreg.QueryValueEx(key, "ProxyServer")[0] or ""
                ).strip()
                if proxy_server:
                    if "=" in proxy_server and ";" in proxy_server:
                        parsed_map = {}
                        for pair in proxy_server.split(";"):
                            if "=" not in pair:
                                continue
                            k, v = pair.split("=", 1)
                            parsed_map[k.strip().lower()] = v.strip()
                        for proto in ("https", "http", "socks", "socks5"):
                            value = parsed_map.get(proto)
                            if value:
                                candidates.append(normalize_proxy_url(value))
                    else:
                        candidates.append(normalize_proxy_url(proxy_server))
    except Exception as exc:
        logger.debug("Failed to read Windows registry proxy: %s", exc)
    return candidates


def collect_proxy_candidates(include_defaults: bool = True) -> List[str]:
    candidates: List[str] = []

    candidates.extend(get_env_proxy_candidates())
    candidates.extend(get_windows_registry_proxy_candidates())

    if include_defaults:
        candidates.extend(get_default_proxy_candidates())

    seen: set = set()
    deduped: List[str] = []
    for item in candidates:
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def detect_live_proxy(candidates: Optional[List[str]] = None, timeout: float = 0.1) -> Optional[str]:
    if candidates is None:
        candidates = collect_proxy_candidates()

    for proxy in candidates:
        try:
            parsed = urlparse(proxy)
            host = parsed.hostname
            port = parsed.port
            if not host or not port:
                continue
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                return proxy
        except Exception:
            continue
    return None


def set_env_proxy(proxy: str) -> None:
    if proxy:
        os.environ["HTTPS_PROXY"] = proxy
        os.environ["HTTP_PROXY"] = proxy
        logger.info("Set proxy: %s", proxy)
