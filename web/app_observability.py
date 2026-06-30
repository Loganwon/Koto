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
        from prometheus_flask_exporter import PrometheusMetrics

        metrics_token = os.environ.get("METRICS_TOKEN", "")
        prometheus = PrometheusMetrics(app, group_by="endpoint")
        prometheus.info("koto_app_info", "Koto application info", version=app_version)

        if metrics_token:
            @app.before_request
            def _guard_metrics():
                if request.path == "/metrics":
                    auth = request.headers.get("Authorization", "")
                    if auth != f"Bearer {metrics_token}":
                        return unauthorized_response()

        logger.info("Prometheus metrics enabled at /metrics")
    except ImportError:
        logger.debug("prometheus-flask-exporter not installed; /metrics disabled")

    try:
        from flasgger import Swagger

        Swagger(app, config=_SWAGGER_CONFIG, template=_SWAGGER_TEMPLATE)
        logger.info("Swagger UI enabled at /apidocs/")
    except ImportError:
        logger.debug("flasgger not installed; Swagger UI disabled")