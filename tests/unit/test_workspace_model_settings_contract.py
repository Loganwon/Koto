from pathlib import Path


def test_workspace_model_init_does_not_restore_retired_inline_output_mode():
    source = (
        Path(__file__).resolve().parents[2] / "web/src/workspace/model-settings.ts"
    ).read_text(encoding="utf-8")
    init_start = source.index("export function initSocket(): void")
    init_end = source.index("export function setLockedModel", init_start)
    init_body = source[init_start:init_end]

    assert "localStorage.removeItem('wa_ai_output_mode');" in init_body
    assert "localStorage.removeItem('wa_locked_model');" in init_body
    assert "localStorage.removeItem('wa_model_choice_explicit');" in init_body
    assert "state.aiOutputMode = 'inline';" not in init_body


def test_workspace_model_controls_have_one_scoped_typescript_click_boundary():
    root = Path(__file__).resolve().parents[2]
    source = (root / "web/src/workspace/model-settings.ts").read_text(encoding="utf-8")
    controls = (root / "web/templates/_workspace_model_controls.html").read_text(
        encoding="utf-8"
    )
    index_html = (root / "web/templates/index.html").read_text(encoding="utf-8")

    assert "KotoSetModelMode" not in controls
    assert "onclick=" not in controls
    assert "function _bindModelModeControls(): void" in source
    assert "root.addEventListener('click'" in source
    assert "root.contains(button)" in source
    assert "setLockedModel(mode);" in source
    assert (
        "controlsRoot?.querySelectorAll('.wa-model-mode-toggle-btn[data-model-mode]')"
        in source
    )
    assert index_html.count("{% include '_workspace_model_controls.html' %}") == 1


def test_workspace_toggle_changes_mode_without_owning_model_selection():
    source = (
        Path(__file__).resolve().parents[2] / "web/src/workspace/model-settings.ts"
    ).read_text(encoding="utf-8")

    switch_start = source.index("function _setWorkspaceModelMode")
    switch_body = source[switch_start:]
    assert "settingLocalModel" not in switch_body
    assert "body: JSON.stringify({ mode: newModel })," in switch_body
    assert "koto:local-model-changed" in source
