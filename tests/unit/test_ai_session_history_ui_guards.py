from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_ai_session_history_uses_aligned_grid_rows():
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )

    assert ".wa-ai-session-item" in css
    assert "grid-template-columns: 24px minmax(0, 1fr) 28px" in css
    assert ".wa-ai-session-top" in css
    assert "grid-template-columns: minmax(0, 1fr) auto" in css
    assert ".wa-ai-session-item.is-active .wa-ai-session-delete" in css


def test_ai_session_history_header_actions_are_koto_buttons():
    css = "\n".join(
        (
            (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
                encoding="utf-8"
            ),
            (
                _repo_root() / "web" / "static" / "css" / "workspace-ai-panel.css"
            ).read_text(encoding="utf-8"),
        )
    )
    template = (_repo_root() / "web" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )

    assert ".wa-ai-session-title-group strong" in css
    assert ".wa-ai-session-actions > button" in css
    assert ".wa-ai-session-actions > .wa-ai-session-new-btn" in css
    assert ".wa-ai-session-actions > .wa-ai-session-clear-btn:hover" in css
    assert ".wa-ai-session-list::-webkit-scrollbar-thumb" in css
    assert 'id="wa-ai-session-clear"' in template
    assert "WA.clearAiSessions" in template
    assert 'id="wa-ai-session-summary"' in template


def test_ai_session_history_clear_all_requires_confirmation():
    src = (
        _repo_root() / "web" / "src" / "workspace" / "conversation-list.ts"
    ).read_text(encoding="utf-8")

    assert "export async function clearAiSessions" in src
    assert "window.confirm(`确认清除全部 ${count} 条历史对话？此操作不可撤销。`)" in src
    assert "await deleteAiSessionRecord(sessionId)" in src
    assert "runtime.reset()" in src
    assert "_sessionActionsBusy = true" in src
    assert "summary.textContent = _sessions.length" in src
    assert "clearAiSessions," in src
    assert "publishWorkspaceApi({" in src


def test_completed_task_history_cards_are_readonly_and_collapsible():
    conversation_src = (
        _repo_root() / "web" / "src" / "workspace" / "conversation.ts"
    ).read_text(encoding="utf-8")
    task_src = (
        _repo_root() / "web" / "src" / "workspace" / "task-runner.ts"
    ).read_text(encoding="utf-8")
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )

    assert (
        "function applyTaskHistoryMetadata(element: HTMLElement | null, turn: WATurn): void"
        in conversation_src
    )
    assert (
        "turn.task_card_snapshot && typeof workspaceApi.restoreTaskRunCard === 'function'"
        in conversation_src
    )
    assert (
        "!taskTurnIsTerminal(turn) && workspaceApi.restoreTaskRunCard"
        not in conversation_src
    )
    assert "element.dataset.taskMemorySummary = memorySummary" in conversation_src
    assert "workspaceApi.syncTaskInteractionSummary(element)" in conversation_src
    assert "function markTaskRunCardAsHistory" in task_src
    assert "card.dataset.historyStatus = historyStatus || 'history'" in task_src
    assert "process.removeAttribute('open')" in task_src
    assert "process.dataset.historyCollapsed = 'true'" in task_src
    assert "statusEl.textContent = statusText" in task_src
    assert (
        "#wa-ai-messages .wa-task-run.is-compact.is-history-snapshot .wa-task-header"
        in css
    )
    assert '.wa-task-history-badge[data-status="completed"]' in css
