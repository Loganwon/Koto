from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_workspace_loader_dedupes_inflight_library_loads():
    js = (_repo_root() / "web" / "static" / "js" / "workspace-assistant.js").read_text(
        encoding="utf-8"
    )

    assert "const _libLoadPromises = { tiptap: null, sheets: null, pdfjs: null };" in js
    assert "const _assetCacheBust = String(Date.now());" in js
    assert "if (_libLoadPromises.sheets) return _libLoadPromises.sheets;" in js
    assert "if (_libLoadPromises.tiptap) return _libLoadPromises.tiptap;" in js


def test_workspace_layout_waits_have_fast_ready_path():
    js = (_repo_root() / "web" / "static" / "js" / "workspace-assistant.js").read_text(
        encoding="utf-8"
    )

    assert "const isReady = () => {" in js
    assert "if (isReady()) return Promise.resolve();" in js


def test_xlsx_mount_no_longer_requires_unconditional_double_raf():
    js = (_repo_root() / "web" / "static" / "js" / "workspace-assistant.js").read_text(
        encoding="utf-8"
    )

    assert "const mountSheets = () => {" in js
    assert "if (wrapper.offsetWidth > 0 && wrapper.offsetHeight > 0) {" in js
    assert "requestAnimationFrame(() => {" in js
    assert (
        "requestAnimationFrame(() => {\n        requestAnimationFrame(() => {" not in js
    )


def test_pptx_initial_render_uses_short_retry_window_without_timeout_poll():
    js = (_repo_root() / "web" / "static" / "js" / "workspace-assistant.js").read_text(
        encoding="utf-8"
    )

    assert "const _pptxMountDeadline = Date.now() + 250;" in js
    assert "requestAnimationFrame(_tryPptxRender);" in js
    assert "setTimeout(_tryPptxRender, 50);" not in js


def test_xlsx_formula_warning_uses_fast_zip_scan_instead_of_second_workbook_load():
    py = (_repo_root() / "app" / "core" / "file" / "file_parser.py").read_text(
        encoding="utf-8"
    )

    assert "def _xlsx_contains_formula_fast(path: str) -> bool:" in py
    assert 'zipfile.ZipFile(path, "r") as zf' in py
    assert (
        "_wb_check = openpyxl.load_workbook(file_path, data_only=False, read_only=True)"
        not in py
    )


def test_docx_progressive_hydration_is_wired_in_workspace_assistant():
    js = (_repo_root() / "web" / "static" / "js" / "workspace-assistant.js").read_text(
        encoding="utf-8"
    )

    assert "function _startDocxProgressiveHydration(tab)" in js
    assert "/api/v1/workspace/docx_full" in js
    assert "state.activeEditor.editor.setEditable(!isLocked);" in js
    assert "DOCX 仍在后台加载剩余内容，请稍后再保存。" in js
