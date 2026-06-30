import re
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    path = _repo_root() / rel_path
    return path.read_text(encoding="utf-8")


def test_workspace_file_assistant_uses_single_task_flow_stream_by_default():
    assistant_js = _read("web/src/workspace/ai-review.ts")
    dispatcher_js = _read("web/src/workspace/task-dispatcher.ts")
    task_js = _read("web/src/workspace/task-runner.ts")
    quick_actions_js = _read("web/src/workspace/quick-actions.ts")

    assert "WA.createTaskDispatcher = createTaskDispatcher" in dispatcher_js
    assert "taskDispatcher.dispatchMessage({" in assistant_js
    assert "taskDispatcher.dispatchQuickAction(action, {" in assistant_js
    assert "WA.streamTaskFlow = streamTaskFlow" in task_js
    assert "csrfFetch('/api/editor/ai/task-stream'" in task_js
    assert "fetch('/api/editor/ai/task-stream'" not in assistant_js
    assert "legacyEditorFallback: true" not in quick_actions_js
    assert "legacyEditorFallback" not in quick_actions_js


def test_workspace_static_js_only_task_renderer_calls_file_task_stream():
    static_js_dir = _repo_root() / "web" / "static" / "js"
    offenders = []
    for path in static_js_dir.glob("*.js"):
        source = path.read_text(encoding="utf-8")
        if (
            "/api/editor/ai/task-stream" in source
            and path.name != "workspace-ai-task.js"
        ):
            offenders.append(path.name)

    assert offenders == []


def test_workspace_notebook_tools_are_split_from_assistant_shell():
    assistant_js = _read("web/src/workspace/ai-review.ts")
    notebook_js = _read("web/src/workspace/notebook.ts")
    asset_scripts = _read("web/templates/_workspace_asset_scripts.html")
    workspace_bundle_entry = _read("web/src/bundles/workspace.ts")

    assert "WA.installWorkspaceNotebookTools" in notebook_js
    assert "WA.doSourceSearch" in notebook_js
    assert "WA.closeAudioModal = closeAudioModal" in notebook_js
    assert "WA.closeNotebookGuide = closeNotebookGuide" in notebook_js
    assert "installWorkspaceNotebookTools({" in _read("web/src/bundles/workspace.ts")
    assert "window.WA.openAudioOverview = async" not in assistant_js
    assert "window.WA.openNotebookGuide = async" not in assistant_js
    assert "window.WA.doSourceSearch = " not in assistant_js
    assert "workspace-bundle.js" in asset_scripts
    assert "workspace-assistant.js" not in asset_scripts
    assert "import '../workspace/notebook';" in workspace_bundle_entry


def test_unified_workspace_mounts_notebook_source_and_audio_surfaces():
    index_template = _read("web/templates/index.html")
    notebook_ts = _read("web/src/workspace/notebook.ts")
    ai_context_ts = _read("web/src/workspace/ai-context.ts")
    workspace_css = "\n".join(
        [
            _read("web/static/css/workspace.css"),
            _read("web/static/css/workspace-ai-panel.css"),
        ]
    )
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    for dom_id in [
        'id="wa-source-preview"',
        'id="wa-source-preview-label"',
        'id="wa-source-preview-body"',
        'id="wa-audio-modal"',
        'id="wa-audio-modal-body"',
        'id="wa-notebook-guide"',
        'id="wa-source-search-input"',
        'id="wa-source-search-results"',
        'id="wa-source-clear-btn"',
        'id="wa-notebook-body"',
    ]:
        assert dom_id in index_template

    assert 'id="wa-notebook-guide"' in index_template
    assert 'id="wa-audio-modal"' in index_template
    assert "学习包" in index_template
    assert "有声概览" in index_template
    assert ".wa-multidoc-actions" in workspace_css
    assert "WA.closeSourcePreview = closeSourcePreview" in notebook_ts
    assert "WA.closeAudioModal = closeAudioModal" in notebook_ts
    assert "WA.closeNotebookGuide = closeNotebookGuide" in notebook_ts
    assert "WA.doSourceSearch = doSourceSearch" in notebook_ts
    assert "WA.clearSourceSearch = clearSourceSearch" in notebook_ts
    assert "fetch('/api/v1/workspace/notebook_guide'" not in notebook_ts
    assert "fetch('/api/v1/workspace/audio_overview'" not in notebook_ts

    for symbol in [
        "doSourceSearch",
        "closeSourcePreview",
        "closeAudioModal",
        "closeNotebookGuide",
        "clearSourceSearch",
    ]:
        assert symbol in workspace_bundle


def test_unified_workspace_restores_pdf_annotation_toolbar_and_ai_bridge():
    index_template = _read("web/templates/index.html")
    pdf_viewer_ts = _read("web/src/editors/pdf-viewer.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    for marker in [
        'id="wa-pdf-annot-bar"',
        "WA.pdfAnnotMode('highlight')",
        "WA.pdfAnnotMode('underline')",
        "WA.pdfAnnotMode('strikethrough')",
        "WA.pdfAnnotMode('note')",
        "WA.pdfAnnotMode('draw')",
        "WA.pdfAnnotMode('rect')",
        "WA.pdfAnnotMode('ellipse')",
        "WA.pdfAnnotMode('line')",
        "WA.pdfAnnotMode('arrow')",
        "WA.pdfAnnotMode('textbox')",
        "WA.pdfAnnotMode('eraser')",
        "WA.pdfSaveAnnotations()",
        "WA.pdfAIAnnotate()",
        "AI 标注",
    ]:
        assert marker in index_template

    assert "(window as any).WA.pdfAIAnnotate" in pdf_viewer_ts
    assert "typeof ed.aiAnnotate === 'function'" in pdf_viewer_ts
    assert "AI 标注功能正在迁移" not in pdf_viewer_ts
    assert "_applyAiAnnotationSuggestions" in pdf_viewer_ts
    assert "_locateAiAnnotationQuote" in pdf_viewer_ts
    assert "pdf_ai_annotate: true" in pdf_viewer_ts
    assert "window.WA.pdfAIAnnotate" in workspace_bundle


