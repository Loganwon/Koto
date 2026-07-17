from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_workspace_api_is_the_single_publisher_for_migrated_cross_bundle_methods():
    root = _repo_root()
    api = (root / "web" / "src" / "shared" / "workspace-api.ts").read_text(
        encoding="utf-8"
    )

    assert "export function getWorkspaceApi" in api
    assert "export function publishWorkspaceApi" in api
    assert "export function getWorkspaceApiMethod" in api

    publishers = {
        "web/src/editors/cdn-loaders.ts": "_ensurePdfJS",
        "web/src/editors/docx-outline.ts": "_setupDocOutline",
        "web/src/workspace/ai-review.ts": "sendMessage",
        "web/src/workspace/runtime-init.ts": "hydrateAiHistory",
        "web/src/editors/pdf-viewer.ts": "pdfAIAnnotate",
        "web/src/workspace/conversation-list.ts": "openAiSession",
        "web/src/workspace/task-workbench.ts": "openTaskWorkbenchForCurrentRun",
        "web/src/workspace/ai-context.ts": "attachFilesToTask",
        "web/src/workspace/fs-context-menu.ts": "_showBrowserCtx",
        "web/src/ui/docx-pptx-toolbar.ts": "docxHoverFmt",
        "web/src/ui/selection-toolbar.ts": "sendSelectionToAI",
        "web/src/workspace/find-replace.ts": "installWorkspaceFindReplace",
        "web/src/workspace/model-settings.ts": "setLockedModel",
        "web/src/workspace/save.ts": "saveFile",
    }
    for relative_path, public_method in publishers.items():
        source = (root / relative_path).read_text(encoding="utf-8")
        assert "publishWorkspaceApi" in source
        assert public_method in source
        assert "publishWorkspaceApi({" in source


def test_workspace_runtime_factories_are_direct_module_dependencies():
    root = _repo_root()
    runtime = (root / "web/src/workspace/runtime-init.ts").read_text(
        encoding="utf-8"
    )
    owners = {
        "web/src/workspace/conversation.ts": "createWorkspaceAiConversation",
        "web/src/workspace/task-dispatcher.ts": "createTaskDispatcher",
        "web/src/workspace/results.ts": "createWorkspaceAiResultsRuntime",
        "web/src/workspace/quick-actions.ts": "createQuickActionDispatcher",
    }

    for relative_path, factory in owners.items():
        source = (root / relative_path).read_text(encoding="utf-8")
        assert f"import {{ {factory} }} from './" in runtime
        assert f"workspaceApi.{factory}" not in runtime
        assert f"publishWorkspaceApi({{ {factory} }})" not in source

    quick_actions = (root / "web/src/workspace/quick-actions.ts").read_text(
        encoding="utf-8"
    )
    assert "createWorkspaceQuickActionRuntime" not in quick_actions
    assert "createWorkspaceQuickActionRuntime" not in runtime
    assert "state," not in runtime.split(
        "_waQuickActionRuntime = createQuickActionDispatcher({", 1
    )[1].split("});", 1)[0]


def test_task_flow_runtime_has_no_same_bundle_window_bus_or_raw_runtime_aliases():
    root = _repo_root()
    runtime = (root / "web/src/workspace/runtime-init.ts").read_text(encoding="utf-8")
    review = (root / "web/src/workspace/ai-review.ts").read_text(encoding="utf-8")
    dispatcher = (root / "web/src/workspace/task-dispatcher.ts").read_text(
        encoding="utf-8"
    )
    direct_chat = (root / "web/src/workspace/task-direct-chat.ts").read_text(
        encoding="utf-8"
    )
    final_report = (root / "web/src/workspace/task-final-report.ts").read_text(
        encoding="utf-8"
    )

    assert "publishWorkspaceApi({ taskCardTestStructure });" not in dispatcher
    assert "taskCardPersistenceStructure," in dispatcher
    assert "_waTaskDispatcher.taskCardPersistenceStructure(card)" in runtime

    for source in (runtime, review, direct_chat, final_report):
        assert "(window as any)._waRenderMarkdown" not in source
        assert "(window as any)._sanitizeRenderedHtml" not in source

    for alias in (
        "_waAiResultsRuntime",
        "_waQuickActionRuntime",
        "_waConversationRuntime",
        "_waTaskDispatcher",
        "_waQuickActionDispatcherAttached",
        "_initWorkspaceAiRuntimes",
        "_hydrateAiConversation",
        "_waSession",
        "_waQuickActionModelMode",
        "_waSampleTaskContext",
        "_persistWorkspaceConversationTurn",
        "_persistTerminalTaskRunCard",
        "_retryWorkspaceConversationPersistence",
    ):
        assert f"(window as any).{alias} =" not in runtime

    assert "getWorkspaceConversationRuntime?.()" in review
    assert "getWorkspaceTaskDispatcher?.()" in review
    assert "getWorkspaceQuickActionRuntime?.()" in review
    assert "getWorkspaceAiResultsRuntime?.()" in review
    assert "_setStreamBtn," in review.split("publishWorkspaceApi({", 1)[1]
    assert "getWorkspaceSessionId: _waSession," in runtime


