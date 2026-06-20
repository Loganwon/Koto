from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_workspace_templates_remove_top_settings_use_bottom_toggle_and_keep_files_above_input():
    embedded_html = _read("web/templates/index.html")
    standalone_html = _read("web/templates/workspace_assistant.html")
    model_controls = _read("web/templates/_workspace_model_controls.html")
    settings_panel = _read("web/templates/_settings_panel.html")

    for html in (embedded_html, standalone_html):
        assert 'id="wa-subject-bar"' not in html
        assert '当前编辑' not in html
        assert 'id="wa-ai-settings-panel"' not in html
        assert 'AI 输出模式' not in html
        assert 'id="wa-footer-file-chip"' not in html
        assert 'id="wa-footer-attach-current-btn"' not in html
        assert "{% include '_workspace_model_controls.html' %}" in html
        assert "能总结分析、改写润色、生成文档、整理文件。输入任务或附加文件，过程和结果都会显示在这里。" in html
        assert '快速读懂当前文件' not in html
        assert '当前文件、选区和附件会自动并入上下文。' not in html
        assert '未选择时处理当前文件' not in html
        assert 'id="wa-actions-bar"' not in html
        assert 'class="wa-quick-btn"' not in html
        assert '润色表达' not in html
        assert '翻译内容' not in html
        assert '提炼要点' not in html
        assert '检查问题' not in html
        assert 'WA.openMyFiles' not in html
        assert 'title="我的文件' not in html
        assert 'id="wa-skill-lib-btn"' not in html
        assert 'id="wa-settings-btn"' not in html
        assert 'id="wa-settings-popover"' not in html
        assert 'id="wa-theme-toggle-btn"' not in html
        assert 'id="wa-pick-local-file-btn"' not in html
        assert 'id="wa-pick-local-folder-btn"' not in html
        assert 'id="wa-local-btns" hidden' in html
        assert '本地文件助手' in html
        assert 'title="添加文件到工作区">添加文件</button>' in html
        assert 'title="打开本地文件">打开</button>' in html
        assert html.index('<div id="wa-ai-file-chips"') < html.index('<div class="wa-input-box">')
        assert html.index('<div class="wa-input-box-footer">') < html.index("{% include '_workspace_model_controls.html' %}")
        assert html.index("{% include '_workspace_model_controls.html' %}") < html.index('<div class="wa-footer-actions">')
        assert html.index('<div class="wa-footer-actions">') < html.index('id="wa-send-btn"')

    assert 'id="navSkillsBtn"' in embedded_html
    assert 'id="navSettingsBtn"' in embedded_html
    assert 'id="navNewAiSessionBtn"' not in embedded_html
    assert 'id="navWorkspaceBtn"' not in embedded_html
    assert 'id="navAiSessionsBtn"' not in embedded_html
    assert 'id="navSkillsBtn" data-label="技能"' in embedded_html
    assert 'id="navSettingsBtn" data-label="设置"' in embedded_html

    assert 'id="wa-model-mode-toggle"' in model_controls
    assert 'id="wa-model-mode-deepseek-btn"' in model_controls
    assert 'id="wa-model-mode-local-btn"' in model_controls
    assert 'id="wa-model-mode-gemini-btn"' not in model_controls
    assert 'class="wa-model-mode-main">Gemini<' not in model_controls
    assert 'class="wa-model-mode-main">DeepSeek<' in model_controls
    assert 'id="wa-model-mode-gemini-model"' not in model_controls
    assert 'id="wa-model-mode-deepseek-model"' in model_controls
    assert 'id="wa-model-mode-local-model"' in model_controls
    assert "Gemini" not in model_controls
    assert 'data-model-mode="gemini"' not in model_controls
    assert "Gemini" not in settings_panel
    assert 'value="gemini"' not in settings_panel
    assert "DeepSeek" in settings_panel


def test_workspace_shell_has_no_legacy_my_files_entrypoints():
    index_template = _read("web/templates/index.html")
    standalone_template = _read("web/templates/workspace_assistant.html")
    app_main = _read("web/src/app/main.ts")
    app_chat_ui = _read("web/src/app/chat-ui.ts")
    app_marketplace = _read("web/src/app/marketplace.ts")
    workspace_fs_actions = _read("web/src/workspace/fs-actions.ts")

    for source in (index_template, standalone_template, app_main, app_chat_ui, app_marketplace, workspace_fs_actions):
        assert "openFileHubModal" not in source
        assert "filehubModal" not in source
        assert "FileHub" not in source
        assert "my_files=1" not in source
        assert "WA.openMyFiles" not in source
        assert "myStuffItem" not in source
        assert "myStuffList" not in source
        assert "toggleMyStuff" not in source

    assert "文件索引" not in index_template


