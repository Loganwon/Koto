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
    # The production bundle is minified, so the local function identifier is
    # unstable; the public WA property is the observable contract.
    assert "window.WA.isTabActuallyUnsaved=" in workspace_bundle

    close_warn_css = workspace_css[
        workspace_css.index(".wa-close-warn-overlay"):
        workspace_css.index("/* ── File rows", workspace_css.index(".wa-close-warn-overlay"))
    ]
    assert "backdrop-filter" not in close_warn_css
    assert "background: rgba(17, 24, 39, 0.42);" in close_warn_css
    assert "border-radius: 8px;" in close_warn_css
    assert "max-height: calc(100vh - 28px);" in close_warn_css
    assert "overflow: auto;" in close_warn_css

    dialog_overlay_css = workspace_css[
        workspace_css.index(".wa-dlg-overlay"):
        workspace_css.index(".wa-close-warn-overlay")
    ]
    assert "backdrop-filter" not in dialog_overlay_css
    assert "background: rgba(17, 24, 39, 0.38);" in dialog_overlay_css
