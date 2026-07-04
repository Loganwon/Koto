from pathlib import Path


def test_workspace_model_init_does_not_restore_retired_inline_output_mode():
    source = (Path(__file__).resolve().parents[2] / "web/src/workspace/model-settings.ts").read_text(
        encoding="utf-8"
    )
    init_start = source.index("export function initSocket(): void")
    init_end = source.index("export function setUseLocalModel", init_start)
    init_body = source[init_start:init_end]

    assert "localStorage.removeItem('wa_ai_output_mode');" in init_body
    assert "state.aiOutputMode = 'inline';" not in init_body
