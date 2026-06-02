"""Guard tests for the retired legacy editor prompt-builder surface.

The file assistant has converged on `/api/editor/ai/task-stream` + the whitebox
FileTaskRuntime. The old `_build_editor_prompt` action ladder and the unused
`/api/editor/ai/chart-rerun` route were removed. These tests pin those removals
so they cannot silently come back.
"""

from __future__ import annotations

import importlib


def test_web_app_no_longer_exposes_legacy_prompt_builder_symbols():
    module = importlib.import_module("web.app")
    for name in (
        "_build_editor_prompt",
        "_EDITOR_AI_STREAM_ACTIONS",
        "_get_user_writing_style",
        "_doc_mode_hint",
    ):
        assert not hasattr(module, name), (
            f"web.app.{name} was removed during file-assistant task-flow "
            "convergence; do not reintroduce it."
        )


def test_editor_ai_chart_rerun_route_is_not_registered():
    module = importlib.import_module("web.app")
    rules = [rule.rule for rule in module.app.url_map.iter_rules()]
    assert "/api/editor/ai/chart-rerun" not in rules, (
        "/api/editor/ai/chart-rerun was removed; the file assistant uses the "
        "whitebox task-stream sandbox path instead."
    )


def test_editor_ai_task_stream_route_is_still_registered():
    module = importlib.import_module("web.app")
    rules = {rule.rule for rule in module.app.url_map.iter_rules()}
    assert "/api/editor/ai/task-stream" in rules, (
        "Canonical file-assistant task-stream route must remain registered."
    )