def test_retired_generic_workspace_transport_stays_removed():
    root = _repo_root()
    bundle = (root / "web/src/bundles/workspace.ts").read_text(encoding="utf-8")
    retained = (root / "docs/WORKSPACE_RETAINED_LEGACY.md").read_text(
        encoding="utf-8"
    )

    assert not (root / "web/src/workspace/transport.ts").exists()
    assert "import '../workspace/transport';" not in bundle
    assert "task-stream-transport.ts" in retained
    assert "task-direct-chat.ts" in retained


def test_workspace_file_and_context_modules_read_the_compatibility_boundary_only():
    root = _repo_root()
    consumers = (
        "web/src/workspace/ai-context.ts",
        "web/src/workspace/file-open.ts",
        "web/src/workspace/file-utils.ts",
        "web/src/workspace/fs-actions.ts",
        "web/src/workspace/fs-context-menu.ts",
        "web/src/workspace/fs-tree.ts",
        "web/src/workspace/ai-review.ts",
        "web/src/workspace/runtime-init.ts",
        "web/src/editors/pdf-viewer.ts",
        "web/src/workspace/conversation.ts",
        "web/src/workspace/conversation-list.ts",
        "web/src/workspace/task-workbench.ts",
        "web/src/ui/docx-pptx-toolbar.ts",
        "web/src/ui/selection-toolbar.ts",
        "web/src/editors/text-editor.ts",
        "web/src/workspace/find-replace.ts",
        "web/src/app/settings.ts",
    )
    for relative_path in consumers:
        source = (root / relative_path).read_text(encoding="utf-8")
        assert "getWorkspaceApi" in source
        assert "(window as any).WA" not in source
        assert "window.WA" not in source


def test_workspace_context_menu_uses_delegated_actions_for_dynamic_rows():
    root = _repo_root()
    source = (root / "web/src/workspace/fs-context-menu.ts").read_text(encoding="utf-8")

    assert 'onclick="WA.' not in source
    assert "data-wa-context-menu-action" in source
    assert "function _installContextMenuActionDelegation(): void" in source
    assert "publishWorkspaceApi({" in source


def test_workspace_state_file_rows_use_delegated_actions():
    root = _repo_root()
    source = (root / "web/src/workspace/state.ts").read_text(encoding="utf-8")

    assert 'onclick="WA.openRecentFile' not in source
    assert (
        'oncontextmenu="event.preventDefault();event.stopPropagation();WA._showBrowserCtx'
        not in source
    )
    assert 'data-wa-file-draggable="true"' in source
    assert 'data-wa-file-action="open"' in source
    assert 'data-wa-workspace-row-action="remove-my"' in source
    assert 'data-wa-workspace-row-action="remove-temp"' in source
    assert "function _installWorkspaceRowActionDelegation(): void" in source


def test_selection_context_bar_uses_delegated_actions():
    root = _repo_root()
    source = (root / "web/src/ui/selection-toolbar.ts").read_text(encoding="utf-8")

    assert 'onclick="WA.clearSelection()"' not in source
    assert 'onclick="WA.clearAIFileContext()"' not in source
    assert "data-wa-selection-context-action" in source
    assert "function _installSelectionToolbarEvents(): void" in source
    assert "publishWorkspaceApi({" in source


def test_find_replace_uses_delegated_template_actions():
    root = _repo_root()
    source = (root / "web/src/workspace/find-replace.ts").read_text(encoding="utf-8")
    template = (root / "web/templates/index.html").read_text(encoding="utf-8")

    assert "window.WA" not in source
    assert "function _installFindReplaceActionDelegation(): void" in source
    assert "data-wa-find-action" in template
    assert 'oninput="WA.docxFind' not in template
    assert 'oninput="WA.pptxFind' not in template
    assert 'onkeydown="WA.docxFind' not in template
    assert 'onkeydown="WA.pptxFind' not in template
    assert 'onclick="WA.docxFind' not in template
    assert 'onclick="WA.pptxFind' not in template
