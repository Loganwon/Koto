"""Regression guard for `_applyFileJson` tabEntry TDZ bug.

If `_syncPrimarySaveButtons(tabEntry)` is called before `tabEntry` is declared,
opening a file in 文件助手 throws:
    Cannot access 'tabEntry' before initialization
and the file fails to mount.  This test pins the safe ordering.
"""

from pathlib import Path


def _workspace_assistant_js() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "web" / "static" / "js" / "workspace-assistant.js").read_text(
        encoding="utf-8"
    )


def test_apply_file_json_initializes_tabentry_before_sync_primary_save_buttons():
    js = _workspace_assistant_js()

    apply_marker = "async function _applyFileJson("
    apply_idx = js.find(apply_marker)
    assert apply_idx != -1, "_applyFileJson must exist in workspace-assistant.js"

    # Locate the function body up to the next top-level `async function ` /
    # `function ` declaration.  A generous slice is fine for our ordering check.
    body = js[apply_idx : apply_idx + 8000]

    decl_idx = body.find("const tabEntry = {")
    assert decl_idx != -1, "_applyFileJson must declare `const tabEntry = {`"

    # All references to tabEntry inside _applyFileJson must come AFTER the
    # `const tabEntry = {` declaration — anything earlier is a TDZ crash.
    sync_call = "_syncPrimarySaveButtons(tabEntry)"
    first_sync = body.find(sync_call)
    assert first_sync != -1, (
        "_applyFileJson should still wire save-button state via "
        "_syncPrimarySaveButtons(tabEntry) after the tab is registered."
    )
    assert first_sync > decl_idx, (
        "_syncPrimarySaveButtons(tabEntry) must be invoked AFTER `const tabEntry "
        "= {...}` is initialized; otherwise opening a file throws "
        "'Cannot access tabEntry before initialization'."
    )
