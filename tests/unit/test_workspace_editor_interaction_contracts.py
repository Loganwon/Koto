import re
from pathlib import Path

from tests.source_graph import read_frontend_partitions

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    if Path(relative_path).suffix in {".ts", ".js", ".css"}:
        return read_frontend_partitions(relative_path)
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_xlsx_cell_deletion_updates_context_and_schedules_persistence():
    univer = _read("web/univer-editor/sheets-main.js")
    editor = _read("web/src/editors/xlsx-editor.ts")

    assert "onCellDataChange(handler)" in univer
    assert "_bindActiveCellSubscription()" in univer
    assert "sheet.onCellDataChange((event)" in univer
    assert "this._cellChangeHandlers" in univer
    assert "KotoSheetsAPI.onCellDataChange" in editor
    assert "_syncXlsxSelectionContext(_xlsxSelectionPayload(), this._session)" in editor
    assert "api.scheduleAutoSave()" in editor


def test_xlsx_tabs_fit_scaled_workspace_and_number_formats_are_enabled():
    univer = _read("web/univer-editor/sheets-main.js")
    editor = _read("web/src/editors/xlsx-editor.ts")
    embedded = _read("web/src/ui/embedded-mode.ts")
    settings = _read("web/src/app/settings.ts")
    workspace_css = _read("web/static/css/workspace.css")

    assert "UniverSheetsNumfmtPlugin" in univer
    assert "runtime.registerPlugin(UniverSheetsNumfmtPlugin);" in univer
    assert "syncNativeRenderSurface" in editor
    assert "createRenderSurfaceController" in editor
    assert "would produce a zoom² overflow" in editor
    assert "setProperty('width', '100%', 'important')" in editor
    assert "ResizeObserver" in _read("web/src/shared/render-surface.ts")
    assert "state.activeEditor.refreshLayout()" in embedded
    assert "#wa-xlsx-viewport" in workspace_css
    assert "zoom: 1 !important;" not in workspace_css
    assert "model_load_failed: '模型损坏'" in settings
    assert "providerData.error === 'runtime_outdated'" in settings


def test_zoomed_fixed_surfaces_use_the_shared_coordinate_contract():
    scale = _read("web/src/shared/ui-scale.ts")
    context_menu = _read("web/src/workspace/fs-context-menu.ts")
    selection = _read("web/src/ui/selection-toolbar.ts")
    toolbar = _read("web/src/ui/docx-pptx-toolbar.ts")
    docx = _read("web/tiptap-editor/koto-docx-editor.js")

    assert "export function placeFixedInViewport" in scale
    assert "document.documentElement).zoom" not in context_menu
    assert "placeFixedInViewport(menu, x, y, 4);" in context_menu
    assert "placeFixedInViewport(tt, left, top);" in selection
    assert "setFixedVisualPosition(hb, fmtLeft, fmtTop);" in toolbar
    assert "window.KotoUiScale.placeFixedInViewport" in docx


def test_pptx_and_pdf_pointer_geometry_uses_logical_coordinates():
    pptx = _read("web/src/editors/pptx-editor.ts")
    pdf = _read("web/src/editors/pdf-viewer.ts")

    assert "viewportPointToElement(canvas, e.clientX, e.clientY)" in pptx
    assert "viewportDeltaToElement(canvas" in pptx
    assert "ev.clientX - rect.left" not in pptx
    assert "viewportPointToElement(wrap, e.clientX, e.clientY)" in pdf
    assert "viewportRectToElement(wrap, r)" in pdf
    assert "getElementLogicalSize(wrap)" in pdf
    assert "e.clientX - wrapRect.left" not in pdf


