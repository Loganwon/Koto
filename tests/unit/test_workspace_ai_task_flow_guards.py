import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _repo_root() -> Path:
    return ROOT


def _read(rel_path: str) -> str:
    path = ROOT / rel_path
    return path.read_text(encoding="utf-8")


def _assert_contains_all(source: str, fragments: tuple[str, ...]) -> None:
    for fragment in fragments:
        assert fragment in source


def _assert_excludes_all(source: str, fragments: tuple[str, ...]) -> None:
    for fragment in fragments:
        assert fragment not in source


# Section: core task-flow entrypoints and workspace surfaces.


def test_workspace_file_assistant_uses_single_task_flow_stream_by_default():
    assistant_js = _read("web/src/workspace/ai-review.ts")
    dispatcher_js = _read("web/src/workspace/task-dispatcher.ts")
    task_js = _read("web/src/workspace/task-runner.ts")
    final_report_js = _read("web/src/workspace/task-final-report.ts")
    quick_actions_js = _read("web/src/workspace/quick-actions.ts")

    assert "publishWorkspaceApi({ createTaskDispatcher })" in dispatcher_js
    assert "taskDispatcher.dispatchMessage({" in assistant_js
    assert "taskDispatcher.dispatchQuickAction(action, {" in assistant_js
    assert "publishWorkspaceApi({" in task_js
    assert "streamTaskFlow," in task_js
    assert "csrfFetch('/api/editor/ai/task-stream'" in task_js
    assert "fetch('/api/editor/ai/task-stream'" not in assistant_js
    assert "legacyEditorFallback: true" not in quick_actions_js
    assert "legacyEditorFallback" not in quick_actions_js


def test_workspace_task_memory_uses_unified_session_pipeline_only():
    assert not (_repo_root() / "app/core/agent/workspace_session.py").exists()
    sources = [
        _read("web/blueprints/sessions.py"),
        _read("web/session_manager.py"),
        _read("web/src/workspace/task-dispatcher.ts"),
        _read("web/src/workspace/runtime-init.ts"),
    ]
    assert all("WorkspaceSessionMemory" not in source for source in sources)
    assert "def _start_task_memory_reflection(" in sources[0]
    assert "turn.get(\"skip_model_context\") is True" in sources[1]


def test_workspace_selection_context_reaches_ai_chat_and_tasks():
    xlsx_editor = _read("web/src/editors/xlsx-editor.ts")
    sheets_main = _read("web/univer-editor/sheets-main.js")
    selection_toolbar = _read("web/src/ui/selection-toolbar.ts")
    ai_review = _read("web/src/workspace/ai-review.ts")
    dispatcher = _read("web/src/workspace/task-dispatcher.ts")
    quick_actions = _read("web/src/workspace/quick-actions.ts")
    stream_orchestrator = _read("web/services/chat_stream/orchestrator.py")

    assert "getSelectionPayload()" in sheets_main
    assert "sheetName" in sheets_main
    assert "rangeA1" in sheets_main
    assert "数据格式: TSV" in sheets_main
    assert "getSelectionPayload(): any" in xlsx_editor
    assert "sourceType: 'xlsx'" in xlsx_editor

    assert "selectionContext?: Record<string, any> | null;" in dispatcher
    assert "selectionContext: explicitSelection || null" in ai_review
    assert "selectionContext: payload.selectionContext || null" in quick_actions
    assert "state.activeEditor.getSelectionPayload" in selection_toolbar

    assert "function buildWorkspaceChatFileContext" in dispatcher
    assert "file_context: buildWorkspaceChatFileContext(context)" in dispatcher
    assert "selection_meta" in dispatcher
    assert "def _workspace_file_context_block(file_context):" in stream_orchestrator
    assert "文件助手上下文" in stream_orchestrator


def test_workspace_static_js_only_task_renderer_calls_file_task_stream():
    static_js_dir = _repo_root() / "web" / "static" / "js"
    offenders = []
    for path in static_js_dir.glob("*.js"):
        source = path.read_text(encoding="utf-8")
        if "/api/editor/ai/task-stream" in source and path.name != "workspace-ai-task.js":
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

    assert "pdfAIAnnotate," in pdf_viewer_ts
    assert "publishWorkspaceApi({" in pdf_viewer_ts
    assert "typeof ed.aiAnnotate === 'function'" in pdf_viewer_ts
    assert "AI 标注功能正在迁移" not in pdf_viewer_ts
    assert "_applyAiAnnotationSuggestions" in pdf_viewer_ts
    assert "_locateAiAnnotationQuote" in pdf_viewer_ts
    assert "pdf_ai_annotate: true" in pdf_viewer_ts
    assert "pdfAIAnnotate" in workspace_bundle


def test_terminal_file_task_results_remain_in_followup_model_context():
    dispatcher = _read("web/src/workspace/task-dispatcher.ts")

    finalizer_start = dispatcher.index("function finalizeWhiteboxTaskTurn(")
    finalizer_end = dispatcher.index("function buildWhiteboxTaskPayload(", finalizer_start)
    finalizer = dispatcher[finalizer_start:finalizer_end]

    assert "taskTurnMetadataFromLoadingEl(loadingEl), {" in finalizer
    assert "skip_model_context: !!skipModelContext" in finalizer
    assert finalizer.index("taskTurnMetadataFromLoadingEl(loadingEl), {") < finalizer.index(
        "skip_model_context: !!skipModelContext"
    )


# Section: task workbench, session history, and persistence.


def test_workspace_task_workbench_is_split_and_mounted():
    workbench_js = _read("web/src/workspace/task-workbench.ts")
    task_js = _read("web/src/workspace/task-runner.ts")
    final_report_js = _read("web/src/workspace/task-final-report.ts")
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
    assert "publishWorkspaceApi({" in workbench_js
    assert "refreshCurrentTaskFlow," in workbench_js
    assert "notifyTaskFlowChanged," in workbench_js
    assert "openTaskWorkbenchForCurrentRun," in workbench_js
    assert "function focusTaskCard(taskId: any, runId: any): boolean" in workbench_js
    assert "fetchJson('/api/tasks?limit=120&order_by=created_at')" in workbench_js
    assert "publishWorkspaceApi({" in task_js
    assert "resumePersistedFileTask," in task_js
    assert "renderArtifactResult" in _read("web/src/workspace/results.ts")
    assert "data-task-open-workbench" not in task_js
    assert "scheduleTaskLiveProgressCollapse" in task_js
    assert "wa-msg ai wa-task-run is-compact" in task_js
    assert "artifactResult && artifactResult.task_id" in task_js
    assert "function liveStepsForTask(task: any): WorkbenchStep[]" in workbench_js
    assert "taskCardForTask(task && task.task_id, runIdForTask(task))" in workbench_js
    assert "function latestLiveTaskCard()" in workbench_js
    assert "function renderFocusedLiveTask(state: WorkbenchState): boolean" in workbench_js
    assert "dataset.taskFollowupPayload || dataset.taskPendingResumePayload" in workbench_js
    assert "function metadataStepsForTask(task: any): WorkbenchStep[]" in workbench_js
    assert "data.model_mode || payload && payload.model_mode" in workbench_js
    assert "模型调用 ·" in workbench_js
    assert "文件上下文 · 已载入" in workbench_js
    assert "结果 · 已完成" in workbench_js
    assert "chipLower.includes('whitebox')" in workbench_js
    assert "const doneTool = chip.match(/^完成\\s+(.+)$/)" in workbench_js
    assert "title === '任务状态' && rows.length === 1" in workbench_js
    assert "function activeSessionTaskId()" not in workbench_js
    assert "const nextTaskId = explicitTaskId || (shouldShow ? activeSessionTaskId() : '')" not in workbench_js
    assert 'title="查看历史任务"' not in workbench_js
    assert 'title="查看历史任务"' not in workspace_template
    assert 'title="查看历史任务"' not in index_template
    assert 'data-task-workbench-filter="all"' not in workspace_template
    assert 'data-task-workbench-filter="all"' not in index_template
    assert "focusedOnly: true" in workbench_js
    assert "state.activeTaskId && !state.loading" in workbench_js
    assert "等待文件任务" in workbench_js
    assert "当请求需要读取、修改或生成文件时，这里会直接展开需求分析、执行计划、进度和结果检查。" in workbench_js
    assert "TASK_REPORT_STAGE_DEFS.map((def)" in workbench_js
    assert "FLOW_STAGE_DEFS" not in workbench_js
    assert "<span>模型调用</span>" not in workbench_js
    assert "function renderStageOverview(steps: WorkbenchStep[]): string" in workbench_js
    assert "function normalizedWorkbenchSteps(steps: any[], task: any): WorkbenchStep[]" in workbench_js
    assert "wa-task-workbench-stage-grid" in workbench_js
    assert "function renderWorkbenchStep(" not in workbench_js
    assert "visibleSteps.map((step, index) => renderWorkbenchStep(step, index)).join('')" not in workbench_js
    assert "任务步骤" not in workbench_js
    assert "详细过程" not in workbench_js
    assert "workspaceApi.notifyTaskFlowChanged(taskId)" in task_js
    assert "function notifyTaskWorkbenchForCard(card: TaskCardElement, options?: { delayed?: boolean }): void" in task_js
    assert "if (options && options.delayed)" in task_js
    assert "seedRouteModelContext(card, payload)" in task_js
    assert "模型调用" in task_js
    assert "from './task-final-report';" in task_js
    assert "export function compactFlowSummary(value: string, fallback = '详细内容见任务结果。'): string" in final_report_js
    assert "function supervisorAuditHtml(data: Record<string, any>, options: { compact?: boolean } = {})" in task_js
    assert "const showDetails = !options.compact || status === 'blocked';" in task_js
    assert "supervisorAuditHtml(data, { compact: true })" in task_js
    assert "function shouldShowSupervisorAuditInResult(data: Record<string, any>): boolean" in task_js
    assert "shouldShowSupervisorAuditInResult(data)" in task_js
    assert "function supervisorAuditStatusLabel(status: unknown): string" in task_js
    assert "需关注" in task_js
    assert "supervisor_audit" in task_js
    assert "audit.execution_constraints" in task_js
    assert "audit.user_actions" in task_js
    assert "执行约束：" in task_js
    assert "需要补充：" in task_js
    assert "actions.map((item) => `要求：" not in task_js
    assert "完整结果见任务结果" not in task_js
    assert "详细内容见任务结果" in task_js
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
    assert workspace_template.index('id="wa-artifact-panel"') < workspace_template.index('id="wa-ai-messages"') < workspace_template.index('id="wa-task-live-progress"')
    assert index_template.index('id="wa-artifact-panel"') < index_template.index('id="wa-ai-messages"') < index_template.index('id="wa-task-live-progress"')
    assert 'id="wa-task-column"' not in workspace_template
    assert 'id="wa-task-column"' not in index_template
    assert "revealTaskColumn(panel)" not in _read("web/src/workspace/results.ts")
    assert ".wa-task-workbench" in workspace_css
    assert ".wa-task-workbench-body" in workspace_css
    assert ".wa-task-workbench-artifacts" in workspace_css
    assert ".wa-task-workbench-stage-grid" in workspace_css
    assert "grid-template-columns: repeat(auto-fit, minmax(136px, 1fr));" in workspace_css
    assert ".wa-task-workbench-stage-top" in workspace_css
    assert ".wa-task-workbench-section-title" in workspace_css
    assert ".wa-task-workbench-step-headline" in workspace_css
    assert ".wa-inline-task-workbench" in workspace_css
    assert "#wa-ai-messages > .wa-inline-task-workbench" in workspace_css
    assert '.wa-task-run.is-compact [data-role="ui-progress"]' in workspace_css
    assert '#wa-ai-messages .wa-task-run.is-compact:not(.streaming) .wa-task-header' in workspace_css
    assert '可追问或查看步骤。' not in task_js
    assert "查看流程" not in task_js
    assert "查看流程" not in workspace_bundle
    assert "openTaskWorkbenchForCurrentRun" in workbench_js
    assert "openTaskWorkbenchForCurrentRun" in workspace_bundle
    assert "查看产物" in workbench_js
    assert "['产物', Array.isArray(result.artifacts) ? result.artifacts.length : 0]" in workbench_js
    assert "['引用', Array.isArray(result.sources) ? result.sources.length : 0]" in workbench_js
    assert "['过程记录', Array.isArray(result.logs) ? result.logs.length : 0]" in workbench_js
    assert "['来源', Array.isArray(result.sources)" not in workbench_js
    assert "['日志', Array.isArray(result.logs)" not in workbench_js
    assert workbench_js.index("stats,") < workbench_js.index("body,")
    assert "whitebox-task" not in _read("web/src/workspace/task-dispatcher.ts")
    assert "白盒任务渲染器未加载" not in _read("web/src/workspace/task-dispatcher.ts")
    assert "task-flow" in _read("web/src/workspace/task-dispatcher.ts")
    assert "revealTaskWorkbenchForCard(card, { scroll: false });" in _read("web/src/workspace/task-runner.ts")
    assert ".wa-task-run.is-workbench-focused" in workspace_css


