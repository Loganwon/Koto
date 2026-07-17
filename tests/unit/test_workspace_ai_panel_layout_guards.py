# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


class _WorkspaceAncestorParser(HTMLParser):
    """Track structural containers without depending on optional HTML packages."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, str, str]] = []
        self.workspace_ancestors: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"div", "main"}:
            return
        values = dict(attrs)
        if values.get("id") == "workspaceView":
            self.workspace_ancestors = list(self.stack)
        self.stack.append(
            (tag, values.get("id", "") or "", values.get("class", "") or "")
        )

    def handle_endtag(self, tag: str) -> None:
        if tag not in {"div", "main"}:
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


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


def test_workspace_view_stays_inside_main_application_shell() -> None:
    parser = _WorkspaceAncestorParser()
    parser.feed(_read("web/templates/index.html"))

    assert ("main", "", "main-content chatgpt-main") in parser.workspace_ancestors
    assert (
        "div",
        "",
        "app-shell chatgpt-app koto-unified-workspace",
    ) in parser.workspace_ancestors


def test_workspace_ai_entry_opens_a_conversation_not_the_history_browser() -> None:
    html = _read("web/templates/index.html")
    conversation_list = _read("web/src/workspace/conversation-list.ts")
    embedded_mode = _read("web/src/ui/embedded-mode.ts")

    assert (
        'id="wa-ai-session-list-view" class="wa-ai-session-list-view" aria-label="AI 对话与任务历史" hidden'
        in html
    )
    assert 'id="wa-ai-chat-view" class="wa-ai-chat-view">' in html
    assert "export function showAiChat(): void" in conversation_list
    assert "_showChatView();" in conversation_list
    assert "publishWorkspaceApi({" in conversation_list
    assert "showAiChat," in conversation_list
    assert "WA?.showAiChat" in embedded_mode
    assert "WA?.showAiSessionList" not in embedded_mode


def test_workspace_ai_panel_rejects_narrow_persisted_split_sizes() -> None:
    panel_layout = _read("web/src/ui/panel-layout.ts")
    embedded_mode = _read("web/src/ui/embedded-mode.ts")
    css = _read("web/static/css/workspace.css")

    assert "const _EMBEDDED_AI_MIN_WIDTH = 420;" in panel_layout
    assert "function _enforceEmbeddedAiWidth" in panel_layout
    assert "_enforceEmbeddedAiWidth(left, canvas, ai);" in panel_layout
    assert "minSize: [..._SPLIT_MIN_WIDTHS]" in panel_layout
    assert "wa_split_sizes_embedded" not in embedded_mode
    assert "min-width: 420px;" in css
    assert "wa_split_sizes_v2" in panel_layout
    assert "wa_split_sizes_embedded_v3" in panel_layout
    assert "_retireLegacySplitLayouts();" in panel_layout
    assert "getItem('wa_split_sizes')" not in panel_layout
    assert "getItem('wa_split_sizes_embedded')" not in panel_layout


def test_workspace_embedded_split_resizes_both_side_panels_without_width_animation() -> None:
    panel_layout = _read("web/src/ui/panel-layout.ts")
    css = _read("web/static/css/workspace.css")

    assert "const _SPLIT_DEFAULT = [15, 53, 32];" in panel_layout
    assert "const targets = ['#wa-left', '#wa-canvas', '#wa-ai'];" in panel_layout
    assert "savedSizes = _isUsableSplitSizes(parsed, 3)" in panel_layout
    assert "_setSplitDragging(true);" in panel_layout
    assert "_clearSplitDragging();" in panel_layout
    assert "body.wa-workspace-split-dragging #wa-left" in css
    assert "body.wa-workspace-split-dragging #wa-canvas" in css
    assert "body.wa-workspace-split-dragging #wa-ai" in css
    assert "transition: none !important;" in css


def test_unified_workspace_has_no_ownerless_legacy_resize_handles() -> None:
    html = _read("web/templates/index.html")
    settings_panel = _read("web/templates/_settings_panel.html")
    panel_layout = _read("web/src/ui/panel-layout.ts")
    style = _read("web/static/css/style.css")
    workspace_css = _read("web/static/css/workspace.css")

    for legacy_id in (
        "sidebarResizeHandle",
        "inputResizeHandle",
        "settingsResizeHandle",
        "skillsResizeHandle",
    ):
        assert legacy_id not in html
        assert legacy_id not in settings_panel

    assert ".resize-handle {" not in style
    assert ".resize-handle-row" not in style
    assert ".resize-handle-sidebar" not in style
    assert ".resize-handle-skills" not in style
    assert ".settings-panel.active .resize-handle" not in workspace_css
    assert ".skills-panel.active .resize-handle" not in workspace_css
    assert ".koto-activity-bar .resize-handle" not in workspace_css
    assert "WA._initSplit" not in panel_layout
    assert "WA.isAiPanelCollapsed" not in panel_layout
    assert "window as any)._applySavedAiPanelState" not in panel_layout
    assert "export interface SplitConfig" not in panel_layout
    assert "export interface PanelLayout" not in panel_layout


def test_workspace_split_lifecycle_recovers_from_stale_state_and_storage_failures() -> None:
    panel_layout = _read("web/src/ui/panel-layout.ts")

    assert "function _readStorage" in panel_layout
    assert "function _writeStorage" in panel_layout
    assert "function _removeStorage" in panel_layout
    assert "function _persistSplitSizes" in panel_layout
    assert "if (!_isUsableSplitSizes(sizes, 3)) return;" in panel_layout
    assert "function _hasLiveSplitInstance" in panel_layout
    assert "function _discardStaleSplitInstance" in panel_layout
    assert "_workspaceGutterCount(workspace) === 2" in panel_layout
    assert "typeof splitFactory !== 'function'" in panel_layout
    assert "function _cancelActiveSplitDrag" in panel_layout
    assert "pair?.dragging && typeof pair.stop === 'function'" in panel_layout
    assert "window.addEventListener('blur', _cancelActiveSplitDrag);" in panel_layout
    assert "window.addEventListener('touchcancel', _cancelActiveSplitDrag, true);" in panel_layout
    assert "if (document.hidden) _cancelActiveSplitDrag();" in panel_layout
    assert "split.parent === workspace" in panel_layout
    assert "_applySavedAiPanelState();" in panel_layout
    assert "_STANDALONE_SPLIT_DEFAULT" not in panel_layout
    assert "_splitLayoutStorageKey" not in panel_layout


def test_workspace_uses_only_current_file_menu_and_skill_message_paths() -> None:
    context_menu = _read("web/src/workspace/fs-context-menu.ts")
    skill_extensions = _read("web/src/skills/skill-ui-extensions.ts")
    skill_ui = _read("web/src/skills/skill-ui.ts")
    active_composer = _read("web/src/shared/active-composer.ts")

    assert "wa._showCtxMenu" not in context_menu
    assert "wa.renameWorkspaceFile" not in context_menu
    assert "function _submitSkillMessage" in skill_extensions
    assert "function sendMessage(text: string)" not in skill_extensions
    assert "#wa-ai-input-area" in skill_extensions
    assert "#wa-ai-messages .wa-msg.ai" in skill_extensions
    assert "#wa-ai-messages, #messages" in skill_extensions
    assert (
        "el.classList.contains('wa-msg') && el.classList.contains('ai')"
        in skill_extensions
    )
    assert "#wa-user-input" in skill_ui
    assert "messageInput" not in skill_ui
    assert "messageInput" not in active_composer
    assert "getActiveKotoComposer" in skill_ui
    assert "from '../shared/active-composer';" in skill_ui


def test_workspace_ai_controls_have_an_actionable_default_state() -> None:
    conversation_list = _read("web/src/workspace/conversation-list.ts")
    composer = _read("web/src/workspace/ai-composer.ts")
    panel_layout = _read("web/src/ui/panel-layout.ts")
    html = _read("web/templates/index.html")

    assert "sessionTitle(meta, _activeAiSessionId) || 'Koto AI'" in conversation_list
    assert (
        "button.disabled = !input || input.disabled || !input.value.trim();" in composer
    )
    assert "const showAiChat = (window as any).WA?.showAiChat;" in panel_layout
    assert "点击左侧快捷卡片" not in html


def test_workspace_click_targets_expose_keyboard_and_expanded_state() -> None:
    html = _read("web/templates/index.html")
    state = _read("web/src/workspace/state.ts")
    css = _read("web/static/css/workspace.css")

    assert 'id="tokenChip"' not in html
    assert (
        'id="statusIndicator"' in html and "onkeydown=\"if(event.key==='Enter'" in html
    )
    assert 'data-wa-section-toggle="workspace"' in html
    assert 'data-wa-section-toggle="recent"' in html
    assert "function _syncSectionToggleState" in state
    assert "_syncSectionToggleState('recent', state._recentOpen);" in state
    assert ".wa-section-toggle:focus-visible" in css


def test_ui_zoom_has_one_owner_and_reflows_workspace_split() -> None:
    html = _read("web/templates/index.html")
    theme = _read("web/src/app/theme.ts")
    panel_layout = _read("web/src/ui/panel-layout.ts")

    assert "document.documentElement.style.zoom=z" not in html
    assert "if (document.body) document.body.style.zoom = normalizedZoom;" in theme
    assert "root.style.zoom = '';" in theme
    assert "requestAnimationFrame(_reflowWorkspaceAfterZoom);" in theme
    assert "export function refreshWorkspaceLayout" in panel_layout
    assert "publishWorkspaceApi({" in panel_layout
    assert "refreshWorkspaceLayout," in panel_layout
    assert "WA.refreshWorkspaceLayout = refreshWorkspaceLayout" not in panel_layout


def test_unified_workspace_has_one_structural_layout_owner() -> None:
    theme = _read("web/src/app/theme.ts")
    state = _read("web/src/workspace/state.ts")
    style = _read("web/static/css/style.css")
    css = _read("web/static/css/workspace.css")

    assert "koto-layout-compact" in theme
    assert "koto-layout-compact" in state
    assert "koto-zoom-compact" not in theme
    assert "koto-zoom-compact" not in state
    assert "koto-zoom-compact" not in css

    assert "#workspaceView #wa-workspace" not in css
    assert "--koto-aux-panel-width:" in css
    assert "--koto-left-aux-panel-width" not in css
    assert "width: var(--koto-aux-panel-width);" in css
    assert "height: var(--koto-layout-height, var(--viewport-h, 100vh));" in css
    assert ".app-shell.koto-unified-workspace .side-panel-scrim" in css
    assert "--settings-panel-width" not in style
    assert "--skills-panel-width" not in style
    assert "--skills-panel-width" not in css
    assert "body.settings-panel-open .main-content" not in style
    assert "body.skills-panel-open .main-content" not in style
    assert "\n.settings-panel {" not in style
    assert "\n        .skills-panel {" not in css
    assert "workspacePanel" not in _read("web/templates/index.html")
    assert ".workspace-panel" not in style
    assert ".workspace-panel" not in css
    assert "openWorkspaceFolder" not in _read("web/src/app/router.ts")


def test_workspace_activity_panels_and_task_workbench_use_ts_runtime() -> None:
    app_marketplace = _read("web/src/app/marketplace.ts")
    app_settings = _read("web/src/app/settings.ts")
    skills_panel = _read("web/src/skills/skills-panel.ts")
    embedded_mode = _read("web/src/ui/embedded-mode.ts")
    task_workbench = _read("web/src/workspace/task-workbench.ts")
    task_workbench_loader = _read("web/src/workspace/task-workbench-loader.ts")
    task_workbench_bundle = _read("web/src/bundles/task-workbench.ts")
    bundle_entry = _read("web/src/bundles/workspace.ts")
    assets = _read("web/templates/_workspace_asset_scripts.html")

    assert "fetch('/api/skills/bindings?binding_type=intent')" in app_marketplace
    assert "`/api/skills/bindings/${encodeURIComponent(bindingId)}`" in app_marketplace
    assert "fetch('/api/jobs/triggers')" not in app_marketplace
    assert "`/api/jobs/triggers/${encodeURIComponent(triggerId)}`" not in app_marketplace
    assert "loadTriggers" not in app_marketplace
    assert "toggleTrigger" not in app_marketplace
    assert "setActivityActive('navSettingsBtn')" in app_settings
    assert "_setActivityActive('navSkillsBtn')" in skills_panel
    assert "isUnifiedWorkspace()" in app_settings
    assert "_isUnifiedWorkspace()" in skills_panel
    assert "export function showFileWorkspace()" in embedded_mode
    assert "export function showAiWorkspace()" in embedded_mode

    assert "import '../workspace/task-workbench';" not in bundle_entry
    assert "installTaskWorkbenchLoader();" in bundle_entry
    assert "import '../workspace/task-workbench';" in task_workbench_bundle
    assert "openTaskWorkbenchBridge" in task_workbench_loader
    assert "task-workbench-bundle.js" in assets
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
    assert "koto:model-runtime-changed" in model_settings
    assert "_localRuntimeModel" in model_settings

    assert "#wa-subject-bar { display: none !important;" not in css
    assert "#wa-actions-bar" not in css
    assert ".wa-quick-btn" not in css
    assert ".wa-input-box-footer" in ai_panel_css
    assert ".wa-footer-meta" in ai_panel_css
    assert ".wa-footer-actions" in ai_panel_css
    assert ".wa-model-mode-toggle" in ai_panel_css
    assert ".wa-model-mode-toggle-btn" in ai_panel_css
    assert ".wa-model-menu-trigger" in ai_panel_css
    assert ".wa-model-mode-menu" in ai_panel_css
    assert ".wa-model-menu-group-label" in ai_panel_css
    assert "font: inherit;" in ai_panel_css
    assert "user-select: none;" in ai_panel_css
    assert ".wa-model-mode-sub[hidden]" in ai_panel_css
    assert ".wa-model-mode-sub::before" in ai_panel_css
    assert ".wa-attach-file-btn" in ai_panel_css
    assert ".wa-wf-active-chip" in ai_panel_css
    assert "content: '·';" in ai_panel_css


def test_activity_latency_popover_uses_an_opaque_surface() -> None:
    style = _read("web/static/css/style.css")
    workspace_css = _read("web/static/css/workspace.css")

    assert "background-color: var(--bg-secondary) !important;" in style
    assert "background-color: var(--bg-secondary) !important;" in workspace_css
    assert "backdrop-filter: none;" in workspace_css
