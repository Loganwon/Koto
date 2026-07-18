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
    assert "#wa-model-menu-trigger" in source
    assert "_setModelModeMenuOpen" in source
    assert "menuRect.width / menu.offsetWidth" in source
    assert "menuRect.height / menu.offsetHeight" in source
    assert "window.visualViewport" in source
    assert "root.addEventListener('keydown'" in source
    assert "document.addEventListener('pointerdown'" in source
    assert "setLockedModel(mode);" in source
    assert (
        "controlsRoot?.querySelectorAll('.wa-model-mode-toggle-btn[data-model-mode]')"
        in source
    )
    assert index_html.count("{% include '_workspace_model_controls.html' %}") == 1


def test_workspace_model_controls_use_single_trigger_and_grouped_menu():
    root = Path(__file__).resolve().parents[2]
    controls = (root / "web/templates/_workspace_model_controls.html").read_text(
        encoding="utf-8"
    )
    css = (root / "web/static/css/workspace-ai-panel.css").read_text(encoding="utf-8")

    assert 'id="wa-model-menu-trigger"' in controls
    assert 'aria-haspopup="listbox"' in controls
    assert 'id="wa-model-mode-menu"' in controls
    assert 'role="listbox"' in controls
    assert 'aria-label="云端模型"' in controls
    assert 'aria-label="本地模型"' in controls
    assert 'id="wa-model-current-provider"' in controls
    assert 'id="wa-model-current-model"' in controls
    assert ".wa-model-mode-menu" in css
    assert "position: fixed;" in css[css.index(".wa-model-mode-menu") :]
    assert ".wa-model-menu-group-label" in css
    assert ".wa-model-option-check" in css


def test_workspace_toggle_changes_mode_without_owning_model_selection():
    source = (
        Path(__file__).resolve().parents[2] / "web/src/workspace/model-settings.ts"
    ).read_text(encoding="utf-8")

    switch_start = source.index("function _setWorkspaceModelMode")
    switch_body = source[switch_start:]
    assert "settingLocalModel" not in switch_body
    assert "body: JSON.stringify({ mode: newModel })," in switch_body
    assert "koto:model-runtime-changed" in source
    assert "koto:local-model-changed" not in source


def test_settings_local_model_selection_activates_the_same_runtime():
    root = Path(__file__).resolve().parents[2]
    settings = (root / "web/src/app/settings.ts").read_text(encoding="utf-8")
    panel = (root / "web/templates/_settings_panel.html").read_text(encoding="utf-8")

    start = settings.index("export async function onLocalModelChange")
    end = settings.index("// ── Setup Wizard", start)
    handler = settings[start:end]
    assert "JSON.stringify({ mode: 'local', model_tag: nextModel })" in handler
    assert "currentSettings.model_mode = 'local';" in handler
    assert "mode: 'local'" in handler
    assert "void checkStatus();" in handler
    assert "选择模型后会立即同步到对话和文件任务" in panel