def test_workspace_activity_panels_use_live_backend_routes():
    app_marketplace = _read("web/src/app/marketplace.ts")
    app_settings = _read("web/src/app/settings.ts")
    skills_panel = _read("web/src/skills/skills-panel.ts")
    embedded_mode = _read("web/src/ui/embedded-mode.ts")
    static_task_workbench = _read("web/static/js/workspace-task-workbench.js")

    assert "fetch('/api/skills/bindings?binding_type=intent')" in app_marketplace
    assert "`/api/skills/bindings/${encodeURIComponent(bindingId)}`" in app_marketplace
    assert "fetch('/api/jobs/triggers')" in app_marketplace
    assert "`/api/jobs/triggers/${encodeURIComponent(triggerId)}`" in app_marketplace
    assert "/api/skill-bindings" not in app_marketplace
    assert "/api/triggers" not in app_marketplace
    assert "setActivityActive('navSettingsBtn')" in app_settings
    assert "export function toggleSettings()" in app_settings
    assert "(window as any).toggleSettings = toggleSettings" in app_settings
    assert "_setActivityActive('navSkillsBtn')" in skills_panel
    assert "isUnifiedWorkspace()" in app_settings
    assert "_isUnifiedWorkspace()" in skills_panel
    assert "function _closeAuxiliaryPanels()" in embedded_mode
    assert "_closeAuxiliaryPanels();" in embedded_mode
    assert "export function showFileWorkspace()" in embedded_mode
    assert "export function showAiWorkspace()" in embedded_mode
    assert "(window as any).WA.showFileWorkspace = showFileWorkspace" in embedded_mode
    assert "(window as any).WA.showAiWorkspace = showAiWorkspace" in embedded_mode
    task_workbench_ts = _read("web/src/workspace/task-workbench.ts")
    assert "function syncTaskColumnToggle" not in task_workbench_ts
    assert "toggleTaskWorkbench" not in task_workbench_ts
    assert "openTaskWorkbenchForCurrentRun" in task_workbench_ts
    assert "function syncTaskColumnToggle" not in static_task_workbench
    assert "toggleTaskWorkbench" not in static_task_workbench
    assert "openTaskWorkbenchForCurrentRun" in static_task_workbench
    assert "csrfFetch('/api/local-model/switch'" in app_settings
    assert "_spCsrfFetch('/api/bg-agent/submit'" in skills_panel


def test_workspace_has_single_unified_frontend_entry():
    pages_bp = _read("web/blueprints/pages.py")
    embedded_mode = _read("web/src/ui/embedded-mode.ts")
    legacy_assistant = _read("web/static/js/workspace-assistant.js")
    build_notes = _read("web/univer-editor/BUILD.md")
    workspace_bff = _read("web/blueprints/workspace_assistant.py")

    assert '@pages_bp.route("/workspace-assistant")' in pages_bp
    assert 'redirect(target, code=302)' in pages_bp
    assert 'request.query_string' in pages_bp
    assert 'render_template("workspace_assistant.html")' not in pages_bp
    assert "window.open('/workspace-assistant'" not in embedded_mode
    assert "window.open('/workspace-assistant'" not in legacy_assistant
    assert "window.open('/', '_blank')" in embedded_mode
    assert "window.open('/', '_blank')" in legacy_assistant
    assert "the only supported app entry is `/`" in build_notes
    assert "`/workspace-assistant` is a compatibility redirect to `/`" in build_notes
    assert '"js" / "build" / "workspace-bundle.js"' in workspace_bff
    assert '"js" / "build" / "review-bundle.js"' in workspace_bff
    assert '"js" / "workspace-assistant.js"' not in workspace_bff


def test_launcher_uses_single_unified_desktop_entry():
    launcher_ps1 = _read("Koto_Start.ps1")
    launcher_bat = _read("Koto_Start.bat")
    launcher_vbs = _read("Koto_Start.vbs")
    launcher_guide = _read("docs/LAUNCHER_GUIDE.md")
    project_structure = _read("docs/PROJECT_STRUCTURE.md")

    assert "Koto 统一桌面启动器 v3.1" in launcher_ps1
    assert "function Normalize-RunMode" in launcher_ps1
    assert "silent 模式已并入统一桌面入口" in launcher_ps1
    assert "server 仅用于开发调试" in launcher_ps1
    assert "function Get-UnifiedAppUrl" in launcher_ps1
    assert 'Start-Process "http://127.0.0.1:$Port"' not in launcher_ps1
    assert 'Start-Process "http://127.0.0.1:$openPort"' not in launcher_ps1
    assert "Koto_Start.bat silent    → 兼容别名，等同 desktop" in launcher_bat
    assert 'if /I "%MODE%"=="silent" set "MODE=desktop"' in launcher_bat
    assert "正在启动统一入口" in launcher_bat
    assert "-Mode desktop" in launcher_vbs

    for doc in (launcher_guide, project_structure):
        assert "src/koto_app.py" in doc
        assert "-> /" in doc
        assert "/workspace-assistant" in doc
        assert "RunSource.bat" not in doc
        assert "run_desktop" not in doc
        assert "Koto.exe" not in doc