def test_all_office_editors_share_one_high_density_render_surface_contract():
    surface = _read("web/src/shared/render-surface.ts")
    xlsx = _read("web/src/editors/xlsx-editor.ts")
    pdf = _read("web/src/editors/pdf-viewer.ts")
    pptx = _read("web/src/editors/pptx-editor.ts")
    docx = _read("web/tiptap-editor/koto-docx-editor.js")
    pagination = _read("web/tiptap-editor/docx-pagination-scheduler.js")

    assert "export class RenderSurfaceController" in surface
    assert "paintScale.x * devicePixelRatio" in surface
    assert "syncCanvasBackingStore" in surface
    assert "prepareCanvas2d" in surface
    assert "syncNativeRenderSurface(sheetEl)" in xlsx
    assert "syncCanvasBackingStore(canvas, cssW, cssH, wrap)" in pdf
    assert "window.devicePixelRatio" not in pdf
    assert "prepareCanvas2d(cv, sw, sh" in pptx
    assert "window.KotoRenderSurface.createController" in pagination
    assert "KotoRenderSurface.createController(scrollEl" in docx


def test_remaining_zoom_sensitive_surfaces_share_one_coordinate_contract():
    framework = _read("web/src/app/framework.ts")
    chat = _read("web/src/app/chat-ui.ts")
    extensions = _read("web/tiptap-editor/docx-extensions.js")
    docx = _read("web/tiptap-editor/koto-docx-editor.js")
    workspace_css = _read("web/static/css/workspace.css")
    panel_css = _read("web/static/css/workspace-ai-panel.css")

    assert "placeFixedInViewport(this.element" in framework
    assert "viewportPointToElement(" in chat
    assert "paintScaleX: paintScale.x" in extensions
    assert "KotoUiScale.viewportDeltaToElement(img" in extensions
    assert "KotoUiScale.viewportPointToElement(layer" in docx
    assert "calc(100vw -" not in workspace_css
    assert "calc(100vh -" not in workspace_css
    assert "calc(100vw -" not in panel_css


def test_logical_viewport_is_the_only_main_app_responsive_owner():
    scale = _read("web/src/shared/ui-scale.ts")
    theme = _read("web/src/app/theme.ts")
    session = _read("web/src/app/session-bridge.ts")
    style = _read("web/static/css/style.css")
    workspace = _read("web/static/css/workspace.css")
    ai_panel = _read("web/static/css/workspace-ai-panel.css")

    assert "LOGICAL_VIEWPORT_BREAKPOINTS" in scale
    assert "syncLogicalViewportClasses(document.body, layoutWidth)" in theme
    assert "devicePixelRatio: window.devicePixelRatio || 1" in theme
    assert "_watchDevicePixelRatio();" in theme
    assert "getLogicalViewportSize().width <= 1200" in session
    assert "matchMedia('(max-width: 1200px)')" not in session
    for css in (style, workspace, ai_panel):
        assert "@media (max-width:" not in css
    assert "body.koto-layout-max-900 .artifacts-panel" in style
    assert "body.koto-layout-max-640 .wa-close-warn-overlay" in workspace
    assert "body.koto-layout-max-860 .wa-footer-actions" in ai_panel


def test_univer_runtime_loader_is_idempotent_across_cache_busts():
    loader = _read("web/src/editors/cdn-loaders.ts")

    assert "const srcBase = src.split('?')[0];" in loader
    assert "_scriptLoadPromises.get(srcBase)" in loader
    assert "script.dataset.kotoLoaderSrc === srcBase" in loader
    assert "if (window.KotoSheetsAPI)" in loader
    assert "_libsLoaded.sheets = true;" in loader


def test_univer_legacy_duplicate_warning_filter_is_exact_and_scoped():
    source = _read("web/univer-editor/sheets-main.js")

    assert "LEGACY_HEADER_FOOTER_DUPLICATE_WARNING" in source
    assert (
        "args.length === 1 && args[0] === LEGACY_HEADER_FOOTER_DUPLICATE_WARNING"
        in source
    )
    assert "setTimeout(restoreWarn, 1000);" in source
    assert "catch (error) {\n    restoreWarn();\n    throw error;" in source
    assert "initializeLegacyUniverRuntime(() =>" in source


def test_pptx_cross_run_deletion_rebuilds_the_shape_model_from_dom():
    editor = _read("web/src/editors/pptx-editor.ts")

    assert "_syncShapeTextFromDom(shape, inner)" in editor
    assert "inner.addEventListener('input'" in editor
    assert "shape.paragraphs = nextParagraphs" in editor
    assert "text: String(inner.textContent || '')" in editor
    assert "getSelectionPayload()" in editor


