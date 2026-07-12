# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Health check endpoints for Koto.

Provides /api/health (detailed) and /api/ping (lightweight) endpoints
used by Docker healthchecks and container orchestrators.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Blueprint, current_app, jsonify

logger = logging.getLogger(__name__)

health_bp = Blueprint("health", __name__)

_START_TIME = time.monotonic()

# Resolve paths once at import time
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_VERSION_FILE = _PROJECT_ROOT / "VERSION"
_WORKSPACE_DIR = _PROJECT_ROOT / "workspace"

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


def _check_disk() -> dict:
    """Check that workspace directory has enough free disk space."""
    try:
        path = str(_WORKSPACE_DIR) if _WORKSPACE_DIR.exists() else str(_PROJECT_ROOT)
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


@health_bp.route("/api/ping/cloud", methods=["GET"])
def ping_cloud():
    """Measure round-trip latency to the active DeepSeek endpoint."""
    provider = "deepseek"
    target_url = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com").strip()

    try:
        t0 = time.monotonic()
        requests.head(target_url, timeout=5, allow_redirects=False)
        latency_ms = round((time.monotonic() - t0) * 1000)
        return (
            jsonify(
                {"reachable": True, "latency_ms": latency_ms, "target": target_url, "provider": provider}
            ),
            200,
        )
    except requests.exceptions.Timeout:
        return (
            jsonify(
                {
                    "reachable": False,
                    "latency_ms": None,
                    "error": "timeout",
                    "target": target_url,
                    "provider": provider,
                }
            ),
            200,
        )
    except Exception as exc:
        return (
            jsonify(
                {
                    "reachable": False,
                    "latency_ms": None,
                    "error": str(exc),
                    "target": target_url,
                    "provider": provider,
                }
            ),
            200,
        )


@health_bp.route("/api/ping/cloud/all", methods=["GET"])
def ping_cloud_all():
    """Return latency for cloud providers exposed by the current product."""
    from urllib.parse import urlparse

    results = {}

    providers = {
        "deepseek": os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com").strip(),
    }

    for provider, base_url in providers.items():
        parsed = urlparse(base_url)
        netloc = parsed.netloc or parsed.path.split("/")[0]
        scheme = parsed.scheme or "https"
        target_url = f"{scheme}://{netloc}"

        try:
            t0 = time.monotonic()
            requests.head(target_url, timeout=5, allow_redirects=False)
            latency_ms = round((time.monotonic() - t0) * 1000)
            results[provider] = {
                "reachable": True,
                "latency_ms": latency_ms,
                "target": target_url,
            }
        except requests.exceptions.Timeout:
            results[provider] = {
                "reachable": False,
                "latency_ms": None,
                "error": "timeout",
                "target": target_url,
            }
        except Exception as exc:
            results[provider] = {
                "reachable": False,
                "latency_ms": None,
                "error": str(exc),
                "target": target_url,
            }

    return jsonify(results), 200