def test_legacy_file_task_stream_does_not_write_old_thinking_panel():
    file_task_stream = _read("web/file_task_stream.py")
    editor_ai = _read("web/blueprints/editor_ai.py")

    assert "yield_thinking=None" in file_task_stream
    assert 'yield_thinking(f"启动 FileTaskRuntime 处理' not in file_task_stream
    assert 'yield_thinking(msg[:200] if msg else f"阶段: {event_type}"' not in file_task_stream
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

    assert "const WA_HISTORY_SCHEMA_VERSION = 2;" in conversation_ts
    assert "function migrateLegacyTurn(raw: any): Record<string, any>" in conversation_ts
    assert "turn.schema_version = WA_HISTORY_SCHEMA_VERSION;" in conversation_ts
    assert "turn.task_kind = 'file_task';" in conversation_ts
    assert "loadSessionHistory?: (sessionId: string) => Promise<any[]>;" in conversation_ts
    assert "const loadSessionHistory = typeof options.loadSessionHistory === 'function'" in conversation_ts
    assert "await loadSessionHistory(sessionId)" in conversation_ts
    assert "renderHistory(turns)" in conversation_ts
    assert "loadSessionHistory" in workspace_bundle


def test_workspace_ai_panel_defaults_to_chat_and_keeps_session_list_navigation():
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

    assert 'id="wa-ai-session-list-view" class="wa-ai-session-list-view" aria-label="AI 对话与任务历史" hidden' in workspace_template
    assert 'id="wa-ai-session-list-view" class="wa-ai-session-list-view" aria-label="AI 对话与任务历史" hidden' in index_template
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
    welcome_copy = "在输入框直接说出任务，或附加文件作为上下文。支持文档分析、PPT生成、代码编写、数据处理等。"
    assert welcome_copy in workspace_template
    assert welcome_copy in index_template
    assert 'class="wa-ai-session-new-btn"' in workspace_template
    assert 'class="wa-ai-session-new-btn"' in index_template
    assert "新建对话" in workspace_template
    assert "新建对话" in index_template
    assert "打开任务步骤" not in workspace_template
    assert "打开任务步骤" not in index_template
    assert "任务流程" in _read("web/src/workspace/task-workbench.ts")
    assert 'id="wa-ai-chat-view" class="wa-ai-chat-view">' in workspace_template
    assert 'id="wa-ai-chat-view" class="wa-ai-chat-view">' in index_template
    assert 'id="wa-ai-session-back"' in workspace_template
    assert 'id="wa-ai-session-back"' in index_template
    assert workspace_template.index('id="wa-ai-session-list-view"') < workspace_template.index('id="wa-ai-chat-view"') < workspace_template.index('id="wa-ai-messages"')
    assert index_template.index('id="wa-ai-session-list-view"') < index_template.index('id="wa-ai-chat-view"') < index_template.index('id="wa-ai-messages"')
    assert "import '../workspace/conversation-list';" in workspace_bundle_entry
    assert "fetch('/api/sessions?preview=1'" in conversation_sessions_ts
    assert "publishWorkspaceApi({" in conversation_list_ts
    assert "openAiSession," in conversation_list_ts
    assert "showAiSessionList," in conversation_list_ts
    assert "newAiSession," in conversation_list_ts
    assert "sendSessionListComposer," in conversation_list_ts
    assert "handleSessionListComposerKeydown," in conversation_list_ts
    assert "deleteAiSession," in conversation_list_ts
    assert "_syncAiSessionSelection: syncAiSessionSelection," in conversation_list_ts
    assert "const _SESSION_PREVIEW_LIMIT = 5;" in conversation_list_ts
    assert "let _sessionsExpanded = false;" in conversation_list_ts
    assert "_sessions.slice(0, _SESSION_PREVIEW_LIMIT)" in conversation_list_ts
    assert 'data-ai-session-expand' in conversation_list_ts
    assert "展开 ${hiddenCount} 条历史" in conversation_list_ts
    assert "收起历史" in conversation_list_ts
    assert "export function sendSessionListComposer(): Promise<any>" in conversation_list_ts
    assert "function _openLatestTaskFlowForSession(sessionId: string): void" in conversation_list_ts
    assert "function _syncHistoricalTaskLiveProgress(session?: AiSessionPreview): void" in conversation_list_ts
    assert "workspaceApi.openTaskWorkbenchForCurrentRun({" in conversation_list_ts
    assert "查看执行过程" in conversation_list_ts
    assert "查看下方步骤" not in conversation_list_ts
    assert "在输入框输入即可开始新对话" in conversation_list_ts
    assert "在底部输入" not in conversation_list_ts
    assert "latest_task_id" in conversation_list_ts
    assert "latest_task_title?: string;" in conversation_sessions_ts
    assert "latest_task_title: String(record.latest_task_title || '').trim()" in conversation_sessions_ts
    assert "const taskTitle = String(session.latest_task_title || '').trim();" in conversation_list_ts
    assert "const title = taskTitle || sessionTitle(session, _activeAiSessionId);" in conversation_list_ts
    assert "data-latest-task-title" in conversation_list_ts
    assert "if (taskTitle) return taskTitle;" in conversation_sessions_ts
    assert "const sessionId = await createAiSessionRecord();" in conversation_list_ts
    assert "await openAiSession(sessionId, { force: true });" in conversation_list_ts
    assert "workspaceApi.sendMessage();" in conversation_list_ts
    assert "function _closeSkillLibrary" in conversation_list_ts
    assert "if (!options.silent) _closeSkillLibrary();" in conversation_list_ts
    assert "task_count?: number;" in conversation_sessions_ts
    assert "latest_task_status?: string;" in conversation_sessions_ts
    assert "wa-ai-session-task-badge" in conversation_list_ts
    assert "data-latest-task-status" in conversation_list_ts
    assert "data-ai-session-delete" in conversation_list_ts
    assert "export async function deleteAiSession" in conversation_list_ts
    assert "`/api/sessions/${encodeURIComponent(normalized)}`" in conversation_sessions_ts
    assert "method: 'DELETE'" in conversation_sessions_ts
    assert "_focusComposer();" in conversation_list_ts
    assert "latest_task_id: String(record.latest_task_id || '').trim()" in conversation_sessions_ts
    assert "taskCount ? `${taskCount} 个任务` : ''" in conversation_list_ts
    assert "export function closeSkillLibrary()" in model_settings_ts
    assert "publishWorkspaceApi({" in model_settings_ts
    assert "closeSkillLibrary," in model_settings_ts
    assert "syncSelection(_hostSessionId)" in runtime_init_ts
    assert 'request.args.get("preview")' in sessions_bp
    assert "def _session_preview(session_filename: str, history: list[object]) -> dict:" in sessions_bp
    assert "def _is_workspace_assistant_session" not in sessions_bp
    assert "if not _is_workspace_assistant_session(session)" not in sessions_bp
    assert "session_files = _get_session_manager().list_sessions()" in sessions_bp
    assert '"task_count": len(task_entries)' in sessions_bp
    assert '"has_task_flow": bool(task_entries)' in sessions_bp
    assert '"latest_task_title": latest_task_title' in sessions_bp
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


def test_workspace_main_view_inerts_legacy_chat_entrypoint():
    embedded_mode_ts = _read("web/src/ui/embedded-mode.ts")
    index_template = _read("web/templates/index.html")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert 'id="messageInput"' in index_template
    assert 'id="wa-user-input"' in index_template
    assert 'id="workspaceView" class="wa-embedded" style="display:none" aria-hidden="true" inert' in index_template
    assert "function setMainViewActive(view: HTMLElement | null, active: boolean): void" in embedded_mode_ts
    assert "view.setAttribute('aria-hidden', active ? 'false' : 'true');" in embedded_mode_ts
    assert "view.removeAttribute('inert');" in embedded_mode_ts
    assert "view.setAttribute('inert', '');" in embedded_mode_ts
    assert "(view as any).inert = !active;" in embedded_mode_ts
    assert "setMainViewActive(chatView, false);" in embedded_mode_ts
    assert "setMainViewActive(wsView, true);" in embedded_mode_ts
    assert "setMainViewActive(wsView, false);" in embedded_mode_ts
    assert "setMainViewActive(chatView, true);" in embedded_mode_ts
    assert "aria-hidden" in workspace_bundle
    assert "inert" in workspace_bundle
    assert "koto.inWorkspace" in workspace_bundle


def test_unified_session_api_includes_workspace_and_editor_sessions(monkeypatch):
    from flask import Flask
    from web.blueprints import sessions as sessions_mod

    class FakeSessionManager:
        def list_sessions(self):
            return ["chat_main.json", "workspace_file_task.json", "editor_doc_review.json"]

        def load_full(self, filename):
            return [
                {"role": "user", "parts": [filename.replace(".json", "")], "timestamp": "2026-06-17T10:00:00"},
                {"role": "model", "parts": ["done"], "task": "file_task", "status": "done", "timestamp": "2026-06-17T10:01:00"},
            ]

    manager = FakeSessionManager()
    monkeypatch.setattr(sessions_mod, "get_session_manager", lambda: manager)

    app = Flask(__name__)
    app.register_blueprint(sessions_mod.sessions_bp)
    client = app.test_client()

    list_payload = client.get("/api/sessions").get_json()
    assert list_payload["sessions"] == ["chat_main", "workspace_file_task", "editor_doc_review"]

    preview_payload = client.get("/api/sessions?preview=1").get_json()
    assert [item["id"] for item in preview_payload["sessions"]] == [
        "chat_main",
        "workspace_file_task",
        "editor_doc_review",
    ]
    assert all(item["has_task_flow"] for item in preview_payload["sessions"])


