from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_workspace_api_is_the_single_publisher_for_migrated_cross_bundle_methods():
    root = _repo_root()
    api = (root / "web" / "src" / "shared" / "workspace-api.ts").read_text(encoding="utf-8")

    assert "export function getWorkspaceApi" in api
    assert "export function publishWorkspaceApi" in api
    assert "export function getWorkspaceApiMethod" in api

    publishers = {
        "web/src/editors/cdn-loaders.ts": "_ensurePdfJS",
        "web/src/editors/docx-outline.ts": "_setupDocOutline",
        "web/src/workspace/transport.ts": "createWorkspaceAiTransport",
        "web/src/workspace/task-refresh.ts": "createFileTaskRefreshController",
        "web/src/workspace/task-dispatcher.ts": "createTaskDispatcher",
        "web/src/workspace/quick-actions.ts": "createQuickActionDispatcher",
    }
    for relative_path, public_method in publishers.items():
        source = (root / relative_path).read_text(encoding="utf-8")
        assert "publishWorkspaceApi" in source
        assert public_method in source
        assert "publishWorkspaceApi({" in source


def test_workspace_file_and_context_modules_read_the_compatibility_boundary_only():
    root = _repo_root()
    consumers = (
        "web/src/workspace/ai-context.ts",
        "web/src/workspace/file-open.ts",
        "web/src/workspace/file-utils.ts",
        "web/src/workspace/fs-actions.ts",
        "web/src/workspace/fs-context-menu.ts",
    )
    for relative_path in consumers:
        source = (root / relative_path).read_text(encoding="utf-8")
        assert "getWorkspaceApi" in source
        assert "(window as any).WA" not in source
        assert "window.WA" not in source
