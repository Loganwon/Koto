from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_workspace_templates_keep_file_tab_bar_before_canvas_body():
    embedded_html = _read("web/templates/index.html")

    assert '<div id="wa-tab-bar"></div>' in embedded_html
    assert embedded_html.index('<div id="wa-tab-bar"></div>') < embedded_html.index('<div id="wa-canvas-body">')


def test_workspace_tab_bar_js_renders_file_labels_without_capability_badges():
    js = _read("web/src/workspace/state.ts")

    assert "function _tabDisplayInfo(tab:" in js
    assert "bar.classList.toggle('single-tab', state.openTabs.length <= 1);" in js
    assert 'data-ext="${extAttr}"' in js
    assert '<span class="tab-main">' in js
    assert '<span class="tab-badge">${badgeEsc}</span>' not in js
    assert "能力：" not in js
    assert "支持：" not in js


def test_workspace_frontend_tracks_capability_profile_in_tab_state_without_visible_badges():
    js = "\n".join(
        [
            _read("web/src/workspace/file-open.ts"),
            _read("web/src/workspace/state.ts"),
            _read("web/templates/index.html"),
            _read("web/static/css/workspace.css"),
        ]
    )

    assert "capabilityProfile: _normalizeCapabilityProfile(json.capability_profile, fileType, fileName)" in js
    assert "state.capabilityProfile = tab.capabilityProfile || null;" in js
    assert "function _ensureSubjectBar()" not in js
    assert "_capabilityPrimaryBadge" not in js
    assert "_capabilityActionList" not in js
    assert "wa-subject-capability-list" not in js
    assert "subject-capability-chip" not in js


def test_workspace_tab_capability_display_does_not_auto_attach_current_file_to_ai_flow():
    js = "\n".join(
        [
            _read("web/src/workspace/quick-actions.ts"),
            _read("web/src/workspace/ai-context.ts"),
            _read("web/src/workspace/task-dispatcher.ts"),
            _read("web/templates/index.html"),
        ]
    )

    assert "function _subjectQuickActions(profile)" not in js
    assert "async function _ensureCurrentFileAttachedForQuickAction()" not in js
    assert "window.WA.runCapabilityQuickAction = async (action) =>" not in js
    assert "window.WA.attachCurrentFileToAIContext" not in js
    assert "wa-subject-action-list" not in js
    assert "subject-action-btn wa-quick-btn wf-chip" not in js


def test_workspace_tab_bar_css_has_document_chrome_and_file_type_accents():
    css = _read("web/static/css/workspace.css")

    assert "#wa-tab-bar.single-tab .wa-tab" in css
    assert '.wa-tab[data-ext="docx"]' in css
    assert ".wa-tab::before" in css
    assert ".wa-tab .tab-badge" not in css
    assert ".subject-capability-chip" not in css
    assert ".subject-action-list" not in css
    assert ".subject-action-btn" not in css