def test_workspace_task_workbench_is_split_and_mounted():
    workbench_js = _read("web/src/workspace/task-workbench.ts")
    task_js = _read("web/src/workspace/task-runner.ts")
    asset_scripts = _read("web/templates/_workspace_asset_scripts.html")
    workspace_bundle_entry = _read("web/src/bundles/workspace.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")
    workspace_template = _read("web/templates/index.html")
    index_template = _read("web/templates/index.html")
    workspace_css = _read("web/static/css/workspace.css")

    assert "window.WA.toggleTaskWorkbench" not in workbench_js
    assert "window.WA.refreshTaskWorkbench" not in workbench_js
    assert "window.WA.notifyTaskWorkbenchChanged" not in workbench_js
    assert "window.WA.focusTaskWorkbenchTask" not in workbench_js
    assert "WA.refreshCurrentTaskFlow = refreshCurrentTaskFlow" in workbench_js
    assert "WA.notifyTaskFlowChanged = notifyTaskFlowChanged" in workbench_js
    assert (
        "WA.openTaskWorkbenchForCurrentRun = openTaskWorkbenchForCurrentRun"
        in workbench_js
    )
    assert "function focusTaskCard(taskId: any, runId: any): boolean" in workbench_js
    assert "fetchJson('/api/tasks?limit=120&order_by=created_at')" in workbench_js
    assert "WA.resumePersistedFileTask = resumePersistedFileTask" in task_js
    assert "renderArtifactResult" in _read("web/src/workspace/results.ts")
    assert "data-task-open-workbench" not in task_js
    assert "scheduleTaskLiveProgressCollapse" in task_js
    assert "wa-msg ai wa-task-run is-compact" in task_js
    assert "artifactResult && artifactResult.task_id" in task_js
    assert "function liveStepsForTask(task: any): WorkbenchStep[]" in workbench_js
    assert "taskCardForTask(task && task.task_id, runIdForTask(task))" in workbench_js
    assert "function latestLiveTaskCard()" in workbench_js
    assert (
        "function renderFocusedLiveTask(state: WorkbenchState): boolean" in workbench_js
    )
    assert (
        "dataset.taskFollowupPayload || dataset.taskPendingResumePayload"
        in workbench_js
    )
    assert "function metadataStepsForTask(task: any): WorkbenchStep[]" in workbench_js
    assert "data.model_mode || payload && payload.model_mode" in workbench_js
    assert "模型调用 ·" in workbench_js
    assert "文件上下文 · 已载入" in workbench_js
    assert "结果 · 已完成" in workbench_js
    assert "chipLower.includes('whitebox')" in workbench_js
    assert "const doneTool = chip.match(/^完成\\s+(.+)$/)" in workbench_js
    assert "title === '任务状态' && rows.length === 1" in workbench_js
    assert "function activeSessionTaskId()" not in workbench_js
    assert (
        "const nextTaskId = explicitTaskId || (shouldShow ? activeSessionTaskId() : '')"
        not in workbench_js
    )
    assert 'title="查看历史任务"' not in workbench_js
    assert 'title="查看历史任务"' not in workspace_template
    assert 'title="查看历史任务"' not in index_template
    assert 'data-task-workbench-filter="all"' not in workspace_template
    assert 'data-task-workbench-filter="all"' not in index_template
    assert "focusedOnly: true" in workbench_js
    assert "state.activeTaskId && !state.loading" in workbench_js
    assert "等待文件任务" in workbench_js
    assert (
        "当请求需要读取、修改或生成文件时，这里会直接展开任务识别、执行方案、进度和核验结果。"
        in workbench_js
    )
    assert "任务识别" in workbench_js
    assert "完成核验" in workbench_js
    assert "FLOW_STAGE_DEFS" in workbench_js
    assert (
        "function renderStageOverview(steps: WorkbenchStep[]): string" in workbench_js
    )
    assert (
        "function normalizedWorkbenchSteps(steps: any[], task: any): WorkbenchStep[]"
        in workbench_js
    )
    assert "wa-task-workbench-stage-grid" in workbench_js
    assert "任务步骤" in workbench_js
    assert "详细过程" not in workbench_js
    assert "(window as any).WA.notifyTaskFlowChanged(taskId)" in task_js
    assert (
        "function notifyTaskWorkbenchForCard(card: TaskCardElement, options?: { delayed?: boolean }): void"
        in task_js
    )
    assert "if (options && options.delayed)" in task_js
    assert "seedRouteModelContext(card, payload)" in task_js
    assert "模型调用" in task_js
    assert (
        "function compactFlowSummary(value: string, fallback = '完整结果见对话汇报。'): string"
        in task_js
    )
    assert "function supervisorAuditHtml(data: Record<string, any>): string" in task_js
    assert "function supervisorAuditStatusLabel(status: unknown): string" in task_js
    assert "需关注" in task_js
    assert "supervisor_audit" in task_js
    assert "完整结果见对话汇报" in task_js
    assert "${esc(payload.summary || '')}${criteriaHtml}${runtimeHtml}" not in task_js
    assert "import '../workspace/results';" in workspace_bundle_entry
    assert "import '../workspace/task-runner';" in workspace_bundle_entry
    assert "workspace-task-workbench.js" not in asset_scripts
    assert "workspace-ai-results.js" not in asset_scripts
    assert "workspace-assistant.js" not in asset_scripts
    assert 'id="wa-task-workbench-toggle"' not in workspace_template
    assert 'id="wa-task-workbench-toggle"' not in index_template
    assert 'id="wa-task-workbench"' not in workspace_template
    assert 'id="wa-task-workbench"' not in index_template
    assert 'id="wa-artifact-panel"' in workspace_template
    assert 'id="wa-artifact-panel"' in index_template
    assert (
        workspace_template.index('id="wa-ai-messages"')
        < workspace_template.index('id="wa-artifact-panel"')
        < workspace_template.index('id="wa-task-live-progress"')
    )
    assert (
        index_template.index('id="wa-ai-messages"')
        < index_template.index('id="wa-artifact-panel"')
        < index_template.index('id="wa-task-live-progress"')
    )
    assert 'id="wa-task-column"' not in workspace_template
    assert 'id="wa-task-column"' not in index_template
    assert "revealTaskColumn(panel)" not in _read("web/src/workspace/results.ts")
    assert ".wa-task-workbench" in workspace_css
    assert ".wa-task-workbench-body" in workspace_css
    assert ".wa-task-workbench-artifacts" in workspace_css
    assert ".wa-task-workbench-stage-grid" in workspace_css
    assert ".wa-task-workbench-stage-top" in workspace_css
    assert ".wa-task-workbench-section-title" in workspace_css
    assert ".wa-task-workbench-step-headline" in workspace_css
    assert ".wa-inline-task-workbench" in workspace_css
    assert "#wa-ai-messages > .wa-inline-task-workbench" in workspace_css
    assert '.wa-task-run.is-compact [data-role="ui-progress"]' in workspace_css
    assert (
        "#wa-ai-messages .wa-task-run.is-compact:not(.streaming) .wa-task-header"
        in workspace_css
    )
    assert "可追问或查看步骤。" not in task_js
    assert "查看流程" not in task_js
    assert "查看流程" not in workspace_bundle
    assert "openTaskWorkbenchForCurrentRun" in workbench_js
    assert "openTaskWorkbenchForCurrentRun" in workspace_bundle
    assert "whitebox-task" not in _read("web/src/workspace/task-dispatcher.ts")
    assert "白盒任务渲染器未加载" not in _read("web/src/workspace/task-dispatcher.ts")
    assert "task-flow" in _read("web/src/workspace/task-dispatcher.ts")
    assert "revealTaskWorkbenchForCard(card, { scroll: true });" in _read(
        "web/src/workspace/task-runner.ts"
    )
    assert ".wa-task-run.is-workbench-focused" in workspace_css


def test_legacy_file_task_stream_does_not_write_old_thinking_panel():
    file_task_stream = _read("web/file_task_stream.py")
    editor_ai = _read("web/blueprints/editor_ai.py")

    assert "yield_thinking=None" in file_task_stream
    assert 'yield_thinking(f"启动 FileTaskRuntime 处理' not in file_task_stream
    assert (
        'yield_thinking(msg[:200] if msg else f"阶段: {event_type}"'
        not in file_task_stream
    )
    assert "结构化任务流程" in editor_ai


def test_workspace_skill_library_falls_back_to_global_skills():
    assistant_js = _read("web/src/workspace/ai-review.ts")
    model_settings = _read("web/src/workspace/model-settings.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")
    workspace_template = _read("web/templates/index.html")
    index_template = _read("web/templates/index.html")

    assert "toggleSkillLibrary" in model_settings
    assert "openSkillsPanel" in model_settings
    assert "navSkillsBtn" in index_template
    assert 'id="wa-skill-lib-btn"' not in workspace_template
    assert 'id="wa-skill-lib-btn"' not in index_template
    assert 'id="wa-theme-toggle-btn"' not in workspace_template
    assert 'id="wa-theme-toggle-btn"' not in index_template
    assert 'id="navSkillsBtn"' in index_template
    assert 'id="navSettingsBtn"' in index_template


def test_workspace_model_and_file_browser_runtime_state_are_defined_in_split_modules():
    model_settings = _read("web/src/workspace/model-settings.ts")
    embedded_mode = _read("web/src/ui/embedded-mode.ts")

    assert "function _clearActiveRoute(): void" in model_settings
    assert "state._activeRoute = null;" in model_settings
    assert "declare function _clearActiveRoute" not in model_settings
    assert "let _fsBrowserCtxTarget" in embedded_mode
    assert "declare var _fsBrowserCtxTarget" not in embedded_mode


def test_workspace_conversation_hydrates_persisted_session_history():
    conversation_ts = _read("web/src/workspace/conversation.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert (
        "loadSessionHistory?: (sessionId: string) => Promise<any[]>;" in conversation_ts
    )
    assert (
        "const loadSessionHistory = typeof options.loadSessionHistory === 'function'"
        in conversation_ts
    )
    assert "await loadSessionHistory(sessionId)" in conversation_ts
    assert "renderHistory(turns)" in conversation_ts
    assert "loadSessionHistory" in workspace_bundle


