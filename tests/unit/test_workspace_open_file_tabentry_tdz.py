"""Regression guard for `_applyFileJson` tabEntry TDZ bug.

If `_syncPrimarySaveButtons(tabEntry)` is called before `tabEntry` is declared,
opening a file in 文件助手 throws:
    Cannot access 'tabEntry' before initialization
and the file fails to mount.  This test pins the safe ordering.
"""

from pathlib import Path


def _workspace_file_open_ts() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "web" / "src" / "workspace" / "file-open.ts").read_text(
        encoding="utf-8"
    )


def test_apply_file_json_initializes_tabentry_before_sync_primary_save_buttons():
    js = _workspace_file_open_ts()

    apply_marker = "export async function _applyFileJson("
    apply_idx = js.find(apply_marker)
    assert apply_idx != -1, "_applyFileJson must exist in file-open.ts"

    # Locate the function body up to the next top-level `async function ` /
    # `function ` declaration.  A generous slice is fine for our ordering check.
    body = js[apply_idx : apply_idx + 8000]

    decl_idx = body.find("const tabEntry: TabInfo = {")
    assert decl_idx != -1, "_applyFileJson must declare `const tabEntry: TabInfo = {`"

    state_call = "_applyTabState(tabEntry)"
    mount_call = "await _mountEditor(tabEntry, json.data)"
    first_state = body.find(state_call)
    first_mount = body.find(mount_call)
    assert (
        first_state != -1
    ), "_applyFileJson must apply tab state for the initialized tabEntry."
    assert first_mount != -1, "_applyFileJson must mount the initialized tabEntry."
    assert first_state > decl_idx
    assert first_mount > decl_idx

    apply_state_idx = js.find("function _applyTabState(tab: TabInfo): void")
    assert apply_state_idx != -1, "_applyTabState must exist in file-open.ts"
    apply_state_body = js[apply_state_idx : apply_state_idx + 1200]
    assert "_syncPrimarySaveButtons(tab)" in apply_state_body