def test_unified_session_preview_filters_mock_browser_task_sessions(monkeypatch):
    from flask import Flask
    from web.blueprints import sessions as sessions_mod

    class FakeSessionManager:
        def list_sessions(self):
            return ["real_task.json", "browser_mock.json"]

        def load_full(self, filename):
            if filename == "browser_mock.json":
                return [
                    {"role": "user", "parts": ["总结当前文件"], "timestamp": "2026-06-17T10:00:00"},
                    {
                        "role": "model",
                        "parts": ["模拟监管任务已完成"],
                        "task": "file_task",
                        "run_id": "browser_supervisor",
                        "task_card_snapshot": {"html": '<div class="wa-task-run" data-task-run-id="browser_supervisor">mocked file task</div>'},
                        "timestamp": "2026-06-17T10:01:00",
                    },
                ]
            return [
                {"role": "user", "parts": ["处理真实文件"], "timestamp": "2026-06-17T10:00:00"},
                {"role": "model", "parts": ["已完成"], "task": "file_task", "status": "done", "timestamp": "2026-06-17T10:01:00"},
            ]

    monkeypatch.setattr(sessions_mod, "get_session_manager", lambda: FakeSessionManager())

    app = Flask(__name__)
    app.register_blueprint(sessions_mod.sessions_bp)
    client = app.test_client()

    preview_payload = client.get("/api/sessions?preview=1").get_json()
    assert [item["id"] for item in preview_payload["sessions"]] == ["real_task"]


def test_workspace_turn_persistence_upserts_by_turn_id(monkeypatch):
    from flask import Flask
    from web.blueprints import sessions as sessions_mod

    class FakeSessionManager:
        def __init__(self):
            self.history = []

        def list_sessions(self):
            return ["demo.json"]

        def load_full(self, filename):
            return list(self.history)

        def save(self, filename, history):
            self.history = list(history)

    manager = FakeSessionManager()
    title_calls = []
    memory_reflections = []

    class FakeBrain:
        def chat(self, history, prompt, model=None, auto_model=True):
            title_calls.append({"prompt": prompt, "model": model, "auto_model": auto_model})
            return {"response": "合同风险审查"}

    monkeypatch.setattr(sessions_mod, "get_session_manager", lambda: manager)
    monkeypatch.setattr(sessions_mod, "_get_brain", lambda: FakeBrain())
    monkeypatch.setattr(sessions_mod, "_get_model_map", lambda: {"CHAT": "title-model"})
    monkeypatch.setattr(sessions_mod, "_start_task_memory_reflection", lambda **kwargs: memory_reflections.append(kwargs))

    app = Flask(__name__)
    app.register_blueprint(sessions_mod.sessions_bp)
    client = app.test_client()

    first = client.post(
        "/api/sessions/demo/workspace-turn",
        json={
            "user": "总结当前文件",
            "assistant": "文件任务已启动，正在执行…",
            "metadata": {"turn_id": "task_1", "task_kind": "file_task", "status": "streaming", "partial": True},
        },
    )
    second = client.post(
        "/api/sessions/demo/workspace-turn",
        json={
            "user": "总结当前文件",
            "assistant": "最终总结完成",
            "metadata": {
                "turn_id": "task_1",
                "task_kind": "file_task",
                "status": "done",
                "partial": False,
                "task_context": {"selection": "合同第 4 条 风险条款", "rangeA1": "Sheet1!A1:B2"},
            },
            "task_card_snapshot": {"html": '<div class="wa-task-run">done</div>'},
        },
    )

    assert first.status_code == 200
    assert "task_title" not in first.get_json()
    assert second.status_code == 200
    second_json = second.get_json()
    assert second_json["task_title"] == "合同风险审查"
    assert "合同第 4 条" in second_json["memory_summary"]
    assert len(manager.history) == 2
    assert manager.history[0]["role"] == "user"
    assert manager.history[0]["schema_version"] == 2
    assert manager.history[1]["parts"] == ["最终总结完成"]
    assert manager.history[1]["schema_version"] == 2
    assert manager.history[1]["turn_id"] == "task_1"
    assert manager.history[1]["task_title"] == "合同风险审查"
    assert manager.history[1]["skip_model_context"] is not True
    assert manager.history[1]["task_context"]["selection"] == "合同第 4 条 风险条款"
    assert "合同第 4 条" in manager.history[1]["memory_summary"]
    assert len(title_calls) == 1
    assert title_calls[-1]["model"] == "title-model"
    assert title_calls[-1]["auto_model"] is False
    assert "不要编号" in title_calls[-1]["prompt"]
    assert len(memory_reflections) == 1
    assert "合同风险审查" in memory_reflections[0]["assistant_text"]
    assert manager.history[1]["task_card_snapshot"]["html"] == '<div class="wa-task-run">done</div>'

    preview_payload = client.get("/api/sessions?preview=1").get_json()
    assert preview_payload["sessions"][0]["title"] == "合同风险审查"
    assert preview_payload["sessions"][0]["latest_task_title"] == "合同风险审查"

    history_payload = client.get("/api/sessions/demo").get_json()
    assert history_payload["schema_version"] == 2
    assert history_payload["history"][1]["schema_version"] == 2


# Section: model routing and file-task contracts.


def test_workspace_find_replace_tools_are_split_from_assistant_shell():
    assistant_js = _read("web/src/workspace/ai-review.ts")
    find_replace_js = _read("web/src/workspace/find-replace.ts")
    asset_scripts = _read("web/templates/_workspace_asset_scripts.html")
    workspace_bundle_entry = _read("web/src/bundles/workspace.ts")

    assert "publishWorkspaceApi({ installWorkspaceFindReplace })" in find_replace_js
    assert "docxFindInput," in find_replace_js
    assert "pptxFindInput," in find_replace_js
    assert "function _installFindReplaceActionDelegation(): void" in find_replace_js
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

    assert '@editor_ai_bp.route("/api/editor/ai/task-stream", methods=["POST"])' in source
    assert '@editor_ai_bp.route("/api/editor/ai/task-stream/cancel", methods=["POST"])' in source
    assert "/api/editor/ai/task-execute" not in source
    assert "/api/editor/ai/skill-execute" not in source
    assert "stream_file_task_request(data)" in source


def test_workspace_unified_assistant_uses_model_route_before_whitebox():
    dispatcher_ts = _read("web/src/workspace/task-dispatcher.ts")
    task_runner_ts = _read("web/src/workspace/task-runner.ts")
    task_interaction_summary_ts = _read("web/src/workspace/task-interaction-summary.ts")
    runtime_init_ts = _read("web/src/workspace/runtime-init.ts")
    editor_ai = _read("web/blueprints/editor_ai.py")
    sessions_bp = _read("web/blueprints/sessions.py")
    workspace_css = _read("web/static/css/workspace.css")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert '@editor_ai_bp.route("/api/workspace/ai/route-intent", methods=["POST"])' in editor_ai
    assert "_WORKSPACE_ROUTE_JUDGE_INSTRUCTION" in editor_ai
    assert '"keyword_policy": "hint_only"' in editor_ai
    assert "词汇信号只能作为提示，不是规则" in editor_ai
    assert '"route_kind": "direct_response | complex_task"' in editor_ai
    assert "第一层只允许两类 route_kind" in editor_ai
    assert "回答必须知道当前文件/附件/选区里的具体内容" in editor_ai
    assert 'normalize_model_mode(data.get("model_mode"), default="deepseek")' in editor_ai
    assert "get_provider_for_model_mode(requested_mode)" in editor_ai
    assert "get_llm_provider(provider=route_provider, model=model_id)" in editor_ai
    assert 'response_format={"type": "json_object"}' in editor_ai

    assert "resolveWorkspaceRouteIntent(context)" in dispatcher_ts
    assert "return runWorkspaceModelRoutedTask(context);" in dispatcher_ts
    assert "shouldForceFileTaskForWorkspaceContext(context, routeDecision)" in dispatcher_ts
    assert "frontend_file_context_guard" in dispatcher_ts
    assert re.search(
        r"streamWorkspaceChatRoute\(context,\s*routeDecision!?\)", dispatcher_ts
    )
    assert "'/api/chat/stream'" in dispatcher_ts
    assert "locked_task: lockedTask" in dispatcher_ts
    assert "function persistTaskTurn" in dispatcher_ts
    assert "taskCardSnapshotFromElement(taskCard)" in dispatcher_ts
    assert "record.task_card_snapshot = snapshot" in dispatcher_ts
    assert "persistTaskTurn(context.text, '文件任务已启动，正在执行…'" in dispatcher_ts
    assert "startTerminalPersistWatch();" in dispatcher_ts
    assert "persistTaskTurn(context.text, '文件任务正在执行…'" not in dispatcher_ts
    assert "turn_id: taskTurnId" in dispatcher_ts
    assert "partial: true" in dispatcher_ts
    assert "partial: false" in dispatcher_ts
    assert "skip_model_context: true" in dispatcher_ts
    assert "skip_model_context: false" in dispatcher_ts
    assert "_workspaceTurnPersistQueue" in runtime_init_ts
    assert "WORKSPACE_TURN_RETRY_KEY = 'wa_workspace_turn_retry_queue_v1'" in runtime_init_ts
    assert "function _queueWorkspaceTurnRetry" in runtime_init_ts
    assert "showToast('对话保存失败，已暂存并自动重试'" in runtime_init_ts
    assert "export async function retryWorkspaceConversationPersistence" in runtime_init_ts
    assert "retryWorkspaceConversationPersistence," in runtime_init_ts
    assert "publishWorkspaceApi({" in runtime_init_ts
    assert "async function _ensureWorkspacePersistenceSession()" in runtime_init_ts
    assert "_hostSessionId = sessionId;" in runtime_init_ts
    assert "ensureSessionId: _ensureWorkspacePersistenceSession" in runtime_init_ts
    assert "ensureSessionId?: () => Promise<string>;" in dispatcher_ts
    assert "await options.ensureSessionId()" in dispatcher_ts
    assert "_sendWorkspaceConversationTurn(sessionId, requestPayload)" in runtime_init_ts
    assert "function _applyPersistedTaskMetadata" in runtime_init_ts
    assert "card.dataset.taskTitle = taskTitle" in runtime_init_ts
    assert "const memorySummary = String(data && (data.memory_summary || data.model_context_text) || '').trim();" in runtime_init_ts
    assert "card.dataset.taskMemorySummary = memorySummary" in runtime_init_ts
    assert "workspaceApi.syncTaskInteractionSummary(card)" in runtime_init_ts
    assert "task_card_snapshot: payload.task_card_snapshot" in runtime_init_ts
    assert "from './task-interaction-summary';" in task_runner_ts
    assert "export function taskContextSummaryText(context: any): string" in task_interaction_summary_ts
    assert "export function renderTaskUnderstandingCard(card:" in task_interaction_summary_ts
    assert "export function renderTaskMemoryCard(card:" in task_interaction_summary_ts
    assert "function syncTaskInteractionSummary(card: TaskCardElement): void" in task_runner_ts
    assert "const semanticTitle = String(card.dataset.taskTitle || '').trim();" in task_runner_ts
    assert "publishWorkspaceApi({" in task_runner_ts
    assert "syncTaskInteractionSummary," in task_runner_ts
    assert "const artifactsHtml = taskArtifactsSummaryHtml(card);" in task_runner_ts
    assert "+ artifactsHtml\n      + auditHtml\n      + taskResultActionsHtml(card)\n      + taskResultContextDetailsHtml(card)\n      + (artifactsHtml ? '' : renderTaskResultSummaryBar(card, result))\n      + '<div class=\"wa-task-final-report\" data-role=\"final-report\" tabindex=\"-1\"><div class=\"wa-task-final-report-content\">'" in task_runner_ts
    assert "function taskResultContextDetailsHtml(card: TaskCardElement): string" in task_runner_ts
    assert ".wa-task-interaction-card" in workspace_css
    assert ".wa-task-memory-card" in workspace_css
    assert "_SESSION_HISTORY_SCHEMA_VERSION = 2" in sessions_bp
    assert "def _normalize_history_entry(entry: object) -> object:" in sessions_bp
    assert '"schema_version": _SESSION_HISTORY_SCHEMA_VERSION' in sessions_bp
    assert 'assistant_entry["task_card_snapshot"]' in sessions_bp
    assert '"skip_model_context"' in sessions_bp
    assert '"task_context"' in sessions_bp
    assert "def _build_task_memory_summary(" in sessions_bp
    assert "def _start_task_memory_reflection(" in sessions_bp
    assert 'response_payload["memory_summary"] = memory_summary' in sessions_bp
    assert '"partial"' in sessions_bp
    assert "_is_mock_workspace_history" in sessions_bp
    assert "turn.get(\"skip_model_context\") is True" in _read("web/session_manager.py")
    assert "os.replace(tmp_path, path)" in _read("web/session_manager.py")
    assert "/api/workspace/ai/route-intent" in workspace_bundle
    assert "persistTaskTurn" in workspace_bundle
    assert "task_card_snapshot" in workspace_bundle