def test_workspace_ai_panel_uses_session_list_then_chat_detail():
    conversation_list_ts = _read("web/src/workspace/conversation-list.ts")
    conversation_sessions_ts = _read("web/src/workspace/conversation-sessions.ts")
    model_settings_ts = _read("web/src/workspace/model-settings.ts")
    runtime_init_ts = _read("web/src/workspace/runtime-init.ts")
    sessions_bp = _read("web/blueprints/sessions.py")
    workspace_bundle_entry = _read("web/src/bundles/workspace.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")
    workspace_template = _read("web/templates/index.html")
    index_template = _read("web/templates/index.html")
    workspace_css = "\n".join(
        [
            _read("web/static/css/workspace.css"),
            _read("web/static/css/workspace-ai-panel.css"),
        ]
    )

    assert 'id="wa-ai-session-list-view"' in workspace_template
    assert 'id="wa-ai-session-list-view"' in index_template
    assert 'id="wa-ai-session-list"' in workspace_template
    assert 'id="wa-ai-session-list"' in index_template
    assert 'id="wa-ai-session-list-composer"' in workspace_template
    assert 'id="wa-ai-session-list-composer"' in index_template
    assert 'id="wa-session-list-composer-host"' in workspace_template
    assert 'id="wa-session-list-composer-host"' in index_template
    assert 'id="wa-user-input"' in workspace_template
    assert 'id="wa-user-input"' in index_template
    assert "WA.handleUnifiedComposerKeydown" in workspace_template
    assert "WA.handleUnifiedComposerKeydown" in index_template
    assert 'aria-label="AI 对话与任务历史"' in workspace_template
    assert 'aria-label="AI 对话与任务历史"' in index_template
    assert "对话与任务" in workspace_template
    assert "对话与任务" in index_template
    assert "wa-ai-session-modebar" not in workspace_template
    assert "wa-ai-session-modebar" not in index_template
    assert (
        "能总结分析、改写润色、生成文档、整理文件。输入任务或附加文件，过程和结果都会显示在这里。"
        in workspace_template
    )
    assert (
        "能总结分析、改写润色、生成文档、整理文件。输入任务或附加文件，过程和结果都会显示在这里。"
        in index_template
    )
    assert 'class="wa-ai-session-new-btn"' in workspace_template
    assert 'class="wa-ai-session-new-btn"' in index_template
    assert "新建对话" in workspace_template
    assert "新建对话" in index_template
    assert "打开任务步骤" not in workspace_template
    assert "打开任务步骤" not in index_template
    assert "任务流程" in _read("web/src/workspace/task-workbench.ts")
    assert 'id="wa-ai-chat-view" class="wa-ai-chat-view" hidden' in workspace_template
    assert 'id="wa-ai-chat-view" class="wa-ai-chat-view" hidden' in index_template
    assert 'id="wa-ai-session-back"' in workspace_template
    assert 'id="wa-ai-session-back"' in index_template
    assert (
        workspace_template.index('id="wa-ai-session-list-view"')
        < workspace_template.index('id="wa-ai-chat-view"')
        < workspace_template.index('id="wa-ai-messages"')
    )
    assert (
        index_template.index('id="wa-ai-session-list-view"')
        < index_template.index('id="wa-ai-chat-view"')
        < index_template.index('id="wa-ai-messages"')
    )
    assert "import '../workspace/conversation-list';" in workspace_bundle_entry
    assert "fetch('/api/sessions?preview=1'" in conversation_sessions_ts
    assert "WA.openAiSession = openAiSession" in conversation_list_ts
    assert "WA.showAiSessionList = showAiSessionList" in conversation_list_ts
    assert "WA.newAiSession = newAiSession" in conversation_list_ts
    assert (
        "WA.sendSessionListComposer = sendSessionListComposer" in conversation_list_ts
    )
    assert (
        "WA.handleSessionListComposerKeydown = handleSessionListComposerKeydown"
        in conversation_list_ts
    )
    assert "WA.deleteAiSession = deleteAiSession" in conversation_list_ts
    assert "WA._syncAiSessionSelection = syncAiSessionSelection" in conversation_list_ts
    assert "const _SESSION_PREVIEW_LIMIT = 5;" in conversation_list_ts
    assert "let _sessionsExpanded = false;" in conversation_list_ts
    assert "_sessions.slice(0, _SESSION_PREVIEW_LIMIT)" in conversation_list_ts
    assert "data-ai-session-expand" in conversation_list_ts
    assert "展开 ${hiddenCount} 条历史" in conversation_list_ts
    assert "收起历史" in conversation_list_ts
    assert (
        "export function sendSessionListComposer(): Promise<any>"
        in conversation_list_ts
    )
    assert (
        "function _openLatestTaskFlowForSession(sessionId: string): void"
        in conversation_list_ts
    )
    assert (
        "function _syncHistoricalTaskLiveProgress(session?: AiSessionPreview): void"
        in conversation_list_ts
    )
    assert "WA.openTaskWorkbenchForCurrentRun({" in conversation_list_ts
    assert "查看下方步骤" in conversation_list_ts
    assert "latest_task_id" in conversation_list_ts
    assert "const sessionId = await createAiSessionRecord();" in conversation_list_ts
    assert "await openAiSession(sessionId, { force: true });" in conversation_list_ts
    assert "WA.sendMessage();" in conversation_list_ts
    assert "function _closeSkillLibrary" in conversation_list_ts
    assert "if (!options.silent) _closeSkillLibrary();" in conversation_list_ts
    assert "task_count?: number;" in conversation_sessions_ts
    assert "latest_task_status?: string;" in conversation_sessions_ts
    assert "wa-ai-session-task-badge" in conversation_list_ts
    assert "data-latest-task-status" in conversation_list_ts
    assert "data-ai-session-delete" in conversation_list_ts
    assert "export async function deleteAiSession" in conversation_list_ts
    assert (
        "`/api/sessions/${encodeURIComponent(normalized)}`" in conversation_sessions_ts
    )
    assert "method: 'DELETE'" in conversation_sessions_ts
    assert "_focusComposer();" in conversation_list_ts
    assert (
        "latest_task_id: String(record.latest_task_id || '').trim()"
        in conversation_sessions_ts
    )
    assert "taskCount ? `${taskCount} 个任务` : ''" in conversation_list_ts
    assert "export function closeSkillLibrary()" in model_settings_ts
    assert "WA.closeSkillLibrary = closeSkillLibrary" in model_settings_ts
    assert "syncSelection(_hostSessionId)" in runtime_init_ts
    assert 'request.args.get("preview")' in sessions_bp
    assert (
        "def _session_preview(session_filename: str, history: list[object]) -> dict:"
        in sessions_bp
    )
    assert "def _is_workspace_assistant_session" not in sessions_bp
    assert "if not _is_workspace_assistant_session(session)" not in sessions_bp
    assert "session_files = _get_session_manager().list_sessions()" in sessions_bp
    assert '"task_count": len(task_entries)' in sessions_bp
    assert '"has_task_flow": bool(task_entries)' in sessions_bp
    assert '"latest_task_status": latest_task_status' in sessions_bp
    assert ".wa-ai-session-list-view" in workspace_css
    assert ".wa-ai-session-list-composer" in workspace_css
    assert ".wa-composer-host" in workspace_css
    assert ".wa-ai-session-list-composer .wa-input-box" in workspace_css
    assert ".wa-ai-session-item" in workspace_css
    assert ".wa-inline-task-workbench" in workspace_css
    assert ".wa-ai-session-task-badge" in workspace_css
    assert ".wa-ai-session-delete" in workspace_css
    assert ".wa-ai-session-new-btn" in workspace_css
    assert ".wa-ai-session-expand" in workspace_css
    assert "min-height: 96px;" in workspace_css
    assert "max-height: 220px;" in workspace_css
    assert ".wa-ai-chat-view" in workspace_css
    assert "z-index: 190;" in workspace_css
    assert "openAiSession" in workspace_bundle
    assert "sendSessionListComposer" in workspace_bundle


def test_unified_session_api_includes_workspace_and_editor_sessions(monkeypatch):
    from flask import Flask

    from web.blueprints import sessions as sessions_mod

    class FakeSessionManager:
        def list_sessions(self):
            return [
                "chat_main.json",
                "workspace_file_task.json",
                "editor_doc_review.json",
            ]

        def load_full(self, filename):
            return [
                {
                    "role": "user",
                    "parts": [filename.replace(".json", "")],
                    "timestamp": "2026-06-17T10:00:00",
                },
                {
                    "role": "model",
                    "parts": ["done"],
                    "task": "file_task",
                    "status": "done",
                    "timestamp": "2026-06-17T10:01:00",
                },
            ]

    manager = FakeSessionManager()
    monkeypatch.setattr(sessions_mod, "get_session_manager", lambda: manager)

    app = Flask(__name__)
    app.register_blueprint(sessions_mod.sessions_bp)
    client = app.test_client()

    list_payload = client.get("/api/sessions").get_json()
    assert list_payload["sessions"] == [
        "chat_main",
        "workspace_file_task",
        "editor_doc_review",
    ]

    preview_payload = client.get("/api/sessions?preview=1").get_json()
    assert [item["id"] for item in preview_payload["sessions"]] == [
        "chat_main",
        "workspace_file_task",
        "editor_doc_review",
    ]
    assert all(item["has_task_flow"] for item in preview_payload["sessions"])


def test_workspace_find_replace_tools_are_split_from_assistant_shell():
    assistant_js = _read("web/src/workspace/ai-review.ts")
    find_replace_js = _read("web/src/workspace/find-replace.ts")
    asset_scripts = _read("web/templates/_workspace_asset_scripts.html")
    workspace_bundle_entry = _read("web/src/bundles/workspace.ts")

    assert "WA.installWorkspaceFindReplace" in find_replace_js
    assert "WA.docxFindInput" in find_replace_js
    assert "WA.pptxFindInput" in find_replace_js
    assert "installWorkspaceFindReplace({" in _read("web/src/bundles/workspace.ts")
    assert "window.WA.docxFindInput = " not in assistant_js
    assert "window.WA.pptxFindInput = " not in assistant_js
    assert "workspace-bundle.js" in asset_scripts
    assert "workspace-assistant.js" not in asset_scripts
    assert "import '../workspace/find-replace';" in workspace_bundle_entry


def test_workspace_file_assistant_never_calls_retired_ai_task_routes():
    checked_paths = [
        "web/src/workspace/ai-review.ts",
        "web/src/workspace/task-dispatcher.ts",
        "web/src/workspace/quick-actions.ts",
        "web/src/workspace/task-runner.ts",
    ]
    retired_routes = [
        "/api/editor/ai/stream",
        "/api/editor/ai/chart",
        "/api/editor/ai/task-execute",
        "/api/editor/ai/skill-execute",
        "/api/v1/workspace/quick-action",
    ]

    for rel_path in checked_paths:
        source = _read(rel_path)
        for route in retired_routes:
            assert route not in source


def test_editor_ai_blueprint_exposes_single_file_task_endpoint():
    source = _read("web/blueprints/editor_ai.py")

    assert (
        '@editor_ai_bp.route("/api/editor/ai/task-stream", methods=["POST"])' in source
    )
    assert (
        '@editor_ai_bp.route("/api/editor/ai/task-stream/cancel", methods=["POST"])'
        in source
    )
    assert "/api/editor/ai/task-execute" not in source
    assert "/api/editor/ai/skill-execute" not in source
    assert "stream_file_task_request(data)" in source


def test_workspace_unified_assistant_uses_model_route_before_whitebox():
    dispatcher_ts = _read("web/src/workspace/task-dispatcher.ts")
    runtime_init_ts = _read("web/src/workspace/runtime-init.ts")
    editor_ai = _read("web/blueprints/editor_ai.py")
    sessions_bp = _read("web/blueprints/sessions.py")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert (
        '@editor_ai_bp.route("/api/workspace/ai/route-intent", methods=["POST"])'
        in editor_ai
    )
    assert "_WORKSPACE_ROUTE_JUDGE_INSTRUCTION" in editor_ai
    assert '"keyword_policy": "hint_only"' in editor_ai
    assert "词汇信号只能作为提示，不是规则" in editor_ai
    assert '"route_kind": "direct_response | complex_task"' in editor_ai
    assert "第一层只允许两类 route_kind" in editor_ai
    assert "回答必须知道当前文件/附件/选区里的具体内容" in editor_ai
    assert 'requested_mode == "deepseek"' in editor_ai
    assert 'get_llm_provider(provider="deepseek", model=model_id)' in editor_ai
    assert 'response_format={"type": "json_object"}' in editor_ai

    assert "resolveWorkspaceRouteIntent(context)" in dispatcher_ts
    assert "return runWorkspaceModelRoutedTask(context);" in dispatcher_ts
    assert (
        "shouldForceFileTaskForWorkspaceContext(context, routeDecision)"
        in dispatcher_ts
    )
    assert "frontend_file_context_guard" in dispatcher_ts
    assert "streamWorkspaceChatRoute(context, routeDecision)" in dispatcher_ts
    assert "'/api/chat/stream'" in dispatcher_ts
    assert "locked_task: lockedTask" in dispatcher_ts
    assert "function persistTaskTurn" in dispatcher_ts
    assert "taskCardSnapshotFromElement(taskCard)" in dispatcher_ts
    assert "record.task_card_snapshot = snapshot" in dispatcher_ts
    assert (
        "persistTaskTurn(context.text, assistantText, taskTurnMetadataFromLoadingEl(loadingEl), payload.files || [], loadingEl)"
        in dispatcher_ts
    )
    assert (
        "persistTaskTurn(context.text, assistantText, taskTurnMetadataFromLoadingEl(loadingEl), payload.files || [], loadingEl)"
        in dispatcher_ts
    )
    assert "task_card_snapshot: payload.task_card_snapshot" in runtime_init_ts
    assert 'assistant_entry["task_card_snapshot"]' in sessions_bp
    assert "/api/workspace/ai/route-intent" in workspace_bundle
    assert "persistTaskTurn" in workspace_bundle
    assert "task_card_snapshot" in workspace_bundle


