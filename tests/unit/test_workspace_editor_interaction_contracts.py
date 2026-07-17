import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_xlsx_cell_deletion_updates_context_and_schedules_persistence():
    univer = _read("web/univer-editor/sheets-main.js")
    editor = _read("web/src/editors/xlsx-editor.ts")

    assert "onCellDataChange(handler)" in univer
    assert "_bindActiveCellSubscription()" in univer
    assert "sheet.onCellDataChange((event)" in univer
    assert "this._cellChangeHandlers" in univer
    assert "KotoSheetsAPI.onCellDataChange" in editor
    assert "_syncXlsxSelectionContext(_xlsxSelectionPayload())" in editor
    assert "api.scheduleAutoSave()" in editor


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
    assert "args.length === 1 && args[0] === LEGACY_HEADER_FOOTER_DUPLICATE_WARNING" in source
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
    for source in (embedded, panel_layout, task_dispatcher, infrastructure):
        assert "(window as any).WA =" not in source
    assert "publishWorkspaceApi({" in embedded
    assert "publishWorkspaceApi({" in panel_layout
    assert "taskCardPersistenceStructure," in task_dispatcher
    assert "publishWorkspaceApi({ taskCardTestStructure });" not in task_dispatcher


def test_workspace_asset_bootstrap_does_not_predeclare_bundle_internals():
    template = _read("web/templates/_workspace_asset_scripts.html")

    assert "var WA = window.WA = window.WA || {};" in template
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
    assert count <= 432


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
    assert "__kotoStartupErrors.splice(0)" in observer_bundle
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
