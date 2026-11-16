from __future__ import annotations

import os
from logging import Logger

from flask import Flask, request

_SWAGGER_CONFIG = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/apispec.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs/",
}

_SWAGGER_TEMPLATE = {
    "info": {
        "title": "Koto API",
        "description": "API documentation for Koto AI Assistant",
        "version": "1.0.0",
    },
    "basePath": "/",
    "schemes": ["http", "https"],
    "securityDefinitions": {
        "Bearer": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "description": "JWT token: `Bearer <token>`",
        }
    },
}


def configure_observability(
    app: Flask,
    logger: Logger,
    app_version: str,
    unauthorized_response,
) -> None:
    """Configure optional observability and API docs integrations."""
    deploy_mode = os.environ.get("KOTO_DEPLOY_MODE", "local").strip().lower()
    metrics_enabled = (
        os.environ.get("KOTO_ENABLE_METRICS", "").strip().lower()
        in {"1", "true", "yes", "on"}
        or deploy_mode in {"cloud", "production", "prod"}
    )
    swagger_enabled = (
        os.environ.get("KOTO_ENABLE_API_DOCS", "").strip().lower()
        in {"1", "true", "yes", "on"}
        or app.debug
    )
    sentry_dsn = os.environ.get("SENTRY_DSN", "")
    if sentry_dsn:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.flask import FlaskIntegration

            sentry_sdk.init(
                dsn=sentry_dsn,
                integrations=[FlaskIntegration()],
                release=app_version,
                traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.1")),
                send_default_pii=False,
            )
            logger.info("Sentry error tracking enabled (release=%s)", app_version)
        except ImportError:
            logger.warning("SENTRY_DSN set but sentry-sdk not installed; skipping")

    try:
        if not metrics_enabled:
            raise ModuleNotFoundError("metrics disabled by runtime profile")
        from prometheus_flask_exporter import PrometheusMetrics

        metrics_token = os.environ.get("METRICS_TOKEN", "")
        prometheus = PrometheusMetrics(app, group_by="endpoint")
        try:
            prometheus.info("koto_app_info", "Koto application info", version=app_version)
        except ValueError as exc:
            # App modules can be reloaded by the desktop runtime and pytest;
            # the Prometheus global registry already owns this constant metric.
            if "koto_app_info" not in str(exc):
                raise
            logger.debug("Prometheus app-info metric already registered")

        if metrics_token:
            @app.before_request
            def _guard_metrics():
                if request.path == "/metrics":
                    auth = request.headers.get("Authorization", "")
                    if auth != f"Bearer {metrics_token}":
                        return unauthorized_response()

        logger.info("Prometheus metrics enabled at /metrics")
    except ImportError:
        logger.debug("Prometheus metrics disabled or dependency unavailable")

    try:
        if not swagger_enabled:
            raise ModuleNotFoundError("API docs disabled by runtime profile")
        from flasgger import Swagger

        Swagger(app, config=_SWAGGER_CONFIG, template=_SWAGGER_TEMPLATE)
        logger.info("Swagger UI enabled at /apidocs/")
    except ImportError:
        logger.debug("Swagger UI disabled or dependency unavailable")
