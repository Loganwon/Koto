# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from app.core.llm.model_mode import normalize_model_mode
from app.core.llm.model_selection import (
    is_archived_cloud_model,
    normalize_cloud_provider,
)
from app.core.llm.provider_boundary import sanitize_public_settings

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_legacy_gemini_values_normalize_to_active_deepseek_boundary() -> None:
    assert normalize_cloud_provider("gemini") == "deepseek"
    assert normalize_model_mode("gemini", default="cloud") == "cloud"
    for model_id in (
        "gemini-2.5-flash",
        "nano-banana-pro-preview",
        "imagen-4.0-generate-001",
        "deep-research-pro-preview-12-2025",
    ):
        assert is_archived_cloud_model(model_id) is True


def test_public_settings_strip_legacy_provider_state() -> None:
    payload = sanitize_public_settings(
        {
            "model_mode": "gemini",
            "ai": {
                "cloud_provider": "gemini",
                "default_model": "gemini-2.5-flash",
                "cloud_model": "nano-banana-pro-preview",
                "gemini_model": "gemini-2.5-pro",
                "gemini_api_key": "secret",
            },
        }
    )

    assert payload["model_mode"] == "cloud"
    assert payload["ai"]["cloud_provider"] == "deepseek"
    assert payload["ai"]["default_model"] == "deepseek-chat"
    assert payload["ai"]["cloud_model"] == "deepseek-chat"
    assert "gemini_model" not in payload["ai"]
    assert "gemini_api_key" not in payload["ai"]


def test_active_model_selection_surfaces_do_not_expose_gemini() -> None:
    settings_template = _read("web/templates/_settings_panel.html")
    model_controls = _read("web/templates/_workspace_model_controls.html")
    model_settings = _read("web/src/workspace/model-settings.ts")

    assert "Gemini" not in settings_template
    assert 'value="gemini"' not in settings_template
    assert "Gemini" not in model_controls
    assert 'data-model-mode="gemini"' not in model_controls
    assert "Gemini" not in model_settings
    assert "'gemini'" not in model_settings


def test_all_interactive_frontend_sources_hide_archived_provider_names() -> None:
    forbidden = ("gemini", "nano-banana", "imagen", "deep-research-pro-preview")
    roots = (
        ROOT / "web" / "src",
        ROOT / "web" / "templates",
        ROOT / "web" / "static" / "css",
    )
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix.lower() not in {".ts", ".html", ".css"}:
                continue
            source = path.read_text(encoding="utf-8").lower()
            for token in forbidden:
                assert token not in source, f"{token} leaked through {path}"


def test_health_and_painter_surfaces_do_not_invoke_archived_provider() -> None:
    health = _read("web/routes/health.py").lower()
    painter = _read("web/services/chat_stream/generate/painter_handler.py").lower()

    assert "gemini" not in health
    assert "generativelanguage.googleapis.com" not in health
    assert "client.models" not in painter
    assert "generate_images" not in painter
    assert "gemini" not in painter
    assert "imagen" not in painter


def test_legacy_interactions_models_fail_closed_at_the_web_compatibility_boundary() -> (
    None
):
    source = _read("web/app.py")

    tracked_models_start = source.index("class _TrackedModels:")
    tracked_models_end = source.index("class _ClientProxy:")
    tracked_models = source[tracked_models_start:tracked_models_end]
    assert "Fail closed: archived models" in tracked_models
    assert "Interactions API 已归档" in tracked_models
    assert "text = _call_interactions_api_sync" not in tracked_models


def test_web_app_does_not_keep_a_google_client_construction_escape_hatch() -> None:
    source = _read("web/app.py")

    assert "_create_research_client_legacy_unreachable" not in source
    assert "google.genai._api_client" not in source
    assert "genai.Client(" not in source


def test_web_app_drops_unreachable_interactions_execution_implementation() -> None:
    source = _read("web/app.py")

    assert "def _poll_interaction(" not in source
    assert "def _extract_interaction_text_global(" not in source
    assert "def _call_interactions_api_sync(" not in source
    assert "_INTERACTION_TERMINAL_STATES" not in source


def test_chat_error_guidance_does_not_send_users_to_archived_gemini_setup() -> None:
    source = _read("web/app.py")
    error_guidance = source[
        source.index('"location is not supported"') : source.index(
            "session_manager.append_and_save",
            source.index('"location is not supported"'),
        )
    ]

    assert "gemini_config.env" not in error_guidance
    assert "aistudio.google.com" not in error_guidance
    assert "Google AI Studio" not in error_guidance
    assert "DeepSeek API 密钥" in error_guidance
    assert "本地 Ollama" in error_guidance


def test_ppt_research_does_not_keep_a_direct_interactions_api_escape_hatch() -> None:
    source = _read("web/web_searcher.py")

    assert '"create_research_client"' not in source
    assert '"_poll_interaction"' not in source


def test_release_manifest_does_not_collect_archived_provider() -> None:
    spec = _read("koto.spec").lower()
    requirements = _read("config/requirements.txt").lower()

    assert "    'gemini_config.env'," not in spec
    assert "app.core.llm.gemini" not in spec
    assert "google-genai" not in requirements
    assert "('gemini.py', 'gemini_config.py')" in spec


def test_public_model_catalog_filters_legacy_models_and_interactions() -> None:
    from web.blueprints.settings import _augment_models_for_cloud_provider

    payload = _augment_models_for_cloud_provider(
        {
            "model_map": {
                "CHAT": {
                    "model_id": "gemini-2.5-flash",
                    "provider": "gemini",
                },
                "RESEARCH": {
                    "model_id": "deep-research-pro-preview-12-2025",
                    "provider": "gemini",
                },
            },
            "available": [
                {"id": "nano-banana-pro-preview", "provider": "gemini"},
                {"id": "deepseek-chat", "provider": "deepseek"},
            ],
            "fallback": "gemini-2.5-flash",
            "interactions_only": ["deep-research-pro-preview-12-2025"],
        }
    )
    serialized = str(payload).lower()

    assert "gemini" not in serialized
    assert "nano-banana" not in serialized
    assert "deep-research-pro-preview" not in serialized
    assert payload["fallback"] == "deepseek-chat"
    assert payload["interactions_only"] == []


def test_active_goal_and_workflow_paths_do_not_import_gemini_provider() -> None:
    active_paths = (
        "app/core/goal/goal_manager.py",
        "app/core/goal/goal_job_handler.py",
        "app/core/workflow_engine.py",
    )
    for path in active_paths:
        source = _read(path)
        assert "app.core.llm.gemini" not in source
        assert 'provider="gemini"' not in source


def test_application_modules_do_not_import_archived_gemini_provider() -> None:
    forbidden = "from app.core.llm.gemini import GeminiProvider"
    for root_name in ("app", "web", "src", "launcher"):
        for path in (ROOT / root_name).rglob("*.py"):
            assert forbidden not in path.read_text(encoding="utf-8"), path


def test_provider_factory_keeps_explicit_archive_rejection() -> None:
    source = _read("app/core/llm/provider_factory.py")
    assert "Gemini cloud provider has been archived" in source