def test_workspace_route_intent_collapses_file_subtypes_to_whitebox_contract():
    editor_ai = _read("web/blueprints/editor_ai.py")
    dispatcher_ts = _read("web/src/workspace/task-dispatcher.ts")

    assert (
        'def _canonical_workspace_route_kind(route: str, route_kind: str = "") -> str:'
        in editor_ai
    )
    assert '"route_kind": route_kind,' in editor_ai
    assert '"base_task_type": (' in editor_ai
    assert (
        '"DIRECT_RESPONSE" if route_kind == "direct_response" else "COMPLEX_TASK"'
        in (editor_ai.replace("\n", " "))
    )
    assert (
        'def _canonical_workspace_task_type(route: str, task_type: str = "") -> str:'
        in editor_ai
    )
    assert 'return "FILE_TASK"' in editor_ai
    assert '"source_task_type": (' in editor_ai
    assert "raw_task_type if raw_task_type and raw_task_type != task_type else" in (
        editor_ai.replace("\n", " ")
    )
    assert (
        "task_type = _canonical_workspace_task_type(route, raw_task_type)" in editor_ai
        or "canonical_task_type = _canonical_workspace_task_type(route, task_type)"
        in editor_ai
    )
    assert (
        '"task_type": task_type,' in editor_ai
        or '"task_type": canonical_task_type,' in editor_ai
    )

    assert (
        "function canonicalWorkspaceRouteKind(route: string, routeKind?: string): string"
        in dispatcher_ts
    )
    assert "route_kind: routeKind," in dispatcher_ts
    assert (
        "base_task_type: routeKind === 'direct_response' ? 'DIRECT_RESPONSE' : 'COMPLEX_TASK'"
        in dispatcher_ts
    )
    assert (
        "function canonicalWorkspaceTaskType(route: string, taskType?: string): string"
        in dispatcher_ts
    )
    assert (
        "if (normalizedRoute === WORKSPACE_FILE_TASK_ROUTE) return 'FILE_TASK';"
        in dispatcher_ts
    )
    assert (
        "const canonicalTaskType = canonicalWorkspaceTaskType(normalizedRoute, rawTaskType);"
        in dispatcher_ts
    )
    assert (
        "rawTaskType && rawTaskType !== canonicalTaskType ? rawTaskType : ''"
        in dispatcher_ts
    )
    assert "task_type: canonicalTaskType," in dispatcher_ts
    assert "source_task_type: sourceTaskType," in dispatcher_ts
    assert "route_kind: WORKSPACE_FILE_TASK_KIND," in dispatcher_ts
    assert "task_type: 'FILE_TASK'," in dispatcher_ts