def test_pdf_and_pptx_selections_reach_the_shared_quick_action_toolbar():
    selection = _read("web/src/ui/selection-toolbar.ts")
    pdf = _read("web/src/editors/pdf-viewer.ts")

    assert "state.fileType === 'pptx' || state.fileType === 'pdf'" in selection
    assert "state.activeEditor.getSelectionPayload()" in selection
    assert "kind: 'pdf-text'" in pdf
    assert "el.classList.remove('wa-hidden')" in pdf
    assert "el.classList.add('wa-hidden')" in pdf


def test_docx_quick_action_uses_anchored_dedicated_replacement_chain():
    selection = _read("web/src/ui/selection-toolbar.ts")
    quick_actions = _read("web/src/workspace/quick-actions.ts")
    tiptap = _read("web/tiptap-editor/koto-docx-editor.js")

    assert "includeAnchorMeta: true" in selection
    assert "optimization_chain: 'docx_selection_v1'" in quick_actions
    assert "_resolveAnchoredTextRange(cmd)" in tiptap
    assert "anchor_occurrence" in tiptap
    assert "anchor_context_before" in tiptap


def test_empty_docx_review_shell_clears_stale_horizontal_scroll():
    layout = _read("web/src/review/layout-position.ts")

    assert "if (!cards.length)" in layout
    assert "if (viewport.scrollLeft) viewport.scrollLeft = 0;" in layout
    assert "revealScrollLeft" not in layout


def test_reopening_an_open_file_activates_its_cached_tab_without_reparsing():
    tree = _read("web/src/workspace/fs-tree.ts")
    file_open = _read("web/src/workspace/file-open.ts")

    assert "async function activateOpenTab(path: string): Promise<boolean>" in tree
    assert (
        "if (!forceReload && await activateOpenTab(requestPath)) return null;" in tree
    )
    assert "if (!forceReload && await activateOpenTab(absPath)) return null;" in tree
    assert "return openWorkspaceFile(filePath, supported, true);" in tree
    assert (
        "state.activeEditor!.render(tab.cache !== null && tab.cache !== undefined ? tab.cache : data);"
        in file_open
    )


def test_pdf_statusbar_and_image_zoom_remain_usable_in_narrow_editors():
    html = _read("web/templates/index.html")
    css = _read("web/static/css/workspace.css")

    assert html.count('class="wa-pdf-sb-label"') == 2
    assert "container-type: inline-size;" in css
    assert "@container (max-width: 520px)" in css
    assert ".wa-pdf-sb-label { display: none; }" in css
    assert "transform-origin: top left;" in css


def test_task_cards_keep_verbose_execution_details_collapsed_by_default():
    task_runner = _read("web/src/workspace/task-runner.ts")
    task_stage_presentation = _read("web/src/workspace/task-stage-presentation.ts")
    terminal_state = _read("web/src/workspace/task-terminal-state.ts")

    assert 'data-role="process"><summary>' in task_stage_presentation
    assert 'data-role="process" open' not in task_stage_presentation
    assert "查看执行详情" in terminal_state


def test_selection_runtime_replaces_ambient_cross_editor_text_state():
    runtime = _read("web/src/shared/selection-runtime.ts")
    selection = _read("web/src/ui/selection-toolbar.ts")
    pptx = _read("web/src/editors/pptx-editor.ts")
    pdf = _read("web/src/editors/pdf-viewer.ts")

    assert "getSelectionRuntime" in runtime
    assert "setLastSelectionText" in runtime
    assert "declare let lastSelectionText" not in selection
    assert "declare let lastSelectionText" not in pptx
    assert "declare let lastSelectionText" not in pdf


