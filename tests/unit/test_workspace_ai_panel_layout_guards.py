from pathlib import Path

from .workspace_css_contract import read_workspace_stylesheet_contract


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_workspace_templates_load_workspace_assistant_css_manifest():
    embedded_html = _read("web/templates/index.html")
    standalone_html = _read("web/templates/workspace_assistant.html")

    assert "filename='css/workspace-assistant.css'" in embedded_html
    assert 'href="/static/css/workspace-assistant.css' in standalone_html


def test_workspace_templates_share_close_warn_dialog_partial():
    embedded_html = _read("web/templates/index.html")
    standalone_html = _read("web/templates/workspace_assistant.html")
    partial_html = _read("web/templates/_workspace_close_warn_dialog.html")

    assert "{% include '_workspace_close_warn_dialog.html' %}" in embedded_html
    assert "{% include '_workspace_close_warn_dialog.html' %}" in standalone_html
    assert 'id="wa-close-warn-overlay"' in partial_html
    assert 'id="wa-close-warn-dialog"' in partial_html
    assert 'id="wa-close-warn-list"' in partial_html
    assert 'id="wa-close-warn-count"' in partial_html
    assert 'class="wa-close-warn-summary"' in partial_html
    assert 'WA._closeWarnCancel()' in partial_html
    assert 'WA._closeWarnDiscard()' in partial_html
    assert 'WA._closeWarnSaveAll()' in partial_html
    assert '放弃修改并退出' in partial_html
    assert '保存全部并退出' in partial_html


def test_workspace_close_warn_dialog_uses_redesigned_structure_and_styles():
    partial_html = _read("web/templates/_workspace_close_warn_dialog.html")
    js = _read("web/static/js/workspace-assistant.js")
    css = read_workspace_stylesheet_contract()

    assert 'class="wa-close-warn-head"' in partial_html
    assert 'class="wa-close-warn-footer"' in partial_html
    assert '.wa-close-warn-dialog' in css
    assert '.wa-close-warn-summary' in css
    assert '.wa-close-warn-item' in css
    assert '.wa-close-warn-discard' in css
    assert 'wa-close-warn-count' in js
    assert 'wa-close-warn-dialog' in js


def test_workspace_templates_share_toast_partial_without_retired_chart_dialog():
    embedded_html = _read("web/templates/index.html")
    standalone_html = _read("web/templates/workspace_assistant.html")
    partial_html = _read("web/templates/_workspace_chart_dialog_and_toast.html")

    assert "{% include '_workspace_chart_dialog_and_toast.html' %}" in embedded_html
    assert "{% include '_workspace_chart_dialog_and_toast.html' %}" in standalone_html
    assert 'id="wa-chart-dialog"' not in partial_html
    assert 'id="wa-chart-prompt"' not in partial_html
    assert 'id="wa-chart-data-hint"' not in partial_html
    assert 'WA.closeChartDialog()' not in partial_html
    assert 'WA.submitChartRequest()' not in partial_html
    assert 'id="wa-toast"' in partial_html


def test_workspace_templates_share_selection_toolbar_partial():
    embedded_html = _read("web/templates/index.html")
    standalone_html = _read("web/templates/workspace_assistant.html")
    partial_html = _read("web/templates/_workspace_selection_toolbar.html")

    assert "{% include '_workspace_selection_toolbar.html' %}" in embedded_html
    assert "{% include '_workspace_selection_toolbar.html' %}" in standalone_html
    assert 'id="wa-pdf-tooltip"' in partial_html
    assert 'id="wa-tooltip-count"' in partial_html
    assert "WA.sendSelectionToAI()" in partial_html
    assert "WA.sendQuickAction('可视化')" in partial_html
    assert 'wa-tooltip-highlight' in partial_html
    assert 'wa-tooltip-underline' in partial_html
    assert 'wa_pdf_tooltip_root_onmousedown' in partial_html
    assert 'wa_pdf_tooltip_show_pdf_annotation_actions' in partial_html


