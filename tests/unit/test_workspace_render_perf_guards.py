from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_workspace_loader_dedupes_inflight_library_loads():
    js = (_repo_root() / "web" / "src" / "editors" / "cdn-loaders.ts").read_text(
        encoding="utf-8"
    )

    assert (
        "const _libLoadPromises: Record<string, Promise<void> | null> = { tiptap: null, sheets: null, pdfjs: null };"
        in js
    )
    assert "const _assetCacheBust = String(Date.now());" in js
    assert "const _scriptLoadPromises = new Map<string, Promise<void>>();" in js
    assert "if (_libLoadPromises.sheets) return _libLoadPromises.sheets;" in js
    assert "if (_libLoadPromises.tiptap) return _libLoadPromises.tiptap;" in js
    assert "s.dataset.kotoLoaderState = 'failed';" in js
    assert "s.remove();" in js


def test_workspace_layout_waits_have_fast_ready_path():
    js = (_repo_root() / "web" / "src" / "workspace" / "state.ts").read_text(
        encoding="utf-8"
    )

    assert "const isReady = () => {" in js
    assert "if (isReady()) return Promise.resolve();" in js


def test_xlsx_mount_no_longer_requires_unconditional_double_raf():
    js = (_repo_root() / "web" / "src" / "editors" / "xlsx-editor.ts").read_text(
        encoding="utf-8"
    )

    assert "const mountSheets = () => {" in js
    assert "if (wrapper.offsetWidth > 0 && wrapper.offsetHeight > 0) {" in js
    assert "requestAnimationFrame(() => {" in js
    assert (
        "requestAnimationFrame(() => {\n        requestAnimationFrame(() => {" not in js
    )


def test_pptx_initial_render_uses_short_retry_window_without_timeout_poll():
    js = (_repo_root() / "web" / "src" / "editors" / "pptx-editor.ts").read_text(
        encoding="utf-8"
    )

    assert "const _pptxMountDeadline = Date.now() + 250;" in js
    assert "requestAnimationFrame(_tryPptxRender);" in js
    assert "setTimeout(_tryPptxRender, 50);" not in js


def test_pptx_editor_requires_structured_slide_data_without_legacy_array_adapter():
    js = (_repo_root() / "web" / "src" / "editors" / "pptx-editor.ts").read_text(
        encoding="utf-8"
    )

    assert "Array.isArray(richData)" in js
    assert "PPTX 编辑器需要结构化幻灯片数据" in js
    assert "_legacyToRich" not in js
    assert "richData.slide_width_emu" in js
    assert "richData.default_title_font_size_pt" in js


def test_xlsx_formula_warning_uses_fast_zip_scan_instead_of_second_workbook_load():
    py = (
        _repo_root() / "app" / "core" / "file" / "parsers" / "xlsx_parser.py"
    ).read_text(encoding="utf-8")

    assert "def xlsx_contains_formula_fast(path: str) -> bool:" in py
    assert 'zipfile.ZipFile(path, "r") as zf' in py
    assert (
        "_wb_check = openpyxl.load_workbook(file_path, data_only=False, read_only=True)"
        not in py
    )


def test_docx_progressive_save_guard_is_wired_to_current_workspace_modules():
    state_ts = (_repo_root() / "web" / "src" / "workspace" / "state.ts").read_text(
        encoding="utf-8"
    )
    save_ts = (_repo_root() / "web" / "src" / "workspace" / "save.ts").read_text(
        encoding="utf-8"
    )

    assert "progressive_loading: type === 'docx'" in state_ts
    assert "const progressive = tab && (tab as any).progressive;" in save_ts
    assert (
        "tab?.fileType === 'docx' && progressive && progressive.loading && !progressive.complete"
        in save_ts
    )
    assert "DOCX 仍在后台加载，请稍后再保存。" in save_ts


