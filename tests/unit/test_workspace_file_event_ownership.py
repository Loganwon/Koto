from __future__ import annotations

import re
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[2] / "web" / "src" / "workspace"
FS_TREE = (WORKSPACE_ROOT / "fs-tree.ts").read_text(encoding="utf-8")
FS_ACTIONS = (WORKSPACE_ROOT / "fs-actions.ts").read_text(encoding="utf-8")


def _wa_assignments(source: str, method: str) -> int:
    return len(re.findall(rf"\bwa\.{method}\s*=", source))


def test_file_tree_is_the_only_owner_of_file_row_wa_handlers():
    for method in ("_browserFileRowMouseDown", "_browserFileRowClick"):
        assert _wa_assignments(FS_TREE, method) == 1
        assert _wa_assignments(FS_ACTIONS, method) == 0


def test_file_actions_does_not_install_a_second_file_row_click_delegate():
    assert "_installBrowserFileRowDelegation" not in FS_ACTIONS
    assert "__waBrowserFileDelegationInstalled" not in FS_ACTIONS
    assert "document.addEventListener('click'" not in FS_ACTIONS


def test_tree_rows_route_click_and_drag_to_the_single_public_owner():
    assert "getWorkspaceApi" in FS_TREE
    assert 'data-wa-file-draggable="true"' in FS_TREE
    assert 'data-wa-file-action="open"' in FS_TREE
    assert 'data-wa-file-action="send-ai"' in FS_TREE
    assert 'data-wa-file-kind="file"' in FS_TREE
    assert 'data-wa-file-kind="folder"' in FS_TREE
    assert 'onmousedown="WA.' not in FS_TREE
    assert 'onclick="WA.' not in FS_TREE
    assert 'onpointerdown="WA.' not in FS_TREE
    assert "window.WA" not in FS_TREE
    assert "document.addEventListener('pointerdown'" in FS_TREE
    assert "document.addEventListener('dragstart'" in FS_TREE
    assert "document.addEventListener('click'" in FS_TREE
    assert "wa._browserFileDragStart = _browserFileDragStart" in FS_TREE
    assert "wa._browserFileDragEnd = _browserFileDragEnd" in FS_TREE