def test_file_frontend_conflict_state_has_single_module_owners():
    runtime = _read("web/src/shared/selection-runtime.ts")
    selection = _read("web/src/ui/selection-toolbar.ts")
    toolbar = _read("web/src/ui/docx-pptx-toolbar.ts")
    fs_tree = _read("web/src/workspace/fs-tree.ts")
    embedded = _read("web/src/ui/embedded-mode.ts")
    file_open = _read("web/src/workspace/file-open.ts")
    runtime_init = _read("web/src/workspace/runtime-init.ts")
    panel_layout = _read("web/src/ui/panel-layout.ts")
    workspace_layout = _read("web/src/ui/workspace-layout.ts")
    task_dispatcher = _read("web/src/workspace/task-dispatcher.ts")
    infrastructure = _read("web/src/workspace/infrastructure.ts")

    assert "docxHoverForceHiddenText" in runtime
    assert "docxNativeSelectionBottom" in runtime
    for source in (selection, toolbar):
        assert "_docxHoverForceHiddenText" not in source
        assert "_docxNativeSelBottom" not in source

    assert "export function ensureFileBrowserLoaded" in fs_tree
    assert "_WA_fileBrowserLoaded" not in fs_tree
    assert "_WA_fileBrowserLoaded" not in embedded
    assert "ensureFileBrowserLoaded" in embedded

    for legacy_export in (
        "(window as any)._serializeEditorForTab",
        "(window as any)._stableWorkspaceSnapshot",
        "(window as any)._rememberSavedSnapshotForTab",
        "(window as any)._escHtml",
    ):
        assert legacy_export not in file_open
    assert "(window as any)._WA_RUNTIME_SESSION_ID" not in runtime_init
    for source in (
        embedded,
        panel_layout,
        workspace_layout,
        task_dispatcher,
        infrastructure,
    ):
        assert "(window as any).WA =" not in source
    assert "registerFeatures({" in embedded
    assert "registerFeatures({" not in panel_layout
    assert (
        "registerFeatures({ refreshWorkspaceLayout, toggleAiPanel, _expandWAPanel,"
        in workspace_layout
    )
    assert (
        "showConversationLayout, showDocumentLayout, initWorkspaceLayout"
        in workspace_layout
    )
    assert "taskCardPersistenceStructure," in task_dispatcher
    assert "registerFeatures({ taskCardTestStructure });" not in task_dispatcher


def test_workspace_asset_bootstrap_does_not_predeclare_bundle_internals():
    template = _read("web/templates/_workspace_asset_scripts.html")

    assert "window.WA" not in template
    assert 'id="koto-workspace-bundle"' in template
    assert "data-pdf-viewer-bundle-url" in template
    assert "var $, WA" not in template
    assert "var _csrfFetch" not in template
    assert "var _waAiResultsRuntime" not in template
    assert "var _hostSessionId" not in template


def test_active_workspace_inline_event_debt_cannot_grow():
    inline_event = re.compile(
        r"\s(?:onclick|oninput|onchange|onkeydown|onkeyup|onmousedown|onmouseup|"
        r"onpointerdown|ondragstart|ondrop|ondragover|oncontextmenu)=",
        re.IGNORECASE,
    )
    active_templates = (
        "web/templates/index.html",
        "web/templates/_workspace_selection_toolbar.html",
        "web/templates/_workspace_close_warn_dialog.html",
        "web/templates/_workspace_docx_color_picker.html",
    )

    count = sum(len(inline_event.findall(_read(path))) for path in active_templates)
    assert count == 0


def test_file_task_recovery_has_no_unresolved_ambient_helpers():
    source = _read("web/src/workspace/file-utils.ts")

    for helper in (
        "_parseTaskMetadata",
        "_conversationTaskTurn",
        "_findRenderedTaskCard",
        "_replaceActiveTaskReconnector",
    ):
        assert f"function {helper}" in source
        assert f"declare function {helper}" not in source


def test_heavy_workspace_editors_are_real_runtime_bundles():
    loader = _read("web/src/editors/lazy-loaders.ts")
    build = _read("web/scripts/build-bundles.mjs")
    template = _read("web/templates/_workspace_asset_scripts.html")

    assert "import('../editors/pptx-editor')" not in loader
    assert "import('../editors/pdf-viewer')" not in loader
    for name in (
        "pptx-editor-bundle",
        "pdf-viewer-bundle",
        "xlsx-editor-bundle",
        "image-viewer-bundle",
    ):
        assert name in loader
        assert name in build
        assert name in template


