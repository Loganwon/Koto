# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import re
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def _css_selectors(css: str) -> set[str]:
    without_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    selectors: set[str] = set()
    for match in re.finditer(r"([^{}]+)\{", without_comments):
        raw = match.group(1).strip()
        if not raw or raw.startswith("@"):
            continue
        for selector in raw.split(","):
            selector = selector.strip()
            if selector and not selector.startswith("@"):
                selectors.add(selector)
    return selectors


def test_workspace_ai_composer_has_one_final_style_owner() -> None:
    html = _read("web/templates/index.html")
    workspace_css = _read("web/static/css/workspace.css")
    css = _read("web/static/css/workspace-ai-panel.css")

    assert html.index("css/workspace.css") < html.index("css/workspace-ai-panel.css")
    assert 'id="wa-session-list-composer-host" class="wa-composer-host"' in html
    assert 'id="wa-chat-composer-host" class="wa-composer-host"' in html
    assert html.count('id="wa-ai-input-area"') == 1
    assert html.count('id="wa-user-input"') == 1
    assert 'id="wa-user-input" class="wa-ai-composer-input"' in html
    assert "wa-session-list-input" not in html
    assert "wa-session-list-send" not in html
    assert ".wa-ai-composer-input," in css
    assert "#wa-user-input {" in css
    assert "min-height: 112px;" in css[css.index("#wa-user-input {") :]
    assert "max-height: min(360px, 42vh);" in css[css.index("#wa-user-input {") :]
    assert "flex: 1 1 240px;" in css
    assert "flex: 0 0 auto;" in css[css.index(".wa-ctx-drop-hint svg"):]
    assert "@media (max-width: 860px)" in css
    assert "flex: 1 1 auto;" in css[css.index("#wa-ai-messages {"):]
    assert "display: flex;" in css[css.index("#wa-ai-messages {"):]
    assert "flex-direction: column;" in css[css.index("#wa-ai-messages {"):]
    assert "--wa-chat-gap: 12px;" in css[css.index("#wa-ai-messages {"):]
    assert "--wa-chat-radius: 8px;" in css[css.index("#wa-ai-messages {"):]
    assert "gap: var(--wa-chat-gap);" in css[css.index("#wa-ai-messages {"):]
    assert "padding: 10px 12px 12px;" in css[css.index("#wa-ai-messages {"):]
    assert "overflow-y: auto;" in css[css.index("#wa-ai-messages {"):]
    assert ".wa-session-list-input" not in css
    assert "border-radius: 0;" in css
    for selector in (
        ".wa-ai-session-list-composer",
        ".wa-composer-host",
        ".wa-input-box",
        "#wa-user-input",
        "#wa-ai-input-area",
        ".wa-footer-meta",
        ".wa-model-mode-toggle",
        "#wa-send-btn",
        ".wa-attach-file-btn",
        ".wa-input-hint",
        ".wa-ctx-drop-hint",
    ):
        assert selector not in workspace_css
        assert selector in css


def test_workspace_ai_message_flow_has_visual_hierarchy_contract() -> None:
    css = _read("web/static/css/workspace-ai-panel.css")
    messages_block = css[css.index("#wa-ai-messages {"):]

    assert "#wa-ai-messages .wa-msg.user {" in messages_block
    assert "max-width: min(82%, calc(100% - 30px));" in messages_block
    assert "border-radius: var(--wa-chat-radius) var(--wa-chat-radius) 3px var(--wa-chat-radius);" in messages_block
    assert "#wa-ai-messages .wa-msg.ai:not(.wa-task-run) {" in messages_block
    assert "border-left: 2px solid color-mix(in srgb, var(--accent) 38%, var(--ai-border));" in messages_block
    assert "#wa-ai-messages .wa-task-run {" in messages_block
    assert "border-left: 3px solid color-mix(in srgb, var(--accent) 68%, var(--ai-border));" in messages_block
    assert "#wa-ai-messages .wa-task-run .wa-task-final-report," in messages_block
    assert "#wa-ai-messages .wa-task-final-answer {" in messages_block
    assert "background: linear-gradient(" in messages_block
    assert ".wa-ctx-drop-hint svg" in messages_block
    assert "flex: 0 0 auto;" in css[css.index(".wa-ctx-drop-hint svg"):]