def test_workspace_retained_legacy_files_are_documented_as_compatibility_contracts():
    retained_map = _read("docs/WORKSPACE_RETAINED_LEGACY.md")
    project_structure = _read("docs/PROJECT_STRUCTURE.md")
    workspace_bff = _read("web/blueprints/workspace_assistant.py")
    legacy_js = _read("web/static/js/workspace-assistant.js")
    legacy_template = _read("web/templates/workspace_assistant.html")
    pages_bp = _read("web/blueprints/pages.py")

    for path in (
        "web/blueprints/workspace_assistant.py",
        "web/static/js/workspace-assistant.js",
        "web/templates/workspace_assistant.html",
        "web/static/css/workspace-assistant.css",
        "web/blueprints/pages.py:/workspace-assistant",
    ):
        assert path in retained_map

    assert "Do not remove a retained legacy-named file only because the name looks old." in retained_map
    assert "docs/WORKSPACE_RETAINED_LEGACY.md" in project_structure
    assert "The module name `workspace_assistant` is legacy" in workspace_bff
    assert "active runtime code" in workspace_bff
    assert "Koto WA compatibility runtime and editor contract surface." in legacy_js
    assert "do not revive" in legacy_js
    assert "Retained compatibility fixture." in legacy_template
    assert "/workspace-assistant redirects to /" in legacy_template
    assert 'render_template("workspace_assistant.html")' not in pages_bp
    assert "redirect(target, code=302)" in pages_bp


def test_workspace_subject_bar_and_action_row_styles_support_restored_layout():
    js = _read("web/static/js/workspace-assistant.js")
    css = _read("web/static/css/workspace.css")
    dispatcher = _read("web/static/js/workspace-task-dispatcher.js")

    assert "toggleCurrentFileAIContext" not in js
    assert "addCurrentFileToAIContext" not in js
    assert "attachCurrentFileToAIContext" not in js
    assert "_ensureCurrentFileAttachedForQuickAction" not in js
    assert "只处理用户明确提供的选中文本和分析文档" in js
    assert "未选择时处理当前文件" not in js
    assert "当前文件上下文" not in js
    assert "处理当前文件任务" not in js
    assert "files.push(currentFile)" not in dispatcher
    assert "getCurrentAIContextPath" not in dispatcher
    assert "looksLikeCurrentFileMutation" not in dispatcher
    assert "currentFile: explicitTaskPayload.current_file || null," in dispatcher
    assert "const currentFile = payload.currentFile || null;" in dispatcher
    assert "按提取文本估算" not in js
    assert "open_tabs: []," in js
    assert "当前文件: ${state.fileName}" not in js
    assert "#wa-subject-bar { display: none !important;" not in css
    assert ".wa-actions-spacer" not in css
    assert "#wa-actions-bar" not in css
    assert ".wa-quick-btn" not in css
    assert ".wa-model-mode-toggle" in css
    assert ".wa-model-mode-toggle-btn" in css
    assert ".wa-model-mode-sub[hidden]" in css
    assert ".wa-model-mode-sub::before" in css
    assert "#wa-local-btns[hidden] { display: none !important; }" in css
    assert "content: '类型'" in css
    assert "content: attr(data-label);" in css
    assert "position: fixed;" in css
    assert "body.koto-unified-workspace.settings-panel-open .main-content" in css
    assert ".app-shell.koto-unified-workspace .settings-panel," in css
    assert ".app-shell.koto-unified-workspace .skills-panel {" in css
    assert ".app-shell.koto-unified-workspace .settings-panel.active" in css
    assert ".app-shell.koto-unified-workspace .skills-panel.active" in css
    assert "transform: none !important;" in css
    assert "visibility: hidden;" in css
    assert "pointer-events: none;" in css
    assert "transition: opacity 0.12s ease, visibility 0s linear 0.12s;" in css
    assert "pointer-events: auto;" in css
    assert "_coerceModelLabel" in js
    assert "wa_model_choice_explicit" in js
    assert "_currentCloudModelHint" in js
    assert "_localRuntimeModel" in js
    assert "localStorage.removeItem('wa_ai_output_mode');" in js
    assert "border-bottom: 1px solid var(--border);" in css
    assert "--ai-bg: #FFFFFF;" in css
    assert "--ai-surface: #FBFCFE;" in css
    assert "--ai-border: rgba(15, 23, 42, 0.10);" in css
    assert "#wa-ai {" in css
    assert "background: var(--ai-bg);" in css
    assert "border: 1px solid color-mix(in srgb, var(--ai-border) 70%, transparent);" in css
