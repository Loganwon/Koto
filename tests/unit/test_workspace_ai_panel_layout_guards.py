# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_workspace_template_uses_bottom_model_toggle_and_keeps_files_above_input() -> (
    None
):
    html = _read("web/templates/index.html")
    model_controls = _read("web/templates/_workspace_model_controls.html")
    settings_panel = _read("web/templates/_settings_panel.html")

    assert not (ROOT / "web/templates/workspace_assistant.html").exists()
    assert "{% include '_workspace_model_controls.html' %}" in html
    assert html.index('<div id="wa-ai-file-chips"') < html.index(
        '<div class="wa-input-box">'
    )
    composer = html[html.index('<div class="wa-input-box">') :]
    assert composer.index('<div class="wa-input-box-footer">') < composer.index(
        "{% include '_workspace_model_controls.html' %}"
    )
    assert composer.index(
        "{% include '_workspace_model_controls.html' %}"
    ) < composer.index('<div class="wa-footer-actions">')
    assert composer.index('<div class="wa-footer-actions">') < composer.index(
        'id="wa-send-btn"'
    )

    assert 'id="wa-model-mode-toggle"' in model_controls
    assert 'id="wa-model-mode-deepseek-btn"' in model_controls
    assert 'id="wa-model-mode-local-btn"' in model_controls
    assert 'id="wa-model-mode-gemini-btn"' not in model_controls
    assert "Gemini" not in model_controls
    assert "Gemini" not in settings_panel
    assert "DeepSeek" in settings_panel


def test_workspace_activity_panels_and_task_workbench_use_ts_runtime() -> None:
    app_marketplace = _read("web/src/app/marketplace.ts")
    app_settings = _read("web/src/app/settings.ts")
    skills_panel = _read("web/src/skills/skills-panel.ts")
    embedded_mode = _read("web/src/ui/embedded-mode.ts")
    task_workbench = _read("web/src/workspace/task-workbench.ts")
    bundle_entry = _read("web/src/bundles/workspace.ts")
    assets = _read("web/templates/_workspace_asset_scripts.html")

    assert "fetch('/api/skills/bindings?binding_type=intent')" in app_marketplace
    assert "`/api/skills/bindings/${encodeURIComponent(bindingId)}`" in app_marketplace
    assert "fetch('/api/jobs/triggers')" in app_marketplace
    assert "`/api/jobs/triggers/${encodeURIComponent(triggerId)}`" in app_marketplace
    assert "setActivityActive('navSettingsBtn')" in app_settings
    assert "_setActivityActive('navSkillsBtn')" in skills_panel
    assert "isUnifiedWorkspace()" in app_settings
    assert "_isUnifiedWorkspace()" in skills_panel
    assert "export function showFileWorkspace()" in embedded_mode
    assert "export function showAiWorkspace()" in embedded_mode

    assert "import '../workspace/task-workbench';" in bundle_entry
    assert "workspace-task-workbench.js" not in assets
    assert not (ROOT / "web/static/js/workspace-task-workbench.js").exists()
    assert "function syncTaskColumnToggle" not in task_workbench
    assert "toggleTaskWorkbench" not in task_workbench
    assert "openTaskWorkbenchForCurrentRun" in task_workbench


def test_workspace_has_single_unified_frontend_entry() -> None:
    pages_bp = _read("web/blueprints/pages.py")
    embedded_mode = _read("web/src/ui/embedded-mode.ts")
    build_notes = _read("web/univer-editor/BUILD.md")
    workspace_bff = _read("web/blueprints/workspace_assistant.py")
    assets = _read("web/templates/_workspace_asset_scripts.html")

    assert '@pages_bp.route("/workspace-assistant")' in pages_bp
    assert "redirect(target, code=302)" in pages_bp
    assert 'render_template("workspace_assistant.html")' not in pages_bp
    assert "window.open('/workspace-assistant'" not in embedded_mode
    assert "window.open('/', '_blank')" in embedded_mode
    assert "the only supported app entry is `/`" in build_notes
    assert "`/workspace-assistant` is a compatibility redirect to `/`" in build_notes
    assert '"js" / "build" / "workspace-bundle.js"' in workspace_bff
    assert '"js" / "workspace-assistant.js"' not in workspace_bff
    assert "workspace-assistant.js" not in assets
    assert not (ROOT / "web/static/js/workspace-assistant.js").exists()


def test_workspace_subject_bar_and_action_row_styles_support_restored_layout() -> None:
    css = _read("web/static/css/workspace.css")
    ai_panel_css = _read("web/static/css/workspace-ai-panel.css")
    task_dispatcher = _read("web/src/workspace/task-dispatcher.ts")
    model_settings = _read("web/src/workspace/model-settings.ts")

    assert "toggleCurrentFileAIContext" not in task_dispatcher
    assert "files.push(currentFile)" not in task_dispatcher
    assert "current_file: currentFile," in task_dispatcher
    assert "wa_model_choice_explicit" in model_settings
    assert "_localRuntimeModel" in model_settings

    assert "#wa-subject-bar { display: none !important;" not in css
    assert "#wa-actions-bar" not in css
    assert ".wa-quick-btn" not in css
    assert ".wa-input-box-footer" in ai_panel_css
    assert ".wa-footer-meta" in ai_panel_css
    assert ".wa-footer-actions" in ai_panel_css
    assert ".wa-model-mode-toggle" in ai_panel_css
    assert ".wa-model-mode-toggle-btn" in ai_panel_css
    assert ".wa-model-mode-sub[hidden]" in ai_panel_css
    assert ".wa-model-mode-sub::before" in ai_panel_css
    assert ".wa-attach-file-btn" in ai_panel_css
    assert ".wa-wf-active-chip" in ai_panel_css
    assert "content: '·';" in ai_panel_css