def test_workspace_ai_panel_does_not_embed_legacy_skill_workflow_systems() -> None:
    html = _read("web/templates/index.html")
    workspace_css = _read("web/static/css/workspace.css")

    legacy_fragments = (
        "window.WaSkills",
        "WaSkills.",
        'id="wa-skill-bar"',
        'id="wa-skill-exec-panel"',
        'id="wa-skill-exec-body"',
        'id="wa-skill-exec-title"',
        'id="wa-workflow-panel"',
        'data-retained-legacy="skill-exec"',
    )
    for fragment in legacy_fragments:
        assert fragment not in html

    legacy_selectors = (
        "#wa-skill-lib-btn",
        "#wa-workflow-btn",
        "#wa-skill-library",
        ".wa-skill-lib-",
        ".wa-skill-start-btn",
        ".wa-skill-active-tag",
        ".wa-skill-tag",
        ".wa-workflow-panel",
        ".wa-wf-header",
        ".wa-wf-card",
        ".wa-wf-form",
        ".wa-wf-progress",
        ".wa-wf-activation-bar",
        ".wa-workflow-suggest-card",
        ".wa-suggest-",
    )
    for selector in legacy_selectors:
        assert selector not in workspace_css

    assert 'id="navSkillsBtn"' in html
    assert 'id="skillsPanel"' in html
    assert "window.KotoSkillsLoader={load:load}" in html


def test_workspace_ai_panel_css_selectors_do_not_overlap_workspace_css() -> None:
    workspace_selectors = _css_selectors(_read("web/static/css/workspace.css"))
    ai_panel_selectors = _css_selectors(_read("web/static/css/workspace-ai-panel.css"))

    overlap = sorted(
        selector
        for selector in workspace_selectors & ai_panel_selectors
        if "wa-" in selector or "#wa-" in selector
    )

    assert overlap == []


def test_workspace_ai_composer_behavior_is_shared_between_entrypoints() -> None:
    composer = _read("web/src/workspace/ai-composer.ts")
    conversation_list = _read("web/src/workspace/conversation-list.ts")
    ai_review = _read("web/src/workspace/ai-review.ts")
    bundle = _read("web/static/js/build/workspace-bundle.js")

    assert "export function resizeWorkspaceAiComposer" in composer
    assert "fallbackMaxHeight: 360" in composer
    assert "requestAnimationFrame(() => applyWorkspaceAiComposerResize(input))" in composer
    assert "pendingComposerResizeFrames" in composer
    assert "export function mountWorkspaceAiComposer" in composer
    assert "export function workspaceAiComposerMode" in composer
    assert "export function setWorkspaceAiComposerValue" in composer
    assert "export function syncWorkspaceAiComposerSendState" in composer
    assert "mountWorkspaceAiComposer('sessionList')" in conversation_list
    assert "mountWorkspaceAiComposer('chat')" in conversation_list
    assert "submitUnifiedAiComposer" in conversation_list
    assert "setWorkspaceAiComposerValue('chat', text" in conversation_list
    assert "setWorkspaceAiComposerValue('chat', text" in ai_review
    assert "wa-session-list-input" not in conversation_list
    assert "wa-chat-composer-host" in bundle
    assert "wa-session-list-composer-host" in bundle
    assert "submitUnifiedAiComposer" in bundle


def test_workspace_ai_session_api_is_split_from_list_rendering() -> None:
    sessions = _read("web/src/workspace/conversation-sessions.ts")
    conversation_list = _read("web/src/workspace/conversation-list.ts")
    bundle = _read("web/static/js/build/workspace-bundle.js")

    assert "export async function fetchAiSessionPreviews" in sessions
    assert "export async function createAiSessionRecord" in sessions
    assert "export async function deleteAiSessionRecord" in sessions
    assert "export function normalizeSession" in sessions
    assert "fetchAiSessionPreviews()" in conversation_list
    assert "createAiSessionRecord()" in conversation_list
    assert "deleteAiSessionRecord(normalized)" in conversation_list
    assert "fetch('/api/sessions?preview=1'" not in conversation_list
    assert "/api/sessions?preview=1" in bundle