def test_workspace_route_intent_collapses_file_subtypes_to_whitebox_contract():
    editor_ai = _read("web/blueprints/editor_ai.py")
    dispatcher_ts = _read("web/src/workspace/task-dispatcher.ts")

    assert "def _canonical_workspace_route_kind(route: str, route_kind: str = \"\") -> str:" in editor_ai
    assert '"route_kind": route_kind,' in editor_ai
    assert '"base_task_type": "DIRECT_RESPONSE" if route_kind == "direct_response" else "COMPLEX_TASK"' in editor_ai
    assert "def _canonical_workspace_task_type(route: str, task_type: str = \"\") -> str:" in editor_ai
    assert "return \"FILE_TASK\"" in editor_ai
    assert '"source_task_type": raw_task_type if raw_task_type and raw_task_type != task_type else ""' in editor_ai
    assert "canonical_task_type = _canonical_workspace_task_type(route, task_type)" in editor_ai
    assert '"task_type": canonical_task_type,' in editor_ai

    assert "function canonicalWorkspaceRouteKind(route: string, routeKind?: string): string" in dispatcher_ts
    assert "route_kind: routeKind," in dispatcher_ts
    assert "base_task_type: routeKind === 'direct_response' ? 'DIRECT_RESPONSE' : 'COMPLEX_TASK'" in dispatcher_ts
    assert "function canonicalWorkspaceTaskType(route: string, taskType?: string): string" in dispatcher_ts
    assert "if (normalizedRoute === WORKSPACE_FILE_TASK_ROUTE) return 'FILE_TASK';" in dispatcher_ts
    assert "const canonicalTaskType = canonicalWorkspaceTaskType(normalizedRoute, rawTaskType);" in dispatcher_ts
    assert "rawTaskType && rawTaskType !== canonicalTaskType ? rawTaskType : ''" in dispatcher_ts
    assert "task_type: canonicalTaskType," in dispatcher_ts
    assert "source_task_type: sourceTaskType," in dispatcher_ts
    assert "route_kind: WORKSPACE_FILE_TASK_KIND," in dispatcher_ts
    assert "task_type: 'FILE_TASK'," in dispatcher_ts
    assert "const EXPLICIT_FILE_REFERENCE_RE" in dispatcher_ts
    assert "function mentionsExplicitTaskFile(" in dispatcher_ts
    assert "frontend_deterministic_explicit_file_reference" in dispatcher_ts