def test_frontend_observer_is_idle_loaded_without_losing_startup_errors():
    workspace = _read("web/src/bundles/workspace.ts")
    loader = _read("web/src/shared/frontend-observer-loader.ts")
    observer_bundle = _read("web/src/bundles/frontend-observer.ts")
    build = _read("web/scripts/build-bundles.mjs")
    template = _read("web/templates/_workspace_asset_scripts.html")

    assert "scheduleFrontendObserverLoad()" in workspace
    assert "installFrontendObserver" not in workspace
    assert "requestIdleCallback" in loader
    assert "frontend-observer-bundle" in loader
    assert "data-koto-frontend-observer" in loader
    assert "installFrontendObserver();" in observer_bundle
    assert "drainStartupErrors()" in observer_bundle
    assert "type: 'startup_error'" in observer_bundle
    assert "'frontend-observer-bundle': 'src/bundles/frontend-observer.ts'" in build
    assert "'workspace-bundle': 520 * 1024" in build
    assert "'frontend-observer-bundle': 80 * 1024" in build
    assert "'docx-review-engine-bundle': 60 * 1024" in build
    assert "frontend-observer-bundle.js" in template


def test_find_replace_runtime_is_focus_warmed_and_idle_loaded() -> None:
    workspace = _read("web/src/bundles/workspace.ts")
    loader = _read("web/src/workspace/find-replace-loader.ts")
    runtime_bundle = _read("web/src/bundles/find-replace.ts")
    build = _read("web/scripts/build-bundles.mjs")
    template = _read("web/templates/_workspace_asset_scripts.html")

    assert "scheduleWorkspaceFindReplaceLoad({" in workspace
    assert "import '../workspace/find-replace';" not in workspace
    assert "requestIdleCallback" in loader
    assert "focusin" in loader
    assert "[data-wa-find-input], [data-wa-find-replace-input]" in loader
    assert "syncFocusedFindInput();" in loader
    assert "import '../workspace/find-replace';" in runtime_bundle
    assert "'find-replace-bundle': 'src/bundles/find-replace.ts'" in build
    assert "'find-replace-bundle': 30 * 1024" in build
    assert "find-replace-bundle.js" in template


def test_task_workbench_runtime_replays_first_open_after_lazy_load() -> None:
    workspace = _read("web/src/bundles/workspace.ts")
    loader = _read("web/src/workspace/task-workbench-loader.ts")
    runtime_bundle = _read("web/src/bundles/task-workbench.ts")
    build = _read("web/scripts/build-bundles.mjs")
    template = _read("web/templates/_workspace_asset_scripts.html")

    assert "installTaskWorkbenchLoader();" in workspace
    assert "import '../workspace/task-workbench';" not in workspace
    assert "function openTaskWorkbenchBridge(" in loader
    assert "open(request);" in loader
    assert "refreshCurrentTaskFlowBridge(): Promise<any>" in loader
    assert "data-koto-task-workbench" in loader
    assert "import '../workspace/task-workbench';" in runtime_bundle
    assert "'task-workbench-bundle': 'src/bundles/task-workbench.ts'" in build
    assert "'task-workbench-bundle': 60 * 1024" in build
    assert "task-workbench-bundle.js" in template


def test_conversation_history_runtime_keeps_normal_chat_on_lightweight_bridge() -> None:
    workspace = _read("web/src/bundles/workspace.ts")
    loader = _read("web/src/workspace/conversation-list-loader.ts")
    runtime_bundle = _read("web/src/bundles/conversation-list.ts")
    build = _read("web/scripts/build-bundles.mjs")
    template = _read("web/templates/_workspace_asset_scripts.html")

    assert "installConversationListLoader();" in workspace
    assert "import '../workspace/conversation-list';" not in workspace
    assert "function showAiSessionListBridge(): null" in loader
    assert "if (options.silent) return Promise.resolve([]);" in loader
    assert "return typeof send === 'function' ? send() : null;" in loader
    assert "import '../workspace/conversation-list';" in runtime_bundle
    assert "'conversation-list-bundle': 'src/bundles/conversation-list.ts'" in build
    assert "'conversation-list-bundle': 50 * 1024" in build
    assert "conversation-list-bundle.js" in template


