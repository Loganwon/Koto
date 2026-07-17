# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Health check endpoints for Koto.

Provides /api/health (detailed) and /api/ping (lightweight) endpoints
used by Docker healthchecks and container orchestrators.
"""

from __future__ import annotations

import hmac
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

health_bp = Blueprint("health", __name__)

_START_TIME = time.monotonic()

# Resolve immutable application paths once at import time. The workspace root
# remains dynamic and is read from the shared runtime owner in _check_disk().
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_VERSION_FILE = _PROJECT_ROOT / "VERSION"

# Minimum free disk space in bytes (100 MB)
_MIN_DISK_FREE_BYTES = 100 * 1024 * 1024


def _read_version() -> str:
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


def _check_ollama() -> dict:
    """Check if Ollama is reachable."""
    try:
        import requests

        resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
        ok = resp.status_code == 200
        return {"status": "ok" if ok else "error", "detail": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _safe_probe_error(response: requests.Response) -> str:
    """Turn a probe response into a short user-safe status without its body."""
    if response.status_code in {401, 403}:
        return "key_invalid"
    if response.status_code == 404:
        return "model_not_found"
    if response.status_code == 429:
        return "rate_limited"
    return f"http_{response.status_code}"


def _probe_deepseek() -> dict:
    """Measure a real authenticated DeepSeek completion, never just its host."""
    from app.core.llm.deepseek_config import DEEPSEEK_DEFAULT_BASE_URL, get_deepseek_api_key
    from app.core.llm.model_selection import get_configured_cloud_model

    key = get_deepseek_api_key()
    model_id = get_configured_cloud_model(task_type="CHAT")
    if not key:
        return {"reachable": False, "latency_ms": None, "error": "key_missing", "model_id": model_id}

    base_url = (
        os.getenv("DEEPSEEK_BASE_URL")
        or os.getenv("DEEPSEEK_API_BASE")
        or DEEPSEEK_DEFAULT_BASE_URL
    ).rstrip("/")
    endpoint = f"{base_url}/chat/completions"
    try:
        started = time.monotonic()
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model_id,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "temperature": 0,
                "stream": False,
            },
            timeout=15,
        )
        latency_ms = round((time.monotonic() - started) * 1000)
        if not response.ok:
            return {"reachable": False, "latency_ms": None, "error": _safe_probe_error(response), "model_id": model_id}
        return {"reachable": True, "latency_ms": latency_ms, "model_id": model_id}
    except requests.exceptions.Timeout:
        return {"reachable": False, "latency_ms": None, "error": "timeout", "model_id": model_id}
    except requests.RequestException:
        logger.info("DeepSeek model probe failed", exc_info=True)
        return {"reachable": False, "latency_ms": None, "error": "network_error", "model_id": model_id}


def _probe_local_model() -> dict:
    """Measure one real Ollama generation for the configured local model."""
    from app.core.llm.local_model_runtime import get_configured_local_model_tag

    model_id = get_configured_local_model_tag()
    if not model_id:
        return {"reachable": False, "latency_ms": None, "error": "model_missing", "model_id": ""}
    base_url = (os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    try:
        started = time.monotonic()
        response = requests.post(
            f"{base_url}/api/generate",
            json={"model": model_id, "prompt": "ping", "stream": False, "options": {"num_predict": 1, "temperature": 0}},
            timeout=20,
            proxies={"http": None, "https": None},
        )
        latency_ms = round((time.monotonic() - started) * 1000)
        if not response.ok:
            return {"reachable": False, "latency_ms": None, "error": _safe_probe_error(response), "model_id": model_id}
        return {"reachable": True, "latency_ms": latency_ms, "model_id": model_id}
    except requests.exceptions.Timeout:
        return {"reachable": False, "latency_ms": None, "error": "timeout", "model_id": model_id}
    except requests.RequestException:
        return {"reachable": False, "latency_ms": None, "error": "service_unavailable", "model_id": model_id}


def _check_disk() -> dict:
    """Check that workspace directory has enough free disk space."""
    try:
        from app.core.config.workspace_runtime import get_workspace_root

        workspace_dir = Path(get_workspace_root())
        path = str(workspace_dir) if workspace_dir.exists() else str(_PROJECT_ROOT)
        usage = shutil.disk_usage(path)
        ok = usage.free > _MIN_DISK_FREE_BYTES
        free_mb = round(usage.free / (1024 * 1024), 1)
        return {"status": "ok" if ok else "error", "free_mb": free_mb}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_blueprint_registration() -> dict:
    """Surface capabilities skipped during application startup.

    Registration is owned by ``web.app_blueprints``.  It writes a compact
    ledger into the Flask application's extensions so a development process
    can still start for diagnosis without falsely reporting a healthy product.
    """
    state = current_app.extensions.get("koto_blueprint_registration", {})
    missing_required = list(state.get("missing_required", ()))
    missing_optional = list(state.get("missing_optional", ()))

    if missing_required:
        return {
            "status": "error",
            "missing_required": missing_required,
            "missing_optional": missing_optional,
        }
    if missing_optional:
        return {
            "status": "warning",
            "missing_required": [],
            "missing_optional": missing_optional,
        }
    return {"status": "ok", "missing_required": [], "missing_optional": []}


def _overall_status(checks: dict) -> str:
    """Derive overall status from individual checks.

    - "healthy"  : all checks pass
    - "degraded" : non-critical checks (ollama or optional blueprint) fail
    - "unhealthy": critical checks (disk or required blueprint) fail
    """
    critical = ["disk", "blueprints"]
    any_fail = any(v.get("status") != "ok" for v in checks.values())
    critical_fail = any(checks.get(k, {}).get("status") == "error" for k in critical)
    if critical_fail:
        return "unhealthy"
    if any_fail:
        return "degraded"
    return "healthy"


@health_bp.route("/api/health", methods=["GET"])
def health():
    """Detailed health check.
    ---
    tags:
      - Health
    responses:
      200:
        description: System is healthy or degraded
        schema:
          type: object
          properties:
            status:
              type: string
              enum: [healthy, degraded, unhealthy]
            uptime_seconds:
              type: number
            version:
              type: string
            checks:
              type: object
            timestamp:
              type: string
      503:
        description: System is unhealthy
    """
    try:
        checks = {
            "ollama": _check_ollama(),
            "disk": _check_disk(),
            "blueprints": _check_blueprint_registration(),
        }
        status = _overall_status(checks)
        payload = {
            "status": status,
            "uptime_seconds": round(time.monotonic() - _START_TIME, 2),
            "version": _read_version(),
            "checks": checks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        launch_token = os.getenv("KOTO_LAUNCH_TOKEN", "").strip()
        presented_token = request.headers.get("X-Koto-Launch-Token", "").strip()
        if (
            launch_token
            and presented_token
            and hmac.compare_digest(launch_token, presented_token)
        ):
            # Return the token only to the launcher that already knows it. This
            # proves the response belongs to the process started in this launch
            # attempt without exposing the token to ordinary health clients.
            payload["launch_token"] = launch_token
        code = 200 if status != "unhealthy" else 503
        return jsonify(payload), code
    except Exception:
        logger.exception("Health check failed unexpectedly")
        return jsonify({"status": "unhealthy", "error": "internal"}), 500


@health_bp.route("/api/ping", methods=["GET"])
def ping():
    """Lightweight liveness probe with provider availability.
    ---
    tags:
      - Health
    responses:
      200:
        description: Service is alive with provider info
    """
    providers = []
    try:
        from app.core.llm.provider_factory import list_available_providers
        providers = list_available_providers()
    except Exception:
        pass

    ollama_available = "ollama" in providers
    cloud_providers = [p for p in providers if p != "ollama"]
    return jsonify({
        "status": "ok",
        "ollama": ollama_available,
        "providers": providers,
        "cloud_providers": cloud_providers,
        "has_any_provider": len(providers) > 0,
    }), 200


@health_bp.route("/api/ping/models", methods=["GET"])
def ping_models():
    """Probe the configured cloud key and local model through real inference calls.

    This endpoint deliberately returns HTTP 200 even when a provider is down:
    the desktop status widget needs to render actionable red state instead of
    treating a failed provider as a failed Koto server.
    """
    from app.core.llm.local_model_runtime import (
        get_configured_local_model_tag,
        get_configured_model_mode,
    )
    from app.core.llm.model_selection import (
        get_configured_cloud_model,
        get_configured_cloud_provider,
    )

    mode = get_configured_model_mode()
    cloud_provider = get_configured_cloud_provider()
    cloud_model = get_configured_cloud_model(task_type="CHAT", provider=cloud_provider)
    local_model = get_configured_local_model_tag()
    cloud = _probe_deepseek()
    local = _probe_local_model()
    active = local if mode == "local" else cloud

    return jsonify(
        {
            "active": {
                "mode": mode,
                "provider": "ollama" if mode == "local" else cloud_provider,
                "model_id": local_model if mode == "local" else cloud_model,
                "reachable": bool(active.get("reachable")),
            },
            "deepseek": cloud,
            "local": local,
        }
    ), 200
