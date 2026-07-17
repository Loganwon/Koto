from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_file_task_refresh_has_one_execution_event_owner():
    root = _repo_root()
    task_runner = _read("web/src/workspace/task-runner.ts")
    execution_events = _read(
        "web/src/workspace/task-execution-event-handlers.ts"
    )
    run_events = _read("web/src/workspace/task-run-event-handlers.ts")
    workspace_bundle = _read("web/src/bundles/workspace.ts")

    assert not (root / "web/src/workspace/task-refresh.ts").exists()
    assert "task-refresh" not in workspace_bundle
    assert "createFileTaskRefreshController" not in task_runner
    assert "file_refresh: handleFileRefresh" in execution_events
    assert "function handleEvent_file_refresh" not in task_runner
    assert "function openFinalTaskOutput" in run_events
    assert "function openFinalTaskOutput" not in task_runner


def test_file_task_refresh_normalizes_workspace_prefixed_paths():
    task_runner = _read("web/src/workspace/task-runner.ts")
    execution_events = _read(
        "web/src/workspace/task-execution-event-handlers.ts"
    )
    review_js = _read("web/src/workspace/docx-review-runtime.ts")

    assert "import { normalizeWorkspaceFilePath } from './docx-review-runtime';" in task_runner
    assert task_runner.count(
        "normalizeWorkspacePath: normalizeWorkspaceFilePath"
    ) == 2
    assert "workspaceApi.normalizeWorkspaceFilePath" not in task_runner
    assert "refreshWorkspaceFile(eventPath.refreshPath || eventPath.path)" in execution_events
    assert "requestFileBrowserRefreshAfterExternalChange" in task_runner
    assert (
        "return normalizedPath.replace(/^\\//, '').replace(/^workspace\\//i, '');"
        in review_js
    )