def test_workspace_close_warning_requires_real_unsaved_snapshot_and_clear_ui():
    root = _repo_root()
    state_ts = (root / "web" / "src" / "workspace" / "state.ts").read_text(
        encoding="utf-8"
    )
    file_open_ts = (root / "web" / "src" / "workspace" / "file-open.ts").read_text(
        encoding="utf-8"
    )
    save_ts = (root / "web" / "src" / "workspace" / "save.ts").read_text(
        encoding="utf-8"
    )
    file_utils_ts = (root / "web" / "src" / "workspace" / "file-utils.ts").read_text(
        encoding="utf-8"
    )
    workspace_css = (root / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )
    workspace_bundle = (
        root / "web" / "static" / "js" / "build" / "workspace-bundle.js"
    ).read_text(encoding="utf-8")

    assert "savedSnapshot?: string | null;" in state_ts
    assert "export function _rememberSavedSnapshotForTab" in file_open_ts
    assert "_rememberSavedSnapshotForTab(tabEntry, state.activeEditor)" in file_open_ts
    assert "tab.savedSnapshot = _stableWorkspaceSnapshot(data)" in save_ts
    assert "export function isTabActuallyUnsaved" in file_utils_ts
    assert "return state.openTabs.filter(isTabActuallyUnsaved)" in file_utils_ts
    assert "const actualUnsavedTabs = getUnsavedTabs();" in file_utils_ts
    assert "resolve('cancel');" in file_utils_ts
    assert "function _trapCloseWarnFocus" in file_utils_ts
    # The production bundle is minified.  This method now publishes through
    # the controlled workspace API boundary instead of a direct global write.
    assert "isTabActuallyUnsaved" in workspace_bundle

    close_warn_start = workspace_css.index("\n    .wa-close-warn-overlay {")
    close_warn_css = workspace_css[
        close_warn_start : workspace_css.index("/* ── File rows", close_warn_start)
    ]
    assert "backdrop-filter" not in close_warn_css
    assert "background: var(--ui-overlay);" in close_warn_css
    assert "border-radius: 14px;" in close_warn_css
    assert "max-height: calc(100vh - 28px);" in close_warn_css
    assert "overflow: auto;" in close_warn_css
    # The overlay is reparented to document.body while open, so it consumes
    # the shared body-level UI primitives rather than workspace-local aliases.
    assert "--wa-close-bg" not in close_warn_css
    assert "background: var(--ui-surface);" in close_warn_css
    assert "background: var(--ui-accent);" in close_warn_css
    assert "outline: none;" in close_warn_css
    # The footer's explanatory copy must not steal horizontal space from the
    # three exit actions: the primary save-and-exit button must remain visible.
    assert (
        ".wa-close-warn-footer {\n      display: flex;\n      flex-direction: column;"
        in close_warn_css
    )
    assert ".wa-close-warn-actions" in close_warn_css
    assert "flex-wrap: nowrap;" in close_warn_css
    assert ".wa-close-warn-save.wa-btn" in close_warn_css
    assert 'showPath ? `<div class="wa-close-warn-item-path">' in file_utils_ts

    dialog_overlay_start = workspace_css.index("\n    .wa-dlg-overlay {")
    dialog_overlay_css = workspace_css[dialog_overlay_start:close_warn_start]
    assert "backdrop-filter" not in dialog_overlay_css
    assert "background: var(--ui-overlay);" in dialog_overlay_css
    assert "background: var(--ui-surface);" in dialog_overlay_css
    assert "color: var(--ui-text);" in dialog_overlay_css