def test_workspace_file_task_steps_are_user_visible_whitebox_stages():
    task_runner_ts = _read("web/src/workspace/task-runner.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    for label in ("任务识别", "执行方案", "执行进度", "完成核验"):
        assert label in task_runner_ts
        assert label in workspace_bundle
    assert "function handleEvent_task_classified" in task_runner_ts
    assert "'task.classified': handleEvent_task_classified" in task_runner_ts
    assert "'plan.created': handleEvent_plan" in task_runner_ts
    assert "'plan.checked': handleEvent_plan_checked" in task_runner_ts
    assert "const step = taskStageStep(card, 'execute');" in task_runner_ts
    assert "const step = taskStageStep(card, 'check');" in task_runner_ts


def test_workspace_task_renderer_compacts_tool_result_details():
    task_runner_ts = _read("web/src/workspace/task-runner.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert "function toolPreviewSummary" in task_runner_ts
    assert "function summarizeParsedResult" in task_runner_ts
    assert "function looksLikeFullAnswerText" in task_runner_ts
    assert "function compactFlowSummary" in task_runner_ts
    assert "读取到 ' + parsed.length + ' 个工作区条目" in task_runner_ts
    assert (
        "payload.result_preview || payload.result_text || payload.result"
        in task_runner_ts
    )
    assert "结果已生成，完整内容见对话汇报。" in task_runner_ts
    assert "步骤已完成，结果见对话汇报。" in task_runner_ts
    assert "任务已完成，完整结果见对话汇报。" in task_runner_ts
    assert "data-full-content" in task_runner_ts
    assert "lazyDetails.querySelector('pre')" in task_runner_ts
    assert "esc(data.result_text || data.error || '')" not in task_runner_ts

    assert "data-full-content" in workspace_bundle
    assert "查看完整结果" in workspace_bundle
    assert "结果已生成，完整内容见对话汇报。" in workspace_bundle


def test_workspace_task_workbench_filters_internal_progress_messages():
    workbench_js = _read("web/src/workspace/task-workbench.ts")

    assert (
        "function userFacingTaskText(value: any, stageId?: string): string"
        in workbench_js
    )
    assert (
        "function normalizedFlowStages(rawSteps: any[], task: any): WorkbenchStep[]"
        in workbench_js
    )
    assert "const INTERNAL_PROGRESS_PATTERNS" in workbench_js
    assert "'task.classified': 'route'" in workbench_js
    for phrase in (
        "你还没有",
        "下一轮必须",
        "完成真实文件写入",
        "original_selection",
        "replace_file_selection",
        "模型路由不可用",
        "后端 SmartDispatcher 兜底",
    ):
        assert phrase in workbench_js
    for label in ("任务识别", "执行方案", "执行进度", "完成核验"):
        assert label in workbench_js


def test_workspace_task_payload_does_not_attach_current_open_file_by_default():
    dispatcher_ts = _read("web/src/workspace/task-dispatcher.ts")
    runtime_init_ts = _read("web/src/workspace/runtime-init.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert "getActiveEditorContent?: () => string;" in dispatcher_ts
    assert "function currentOpenTaskFile(): TaskFileInfo | null" in dispatcher_ts
    assert (
        "function mentionsAttachedFileContext(text: string): boolean" in dispatcher_ts
    )
    assert (
        "if (currentFile && !rawFiles.some((file) => sameTaskFile(file, currentFile))) rawFiles.unshift(currentFile);"
        not in dispatcher_ts
    )
    assert "current_file: currentFile" in dispatcher_ts
    assert "currentFile, targetFile" in dispatcher_ts
    assert "getActiveEditorContent: () =>" in runtime_init_ts
    assert "mentionsAttachedFileContext" in workspace_bundle
    assert "currentOpenTaskFile" in workspace_bundle
    assert "current_file: currentFile" in workspace_bundle


def test_workspace_docx_review_runtime_restores_structured_review_bridge():
    runtime_ts = _read("web/src/workspace/docx-review-runtime.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    required_runtime_symbols = [
        "WA.applyStructuredDocToolCall",
        "WA.applyStructuredReviewChangePayload",
        "WA.applyStructuredReviewProgressPayload",
        "WA.normalizeWorkspaceFilePath",
        "WA.focusReviewThread",
        "WA.openRevisionReviewCenter",
        "WA.onDocxCommentsChanged",
        "function _appendStructuredReviewComments",
        "function _applyStructuredReviewProgressPayload",
        "function _buildReviewProposalFromSelection",
    ]
    for symbol in required_runtime_symbols:
        assert symbol in runtime_ts

    assert "修订建议会在任务完成后显示在这里" not in runtime_ts
    assert "createReviewRevision = _createReviewRevision" in runtime_ts
    assert "reviewState.proposals = _mergeReviewProposals" in runtime_ts

    for symbol in [
        "applyStructuredDocToolCall",
        "applyStructuredReviewChangePayload",
        "applyStructuredReviewProgressPayload",
        "normalizeWorkspaceFilePath",
        "focusReviewThread",
        "openRevisionReviewCenter",
        "onDocxCommentsChanged",
    ]:
        assert symbol in workspace_bundle


def test_workspace_selection_toolbar_restores_pin_and_context_bridge():
    selection_ts = _read("web/src/ui/selection-toolbar.ts")
    text_editor_ts = _read("web/src/editors/text-editor.ts")
    ai_context_ts = _read("web/src/workspace/ai-context.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert "document.addEventListener('mouseup'" in selection_ts
    assert "document.addEventListener('selectionchange'" in selection_ts
    assert "WA.sendSelectionToAI = sendSelectionToAI" in selection_ts
    assert "WA.clearSelection = clearSelection" in selection_ts
    assert (
        "WA._showSelectionToolbarForCurrentSelection = _showSelectionToolbarForCurrentSelection"
        in selection_ts
    )
    assert "export function _resetDocxSelection(): void" in selection_ts
    assert "(window as any)._resetDocxSelection = _resetDocxSelection" in selection_ts
    assert "(window as any)._hideDocxHoverBar = _hideDocxHoverBar" in selection_ts
    assert "(window as any)._pinSelectionChip = _pinSelectionChip" in selection_ts
    assert "_selectionPayloadForToolbar()" in selection_ts
    assert "_selectionPayloadForToolbar({ allowStaleFallback: false })" in selection_ts
    assert "_clearSelectionInjectionIfIdle()" in selection_ts
    assert "_isAIInputTarget(el)" in selection_ts
    assert "input.addEventListener('mousedown'" in selection_ts
    assert (
        "this._ta.addEventListener('select', this._handleSelectionChange)"
        in text_editor_ts
    )
    assert (
        "this._ta.addEventListener('keyup', this._handleSelectionChange)"
        in text_editor_ts
    )
    assert "WA._showSelectionToolbarForCurrentSelection" in text_editor_ts
    assert "已注入选中文本" in workspace_bundle
    assert "取消文本注入" in workspace_bundle
    assert "window._resetDocxSelection = _resetDocxSelection" in workspace_bundle
    assert "window._hideDocxHoverBar = _hideDocxHoverBar" in workspace_bundle
    assert 'data-selection-injected="true"' in selection_ts
    assert 'data-selection-injected="true"' in workspace_bundle
    assert (
        "const update = (window as any).WA && (window as any).WA._updateContextBar;"
        in ai_context_ts
    )


def test_workspace_unified_shell_restores_save_contract():
    save_ts = _read("web/src/workspace/save.ts")
    bundle_entry = _read("web/src/bundles/workspace.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert "import '../workspace/save';" in bundle_entry
    assert "(window as any).WA.saveFile = saveFile" in save_ts
    assert "(window as any).WA.saveAs = saveAs" in save_ts
    assert "(window as any).WA.scheduleAutoSave = scheduleAutoSave" in save_ts
    assert "(window as any).WA.autoSave = autoSave" in save_ts
    assert "/api/v1/workspace/auto_save" in save_ts
    assert "/api/v1/workspace/raw/" in save_ts
    assert "showSaveFilePicker" in save_ts
    assert "window.WA.saveFile = saveFile" in workspace_bundle
    assert "window.WA.saveAs = saveAs" in workspace_bundle


def test_workspace_unified_shell_hides_retained_legacy_skill_surfaces():
    index_template = _read("web/templates/index.html")

    assert 'id="wa-skill-bar"' not in index_template
    assert 'id="wa-skill-exec-panel"' not in index_template
    assert "window.openSkillsPanel();" in index_template
    assert (
        "document.body.classList.contains('koto-unified-workspace')" in index_template
    )
    assert 'id="macroToast" hidden aria-hidden="true"' in index_template


def test_workspace_task_target_inference_does_not_use_bare_attachment_name():
    dispatcher_js = _read("web/src/workspace/task-dispatcher.ts")

    assert (
        "function inferAttachedWriteTargetFile(text: string, files: TaskFileInfo[]): TaskFileInfo | null"
        in dispatcher_js
    )
    assert "score: targetMentionScore(lowered, f)" in dispatcher_js
    assert "inferCompareTargetFromRoleHint(text, files)" in dispatcher_js
    assert "inferCompareAnnotatedTargetFile(text, files)" in dispatcher_js
    assert "explicitNameMatches" not in dispatcher_js
    assert "lowered.includes(baseName)" not in dispatcher_js


def test_workspace_task_payload_enables_model_primary_intent_router():
    dispatcher_js = _read("web/src/workspace/task-dispatcher.ts")

    assert "enable_ai_intent_adjudicator" in dispatcher_js
    assert "model_primary_intent" in dispatcher_js


def test_workspace_model_controls_default_to_deepseek_primary_path():
    state_ts = _read("web/src/workspace/state.ts")
    model_settings_ts = _read("web/src/workspace/model-settings.ts")
    controls_html = _read("web/templates/_workspace_model_controls.html")
    task_runner_ts = _read("web/src/workspace/task-runner.ts")
    task_workbench_ts = _read("web/src/workspace/task-workbench.ts")
    workbench_js = _read("web/src/workspace/task-workbench.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert (
        "lockedModel: _normalizeWorkspaceModelMode(localStorage.getItem('wa_locked_model') || '', 'deepseek')"
        in state_ts
    )
    assert "_cloudProvider: 'deepseek'" in state_ts
    assert "state._cloudProvider || 'deepseek'" in model_settings_ts
    assert (
        "return _modelDisplayName('deepseek-v4-pro', 'DeepSeek V4 Pro');"
        in model_settings_ts
    )
    assert 'id="wa-model-mode-gemini-btn"' not in controls_html
    assert (
        'id="wa-model-mode-deepseek-btn" type="button" class="wa-model-mode-toggle-btn active"'
        in controls_html
    )
    assert "mode:'deepseek'" in controls_html
    assert "Gemini" not in controls_html
    assert "Gemini" not in task_runner_ts
    assert "Gemini" not in task_workbench_ts
    assert "Gemini" not in workbench_js
    assert 'data-model-mode="gemini"' not in controls_html
    assert (
        'localStorage.getItem("wa_locked_model") || "", "deepseek"' in workspace_bundle
    )


def test_workspace_quick_actions_do_not_keyword_route_freeform_tasks():
    dispatcher_js = _read("web/src/workspace/task-dispatcher.ts")
    quick_actions_js = _read("web/src/workspace/quick-actions.ts")
    assistant_js = _read("web/src/workspace/ai-review.ts")

    assert "registerQuickActionKeyword" not in dispatcher_js
    assert "registerTaskActionKeyword" not in assistant_js
    assert "quickActionKeywords" not in dispatcher_js
    assert "source.includes(entry.keyword)" not in dispatcher_js
    assert (
        "keywords.some((keyword) => source.includes(keyword))" not in quick_actions_js
    )
    assert "ACTION_KEYWORDS" not in assistant_js
    assert "return quickActionHandlers.has(source) ? source : '';" in dispatcher_js


def test_workspace_task_payload_extracts_explicit_text_write_target():
    dispatcher_ts = _read("web/src/workspace/task-dispatcher.ts")
    dispatcher_js = _read("web/src/workspace/task-dispatcher.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    for source in (dispatcher_ts, dispatcher_js):
        assert "explicitWriteTargetPathFromText" in source
        assert (
            "const explicitTextTargetPath = explicitWriteTargetPathFromText(text);"
            in source
        )
        assert (
            "files.push(targetFile);" in source
            or "rawFiles.push(targetFile);" in source
        )
        assert "target_path: inferredTargetPath," in source
        assert "baseNameFromPath(explicitTextTargetPath)" in source
        assert "fileTypeFromPath(explicitTextTargetPath)" in source
        assert "[^\\s\"'<>|:：,，。；;、!?！？()[\\]【】]" in source
        assert "explicitOutputBeforePattern.test(before)" in source
        assert "sourceBeforePattern.test(before)" in source

    assert "explicitWriteTargetPathFromText" in workspace_bundle
    assert "rawFiles.push(targetFile)" in workspace_bundle


def test_workspace_task_renderer_surfaces_supervisor_status():
    renderer_js = _read("web/src/workspace/task-runner.ts")
    workspace_template = _read("web/templates/index.html")
    index_template = _read("web/templates/index.html")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert (
        "function taskRecognitionText(data: Record<string, any>): string" in renderer_js
    )
    assert (
        "function planCheckSummaryText(data: Record<string, any>, passed: boolean): string"
        in renderer_js
    )
    assert "'supervisor.status': handleEvent_supervisor_status" in renderer_js
    assert "'supervisor.status:' + stage" in renderer_js
    assert "监管检查已更新。" in renderer_js
    assert (
        "'read_request_escalated_to_write': '只读任务被错误升级为写入'" in renderer_js
    )
    assert "计划检查通过：本轮只读，不会修改文件。" in renderer_js
    assert "taskRecognitionText(data)" in renderer_js
    assert "if (passed) return;" not in renderer_js

    for source in (renderer_js, workspace_template, index_template, workspace_bundle):
        assert "按计划 0/0" not in source
        assert "准备识别任务" in source


def test_workspace_assistant_does_not_open_files_with_os_native_apps():
    assistant_js = "\n".join(
        [
            _read("web/src/workspace/fs-tree.ts"),
            _read("web/src/workspace/ai-context.ts"),
            _read("web/src/ui/embedded-mode.ts"),
        ]
    )
    workspace_bp = _read("web/blueprints/workspace_assistant.py")

    assert ("/api/v1/workspace/open-" + "native") not in assistant_js
    assert ("/api/v1/workspace/open-" + "native") not in workspace_bp
    assert ("os." + "startfile") not in workspace_bp
    assert ("xdg-" + "open") not in workspace_bp


def test_global_file_search_native_open_routes_stay_removed():
    app_main_ts = _read("web/src/app/main.ts")
    app_settings_ts = _read("web/src/app/settings.ts")
    app_bundle = _read("web/static/js/build/app-bundle.js")
    file_editor_bp = _read("web/blueprints/file_editor.py")
    file_scanner = _read("web/file_scanner.py")
    app_py = _read("web/app.py")

    assert ("/api/scan/" + "open") not in app_main_ts
    assert ("/api/scan/" + "open") not in app_settings_ts
    assert ("/api/scan/" + "open") not in app_bundle
    assert ("/api/scan/" + "open") not in file_editor_bp
    assert "def scan_open" not in file_editor_bp
    assert "def open_file(cls, path" not in file_scanner
    assert "FileScanner.open_file" not in app_py


def test_file_network_native_open_route_stays_removed():
    misc_api_bp = _read("web/blueprints/misc_api.py")
    file_network = _read("web/processed_file_network.py")
    file_network_html = _read("web/templates/file_network.html")

    assert ("/api/file-network/" + "open") not in misc_api_bp
    assert "def file_network_open" not in misc_api_bp
    assert "def open_file(self, file_id" not in file_network
    assert ("/api/file-network/" + "open") not in file_network_html
    assert "copyFilePath" in file_network_html


def test_productivity_plugin_does_not_expose_native_open_tool():
    plugin = _read("app/core/agent/plugins/productivity_plugin.py")
    tool_router = _read("app/core/routing/tool_router.py")

    assert "open_file_or_folder" not in plugin
    assert "open_file_or_folder" not in tool_router
    assert ("os." + "startfile") not in plugin
    assert ("xdg-" + "open") not in plugin


def test_productivity_plugin_does_not_expose_file_or_email_side_effect_tools():
    plugin = _read("app/core/agent/plugins/productivity_plugin.py")
    tool_router = _read("app/core/routing/tool_router.py")

    retired_tools = {
        "send_email",
        "move_file",
        "delete_file",
        "zip_files",
        "unzip_file",
    }
    for tool_name in retired_tools:
        assert tool_name not in plugin
        assert tool_name not in tool_router


def test_standalone_email_client_routes_stay_removed():
    misc_api_bp = _read("web/blueprints/misc_api.py")

    assert not (_repo_root() / "web/email_manager.py").exists()
    assert "/api/email/" not in misc_api_bp
    assert "get_email_manager" not in misc_api_bp


def test_alerting_plugin_stays_local_log_only():
    alerting_plugin = _read("app/core/agent/plugins/alerting_plugin.py")
    alert_manager = _read("app/core/monitoring/alert_manager.py")

    for removed in (
        "configure_email_alerts",
        "add_webhook_alert",
        "AlertChannel.EMAIL",
        "AlertChannel.WEBHOOK",
        "smtplib",
        "requests.post",
        "_send_email",
        "_send_webhook",
    ):
        assert removed not in alerting_plugin
        assert removed not in alert_manager


def test_network_plugin_stays_read_only():
    network_plugin = _read("app/core/agent/plugins/network_plugin.py")

    assert "http_post" not in network_plugin
    assert "requests.post" not in network_plugin


def test_system_fix_script_generation_stays_removed():
    factory = _read("app/core/agent/factory.py")
    agent_routes = _read("app/api/agent_routes.py")

    assert not (
        _repo_root() / "app/core/agent/plugins/script_generation_plugin.py"
    ).exists()
    assert not (_repo_root() / "app/core/scripts/script_generator.py").exists()
    assert "ScriptGenerationPlugin" not in factory
    assert "/generate-script" not in agent_routes
    for dangerous_text in (
        "Stop-Process",
        "Remove-Item",
        "systemctl restart",
        "generate_fix_script",
    ):
        assert dangerous_text not in factory
        assert dangerous_text not in agent_routes


def test_local_executor_no_longer_performs_system_side_effects():
    local_executor = _read("web/local_executor.py")

    assert "APP_ALIASES" not in local_executor
    assert "SYSTEM_KEYWORDS" not in local_executor
    assert "def extract_app_name" not in local_executor
    assert "def find_app_in_start_menu" not in local_executor
    assert "def find_app_smart" not in local_executor
    assert "def open_file_or_directory" not in local_executor
    assert "def send_keystroke" not in local_executor
    assert ("os." + "startfile") not in local_executor
    assert "shutdown /" not in local_executor
    assert "snippingtool" not in local_executor
    assert "webbrowser.open" not in local_executor
    assert "keyboard.hotkey" not in local_executor


def test_agent_tool_router_does_not_offer_system_side_effect_tools():
    plugin = _read("app/core/agent/plugins/productivity_plugin.py")
    sandbox_plugin = _read("app/core/agent/plugins/sandbox_plugin.py")
    system_tools_plugin = _read("app/core/agent/plugins/system_tools_plugin.py")
    tool_router = _read("app/core/routing/tool_router.py")

    assert "shell_command" not in plugin
    assert "take_screenshot" not in plugin
    assert "run_shell_command" not in sandbox_plugin
    assert "pip_install" not in system_tools_plugin
    assert "open_application" not in tool_router
    assert "take_screenshot" not in tool_router
    assert "shell_command" not in tool_router


def test_routing_layer_does_not_fast_track_app_control_as_system():
    rule_router = _read("app/core/routing/rule_router.py")
    smart_dispatcher = _read("app/core/routing/smart_dispatcher.py")
    ai_router = _read("app/core/routing/ai_router.py")

    assert "_sys_starters" not in rule_router
    assert "_sys_action_starters" not in smart_dispatcher
    assert "_fb_sys_starters" not in smart_dispatcher
    assert "Action-Direct" not in smart_dispatcher
    assert "Fallback-ActionVerb" not in smart_dispatcher
    assert "打开微信/Chrome/某应用" not in ai_router


def test_workspace_file_tree_drag_to_ai_stays_readonly_attachment_flow():
    assistant_js = _read("web/src/workspace/fs-tree.ts")
    fs_tree = _read("web/src/workspace/fs-tree.ts")
    embedded = _read("web/src/ui/embedded-mode.ts")
    ai_context = _read("web/src/workspace/ai-context.ts")
    workspace_template = _read("web/templates/index.html")
    index_template = _read("web/templates/index.html")
    workspace_css = _read("web/static/css/workspace.css")

    assert 'draggable="true"' in assistant_js
    assert "application/wa-file-path" in assistant_js
    assert "_getAIAttachmentDropPayload" in embedded
    assert "wa.attachFilesToTask = _attachFilesToTask" in ai_context
    assert (
        "await _attachFilesToTask([payload.filePath], { source, focusInput: !_isAiSessionListVisible() })"
        in embedded
    )
    assert "'ai_panel_drop'" in embedded
    assert "function _fileDragAttrs()" in fs_tree
    assert "function _fileOpenHitDragAttrs()" in fs_tree
    assert "function _installBrowserPointerDragFallback()" in fs_tree
    assert "wa._browserFileRowMouseDown =" in fs_tree
    assert "wa._browserFileRowClick =" in fs_tree
    assert "wa._browserFileRowPointerDown =" in fs_tree
    assert 'onpointerdown="WA._browserFileRowPointerDown(event,this)"' in fs_tree
    assert (
        "onpointerdown=\"WA._browserFileRowPointerDown(event,this.closest(\\'.wa-file-item\\'))\""
        in fs_tree
    )
    assert (
        "document.addEventListener('pointermove', (event) => _onBrowserPointerMove(event));"
        in fs_tree
    )
    assert "document.addEventListener('pointerup', (event) => {" in fs_tree
    assert "WA._browserFileDragStart(event,this)" in fs_tree
    assert (
        "WA._browserFileDragStart(event,this.closest(\\'.wa-file-item\\'))" in fs_tree
    )
    assert "wa._browserFileDragStart = _browserFileDragStart" in fs_tree
    assert "async function _attachBrowserFileToAI" in fs_tree
    assert "async function _sendBrowserFileToAI" in fs_tree
    assert "wa.sendBrowserFileToAI = _sendBrowserFileToAI" in fs_tree
    assert 'class="wa-file-send-ai"' in fs_tree
    assert "file_tree_inline_action" in fs_tree
    assert "_attachBrowserFileToAI(path, 'file_tree_dragend_drop')" in fs_tree
    assert "_attachBrowserFileToAI(drag.path, 'file_tree_pointer_drop')" in fs_tree
    assert "_installBrowserPointerDragFallback();" in fs_tree
    assert "` ${_fileDragAttrs()}`" in fs_tree
    assert "`${_fileDragAttrs()} `" in fs_tree
    assert (
        "const sessionListComposer = document.getElementById('wa-ai-session-list-composer')"
        in embedded
    )
    assert "sessionListComposer.classList.add('wa-session-list-drag-over')" in embedded
    assert "focusInput: !_isAiSessionListVisible()" in embedded
    assert "_focusVisibleAIComposer();" in embedded
    assert "document.getElementById('wa-ai-file-chips')" in ai_context
    assert "document.getElementById('wa-ai-file-chip-list')" in ai_context
    assert 'id="wa-ai-file-chips"' in workspace_template
    assert 'id="wa-ai-file-chips"' in index_template
    assert ".wa-session-list-drag-over" in workspace_css
    assert "#wa-ai-file-chips" in workspace_css
    assert ".wa-file-actions .wa-file-send-ai" in workspace_css


def test_workspace_file_row_handlers_keep_drag_fallback_owner():
    fs_tree = _read("web/src/workspace/fs-tree.ts")
    fs_actions = _read("web/src/workspace/fs-actions.ts")

    assert (
        "wa._browserFileRowMouseDown = (event: MouseEvent, el: HTMLElement): void =>"
        in fs_tree
    )
    assert (
        "wa._browserFileRowClick = (event: MouseEvent, el: HTMLElement): void =>"
        in fs_tree
    )
    assert (
        "if (typeof wa._browserFileRowMouseDown !== 'function') wa._browserFileRowMouseDown = _browserFileRowMouseDown;"
        in fs_actions
    )
    assert (
        "if (typeof wa._browserFileRowClick !== 'function') wa._browserFileRowClick = _browserFileRowClick;"
        in fs_actions
    )
    action_lines = {line.strip() for line in fs_actions.splitlines()}
    assert "wa._browserFileRowMouseDown = _browserFileRowMouseDown;" not in action_lines
    assert "wa._browserFileRowClick = _browserFileRowClick;" not in action_lines


def test_workspace_task_run_finished_closes_run_stage_step():
    task_runner_ts = _read("web/src/workspace/task-runner.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert (
        'const runStep = card.querySelector(\'[data-role="steps"] .wa-task-step[data-step-id="run"]\')'
        in task_runner_ts
    )
    assert "markStepFailed(runStep)" in task_runner_ts
    assert "markStepDone(runStep)" in task_runner_ts
    assert 'data-step-id="run"' in workspace_bundle
    assert "markStepFailed(runStep)" in workspace_bundle
    assert "markStepDone(runStep)" in workspace_bundle


def test_workspace_file_browser_folder_actions_are_available():
    assistant_js = _read("web/src/workspace/fs-tree.ts")
    workspace_bp = _read("web/blueprints/workspace_assistant.py")

    assert "_dropOntoFolder" in assistant_js
    assert ("fs_" + "copy") in assistant_js
    assert ("upload-" + "to-folder") in assistant_js
    assert "def fs_create_file" in workspace_bp
    assert "def fs_create_folder" in workspace_bp
    assert "def fs_rename" in workspace_bp
    assert "def fs_copy" in workspace_bp
    assert "def fs_delete" in workspace_bp
    assert "def upload_to_folder" in workspace_bp
    assert "open-native" not in workspace_bp


def test_workspace_search_merges_fresh_workspace_list_files():
    fs_tree = _read("web/src/workspace/fs-tree.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert "async function _searchLiveWorkspaceFiles" in fs_tree
    assert "fetch('/api/v1/workspace/list_files', { cache: 'no-store' })" in fs_tree
    assert "_flattenWorkspaceListFiles(data.files || []" in fs_tree
    assert "function _mergeSearchResults" in fs_tree
    assert "function _searchCachedBrowserEntries" in fs_tree
    assert (
        "if (cachedResults.length) _renderSearchResults(cachedResults, q);" in fs_tree
    )
    assert (
        "_renderSearchResults(_mergeSearchResults(cachedResults, indexedResults, 60), q);"
        in fs_tree
    )
    assert "_searchLiveWorkspaceFiles(q, cat, 60).then" in fs_tree
    assert "function _searchCachedBrowserEntries" in workspace_bundle
    assert "function _mergeSearchResults" in workspace_bundle


def test_workspace_file_browser_bootstraps_from_bundle_runtime():
    fs_tree = _read("web/src/workspace/fs-tree.ts")
    state_ts = _read("web/src/workspace/state.ts")
    embedded = _read("web/src/ui/embedded-mode.ts")
    app_main_ts = _read("web/src/app/main.ts")
    app_settings_ts = _read("web/src/app/settings.ts")
    app_bundle = _read("web/static/js/build/app-bundle.js")
    index_template = _read("web/templates/index.html")
    workspace_css = _read("web/static/css/workspace.css")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert "export async function loadFileBrowser()" in fs_tree
    assert "wa.loadFileBrowser = loadFileBrowser" in fs_tree
    assert "(window as any).loadFileBrowser = loadFileBrowser" in fs_tree
    assert "function _autoLoadStandaloneFileBrowser()" in fs_tree
    assert "_bindLocalFilePickers();" in fs_tree
    assert "wa._openLocalFile = () => _openFilePicker" in fs_tree
    assert "wa._openLocalFolder = () =>" in fs_tree

    assert "export async function loadRecentFiles()" in state_ts
    assert "wa.refreshRecent = () => loadRecentFiles();" in state_ts
    assert "wa.toggleRecentSection = () =>" in state_ts
    assert (
        "if (typeof wa.loadFileBrowser === 'function') await wa.loadFileBrowser();"
        in state_ts
    )

    assert "typeof (window as any).WA.loadFileBrowser === 'function'" in embedded
    assert "typeof loadFileBrowser === 'function'" not in embedded
    assert "typeof loadFileBrowser === 'function'" not in app_main_ts
    assert 'id="wa-left"' in index_template
    assert 'id="wa-files-list"' in index_template
    assert 'id="wa-recent-list"' in index_template
    assert 'id="wa-left-latency-slot"' in index_template
    assert 'id="wa-local-file-input"' in index_template
    assert 'id="wa-local-folder-input"' in index_template
    assert 'for="wa-file-input-left"' in index_template
    assert 'id="wa-ctx-menu"' in index_template
    assert (
        index_template.index('id="wa-left"')
        < index_template.index('id="wa-canvas"')
        < index_template.index('id="wa-ai"')
    )
    assert ".wa-local-folder-picker" in workspace_css
    assert "#wa-recent-list .wa-file-item.wa-recent-file" in workspace_css
    assert ".wa-left-latency-slot .latency-detail.open" in workspace_css
    assert (
        "const leftSlot = document.getElementById('wa-left-latency-slot')"
        in app_settings_ts
    )
    assert "leftSlot.appendChild(detail)" in app_settings_ts
    assert "wa-left-latency-slot" in app_bundle
    assert "function _recentFileDragAttrs()" in state_ts
    assert "function _recentFileOpenHitDragAttrs()" in state_ts
    assert 'class="wa-file-item file wa-recent-file"' in state_ts
    assert "_mergeRecentFiles(localRecent, apiRecent)" in state_ts
    assert "if (localRecent.length)" in state_ts
    assert "_loadLocalRecentFiles()" in state_ts
    assert (
        "WA._browserFileDragStart(event,this.closest(\\'.wa-file-item\\'))" in state_ts
    )

    assert "function loadFileBrowser()" in workspace_bundle
    assert (
        "wa$4.loadFileBrowser = loadFileBrowser" in workspace_bundle
        or ".loadFileBrowser = loadFileBrowser" in workspace_bundle
    )
    assert "refreshRecent = () => loadRecentFiles" in workspace_bundle
    assert "window.loadRecentFiles = loadRecentFiles" in workspace_bundle
    assert "wa-recent-file" in workspace_bundle


def test_workspace_bundle_restores_legacy_interaction_entrypoints():
    ai_review = _read("web/src/workspace/ai-review.ts")
    toolbar = _read("web/src/ui/docx-pptx-toolbar.ts")
    pdf_viewer = _read("web/src/editors/pdf-viewer.ts")
    fs_tree = _read("web/src/workspace/fs-tree.ts")
    state_ts = _read("web/src/workspace/state.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")
    workspace_template = _read("web/templates/index.html")
    index_template = _read("web/templates/index.html")

    for expected in (
        "WA.handleInputKeydown = handleInputKeydown",
        "WA.closeReviewCenter = closeReviewCenter",
        "WA.setReviewMode = setReviewMode",
    ):
        assert expected in ai_review

    for expected in (
        "WA.pptxFmt = pptxFmt",
        "WA.pptxAlign = pptxAlign",
        "WA.pptxFontSize = pptxFontSize",
        "WA.pptxFontName = pptxFontName",
        "WA.pptxFontColor = pptxFontColor",
        "WA.pptxColorPicker = pptxColorPicker",
        "WA._pptxPickColor = _pptxPickColor",
        "WA.pptxHoverAI = pptxHoverAI",
        "WA.pptxZoom = pptxZoom",
        "WA.pptxNav = pptxNav",
        "WA.pptxInsertShape = pptxInsertShape",
        "WA.pptxSetShapeSize = pptxSetShapeSize",
        "WA.pptxSetShapePos = pptxSetShapePos",
        "WA.pptxSetShapeRot = pptxSetShapeRot",
        "WA.pptxInsertImageClick = pptxInsertImageClick",
        "WA.pptxInsertImageFile = pptxInsertImageFile",
        "WA.docxZoom = docxZoom",
    ):
        assert expected in toolbar
    assert "document.getElementById('wa-pptx-img-input')" in toolbar
    assert "PPT 图片插入正在迁移" not in toolbar
    for template in (workspace_template, index_template):
        assert 'id="wa-pptx-img-input"' in template
        assert "WA.pptxInsertImageClick()" in template
        assert "WA.pptxInsertImageFile(this)" in template
        assert "WA.pptxSwitchTab(this,'format')" in template
        for shape_type in ("rect", "roundRect", "ellipse", "line", "rightArrow"):
            assert f"WA.pptxInsertShape('{shape_type}')" in template
        for marker in (
            'id="wa-pptx-shapeW"',
            'id="wa-pptx-shapeH"',
            'id="wa-pptx-shapeX"',
            'id="wa-pptx-shapeY"',
            'id="wa-pptx-shapeRot"',
            "WA.pptxSetShapeSize('w',this.value)",
            "WA.pptxSetShapePos('x',this.value)",
            "WA.pptxSetShapeRot(this.value)",
        ):
            assert marker in template

    for expected in (
        "WA.pdfZoom =",
        "WA.pdfSearchOpen =",
        "WA.pdfSearchInput =",
        "WA.pdfAnnotOpen =",
        "WA.pdfAnnotMode =",
        "WA.pdfPageMgrOpen =",
        "WA.pdfPageMgrApply =",
        "WA.pdfConvert =",
        "WA.pdfWatermarkClose =",
        "_pdfDocumentForEditor(ed)",
    ):
        assert expected in pdf_viewer

    for expected in (
        "wa._openLocalFile =",
        "wa.openSystemFileList =",
        "wa.cycleBrowserSort =",
    ):
        assert expected in fs_tree

    for expected in (
        "wa.clearSearch =",
        "wa.setSearchFilter =",
        "wa.toggleSection =",
        "wa.toggleRecentSection =",
        "wa.clearTempWorkspace =",
    ):
        assert expected in state_ts

    for expected in (
        "handleInputKeydown",
        "pptxColorPicker",
        "pptxInsertImageClick",
        "pptxInsertShape",
        "pptxSetShapeSize",
        "pdfPageMgrOpen",
        "pdfConvert",
        "openSystemFileList",
    ):
        assert expected in workspace_bundle


def test_main_workspace_template_keeps_restored_editor_controls_in_sync():
    workspace_template = _read("web/templates/index.html")
    index_template = _read("web/templates/index.html")

    workspace_wa_calls = set(re.findall(r"WA\.([A-Za-z_$][\w$]*)", workspace_template))
    index_wa_calls = set(re.findall(r"WA\.([A-Za-z_$][\w$]*)", index_template))
    assert sorted(workspace_wa_calls - index_wa_calls) == []

    workspace_ids = set(re.findall(r'id="([^"]+)"', workspace_template))
    index_ids = set(re.findall(r'id="([^"]+)"', index_template))
    assert sorted(workspace_ids - index_ids) == []

    for marker in (
        'id="wa-docx-find-bar"',
        "WA.docxHoverAI('polish')",
        'id="wa-docx-ctx"',
        'id="wa-pptx-find-bar"',
        'id="wa-pptx-undo"',
        "WA.pptxDupSlide()",
        "WA.pptxClearFormat()",
        "WA.pptxToggleBullet()",
        "WA.pptxOpacity(this.value)",
        "WA.pptxSetBgImage(this)",
        'id="wa-pptx-hoverbar"',
        'id="wa-pptx-cp"',
        'id="wa-pdf-editor"',
        'id="wa-pdf-sidebar"',
        'id="wa-pdf-search-bar"',
        "WA.pdfPageMgrOpen()",
        "WA.pdfConvert('docx')",
        "WA.pdfRemoveWatermark()",
        'id="wa-pdf-pagemgr"',
        'id="wa-pdf-watermark-overlay"',
        'id="wa-autosave-toggle"',
        'id="wa-open-folder-overlay"',
    ):
        assert marker in index_template

    assert "旧版技能执行入口已下线" not in index_template
    assert "入口已下线" not in index_template
    assert 'id="navSkillsBtn"' in index_template
    assert 'id="skillsPanel"' in index_template
    assert 'aria-label="Skills 库"' in index_template


def test_workspace_assistant_unsafe_requests_include_csrf_token():
    assistant_js = "\n".join(
        [
            _read("web/src/workspace/infrastructure.ts"),
            _read("web/src/workspace/fs-tree.ts"),
            _read("web/src/workspace/ai-review.ts"),
        ]
    )
    workspace_template = _read("web/templates/index.html")
    index_template = _read("web/templates/index.html")

    assert '<meta name="csrf-token"' in workspace_template
    assert "csrf_token() if csrf_token is defined else ''" in workspace_template
    assert '<meta name="csrf-token"' in index_template
    assert "csrf_token() if csrf_token is defined else ''" in index_template
    assert (
        "export async function _csrfFetch(url: string, options: CsrfOptions = {}): Promise<Response>"
        in assistant_js
    )
    assert "document.querySelector('meta[name=\"csrf-token\"]')" in assistant_js
    assert "X-CSRFToken" in assistant_js
    assert "async function _refreshCsrfToken(): Promise<string>" in assistant_js
    assert "fetch('/api/csrf-token'" in assistant_js
    assert "response.status === 400 && _needsCsrf(fetchOptions.method)" in assistant_js
    assert (
        "fetchOptions.headers = _headersWithCsrf(fetchOptions.headers)" in assistant_js
    )
    assert (
        "const res = await _csrfFetch('/api/v1/workspace/open_file_by_path'"
        in assistant_js
    )
    assert "const res = await _csrfFetch('/api/v1/workspace/open_file'" in assistant_js

    direct_unsafe_fetches = []
    for method_marker in (
        "method: 'POST'",
        "method: 'PATCH'",
        "method: 'DELETE'",
        'method: "POST"',
        'method: "PATCH"',
        'method: "DELETE"',
    ):
        start = 0
        while True:
            idx = assistant_js.find(method_marker, start)
            if idx < 0:
                break
            prefix = assistant_js[max(0, idx - 160) : idx]
            if "fetch(" in prefix and "_csrfFetch(" not in prefix:
                line = assistant_js.count("\n", 0, idx) + 1
                direct_unsafe_fetches.append((line, method_marker))
            start = idx + len(method_marker)

    assert direct_unsafe_fetches == []


def test_workspace_task_stream_requests_include_csrf_token():
    task_js = _read("web/src/workspace/task-runner.ts")

    assert (
        "async function csrfFetch(url: string, options: RequestInit = {}): Promise<Response>"
        in task_js
    )
    assert "document.querySelector('meta[name=\"csrf-token\"]')" in task_js
    assert "X-CSRFToken" in task_js
    assert "function csrfToken(): string" in task_js
    assert "headersWithCsrf(fetchOptions.headers as any)" in task_js
    assert (
        "async function describeHttpError(resp: Response): Promise<string>" in task_js
    )
    assert "const resp = await csrfFetch('/api/editor/ai/task-stream'" in task_js
    assert "card._abortFileTaskStream = () =>" in task_js
    assert "fetch('/api/editor/ai/task-stream'" not in task_js

    direct_unsafe_fetches = []
    for method_marker in (
        "method: 'POST'",
        "method: 'PATCH'",
        "method: 'DELETE'",
        'method: "POST"',
        'method: "PATCH"',
        'method: "DELETE"',
    ):
        start = 0
        while True:
            idx = task_js.find(method_marker, start)
            if idx < 0:
                break
            prefix = task_js[max(0, idx - 160) : idx]
            if "fetch(" in prefix and "csrfFetch(" not in prefix:
                line = task_js.count("\n", 0, idx) + 1
                direct_unsafe_fetches.append((line, method_marker))
            start = idx + len(method_marker)

    assert direct_unsafe_fetches == []


def test_http_wiring_exposes_csrf_refresh_endpoint():
    app_http = _read("web/app_http.py")

    assert '@app.route("/api/csrf-token", methods=["GET"])' in app_http
    assert "generate_csrf()" in app_http
    assert "CSRF_FAILED" in app_http


def test_workspace_task_card_renderer_guards_non_dom_cards():
    task_js = _read("web/src/workspace/task-runner.ts")

    assert (
        "function isTaskCardElement(value: unknown): value is TaskCardElement"
        in task_js
    )
    assert (
        "typeof (value as TaskCardElement).querySelectorAll === 'function'" in task_js
    )
    assert "if (!isTaskCardElement(card)) return;" in task_js
    assert (
        "function ensureTaskUiState(card: TaskCardElement): FileTaskUiState" in task_js
    )
    assert (
        "function taskTerminalResult(card: TaskCardElement, fallbackSummary?: string): TerminalResult"
        in task_js
    )
    assert (
        "if (!isTaskCardElement(card) || !payload || typeof payload !== 'object') return;"
        in task_js
    )


def test_workspace_task_progress_has_live_plan_linked_feedback():
    task_js = _read("web/src/workspace/task-runner.ts")
    workspace_css = _read("web/static/css/workspace.css")
    workspace_template = _read("web/templates/index.html")
    index_template = _read("web/templates/index.html")

    assert 'id="wa-task-live-progress"' in workspace_template
    assert 'id="wa-task-live-progress"' in index_template
    assert "function syncTaskLiveProgress(card: TaskCardElement): void" in task_js
    assert (
        "function taskPlanProgress(card: TaskCardElement): { total: number; completed: number; running: boolean }"
        in task_js
    )
    assert "ensureTaskUiState(card).plannedStepCount = steps.length;" in task_js
    assert "state.progressExplicit = true;" in task_js
    assert (
        "basis = explicit ? 'explicit' : (plan.total ? 'planned' : 'estimated')"
        in task_js
    )
    assert "valueText = '步骤 ' + plan.completed + '/' + plan.total;" in task_js
    assert "syncTaskLiveProgress(card);" in task_js
    assert ".wa-task-live-progress" in workspace_css
    assert '.wa-task-progress[data-basis="planned"]' in workspace_css
    assert '.wa-task-progress[data-basis="estimated"]' in workspace_css


def test_workspace_stepwise_resume_payload_does_not_increment_explicit_step_index():
    dispatcher_js = _read("web/src/workspace/task-dispatcher.ts")

    assert (
        "const existingWorkflowCheckpoint = options.workflow_checkpoint"
        in dispatcher_js
    )
    assert "delete options.batch_control;" in dispatcher_js
    assert "options.workflow_checkpoint = Object.assign" in dispatcher_js
    assert (
        "const hasExplicitStepIndex = Object.prototype.hasOwnProperty.call(checkpointSeed, 'step_index')"
        in dispatcher_js
    )
    assert (
        "const resumeStepIndex = hasExplicitStepIndex ? currentStep : currentStep + 1;"
        in dispatcher_js
    )
    assert "step_index: resumeStepIndex" in dispatcher_js
    assert "next_step_index: resumeStepIndex" in dispatcher_js


def test_workspace_stepwise_resume_payload_prefers_workflow_checkpoint():
    dispatcher_js = _read("web/src/workspace/task-dispatcher.ts")
    task_js = _read("web/src/workspace/task-runner.ts")

    assert (
        "compact.options = { workflow_checkpoint: workflowCheckpoint }" in dispatcher_js
    )
    assert "workflowCheckpointFallback" not in dispatcher_js
    assert (
        "compactPayload.options.workflow_checkpoint || compactPayload.options.batch_control"
        not in dispatcher_js
    )
    assert (
        "function workflowCheckpointFromOptions(options?: Record<string, any>): Record<string, any> | null"
        in task_js
    )
    assert (
        "source.workflow_checkpoint && typeof source.workflow_checkpoint === 'object'"
        in task_js
    )
    assert (
        "return source.batch_control && typeof source.batch_control === 'object'"
        not in task_js
    )


def test_doc_annotate_resume_payload_uses_workflow_checkpoint():
    bridge_py = _read("app/core/agent/file_task_doc_annotate_bridge.py")
    workflow_py = _read("app/core/agent/file_task_workflow_state.py")

    assert 'options.pop("batch_control", None)' in bridge_py
    assert 'options["workflow_checkpoint"] = {' in bridge_py
    assert 'options["batch_control"] = {' not in bridge_py
    assert "workflow_checkpoint_from_options(resume_options)" in workflow_py
    assert 'resume_options.get("batch_control")' not in workflow_py
    assert '"batch_index"' in workflow_py


def test_workspace_browser_select_mode_rerenders_and_toggles_rows():
    workspace_js = _read("web/src/workspace/fs-tree.ts")
    fs_actions = _read("web/src/workspace/fs-actions.ts")
    workspace_css = _read("web/static/css/workspace.css")

    assert (
        "wa._browserFileRowMouseDown = (event: MouseEvent, el: HTMLElement): void =>"
        in workspace_js
    )
    assert (
        "wa._browserFileRowClick = (event: MouseEvent, el: HTMLElement): void =>"
        in workspace_js
    )
    assert "(event.target as HTMLElement).closest('.wa-file-check')" in workspace_js
    assert (
        'onmousedown="WA._browserFileRowMouseDown(event,this)" onclick="WA._browserFileRowClick(event,this)"'
        in workspace_js
    )
    assert 'onclick="WA._browserFileRowClick(event,this)"' in workspace_js
    assert "if (!state._searchActive || `${state.searchQuery}" in workspace_js
    assert "(window as any).WA._renderBrowserTree();" in fs_actions
    assert "flex: 1 1 0;" in workspace_css
    assert "contain: paint;" in workspace_css