def test_file_context_menu_runtime_loads_only_on_first_menu_action() -> None:
    workspace = _read("web/src/bundles/workspace.ts")
    loader = _read("web/src/workspace/fs-context-menu-loader.ts")
    runtime = _read("web/src/workspace/fs-context-menu.ts")
    runtime_bundle = _read("web/src/bundles/fs-context-menu.ts")
    embedded = _read("web/src/ui/embedded-mode.ts")
    build = _read("web/scripts/build-bundles.mjs")
    template = _read("web/templates/_workspace_asset_scripts.html")

    assert "installFsContextMenuLoader();" in workspace
    assert "import '../workspace/fs-context-menu';" not in workspace
    assert "function showBrowserContextMenuBridge(" in loader
    assert "event.preventDefault();" in loader
    assert "show(event, element);" in loader
    assert "Closing a menu that has never opened must remain a no-op" in loader
    assert "data-koto-fs-context-menu" in loader
    assert "import '../workspace/fs-context-menu';" in runtime_bundle
    assert "'fs-context-menu-bundle': 'src/bundles/fs-context-menu.ts'" in build
    assert "'fs-context-menu-bundle': 60 * 1024" in build
    assert "fs-context-menu-bundle.js" in template

    assert "Workspace File Operations (legacy)" not in runtime
    assert "Legacy Context Menu (workspace tree)" not in runtime
    assert "'workspace-open':" not in runtime
    assert "WA.openBrowserFile(path, supported)" in embedded
    assert "navigator.clipboard.writeText(path)" in embedded
    assert "WA._fsBrowserOpen()" not in embedded
    assert "WA._fsBrowserCopyPath()" not in embedded


def test_file_tree_keyboard_open_target_has_a_visible_focus_state():
    tree = _read("web/src/workspace/fs-tree.ts")
    recent = _read("web/src/workspace/state.ts")
    css = _read("web/static/css/workspace.css")

    assert 'class="wa-file-open-hit"' in tree
    assert 'aria-label="打开 ${_escHtml(entry.name)}"' in tree
    assert 'class="wa-file-open-hit"' in recent
    assert ".wa-file-open-hit:focus-visible" in css
    assert "outline: 2px solid var(--accent);" in css


def test_keyboard_docx_selection_opens_the_shared_quick_action_toolbar():
    source = _read("web/src/ui/panel-layout.ts")

    assert "_showSelectionToolbarForCurrentSelection" in source
    assert "if (_ws && !_ws.isCollapsed && _ws.rangeCount)" in source


def test_p2_workspace_editors_use_one_explicit_session_without_window_state():
    session = _read("web/src/editors/editor-session.ts")
    file_open = _read("web/src/workspace/file-open.ts")
    infrastructure = _read("web/src/workspace/infrastructure.ts")
    observer = _read("web/src/mcp/frontend-observer.ts")
    editor_sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in (ROOT / "web/src/editors").glob("*.ts")
        if not path.name.endswith(".test.ts")
    }
    production_sources = [
        path.read_text(encoding="utf-8")
        for path in (ROOT / "web/src").rglob("*.ts")
        if not path.name.endswith(".test.ts")
    ]

    assert "export function createEditorSession" in session
    assert "mount<T extends WorkspaceEditor>(editor: T): T" in session
    assert "const editorSession = createEditorSession(state);" in file_open
    for constructor in (
        "new XlsxEditor(editorSession)",
        "KotoPptxEditor(editorSession)",
        "KotoPdfViewer(editorSession)",
        "KotoImageViewer(editorSession)",
        "new KotoTextEditor(editorSession, tab.fileType)",
        "KotoTipTapEditor(editorSession)",
    ):
        assert constructor in file_open

    assert "_inspectWorkspaceRuntime" in file_open
    assert "_workspaceRuntime()" in observer
    assert "_saveEditorRange" not in infrastructure
    assert all("(window as any).state" not in source for source in production_sources)
    assert all("window.state" not in source for source in production_sources)
    assert "getPinnedSelection()" in editor_sources["xlsx-editor.ts"]
    assert "this._session.snapshot()" in editor_sources["pdf-viewer.ts"]