def test_body_level_dialogs_share_one_token_and_workspace_button_owner():
    root = _repo_root()
    style_css = (root / "web" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    main_ts = (root / "web" / "src" / "app" / "main.ts").read_text(encoding="utf-8")
    workspace_css = (root / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )

    for token in (
        "--ui-surface:",
        "--ui-surface-subtle:",
        "--ui-hover:",
        "--ui-border:",
        "--ui-text:",
        "--ui-text-muted:",
        "--ui-accent:",
        "--ui-accent-hover:",
        "--ui-accent-subtle:",
        "--ui-overlay:",
    ):
        assert token in style_css

    koto_dialog_css = style_css[
        style_css.index(".koto-dialog-overlay") : style_css.index(
            "/* 返回底部浮动按钮", style_css.index(".koto-dialog-overlay")
        )
    ]
    assert "var(--accent-color)" not in koto_dialog_css
    assert "background: var(--ui-surface);" in koto_dialog_css
    assert "background: var(--ui-overlay);" in koto_dialog_css
    assert "var(--accent-color" not in style_css
    assert "var(--accent-rgb" not in style_css
    assert "koto-dialog-confirm ui-dialog-button primary" in main_ts
    assert "koto-dialog-cancel ui-dialog-button secondary" in main_ts

    assert (
        workspace_css.count(
            ":is(#workspaceView, .wa-embedded, .wa-dlg-overlay, .wa-close-warn-overlay) .wa-btn {"
        )
        == 1
    )
    assert "\n    .wa-btn {\n" not in workspace_css
    assert "--accent-subtle: var(--ui-accent-subtle);" in workspace_css


def test_agent_and_template_modals_use_shared_dialog_primitives():
    root = _repo_root()
    style_css = (root / "web" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    main_ts = (root / "web" / "src" / "app" / "main.ts").read_text(encoding="utf-8")
    modal_css = style_css[
        style_css.index("/* ===== Shared dialog primitives ===== */") : style_css.index(
            "/* ===== Setup Wizard ===== */"
        )
    ]
    assert ":is(.ui-dialog-button, .btn-primary, .btn-secondary) {" in modal_css
    assert ":is(.ui-dialog-button.primary, .btn-primary) {" in modal_css
    assert "background: var(--ui-overlay);" in modal_css
    assert "z-index: var(--z-modal);" in modal_css
    assert "backdrop-filter" not in modal_css
    assert "z-index: 50" not in modal_css

    agent_css = style_css[
        style_css.index(".agent-dialog-overlay") : style_css.index(
            "/* ===== 文件生成进度显示 ===== */"
        )
    ]
    assert "background: var(--ui-surface);" in agent_css
    assert "background: var(--ui-overlay);" in agent_css
    assert ".agent-choice-option {" in agent_css

    agent_ts = main_ts[
        main_ts.index("// ── Agent Confirmation Dialogs ──") : main_ts.index(
            "// ── Meeting Actions ──"
        )
    ]
    assert 'class="ui-dialog-button secondary"' in agent_ts
    assert 'class="ui-dialog-button primary"' in agent_ts
    assert 'class="agent-choice-options"' in agent_ts
    assert "style=" not in agent_ts
    assert "agent-confirm-yes" not in agent_ts
    assert "agent-confirm-no" not in agent_ts
    assert "agent-choice-cancel" not in agent_ts


def test_template_modal_buttons_and_manager_routes_have_one_current_owner():
    root = _repo_root()
    style_css = (root / "web" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    index_html = (root / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    chat_ui_ts = (root / "web" / "src" / "app" / "chat-ui.ts").read_text(
        encoding="utf-8"
    )
    router_ts = (root / "web" / "src" / "app" / "router.ts").read_text(encoding="utf-8")

    primitive_css = style_css[
        style_css.index("/* ===== Shared dialog primitives ===== */") : style_css.index(
            "/* ===== Setup Wizard ===== */"
        )
    ]
    assert ":is(.ui-dialog-button, .btn-primary, .btn-secondary) {" in primitive_css
    assert ":is(.ui-dialog-button.primary, .btn-primary) {" in primitive_css
    assert ".btn-primary { background: var(--accent-gradient)" not in style_css
    assert ".btn-secondary { background: transparent" not in style_css
    assert ".btn-sm {\n    min-height: 32px;" in style_css
    assert ".suggestion-quick-actions > .btn-sm {" in style_css

    assert 'class="modal modal-wide"' in index_html
    assert 'class="modal modal-compact"' in index_html
    assert 'class="modal" style="width:460px' not in index_html
    assert 'class="modal" style="width:340px' not in index_html
    assert 'class="modal-actions" style="margin-top:16px' not in index_html
    assert index_html.count('class="ui-dialog-button primary"') >= 3
    assert index_html.count('class="ui-dialog-button secondary"') >= 4

    assert "getElementById('hotkeySheetModal')" in chat_ui_ts
    assert "getElementById('hotkeySheet')" not in chat_ui_ts
    assert "overlay.classList.toggle('active')" in chat_ui_ts

    assert "getElementById('projectsManagerList')" in router_ts
    assert "getElementById('projectsList')" not in router_ts
    assert "panel.classList.add('active')" in router_ts
    assert "panel.style.display = 'flex'" not in router_ts
    assert "row.className = 'proj-mgr-item'" in router_ts
    assert "input?.value.trim() || '新项目'" in router_ts


def test_ghost_buttons_have_one_base_owner_and_explicit_surface_modifiers():
    root = _repo_root()
    style_css = (root / "web" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    index_html = (root / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    settings_ts = (root / "web" / "src" / "app" / "settings.ts").read_text(
        encoding="utf-8"
    )

    assert style_css.count(":is(.ui-ghost-button, .ghost-btn) {") == 1
    assert "\n.ghost-btn {\n" not in style_css
    assert ".top-actions > .ghost-btn" not in style_css
    assert ".ui-ghost-button--glass {" in style_css
    assert ".ui-ghost-button--icon {" in style_css
    assert ".ui-ghost-button--compact {" in style_css
    assert ".batch-job-output {" in style_css

    assert 'class="ghost-btn' not in index_html
    assert 'class="ui-ghost-button ui-ghost-button--glass"' in index_html
    assert index_html.count('class="ui-ghost-button ui-ghost-button--icon') == 2
    assert 'class="ui-ghost-button" onclick="refreshBatchJobs()"' in index_html

    assert 'class="ghost-btn"' not in settings_ts
    assert 'class="ui-ghost-button ui-ghost-button--compact"' in settings_ts
    assert 'style="padding:2px 8px;font-size:12px;"' not in settings_ts
    assert 'class="batch-job-meta batch-job-output"' in settings_ts


def test_close_buttons_and_batch_modal_have_one_current_state_owner():
    root = _repo_root()
    style_css = (root / "web" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    index_html = (root / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    settings_html = (root / "web" / "templates" / "_settings_panel.html").read_text(
        encoding="utf-8"
    )
    settings_ts = (root / "web" / "src" / "app" / "settings.ts").read_text(
        encoding="utf-8"
    )

    assert style_css.count(":is(.ui-close-button, .close-panel) {") == 1
    assert "\n.close-panel {" not in style_css
    assert ".suggestion-panel .close-panel" not in style_css
    assert ".batch-panel .close-panel" not in style_css
    assert ".ui-close-button--quiet {" in style_css
    assert ".ui-close-button--compact {" in style_css

    assert 'class="close-panel"' not in index_html
    assert 'class="close-panel"' not in settings_html
    assert index_html.count('class="ui-close-button"') >= 6
    assert index_html.count('class="ui-close-button ui-close-button--quiet"') >= 2
    assert 'id="batchPanelModal" aria-hidden="true"' in index_html
    assert 'role="dialog" aria-modal="true"' in index_html
    assert "#skillsPanel .ui-close-button" in index_html

    batch_ts = settings_ts[
        settings_ts.index("// ── Batch Jobs Panel ──") : settings_ts.index(
            "export async function resetSettings"
        )
    ]
    assert "modal.classList.add('active')" in batch_ts
    assert "modal.classList.remove('active')" in batch_ts
    assert "modal.setAttribute('aria-hidden', 'false')" in batch_ts
    assert "modal.setAttribute('aria-hidden', 'true')" in batch_ts
    assert "modal.style.display" not in batch_ts


def test_suggestion_panel_and_compact_closers_use_current_ui_state():
    root = _repo_root()
    style_css = (root / "web" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    workspace_css = (root / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )
    index_html = (root / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    main_ts = (root / "web" / "src" / "app" / "main.ts").read_text(encoding="utf-8")
    settings_ts = (root / "web" / "src" / "app" / "settings.ts").read_text(
        encoding="utf-8"
    )

    assert ".suggestion-panel-modal.active {" in style_css
    assert ".suggestion-stats[hidden]," in style_css
    assert ".suggestion-footer[hidden] {" in style_css
    assert ".ui-close-button--inverse {" in style_css
    assert ".tp-close {" not in workspace_css
    assert ".tp-close:hover" not in workspace_css

    assert 'id="suggestionPanelModal" aria-hidden="true"' in index_html
    assert 'id="suggestionStats" hidden' in index_html
    assert 'id="suggestionFooter" hidden' in index_html
    assert 'id="suggestionPanelModal" style=' not in index_html
    assert 'id="apiKeyBanner" class="api-key-banner" hidden' in index_html
    assert 'class="dismiss-btn"' not in index_html
    assert 'class="tp-close"' not in index_html
    assert "ui-close-button--inverse" in index_html
    assert index_html.count("ui-close-button--compact") >= 1

    suggestion_ts = main_ts[
        main_ts.index("// ── Document Suggestions ──") : main_ts.index(
            "// ── Catalog Schedule Wizard ──"
        )
    ]
    assert "panel.classList.add('active')" in suggestion_ts
    assert "panel.classList.remove('active')" in suggestion_ts
    assert "updateSuggestionSummary" in suggestion_ts
    assert "suggestionState.loading" in suggestion_ts
    assert "setSuggestionSummaryVisible(false)" in suggestion_ts
    assert "panel.style.display" not in suggestion_ts

    assert "function setApiKeyBannerVisible" in settings_ts
    assert "banner.toggleAttribute('hidden', !visible)" in settings_ts
    assert (
        "banner.style.display"
        not in settings_ts[
            settings_ts.index("export function skipSetup") : settings_ts.index(
                "export function finishSetup"
            )
        ]
    )


def test_dead_token_monitor_is_removed_and_skill_creation_modals_have_one_owner():
    root = _repo_root()
    style_css = (root / "web" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    workspace_css = (root / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )
    index_html = (root / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    main_ts = (root / "web" / "src" / "app" / "main.ts").read_text(encoding="utf-8")
    marketplace_ts = (root / "web" / "src" / "app" / "marketplace.ts").read_text(
        encoding="utf-8"
    )
    modal_state_ts = (root / "web" / "src" / "shared" / "modal-state.ts").read_text(
        encoding="utf-8"
    )

    assert "Token Monitor" not in workspace_css
    assert "\n#tokenPanel {" not in workspace_css
    assert "\n#tokenChip {" not in workspace_css
    assert "\n.skill-editor-modal {" not in workspace_css
    assert "\n.skill-editor-inner {" not in workspace_css

    assert "#tokenMonitor" not in style_css
    assert "#tokenPanel" not in style_css
    assert "#tokenChip" not in style_css
    assert "token-monitor-spin" not in style_css
    assert style_css.count("\n.skill-editor-modal {") == 1
    assert ".skill-editor-modal.active {" in style_css
    assert ".skill-editor-inner--wide {" in style_css
    assert ".skill-editor-inner--compact {" in style_css

    assert 'id="tokenMonitor"' not in index_html
    assert 'id="tokenPanel"' not in index_html
    assert 'id="tokenChip"' not in index_html
    assert "const tokenWidget" not in index_html
    assert "fetch('/api/token-stats')" not in index_html

    for modal_id in (
        "createBindingModal",
        "createSkillModal",
        "catalogWizardModal",
        "skillEditorModal",
        "templateUploadModal",
    ):
        assert (
            f'id="{modal_id}" class="skill-editor-modal" aria-hidden="true"'
            in index_html
        )
        assert f'id="{modal_id}" class="skill-editor-modal" style=' not in index_html
    assert 'class="skill-editor-inner skill-editor-inner--wide"' in index_html
    assert 'class="skill-editor-inner skill-editor-inner--compact"' in index_html
    assert 'class="skill-editor-inner template-upload-dialog"' in index_html
    assert 'class="ske-panel" role="dialog" aria-modal="true"' in index_html
    assert 'id="templateDropZone"' in index_html
    assert 'role="button" tabindex="0" data-modal-initial-focus' in index_html
    assert 'role="dialog" aria-modal="true"' in index_html
    assert (
        "window.KotoModalState.open('templateUploadModal', '#templateDropZone')"
        in index_html
    )
    assert "window.KotoModalState.close('templateUploadModal')" in index_html
    assert "getElementById('templateUploadModal').style.display" not in index_html

    creation_ts = main_ts[
        main_ts.index("// ── Catalog Schedule Wizard ──") : main_ts.index(
            "// ── Console init message ──"
        )
    ]
    assert "const skillCreationModalIds" in creation_ts
    assert "if (open) openModal(modalId)" in creation_ts
    assert "else closeSharedModal(modalId)" in creation_ts
    assert "function closeActiveSkillModal()" in creation_ts
    assert "isModalOpen('skillEditorModal')" in creation_ts
    assert "isModalOpen('templateUploadModal')" in creation_ts
    assert "catalogScheduleModal" not in creation_ts
    assert "modal.style.display" not in creation_ts
    assert "e.key === 'Escape' && closeActiveSkillModal()" in main_ts

    assert "export function openModal(" in modal_state_ts
    assert "export function closeModal(" in modal_state_ts
    assert "export function isModalOpen(" in modal_state_ts
    assert "modal.classList.add('active')" in modal_state_ts
    assert "modal.classList.remove('active')" in modal_state_ts
    assert "modalOpeners.set(modal, activeElement)" in modal_state_ts
    assert "(window as any).KotoModalState" in modal_state_ts

    skill_editor_ts = marketplace_ts[
        marketplace_ts.index("export function openSkillEditor") : marketplace_ts.index(
            "export function skeUpdateCount"
        )
    ]
    assert "openModal('skillEditorModal'" in skill_editor_ts
    assert "closeModal('skillEditorModal')" in skill_editor_ts
    assert "modal.style.display" not in skill_editor_ts