def test_workspace_templates_share_docx_color_picker_partial():
    embedded_html = _read("web/templates/index.html")
    standalone_html = _read("web/templates/workspace_assistant.html")
    partial_html = _read("web/templates/_workspace_docx_color_picker.html")

    assert "{% include '_workspace_docx_color_picker.html' %}" in embedded_html
    assert "{% include '_workspace_docx_color_picker.html' %}" in standalone_html
    assert 'id="wa-docx-cp"' in partial_html
    assert 'id="wa-docx-cp-grid"' in partial_html
    assert 'id="wa-docx-cp-custom"' in partial_html
    assert 'id="wa-docx-cp-hex"' in partial_html
    assert 'WA._docxPickColor(this.value,true)' in partial_html


def test_workspace_templates_remove_top_settings_use_bottom_toggle_and_keep_files_above_input():
    embedded_html = _read("web/templates/index.html")
    standalone_html = _read("web/templates/workspace_assistant.html")

    for html in (embedded_html, standalone_html):
        assert 'id="wa-subject-bar"' not in html
        assert '当前编辑' not in html
        assert 'id="wa-ai-settings-panel"' not in html
        assert 'AI 输出模式' not in html
        assert 'id="wa-footer-file-chip"' not in html
        assert 'id="wa-footer-attach-current-btn"' not in html
        assert "{% include '_workspace_model_controls.html' %}" in html
        assert '只有明确选中的文本和分析文档会进入当前任务上下文。' in html
        assert '快速读懂当前文件' not in html
        assert '当前文件、选区和附件会自动并入上下文。' not in html
        assert html.index('<div id="wa-ai-file-chips"') < html.index('<div id="wa-actions-bar">')
        assert html.index('<div id="wa-ai-file-chips"') < html.index('<div class="wa-input-box">')
        assert html.index('<div class="wa-input-box-footer">') < html.index("{% include '_workspace_model_controls.html' %}")
        assert html.index("{% include '_workspace_model_controls.html' %}") < html.index('<div class="wa-footer-actions">')
        assert html.index('<div class="wa-footer-actions">') < html.index('id="wa-send-btn"')


def test_workspace_subject_bar_and_action_row_styles_support_restored_layout():
    js = _read("web/static/js/workspace-assistant.js")
    css = read_workspace_stylesheet_contract()

    assert "toggleCurrentFileAIContext" not in js
    assert "addCurrentFileToAIContext" not in js
    assert "只处理用户明确提供的选中文本和分析文档" in js
    assert "按提取文本估算" not in js
    assert "open_tabs: []," in js
    assert "当前文件: ${state.fileName}" not in js
    assert "#wa-subject-bar { display: none !important;" not in css
    assert ".wa-actions-spacer" in css
    assert ".wa-model-mode-toggle" in css
    assert ".wa-model-mode-toggle-btn" in css
    assert ".wa-model-mode-sub[hidden]" in css
    assert ".wa-model-mode-sub::before" in css
    assert "_coerceModelLabel" in js
    assert "wa_model_choice_explicit" in js
    assert "_currentCloudModelHint" in js
    assert "state._modelMap?.FILE_TASK" in js
    assert "文件: ${cloudModelHint}" in js
    assert "云端文件任务模型" in js
    assert "_localRuntimeModel" in js
    assert "_normalizeLocalRuntimeModelLabel" in js
    assert "_formatLocalRuntimeModelLabel" in js
    assert "（未启动）" in js
    assert "localButton.disabled = false;" in js
    assert "localButton.disabled = state.lockedModel !== 'local';" not in js
    assert "localStorage.removeItem('wa_ai_output_mode');" in js
    assert "border-bottom: 1px solid var(--border);" in css
    assert "--ai-bg: #FFFFFF;" in css
    assert "--ai-surface: #FBFCFE;" in css
    assert "--ai-border: rgba(15, 23, 42, 0.10);" in css
    assert "#wa-ai {" in css
    assert "background: var(--ai-bg);" in css
    assert "border: 1px solid color-mix(in srgb, var(--ai-border) 70%, transparent);" in css


