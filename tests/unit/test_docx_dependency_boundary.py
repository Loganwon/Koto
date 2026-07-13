"""Keep Koto's DOCX editor on one supported TipTap/ProseMirror boundary."""

from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[2]


def test_docx_extensions_use_only_tiptap_prosemirror_entrypoints():
    source = (ROOT / "web" / "tiptap-editor" / "docx-extensions.js").read_text(encoding="utf-8")

    assert "from '@tiptap/pm/state'" in source
    assert "from '@tiptap/pm/view'" in source
    assert "from '@tiptap/pm/tables'" in source
    assert "from 'prosemirror-state'" not in source
    assert "from 'prosemirror-view'" not in source
    assert "from 'prosemirror-tables'" not in source


def test_docx_preview_asset_is_not_shipped_as_a_second_renderer():
    assert not (ROOT / "web" / "static" / "docx-preview.min.js").exists()
    for relative_path in (
        "Build_Release.ps1",
        "tests/installer/test_portable_e2e.ps1",
        "tests/installer/test_installer_e2e.ps1",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "docx-preview.min.js" not in source


def test_docx_editor_pins_the_single_verified_tiptap_release():
    package_json = json.loads(
        (ROOT / "web" / "tiptap-editor" / "package.json").read_text(encoding="utf-8")
    )
    lock_json = json.loads(
        (ROOT / "web" / "tiptap-editor" / "package-lock.json").read_text(encoding="utf-8")
    )
    declared = package_json["dependencies"]
    locked = lock_json["packages"][""]["dependencies"]
    tiptap_dependencies = {
        name: version for name, version in declared.items() if name.startswith("@tiptap/")
    }

    assert tiptap_dependencies
    assert set(tiptap_dependencies) == {
        name for name in locked if name.startswith("@tiptap/")
    }
    assert set(tiptap_dependencies.values()) == {"2.27.2"}
    assert {locked[name] for name in tiptap_dependencies} == {"2.27.2"}