def test_workspace_file_task_steps_are_user_visible_whitebox_stages():
    task_runner_ts = _read("web/src/workspace/task-runner.ts")
    task_report_layout_ts = _read("web/src/workspace/task-report-layout.ts")
    task_step_labels_ts = _read("web/src/workspace/task-step-labels.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert "import { taskReportStageDoneText } from './task-report-layout';" in task_runner_ts
    assert "from './task-step-labels';" in task_runner_ts
    assert "const PRIMARY_STEP_TITLES" not in task_runner_ts
    assert "export function taskReportStageTitle(stageId: string, fallback = '步骤'): string" in task_report_layout_ts
    assert "export function taskReportStageDoneText(stageId: string, fallback = ''): string" in task_report_layout_ts
    assert "const sharedDoneText = taskReportStageDoneText(stepId);" in task_runner_ts
    assert "const EXTRA_STEP_TITLES: Record<string, string> = {" not in task_runner_ts
    assert "const EXTRA_STEP_TITLES: Record<string, string> = {" in task_step_labels_ts
    assert "export function taskStepTitle(stepId: string, fallback?: string): string" in task_step_labels_ts
    assert "export function taskPlanViolationLabel(code: string): string" in task_step_labels_ts
    assert "export function taskToolLabel(name: string): string" in task_step_labels_ts
    assert "export function shouldAlwaysSuppressTaskToolFinished(name: string): boolean" in task_step_labels_ts
    for label in ("分析需求", "制定计划", "正在处理", "检查结果"):
        assert label in task_report_layout_ts
        assert label in workspace_bundle
    assert "function handleEvent_task_classified" in task_runner_ts
    assert "'task.classified': handleEvent_task_classified" in task_runner_ts
    assert "'plan.created': handleEvent_plan" in task_runner_ts
    assert "'plan.checked': handleEvent_plan_checked" in task_runner_ts
    assert "const step = taskStageStep(card, 'execute');" in task_runner_ts
    assert "const step = taskStageStep(card, 'check');" in task_runner_ts


def test_workspace_blocked_plan_checked_is_not_rendered_as_confirmation_wait():
    task_runner_ts = _read("web/src/workspace/task-runner.ts")
    status_ts = _read("web/src/workspace/file-task-status.ts")

    assert "from './file-task-status';" in task_runner_ts
    assert "export function normalizeFileTaskTerminalStatus(value: unknown): string" in status_ts
    assert "export function fileTaskOutcomeCopy(status: unknown, requiresConfirmation = false): FileTaskOutcomeCopy" in status_ts
    assert "export const FILE_TASK_CONFIRMATION_TERMINAL_STATUSES = new Set([" in status_ts
    assert "export function isFileTaskConfirmationStatus(status: string): boolean" in status_ts
    assert "export function isFileTaskAttentionStatus(status: string): boolean" in status_ts
    assert "export function isFileTaskTerminalStatus(status: string): boolean" in status_ts
    assert "export function fileTaskTerminalUiStatus(status: string, completedTask: boolean, fatalSummary = ''): string" in status_ts
    assert "export function isFileTaskIncompleteBlockedStatus(status: string, completedTask: boolean): boolean" in status_ts
    assert "export function normalizedResumeStatus(status: string): string" in status_ts
    assert "if (status === 'waiting') return 'awaiting_confirmation';" not in status_ts
    assert "return (terminalStatus === 'plan_checked' && !completedTask) || isFileTaskFailureStatus(terminalStatus);" in status_ts
    assert "if (isFileTaskConfirmationStatus(terminalStatus)) return 'pending';" in status_ts
    assert "return terminalStatus === 'needs_attention' || terminalStatus === 'context_summary_fallback';" in status_ts
    assert "if (isFileTaskAttentionStatus(terminalStatus)) return 'pending';" in status_ts
    assert "if (isFileTaskWaitingStatus(terminalStatus)) return 'pending';" not in status_ts
    assert "const status = fileTaskTerminalUiStatus(terminalStatus, completedTask, fatalSummary);" in task_runner_ts
    assert ": ['completed', 'done', 'verified'].includes(terminalStatus);" in task_runner_ts
    assert "Object.prototype.hasOwnProperty.call(dataset, 'taskCompleted') ? boolAttr(dataset.taskCompleted) : true" not in task_runner_ts
    assert "function taskResultRequiresUserConfirmation(result: TerminalResult): boolean" in task_runner_ts
    assert "const incompleteBlocked = isFileTaskIncompleteBlockedStatus(terminal, completedTask);" in task_runner_ts
    assert "improveText = '重新发起'" in task_runner_ts
    assert "setStatus(card, data.tool_name === 'ask_user' || isFileTaskConfirmationStatus(data.status || data.terminal_status || '') ? '待确认' : '已阻止');" in task_runner_ts
    assert "isFileTaskAttentionStatus(result && result.terminal_status)" in task_runner_ts
    assert "normalizeFileTaskTerminalStatus(result && result.terminal_status) === 'context_summary_fallback'" in task_runner_ts
    assert "fileTaskOutcomeCopy(result && result.status || 'done'" in task_runner_ts
    assert "const copy = taskResultOutcomeCopy(result);" in task_runner_ts
    assert "result.status === 'pending') return '任务等待确认。';" not in task_runner_ts
    assert "任务仍在处理中或等待同步" in status_ts
    assert "当前进度已保留，可查看过程并继续处理。" in status_ts
    assert "if (normalized === 'needs_attention') {" in status_ts
    assert "任务需要处理，请查看任务结果" in status_ts
    assert "失败原因和可继续处理的建议已整理到任务结果区域。" in status_ts
    assert "任务已完成，结果和产物已就绪" in status_ts
    assert "任务需要复核：当前只是临时摘要" in status_ts
    assert "已完成核验，任务结果已更新。" not in task_runner_ts
    assert "核验已结束，结论已同步到任务结果。" in _read("web/src/workspace/task-report-layout.ts")
    assert "任务结果见下方" not in task_runner_ts


def test_workspace_system_action_has_whitelisted_app_fast_path():
    dispatcher_ts = _read("web/src/workspace/task-dispatcher.ts")
    local_executor = _read("web/local_executor.py")
    system_handler = _read("web/services/chat_stream/generate/system_handler.py")

    assert "const WHITELISTED_APP_LAUNCH_RE" in dispatcher_ts
    assert "WHITELISTED_APP_LAUNCH_RE.test(text)" in dispatcher_ts
    assert '"wechat"' in local_executor
    assert "def open_whitelisted_app(cls, app_key):" in local_executor
    assert "subprocess.Popen([value], close_fds=True)" in local_executor
    assert "exec_result.get(\"retryable\") is not False" in system_handler


def test_workspace_completed_task_actions_are_not_labeled_as_confirmation_flow():
    task_runner_ts = _read("web/src/workspace/task-runner.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    for source in (task_runner_ts, workspace_bundle):
        assert "任务已完成，后续操作会作为新请求发送。" in source
        assert 'data-task-followup-action="question">追问</button>' not in source
        assert "询问结果" in source
        assert "继续处理" in source
    assert "const questionText = completed ? '询问结果' : '追问原因';" in task_runner_ts
    assert "let improveText = completed ? '继续处理' : '继续修复';" in task_runner_ts
    assert "const actionHint = completed ? '任务已完成，后续操作会作为新请求发送。' : '可继续补充要求或重新处理。';" in task_runner_ts
    assert "let improveText = completed ? '继续优化' : '继续修复';" not in task_runner_ts


def test_workspace_non_confirmation_status_labels_do_not_say_pending_confirmation():
    workbench_js = _read("web/src/workspace/task-workbench.ts")
    results_js = _read("web/src/workspace/results.ts")
    conversation_ts = _read("web/src/workspace/conversation.ts")
    sessions_ts = _read("web/src/workspace/conversation-sessions.ts")
    sessions_bp = _read("web/blueprints/sessions.py")
    status_ts = _read("web/src/workspace/file-task-status.ts")

    assert "export function fileTaskStatusLabel(status: unknown, fallback = '任务'): string" in status_ts
    assert "if (status === 'in_progress') return 'running';" in status_ts
    assert "if (normalized === 'waiting') return '待处理';" in status_ts
    assert "if (normalized === 'awaiting_confirmation') return '等待确认';" in status_ts
    assert "import { fileTaskStatusLabel, isFileTaskAttentionStatus, normalizeFileTaskTerminalStatus } from './file-task-status';" in workbench_js
    assert "return fileTaskStatusLabel(normalized, '任务');" in workbench_js
    assert "metadata.task_terminal_status || metadata.terminal_status || metadata.status || (task && task.status)" in workbench_js
    assert "return normalizeFileTaskTerminalStatus(task && task.status) || 'running';" not in workbench_js
    assert "terminal === 'verified'" not in workbench_js
    assert "waiting: '待处理'" not in workbench_js
    assert "waiting: '待确认'" not in workbench_js
    assert "import { fileTaskStatusLabel } from './file-task-status';" in results_js
    assert "return fileTaskStatusLabel(status, '进行中');" in results_js
    assert "if (isFileTaskFailureStatus(normalized)) return '失败';" in status_ts
    assert "if (normalized === 'failed' || normalized === 'error') return '失败';" not in status_ts
    assert "if (normalized === 'needs_review') return '需复核';" in status_ts
    assert "if (value === 'needs_review') return '待确认';" not in results_js
    assert "import { fileTaskStatusLabel, isFileTaskTerminalStatus, normalizeFileTaskTerminalStatus } from './file-task-status';" in conversation_ts
    assert "import { taskReportStageTitle } from './task-report-layout';" in conversation_ts
    assert "return status ? fileTaskStatusLabel(status, testStructureText(value, 28)) : '待处理';" in conversation_ts
    assert "taskReportStageTitle(key, testStructureText(value || fallback || '步骤', 80))" in conversation_ts
    assert "route: '识别任务'" not in conversation_ts
    assert "plan: '制定方案'" not in conversation_ts
    assert "execute: '执行处理'" not in conversation_ts
    assert "check: '核验完成'" not in conversation_ts
    assert "if (status === 'running' || status === 'in_progress') return '执行中';" not in conversation_ts
    assert "import { fileTaskStatusLabel } from './file-task-status';" in sessions_ts
    assert "return fileTaskStatusLabel(status, '任务');" in sessions_ts
    assert "if (normalized === 'waiting' || normalized === 'awaiting_confirmation') return '等待确认';" not in sessions_ts
    assert 'if normalized in {"awaiting_confirmation", "waiting"}:' not in sessions_bp
    assert 'if normalized == "awaiting_confirmation":' in sessions_bp
    assert 'if normalized == "waiting":' in sessions_bp
    assert '"quality_gate_failed",' in sessions_bp
    assert '"no_file_change",' in sessions_bp
    assert '"model_unavailable",' in sessions_bp


def test_workspace_restored_waiting_task_is_not_forced_into_confirmation_copy():
    task_runner_ts = _read("web/src/workspace/task-runner.ts")
    file_utils_ts = _read("web/src/workspace/file-utils.ts")

    assert "const waiting = isFileTaskWaitingStatus(settings.initialStatus);" in task_runner_ts
    assert "const confirmation = isFileTaskConfirmationStatus(settings.initialStatus);" in task_runner_ts
    assert "statusEl.textContent = confirmation ? '待确认' : (waiting ? '待处理' : '恢复中');" in task_runner_ts
    assert "已恢复待处理的后台任务，正在同步最新进度" in task_runner_ts
    assert "if (isFileTaskWaitingStatus(settings.initialStatus)) { cardEl.classList.add('pending'); }" in task_runner_ts
    assert "from './file-task-status';" in file_utils_ts
    assert "isFileTaskConfirmationStatus" in file_utils_ts
    assert "isFileTaskAttentionStatus" in file_utils_ts
    assert "fileTaskTerminalUiStatus" in file_utils_ts
    assert "normalizeFileTaskTerminalStatus" in file_utils_ts
    assert "const awaitingConfirmation = isFileTaskConfirmationStatus(terminalStatus);" in file_utils_ts
    assert "const needsAttention = isFileTaskAttentionStatus(terminalStatus);" in file_utils_ts
    assert "initialStatus: terminalStatus || taskStatus," in file_utils_ts
    assert "initialStatus: String(task.status || '').trim().toLowerCase()," not in file_utils_ts
    assert "needsAttention || taskStatus === 'waiting' ? '\\u5df2\\u6062\\u590d\\u5f85\\u5904\\u7406\\u7684\\u540e\\u53f0\\u4efb\\u52a1\\u3002'" in file_utils_ts
    assert "\\u6587\\u4ef6\\u4efb\\u52a1\\u6d41\\u5df2\\u7ed3\\u675f\\u3002" in file_utils_ts
    assert "\\u6587\\u4ef6\\u4efb\\u52a1\\u6d41\\u5df2\\u5b8c\\u6210\\u3002" not in file_utils_ts


def test_workspace_file_task_terminal_status_has_single_shared_frontend_contract():
    dispatcher_ts = _read("web/src/workspace/task-dispatcher.ts")
    runtime_init_ts = _read("web/src/workspace/runtime-init.ts")
    conversation_ts = _read("web/src/workspace/conversation.ts")

    assert "import { isFileTaskTerminalStatus, normalizeFileTaskTerminalStatus } from './file-task-status';" in dispatcher_ts
    assert "if (isFileTaskTerminalStatus(status)) return true;" in dispatcher_ts
    assert "['completed', 'done', 'verified'].includes(terminal)" in dispatcher_ts
    assert "['completed', 'done', 'verified', 'failed', 'error', 'cancelled', 'canceled', 'awaiting_confirmation', 'blocked']" not in dispatcher_ts

    assert "import { fileTaskTerminalUiStatus, normalizeFileTaskTerminalStatus } from './file-task-status';" in runtime_init_ts
    assert "const terminalStatus = normalizeFileTaskTerminalStatus(dataset.taskTerminalStatus || (completedTask ? 'completed' : 'needs_attention'));" in runtime_init_ts
    assert "const uiStatus = fileTaskTerminalUiStatus(terminalStatus, completedTask);" in runtime_init_ts
    assert "status: String(dataset.taskTerminalStatus || 'done')" not in runtime_init_ts
    assert "task_terminal_status: String(dataset.taskTerminalStatus || 'completed')" not in runtime_init_ts

    assert "function taskTurnIsTerminal(turn: WATurn): boolean" in conversation_ts
    assert "isFileTaskTerminalStatus(status)" in conversation_ts
    assert "isFileTaskTerminalStatus(terminal)" in conversation_ts


def test_file_task_artifact_status_preserves_attention_diagnostics():
    from web.file_task_stream import _file_task_artifact_status

    assert _file_task_artifact_status(
        "run.finished",
        {
            "completed_task": False,
            "runtime": {"terminal_status": "needs_attention"},
        },
    ) == "needs_attention"
    assert _file_task_artifact_status(
        "run.finished",
        {
            "completed_task": False,
            "runtime": {"terminal_status": "context_summary_fallback"},
        },
    ) == "context_summary_fallback"
    assert _file_task_artifact_status(
        "run.finished",
        {
            "completed_task": False,
            "runtime": {"terminal_status": "quality_gate_failed"},
        },
    ) == "quality_gate_failed"
    assert _file_task_artifact_status(
        "run.finished",
        {
            "completed_task": False,
            "runtime": {"terminal_status": "no_file_change"},
        },
    ) == "no_file_change"


def test_workspace_docx_selection_mouse_state_uses_safe_lookup():
    panel_layout_ts = _read("web/src/ui/panel-layout.ts")

    assert "function _isDocxMouseDown()" in panel_layout_ts
    assert "_isDocxMouseDown() && document.querySelector" in panel_layout_ts
    assert "if (_docxMouseIsDown &&" not in panel_layout_ts


def test_workspace_task_renderer_compacts_tool_result_details():
    task_runner_ts = _read("web/src/workspace/task-runner.ts")
    task_final_report_ts = _read("web/src/workspace/task-final-report.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert "function toolPreviewSummary" in task_runner_ts
    assert "function summarizeParsedResult" in task_runner_ts
    assert "export function looksLikeFullAnswerText" in task_final_report_ts
    assert "export function compactFlowSummary" in task_final_report_ts
    assert "读取到 ' + parsed.length + ' 个工作区条目" in task_runner_ts
    assert "payload.result_preview || payload.result_text || payload.result" in task_runner_ts
    assert "已收到较长内容，详细内容见任务结果。" in task_runner_ts
    assert "步骤已结束，详细内容见任务结果。" in task_runner_ts
    assert "任务已完成，完整结果见任务结果。" not in task_runner_ts
    assert "'文件任务流已结束。'" in task_runner_ts
    assert "'文件任务流已完成。'" not in task_runner_ts
    assert "data-full-content" in task_runner_ts
    assert "lazyDetails.querySelector('pre')" in task_runner_ts
    assert "esc(data.result_text || data.error || '')" not in task_runner_ts

    assert "data-full-content" in workspace_bundle
    assert "已收到较长内容，详细内容见任务结果。" in workspace_bundle


def test_workspace_task_dispatcher_uses_neutral_stream_end_fallback():
    task_dispatcher_ts = _read("web/src/workspace/task-dispatcher.ts")

    assert "|| '文件任务流已结束。';" in task_dispatcher_ts
    assert "'文件任务流已完成。'" not in task_dispatcher_ts


def test_workspace_task_workbench_filters_internal_progress_messages():
    workbench_js = _read("web/src/workspace/task-workbench.ts")
    task_report_layout_ts = _read("web/src/workspace/task-report-layout.ts")

    assert "function userFacingTaskText(value: any, stageId?: string): string" in workbench_js
    assert "function normalizedFlowStages(rawSteps: any[], task: any): WorkbenchStep[]" in workbench_js
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
    assert "TASK_REPORT_STAGE_DEFS.map((def)" in workbench_js
    for label in ("分析需求", "制定计划", "正在处理", "检查结果"):
        assert label in task_report_layout_ts


def test_workspace_task_payload_does_not_attach_current_open_file_by_default():
    dispatcher_ts = _read("web/src/workspace/task-dispatcher.ts")
    runtime_init_ts = _read("web/src/workspace/runtime-init.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert "getActiveEditorContent?: () => string;" in dispatcher_ts
    assert "function currentOpenTaskFile(): TaskFileInfo | null" in dispatcher_ts
    assert "function mentionsAttachedFileContext(text: string): boolean" in dispatcher_ts
    assert "if (currentFile && !rawFiles.some((file) => sameTaskFile(file, currentFile))) rawFiles.unshift(currentFile);" not in dispatcher_ts
    assert "current_file: currentFile" in dispatcher_ts
    assert "currentFile, targetFile" in dispatcher_ts
    assert "getActiveEditorContent: () =>" in runtime_init_ts
    assert "current_file" in workspace_bundle
    assert "selection_source" in workspace_bundle
    assert "skip_model_context" in workspace_bundle


# Section: editor context, selection, and save safety.


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
    assert '.replace(/^workspace\\//i, \'\')' in runtime_ts


def test_workspace_selection_toolbar_restores_pin_and_context_bridge():
    selection_ts = _read("web/src/ui/selection-toolbar.ts")
    text_editor_ts = _read("web/src/editors/text-editor.ts")
    ai_context_ts = _read("web/src/workspace/ai-context.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert "document.addEventListener('mouseup'" in selection_ts
    assert "document.addEventListener('selectionchange'" in selection_ts
    assert "publishWorkspaceApi({" in selection_ts
    assert "sendSelectionToAI," in selection_ts
    assert "clearSelection," in selection_ts
    assert "_showSelectionToolbarForCurrentSelection," in selection_ts
    assert "export function _resetDocxSelection(): void" in selection_ts
    assert "(window as any)._resetDocxSelection = _resetDocxSelection" in selection_ts
    assert "(window as any)._hideDocxHoverBar = _hideDocxHoverBar" in selection_ts
    assert "(window as any)._pinSelectionChip = _pinSelectionChip" in selection_ts
    assert "_selectionPayloadForToolbar()" in selection_ts
    assert "_selectionPayloadForToolbar({ allowStaleFallback: false })" in selection_ts
    assert "_clearSelectionInjectionIfIdle()" in selection_ts
    assert "_isAIInputTarget(el)" in selection_ts
    assert "input.addEventListener('mousedown'" in selection_ts
    assert "this._ta.addEventListener('select', this._handleSelectionChange)" in text_editor_ts
    assert "this._ta.addEventListener('keyup', this._handleSelectionChange)" in text_editor_ts
    assert "getWorkspaceApi()._showSelectionToolbarForCurrentSelection" in text_editor_ts
    assert "已注入选中文本" in workspace_bundle
    assert "取消选择" in workspace_bundle
    assert "ctx-bar-clear-selection" in selection_ts
    assert "ctx-bar-clear-files" in selection_ts
    assert "清除文件" in workspace_bundle
    assert "export function removeAIFileContext" in ai_context_ts
    assert "export function clearAIFileContext" in ai_context_ts
    assert '<button type="button" class="ctx-row-remove"' in ai_context_ts
    assert "removeAIFileContext" in workspace_bundle
    assert "_resetDocxSelection" in workspace_bundle
    assert "_hideDocxHoverBar" in workspace_bundle
    assert 'data-selection-injected="true"' in selection_ts
    assert 'data-selection-injected="true"' in workspace_bundle
    assert "const update = getWorkspaceApi()._updateContextBar;" in ai_context_ts


def test_workspace_unified_shell_restores_save_contract():
    save_ts = _read("web/src/workspace/save.ts")
    bundle_entry = _read("web/src/bundles/workspace.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert "import '../workspace/save';" in bundle_entry
    assert "publishWorkspaceApi({" in save_ts
    assert "saveFile," in save_ts
    assert "saveAs," in save_ts
    assert "scheduleAutoSave," in save_ts
    assert "markExternalFileChange," in save_ts
    assert "clearExternalFileChange," in save_ts
    assert "文件已被任务更新，请重新打开后再保存，避免覆盖任务结果。" in save_ts
    assert "autoSave," in save_ts
    assert "/api/v1/workspace/auto_save" in save_ts
    assert "/api/v1/workspace/raw/" in save_ts
    assert "showSaveFilePicker" in save_ts
    assert "saveFile" in workspace_bundle
    assert "saveAs" in workspace_bundle
    assert "markExternalFileChange" in workspace_bundle


def test_workspace_unified_shell_hides_retained_legacy_skill_surfaces():
    index_template = _read("web/templates/index.html")

    assert 'id="wa-skill-bar"' not in index_template
    assert 'id="wa-skill-exec-panel"' not in index_template
    assert "window.openSkillsPanel();" in index_template
    assert "document.body.classList.contains('koto-unified-workspace')" in index_template
    assert 'id="macroToast" hidden aria-hidden="true"' in index_template


def test_workspace_task_target_inference_does_not_use_bare_attachment_name():
    dispatcher_js = _read("web/src/workspace/task-dispatcher.ts")

    assert "function inferAttachedWriteTargetFile(text: string, files: TaskFileInfo[]): TaskFileInfo | null" in dispatcher_js
    assert "score: targetMentionScore(lowered, f)" in dispatcher_js
    assert "inferCompareTargetFromRoleHint(text, files)" in dispatcher_js
    assert "inferCompareAnnotatedTargetFile(text, files)" in dispatcher_js
    assert "explicitNameMatches" not in dispatcher_js
    assert "lowered.includes(baseName)" not in dispatcher_js


def test_workspace_task_payload_enables_model_primary_intent_router():
    dispatcher_js = _read("web/src/workspace/task-dispatcher.ts")

    assert "enable_ai_intent_adjudicator" in dispatcher_js
    assert "overrideOptions.enable_ai_intent_adjudicator = true;" not in dispatcher_js
    assert "delete overrideOptions.enable_ai_intent_adjudicator;" in dispatcher_js
    assert "model_primary_intent" in dispatcher_js


def test_workspace_model_controls_default_to_deepseek_primary_path():
    state_ts = _read("web/src/workspace/state.ts")
    model_settings_ts = _read("web/src/workspace/model-settings.ts")
    controls_html = _read("web/templates/_workspace_model_controls.html")
    task_runner_ts = _read("web/src/workspace/task-runner.ts")
    task_workbench_ts = _read("web/src/workspace/task-workbench.ts")
    workbench_js = _read("web/src/workspace/task-workbench.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert "lockedModel: 'deepseek'" in state_ts
    assert "localStorage.getItem('wa_locked_model')" not in state_ts
    assert "_cloudProvider: 'deepseek'" in state_ts
    assert "state._cloudProvider || 'deepseek'" in model_settings_ts
    assert "return _modelDisplayName('deepseek-chat', 'DeepSeek Chat');" in model_settings_ts
    assert 'id="wa-model-mode-gemini-btn"' not in controls_html
    assert 'id="wa-model-mode-deepseek-btn" type="button" class="wa-model-mode-toggle-btn active"' in controls_html
    assert 'data-model-mode="deepseek"' in controls_html
    assert "Gemini" not in controls_html
    assert "Gemini" not in task_runner_ts
    assert "Gemini" not in task_workbench_ts
    assert "Gemini" not in workbench_js
    assert 'data-model-mode="gemini"' not in controls_html
    assert "__kotoSettingsModelBridgeBound" in workspace_bundle
    assert "deepseek-chat" in workspace_bundle


def test_workspace_quick_actions_do_not_keyword_route_freeform_tasks():
    dispatcher_js = _read("web/src/workspace/task-dispatcher.ts")
    quick_actions_js = _read("web/src/workspace/quick-actions.ts")
    assistant_js = _read("web/src/workspace/ai-review.ts")

    assert "registerQuickActionKeyword" not in dispatcher_js
    assert "registerTaskActionKeyword" not in assistant_js
    assert "quickActionKeywords" not in dispatcher_js
    assert "source.includes(entry.keyword)" not in dispatcher_js
    assert "keywords.some((keyword) => source.includes(keyword))" not in quick_actions_js
    assert "ACTION_KEYWORDS" not in assistant_js
    assert "return quickActionHandlers.has(source) ? source : '';" in dispatcher_js


def test_workspace_quick_action_aliases_keep_hoverbars_wired():
    quick_actions_js = _read("web/src/workspace/quick-actions.ts")
    selection_toolbar_js = _read("web/src/ui/selection-toolbar.ts")
    index_template = _read("web/templates/index.html")

    assert "polish: '润色'" in quick_actions_js
    assert "translate: '翻译'" in quick_actions_js
    assert "explain: '解释'" in quick_actions_js
    assert "aliasesForAction(action.action).forEach" in quick_actions_js
    assert "normalizeQuickActionId(actionId)" in quick_actions_js
    assert "WA.docxHoverAI('polish')" in index_template
    assert "publishWorkspaceApi({" in selection_toolbar_js
    assert "closeSelectionToolbar," in selection_toolbar_js


def test_workspace_task_payload_extracts_explicit_text_write_target():
    dispatcher_ts = _read("web/src/workspace/task-dispatcher.ts")
    dispatcher_js = _read("web/src/workspace/task-dispatcher.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    for source in (dispatcher_ts, dispatcher_js):
        assert "explicitWriteTargetPathFromText" in source
        assert "const explicitTextTargetPath = explicitWriteTargetPathFromText(text);" in source
        assert "files.push(targetFile);" in source or "rawFiles.push(targetFile);" in source
        assert "target_path: inferredTargetPath," in source
        assert "baseNameFromPath(explicitTextTargetPath)" in source
        assert "fileTypeFromPath(explicitTextTargetPath)" in source
        assert "[^\\s\"'<>|:：,，。；;、!?！？()[\\]【】]" in source
        assert "explicitOutputBeforePattern.test(before)" in source
        assert "sourceBeforePattern.test(before)" in source

    assert "target_path" in workspace_bundle
    assert "source_path" in workspace_bundle
    assert "file_type" in workspace_bundle


def test_workspace_task_renderer_surfaces_supervisor_status():
    renderer_js = _read("web/src/workspace/task-runner.ts")
    workspace_template = _read("web/templates/index.html")
    index_template = _read("web/templates/index.html")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert "function taskRecognitionText(data: Record<string, any>): string" in renderer_js
    assert "function planCheckSummaryText(data: Record<string, any>, passed: boolean): string" in renderer_js
    assert "'supervisor.status': handleEvent_supervisor_status" in renderer_js
    assert "'supervisor.status:' + stage" in renderer_js
    assert "监管检查已更新。" in renderer_js
    assert "'read_request_escalated_to_write': '只读任务被错误升级为写入'" in renderer_js
    assert "计划检查通过：本轮只读，不会修改文件。" in renderer_js
    assert "taskRecognitionText(data)" in renderer_js
    assert "if (passed) return;" not in renderer_js

    for source in (renderer_js, workspace_template, index_template, workspace_bundle):
        assert "按计划 0/0" not in source
        assert "准备识别任务" in source


# Section: retired system side effects.


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

    assert not (_repo_root() / "app/core/agent/plugins/script_generation_plugin.py").exists()
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


def test_local_executor_only_performs_whitelisted_system_side_effects():
    local_executor = _read("web/local_executor.py")
    chat_system_instruction = _read("web/chat_system_instruction.py")
    context_injector = _read("web/context_injector.py")

    _assert_excludes_all(
        local_executor,
        (
            "APP_ALIASES",
            "SYSTEM_KEYWORDS",
            "def extract_app_name",
            "def find_app_in_start_menu",
            "def find_app_smart",
            "def open_file_or_directory",
            "def send_keystroke",
            "shutdown /",
            "snippingtool",
            "webbrowser.open",
            "keyboard.hotkey",
        ),
    )
    assert "APP_LAUNCHERS = {" in local_executor
    assert "def open_whitelisted_app(cls, app_key):" in local_executor
    assert '"wechat"' in local_executor
    for instruction_source in (chat_system_instruction, context_injector):
        assert "联动本地应用" not in instruction_source
        assert "可以执行 Koto 白名单内的简单应用启动" in instruction_source
        assert "不发送消息、不截图、不代替用户操作应用内容" in instruction_source


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


def test_routing_layer_only_fast_tracks_whitelisted_app_launch_as_system():
    rule_router = _read("app/core/routing/rule_router.py")
    smart_dispatcher = _read("app/core/routing/smart_dispatcher.py")
    ai_router = _read("app/core/routing/ai_router.py")
    synthetic_data = _read("app/core/learning/synthetic_data_generator.py")
    training_builder = _read("app/core/learning/training_data_builder.py")
    local_model_router = _read("app/core/routing/local_model_router.py")

    assert "_sys_starters" not in rule_router
    assert "_sys_action_starters" not in smart_dispatcher
    assert "_fb_sys_starters" not in smart_dispatcher
    assert "Action-Direct" not in smart_dispatcher
    assert "Fallback-ActionVerb" not in smart_dispatcher
    assert "启动白名单应用" in ai_router
    assert "启动白名单应用" in local_model_router
    assert '("打开微信", "SYSTEM"' in synthetic_data
    assert '("open WeChat", "SYSTEM"' in synthetic_data
    assert '("打开微信", "SYSTEM"' in training_builder
    assert '("帮我打开微信，然后截图", "AGENT"' in synthetic_data
    _assert_excludes_all(
        synthetic_data,
        (
            '("帮我打开微信，然后截图", "SYSTEM"',
        ),
    )


# Section: file browser, bundle wiring, and runtime actions.


def test_workspace_file_tree_drag_to_ai_stays_readonly_attachment_flow():
    assistant_js = _read("web/src/workspace/fs-tree.ts")
    fs_tree = _read("web/src/workspace/fs-tree.ts")
    embedded = _read("web/src/ui/embedded-mode.ts")
    ai_context = _read("web/src/workspace/ai-context.ts")
    asset_scripts = _read("web/templates/_workspace_asset_scripts.html")
    workspace_template = _read("web/templates/index.html")
    index_template = _read("web/templates/index.html")
    workspace_css = _read("web/static/css/workspace.css")

    assert 'draggable="true"' in assistant_js
    assert "application/wa-file-path" in assistant_js
    assert "_getAIAttachmentDropPayload" in embedded
    assert "attachFilesToTask: _attachFilesToTask," in ai_context
    assert "publishWorkspaceApi({" in ai_context
    assert "WA._pendingSendBrowserFilesToAI = WA._pendingSendBrowserFilesToAI || []" in asset_scripts
    assert "WA.sendBrowserFileToAI = WA.sendBrowserFileToAI || function(path)" in asset_scripts
    assert "WA._pendingSendBrowserFilesToAI.push(path)" in asset_scripts
    assert "const pendingBrowserFilesToAI = Array.isArray(workspaceApi._pendingSendBrowserFilesToAI)" in ai_context
    assert "_attachFilesToTask(pendingBrowserFilesToAI" in ai_context
    assert "await _attachFilesToTask([payload.filePath], { source, focusInput: !_isAiSessionListVisible() })" in embedded
    assert "'ai_panel_drop'" in embedded
    assert "function _fileDragAttrs()" in fs_tree
    assert "function _fileOpenHitDragAttrs()" in fs_tree
    assert "function _installBrowserPointerDragFallback()" in fs_tree
    assert "wa._browserFileRowMouseDown =" in fs_tree
    assert "wa._browserFileRowClick =" in fs_tree
    assert "wa._browserFileRowPointerDown =" in fs_tree
    assert 'data-wa-file-draggable="true"' in fs_tree
    assert "document.addEventListener('pointerdown'" in fs_tree
    assert "document.addEventListener('pointermove', (event) => _onBrowserPointerMove(event));" in fs_tree
    assert "document.addEventListener('pointerup', (event) => {" in fs_tree
    assert "document.addEventListener('dragstart'" in fs_tree
    assert "wa._browserFileDragStart = _browserFileDragStart" in fs_tree
    assert "async function _attachBrowserFileToAI" in fs_tree
    assert "async function _sendBrowserFileToAI" in fs_tree
    assert "function _installBrowserFileActionDelegation()" in fs_tree
    assert 'data-wa-file-action="send-ai"' in fs_tree
    assert "target.closest('.wa-file-send-ai[data-wa-file-action=\"send-ai\"]')" in fs_tree
    assert "onpointerdown=\"window.WA._sendBrowserFileButton(event,this)\"" not in fs_tree
    assert "onclick=\"window.WA._sendBrowserFileButton(event,this)\"" not in fs_tree
    assert "function _sendBrowserFileButtonToAI(event: Event, button: HTMLElement | null): void" in fs_tree
    assert "wa._sendBrowserFileButton = _sendBrowserFileButtonToAI" in fs_tree
    assert "onclick=\"event.preventDefault();event.stopPropagation();window.WA.sendBrowserFileToAI" not in fs_tree
    assert "onclick=\"event.preventDefault();event.stopPropagation();WA.sendBrowserFileToAI" not in fs_tree

    assert "wa.sendBrowserFileToAI = _sendBrowserFileToAI" in fs_tree
    assert "WA = window.WA = window.WA || {}" in asset_scripts
    workspace_bundle_entry = _read("web/src/bundles/workspace.ts")
    assert workspace_bundle_entry.index("import '../workspace/ai-context';") < workspace_bundle_entry.index("import '../workspace/fs-tree';")
    assert "class=\"wa-file-send-ai\"" in fs_tree
    assert "file_tree_inline_action" in fs_tree
    assert "_attachBrowserFileToAI(path, 'file_tree_dragend_drop')" in fs_tree
    assert "_attachBrowserFileToAI(drag.path, 'file_tree_pointer_drop')" in fs_tree
    assert "_installBrowserFileActionDelegation();" in fs_tree
    assert "_installBrowserPointerDragFallback();" in fs_tree
    assert "` ${_fileDragAttrs()}`" in fs_tree
    assert "`${_fileDragAttrs()} data-wa-file-kind=\"file\" `" in fs_tree
    assert "const sessionListComposer = document.getElementById('wa-ai-session-list-composer')" in embedded
    assert "sessionListComposer.classList.add('wa-session-list-drag-over')" in embedded
    assert "focusInput: !_isAiSessionListVisible()" in embedded
    assert "_focusVisibleAIComposer();" in embedded
    assert "document.getElementById('wa-ai-file-chips')" in ai_context
    assert "document.getElementById('wa-ai-file-chip-list')" in ai_context
    assert "onclick=\"WA." not in ai_context
    assert "data-wa-context-action" in ai_context
    assert "function _installAIContextActionDelegation(): void" in ai_context
    assert 'id="wa-ai-file-chips"' in workspace_template
    assert 'id="wa-ai-file-chips"' in index_template
    assert ".wa-session-list-drag-over" in workspace_css
    assert "#wa-ai-file-chips" in workspace_css
    assert ".wa-file-actions .wa-file-send-ai" in workspace_css


def test_mcp_attach_task_file_replaces_previous_frontend_context_by_default():
    ai_context = _read("web/src/workspace/ai-context.ts")
    frontend_observer = _read("web/src/mcp/frontend-observer.ts")

    assert "replaceExisting?: boolean" in ai_context
    assert "if (options.replaceExisting && state._aiFileContext.length)" in ai_context
    assert "state._aiFileContext = []" in ai_context
    assert "state._aiTargetFileIdx = -1" in ai_context
    assert "function _normalizeFrontendTaskPath(path: string): string" in frontend_observer
    assert "value.replace(/^\\.\\//, '')" in frontend_observer
    assert "/^workspace\\//i.test(value)" in frontend_observer
    assert "value.slice('workspace/'.length)" in frontend_observer
    assert "replaceExisting: action.options?.replaceExisting !== false" in frontend_observer


def test_mcp_frontend_action_exposes_stable_task_result_evidence():
    frontend_observer = _read("web/src/mcp/frontend-observer.ts")

    assert "| 'task_result_evidence'" in frontend_observer
    assert "function _taskResultEvidence(action: FrontendAction): Record<string, unknown>" in frontend_observer
    assert "if (action.action === 'task_result_evidence') return _taskResultEvidence(action);" in frontend_observer
    assert ".wa-task-run[data-task-id=" in frontend_observer
    assert ".wa-task-run[data-task-run-id=" in frontend_observer
    assert "finalAnswer: finalReport ? _visibleText(finalReport, limit) : ''" in frontend_observer
    assert "screenshotClip: _elementViewportClip(card, Number(opts.padding || 8))" in frontend_observer
    assert "chips = Array.from(document.querySelectorAll('#wa-ai-file-chip-list .wa-ctx-file-row'))" in frontend_observer
    assert "function _renderTaskEvidenceOverlay(evidence: Record<string, unknown>): HTMLElement" in frontend_observer
    assert "overlay.id = 'koto-task-evidence-capture'" in frontend_observer
    assert "if (opts.renderOverlay)" in frontend_observer
    assert "evidence.overlayClip = _elementViewportClip(overlay, 4)" in frontend_observer


def test_mcp_frontend_submit_prompt_targets_unified_workspace_composer():
    frontend_observer = _read("web/src/mcp/frontend-observer.ts")

    assert "function _ensureUnifiedAiComposerVisible()" in frontend_observer
    assert "wa.showAiWorkspace();" in frontend_observer
    assert "function _assistantComposerTargets()" in frontend_observer
    assert "_findFirstVisible(['#wa-user-input'])" in frontend_observer
    assert "_findFirstVisible(['#wa-send-btn'])" in frontend_observer
    assert "_findFirstVisible(['#messageInput'])" in frontend_observer
    assert "_findFirstVisible(['#sendBtn'])" in frontend_observer
    submit_block = frontend_observer[
        frontend_observer.index("if (action.action === 'submit_prompt')") :
    ]
    assert "'textarea'" not in submit_block
    assert "'[contenteditable=\"true\"]'" not in submit_block
    assert "legacyFallback: targets.legacy" in submit_block


def test_workspace_file_row_handlers_have_a_single_tree_owner():
    fs_tree = _read("web/src/workspace/fs-tree.ts")
    fs_actions = _read("web/src/workspace/fs-actions.ts")

    assert "wa._browserFileRowMouseDown = (event: MouseEvent, el: HTMLElement): void =>" in fs_tree
    assert "wa._browserFileRowClick = (event: MouseEvent, el: HTMLElement): void =>" in fs_tree
    assert "_browserFileRowMouseDown" not in fs_actions
    assert "_browserFileRowClick" not in fs_actions
    assert "_installBrowserFileRowDelegation" not in fs_actions


def test_workspace_task_run_finished_closes_run_stage_step():
    task_runner_ts = _read("web/src/workspace/task-runner.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")

    assert "const runStep = card.querySelector('[data-role=\"steps\"] .wa-task-step[data-step-id=\"run\"]')" in task_runner_ts
    assert "markStepFailed(runStep)" in task_runner_ts
    assert "markStepDone(runStep)" in task_runner_ts
    assert 'data-step-id="run"' in workspace_bundle


def test_workspace_file_task_refresh_normalizes_paths_and_blocks_stale_save():
    fs_tree = _read("web/src/workspace/fs-tree.ts")
    task_refresh = _read("web/src/workspace/task-refresh.ts")
    task_runner = _read("web/src/workspace/task-runner.ts")
    file_open = _read("web/src/workspace/file-open.ts")

    assert ".replace(/^workspace\\//i, '')" in fs_tree
    assert "const rawPath = payload.path || payload.file_path || payload.output_path || payload.target_path;" in task_refresh
    assert "const path = normalizePath(rawPath || '') || rawPath;" in task_refresh
    assert "workspaceApi.markExternalFileChange(refreshPath || path)" in task_runner
    assert "reload(refreshPath || path, true)" in task_runner
    assert "const clearExternalFileChange = getWorkspaceApi().clearExternalFileChange;" in file_open
    assert "clearExternalFileChange(resolvedPath);" in file_open


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
    assert "if (cachedResults.length) _renderSearchResults(cachedResults, q);" in fs_tree
    assert "_renderSearchResults(_mergeSearchResults(cachedResults, indexedResults, 60), q);" in fs_tree
    assert "_searchLiveWorkspaceFiles(q, cat, 60).then" in fs_tree
    assert "/api/v1/workspace/list_files" in workspace_bundle
    assert "/api/files/search" in workspace_bundle
    assert "wa-search-header" in workspace_bundle


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
    assert "if (typeof wa.loadFileBrowser === 'function') await wa.loadFileBrowser();" in state_ts

    assert "typeof (window as any).WA.loadFileBrowser === 'function'" in embedded
    assert "typeof loadFileBrowser === 'function'" not in embedded
    assert "typeof loadFileBrowser === 'function'" not in app_main_ts
    assert 'id="wa-left"' in index_template
    assert 'id="wa-files-list"' in index_template
    assert 'id="wa-recent-list"' in index_template
    assert 'id="statusIndicator"' in index_template
    assert 'id="latencyDetail"' in index_template
    assert 'id="wa-left-latency-slot"' not in index_template
    assert 'id="wa-local-file-input"' in index_template
    assert 'id="wa-local-folder-input"' in index_template
    assert 'for="wa-file-input-left"' in index_template
    assert 'id="wa-ctx-menu"' in index_template
    assert index_template.index('id="wa-left"') < index_template.index('id="wa-canvas"') < index_template.index('id="wa-ai"')
    assert ".wa-local-folder-picker" in workspace_css
    assert "#wa-recent-list .wa-file-item.wa-recent-file" in workspace_css
    assert ".koto-activity-bar .latency-detail.open" in workspace_css
    assert "Keep its DOM owner stable" in app_settings_ts
    assert "const leftSlot = document.getElementById('wa-left-latency-slot')" not in app_settings_ts
    assert "wa-left-latency-slot" not in app_bundle
    assert "function _recentFileDragAttrs()" in state_ts
    assert "function _recentFileOpenHitDragAttrs()" in state_ts
    assert 'class="wa-file-item file wa-recent-file"' in state_ts
    assert "_mergeRecentFiles(localRecent, apiRecent)" in state_ts
    assert "if (localRecent.length)" in state_ts
    assert "_loadLocalRecentFiles()" in state_ts
    assert 'data-wa-file-draggable="true"' in state_ts
    assert 'data-wa-file-action="open"' in state_ts
    assert 'onclick="WA.openRecentFile' not in state_ts
    assert 'oncontextmenu="event.preventDefault();event.stopPropagation();WA._showBrowserCtx' not in state_ts
    assert "function _installWorkspaceRowActionDelegation(): void" in state_ts
    assert 'data-wa-workspace-row-action="remove-my"' in state_ts
    assert 'data-wa-workspace-row-action="remove-temp"' in state_ts

    assert "loadFileBrowser" in workspace_bundle
    assert "refreshRecent" in workspace_bundle
    assert "loadRecentFiles" in workspace_bundle
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
        "handleInputKeydown,",
        "closeReviewCenter,",
        "setReviewMode,",
    ):
        assert expected in ai_review
    assert "publishWorkspaceApi({" in ai_review

    for expected in (
        "pptxFmt,",
        "pptxAlign,",
        "pptxFontSize,",
        "pptxFontName,",
        "pptxFontColor,",
        "pptxColorPicker,",
        "_pptxPickColor,",
        "pptxHoverAI,",
        "pptxZoom,",
        "pptxNav,",
        "pptxInsertShape,",
        "pptxSetShapeSize,",
        "pptxSetShapePos,",
        "pptxSetShapeRot,",
        "pptxInsertImageClick,",
        "pptxInsertImageFile,",
        "docxZoom,",
    ):
        assert expected in toolbar
    assert "publishWorkspaceApi({" in toolbar
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
        "pdfZoom,",
        "pdfSearchOpen,",
        "pdfSearchInput,",
        "pdfAnnotOpen,",
        "pdfAnnotMode,",
        "pdfPageMgrOpen,",
        "pdfPageMgrApply,",
        "pdfConvert,",
        "pdfWatermarkClose,",
        "_pdfDocumentForEditor(ed)",
    ):
        assert expected in pdf_viewer
    assert "publishWorkspaceApi({" in pdf_viewer

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
    assert "export async function _csrfFetch(url: string, options: CsrfOptions = {}): Promise<Response>" in assistant_js
    assert "document.querySelector('meta[name=\"csrf-token\"]')" in assistant_js
    assert "X-CSRFToken" in assistant_js
    assert "async function _refreshCsrfToken(): Promise<string>" in assistant_js
    assert "fetch('/api/csrf-token'" in assistant_js
    assert "response.status === 400 && _needsCsrf(fetchOptions.method)" in assistant_js
    assert "fetchOptions.headers = _headersWithCsrf(fetchOptions.headers)" in assistant_js
    assert "const res = await _csrfFetch('/api/v1/workspace/open_file_by_path'" in assistant_js
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

    assert "async function csrfFetch(url: string, options: RequestInit = {}): Promise<Response>" in task_js
    assert "document.querySelector('meta[name=\"csrf-token\"]')" in task_js
    assert "X-CSRFToken" in task_js
    assert "function csrfToken(): string" in task_js
    assert "headersWithCsrf(fetchOptions.headers as any)" in task_js
    assert "async function describeHttpError(resp: Response): Promise<string>" in task_js
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


def test_workspace_visible_ai_runtime_actions_are_registered():
    ai_review = _read("web/src/workspace/ai-review.ts")
    pdf_viewer = _read("web/src/editors/pdf-viewer.ts")
    state_js = _read("web/src/workspace/state.ts")
    fs_actions = _read("web/src/workspace/fs-actions.ts")

    assert "workspaceApi.sendCustomMessage" in pdf_viewer
    assert "export function sendCustomMessage(text: string): void" in ai_review
    assert "publishWorkspaceApi({" in ai_review
    assert "sendCustomMessage," in ai_review

    assert "workspaceApi.stopStream" in ai_review
    assert "export function stopStream(): boolean" in ai_review
    assert "stopStream," in ai_review
    assert "state._streamAbortCtrl" in ai_review
    assert "ctrl.abort()" in ai_review

    assert "workspaceApi._removeOpenTabAfterFileDeleted" in fs_actions
    assert "export async function _removeOpenTabAfterFileDeleted(path: string): Promise<boolean>" in state_js
    assert "wa._removeOpenTabAfterFileDeleted = _removeOpenTabAfterFileDeleted" in state_js


def test_workspace_file_row_actions_do_not_start_drag_fallback():
    fs_tree = _read("web/src/workspace/fs-tree.ts")

    assert 'const isolatedPressAttrs = \'draggable="false"' in fs_tree
    assert 'onpointerdown="event.stopPropagation()"' not in fs_tree
    assert 'ondragstart="event.preventDefault();event.stopPropagation()"' not in fs_tree
    assert "target?.closest('[data-wa-file-action], .wa-file-check')" in fs_tree
    assert "function _isBrowserFileActionTarget(target: EventTarget | null): boolean" in fs_tree
    assert "el.closest('.wa-file-actions, .wa-file-check, input, select, textarea, a')" in fs_tree
    assert "if (_isBrowserFileActionTarget(event.target)) return;" in fs_tree


# Section: HTTP safety, progress, resume, and browser selection.


def test_http_wiring_exposes_csrf_refresh_endpoint():
    app_http = _read("web/app_http.py")

    assert '@app.route("/api/csrf-token", methods=["GET"])' in app_http
    assert "generate_csrf()" in app_http
    assert "CSRF_FAILED" in app_http


def test_workspace_task_card_renderer_guards_non_dom_cards():
    task_js = _read("web/src/workspace/task-runner.ts")

    assert "function isTaskCardElement(value: unknown): value is TaskCardElement" in task_js
    assert "typeof (value as TaskCardElement).querySelectorAll === 'function'" in task_js
    assert "if (!isTaskCardElement(card)) return;" in task_js
    assert "function ensureTaskUiState(card: TaskCardElement): FileTaskUiState" in task_js
    assert "function taskTerminalResult(card: TaskCardElement, fallbackSummary?: string): TerminalResult" in task_js
    assert "if (!isTaskCardElement(card) || !payload || typeof payload !== 'object') return;" in task_js


def test_workspace_task_progress_has_live_plan_linked_feedback():
    task_js = _read("web/src/workspace/task-runner.ts")
    workspace_css = _read("web/static/css/workspace.css")
    workspace_template = _read("web/templates/index.html")
    index_template = _read("web/templates/index.html")

    assert 'id="wa-task-live-progress"' in workspace_template
    assert 'id="wa-task-live-progress"' in index_template
    assert "function syncTaskLiveProgress(card: TaskCardElement): void" in task_js
    assert "function taskPlanProgress(card: TaskCardElement): { total: number; completed: number; running: boolean }" in task_js
    assert "ensureTaskUiState(card).plannedStepCount = steps.length;" in task_js
    assert "state.progressExplicit = true;" in task_js
    assert "basis = explicit ? 'explicit' : (plan.total ? 'planned' : 'estimated')" in task_js
    assert "valueText = '步骤 ' + plan.completed + '/' + plan.total;" in task_js
    assert "syncTaskLiveProgress(card);" in task_js
    assert ".wa-task-live-progress" in workspace_css
    assert '.wa-task-progress[data-basis="planned"]' in workspace_css
    assert '.wa-task-progress[data-basis="estimated"]' in workspace_css


def test_workspace_stepwise_resume_payload_does_not_increment_explicit_step_index():
    dispatcher_js = _read("web/src/workspace/task-dispatcher.ts")

    assert "const existingWorkflowCheckpoint = options.workflow_checkpoint" in dispatcher_js
    assert "delete options.batch_control;" in dispatcher_js
    assert "options.workflow_checkpoint = Object.assign" in dispatcher_js
    assert "const hasExplicitStepIndex = Object.prototype.hasOwnProperty.call(checkpointSeed, 'step_index')" in dispatcher_js
    assert "const resumeStepIndex = hasExplicitStepIndex ? currentStep : currentStep + 1;" in dispatcher_js
    assert "step_index: resumeStepIndex" in dispatcher_js
    assert "next_step_index: resumeStepIndex" in dispatcher_js


def test_workspace_stepwise_resume_payload_prefers_workflow_checkpoint():
    dispatcher_js = _read("web/src/workspace/task-dispatcher.ts")
    task_js = _read("web/src/workspace/task-runner.ts")

    assert "compact.options = { workflow_checkpoint: workflowCheckpoint }" in dispatcher_js
    assert "workflowCheckpointFallback" not in dispatcher_js
    assert "compactPayload.options.workflow_checkpoint || compactPayload.options.batch_control" not in dispatcher_js
    assert "function workflowCheckpointFromOptions(options?: Record<string, any>): Record<string, any> | null" in task_js
    assert "source.workflow_checkpoint && typeof source.workflow_checkpoint === 'object'" in task_js
    assert "return source.batch_control && typeof source.batch_control === 'object'" not in task_js


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

    assert "wa._browserFileRowMouseDown = (event: MouseEvent, el: HTMLElement): void =>" in workspace_js
    assert "wa._browserFileRowClick = (event: MouseEvent, el: HTMLElement): void =>" in workspace_js
    assert "(event.target as HTMLElement).closest('.wa-file-check')" in workspace_js
    assert 'onmousedown="WA._browserFileRowMouseDown(event,this)"' not in workspace_js
    assert 'onclick="WA._browserFileRowClick(event,this)"' not in workspace_js
    assert "document.addEventListener('click'" in workspace_js
    assert "if (!state._searchActive || `${state.searchQuery}" in workspace_js
    assert "workspaceApi._renderBrowserTree();" in fs_actions
    assert "flex: 1 1 0;" in workspace_css
    assert "contain: paint;" in workspace_css