def test_ai_file_attachment_loading_has_timeout_failure_and_retry_controls():
    js = _read("web/static/js/workspace-assistant.js")
    css = read_workspace_stylesheet_contract()

    assert "_WA_AI_CONTEXT_PREVIEW_TIMEOUT_MS" in js
    assert "_WA_AI_LOCAL_SAVE_TIMEOUT_MS" in js
    assert "AbortController" in js
    assert "Promise.race([requestPromise, timeoutPromise])" in js
    assert "_startAIContextWatchdog" in js
    assert "_markAIContextFileFailed" in js
    assert "_fetchJsonWithTimeout('/api/v1/workspace/ai_context_preview'" in js
    assert "文件读取超时，请重试或选择较小文件" in js
    assert "placeholder.error" in js
    assert "WA.retryAIFileContext" in js
    assert "ctx-row-retry" in js
    assert "请先重试或移除读取失败的文件" in js
    assert "_readyAIFileContext()" in js
    assert ".wa-ctx-file-row.error" in css
    assert ".ctx-row-retry" in css


def test_workspace_file_task_refresh_normalizes_workspace_paths():
    assistant = _read("web/static/js/workspace-assistant.js")
    task_runtime = _read("web/static/js/workspace-ai-task.js")
    refresh = _read("web/static/js/workspace-ai-task-refresh.js")

    assert "window.WA.normalizeWorkspaceFilePath = _normalizeReviewProgressPath;" in assistant
    assert "const marker = '/workspace/';" in assistant
    assert "lowered.lastIndexOf(marker)" in assistant
    assert "normalizePath: (path) => (" in task_runtime
    assert "typeof window.WA.normalizeWorkspaceFilePath === 'function'" in task_runtime
    assert "const normalizePath = typeof options.normalizePath === 'function'" in refresh
    assert "String(normalizePath(path) || path || '')" in refresh
    assert "['pending', 'refreshing', 'reloaded'].includes(previousStatus)" in refresh


def test_workspace_file_rows_stay_clickable_when_scrolled_under_headers():
    css = read_workspace_stylesheet_contract()

    assert ".wa-file-item {" in css
    assert "z-index: 1;" in css
    assert "scroll-margin-block-start: 72px;" in css
    assert "#wa-recent-list {" in css
    assert "max-height: 168px;" in css
    assert "overflow-y: auto;" in css


def test_workspace_file_task_flow_is_primary_frontend_runtime():
    assistant = _read("web/static/js/workspace-assistant.js")
    dispatcher = _read("web/static/js/workspace-task-dispatcher.js")
    task_runtime = _read("web/static/js/workspace-ai-task.js")
    asset_partial = _read("web/templates/_workspace_asset_scripts.html")

    assert "workspace-ai-task.js" in asset_partial
    assert asset_partial.index("workspace-ai-task.js") < asset_partial.index("workspace-task-dispatcher.js")
    assert "function buildFileTaskPayload(text, pinnedSelText, pinnedSelSource, overrides)" in dispatcher
    assert "const payload = buildFileTaskPayload(context.text, context.pinnedSelText, context.pinnedSelSource, context);" in dispatcher
    assert "const streamFileTask = typeof options.streamFileTask === 'function'" in dispatcher
    assert "return Promise.resolve(streamFileTask({" in dispatcher
    assert "streamFileTask: (options) => window.WA.streamFileTask(options)," in assistant
    assert "window.WA.streamFileTask = async function streamFileTask(options)" in task_runtime
    assert "window.WA.resumePersistedFileTask = function resumePersistedFileTask(options)" in task_runtime
    assert "window.WA.cancelFileTaskRun = async function cancelFileTaskRun(runId)" in task_runtime
    assert "function applyUiState(card, uiState)" in task_runtime
    assert "if (kind === 'progress') return;" in task_runtime
    assert 'data-role="ui-progress"' in task_runtime
    assert ".wa-task-progress-track" in read_workspace_stylesheet_contract()
    retired = "white" + "box"
    assert "stream" + "White" + "box" + "Task" not in task_runtime
    assert "resumePersisted" + "White" + "box" + "Task" not in task_runtime
    assert "cancel" + "White" + "box" + "TaskRun" not in task_runtime
    assert "stream" + "White" + "box" + "Task" not in dispatcher
    assert "build" + "White" + "box" + "TaskPayload" not in dispatcher
    assert "file_task_" + retired not in assistant
    assert retired not in assistant.lower()
    assert retired not in dispatcher.lower()
    assert retired not in task_runtime.lower()
