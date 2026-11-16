import re
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_css(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    linked = []
    for ref in re.findall(r'@import\s+url\(["\'](\./[^"\']+)["\']\)', source):
        linked.append((path.parent / ref).read_text(encoding="utf-8"))
    return source + "\n" + "\n".join(linked)


def test_ai_session_history_uses_aligned_grid_rows():
    css = _read_css(_repo_root() / "web/static/css/workspace-shell.css")
    assert ".koto-task-row" in css
    assert ".koto-task-item" in css
    assert ".koto-task-row:focus-within .koto-task-delete" in css
    assert "text-overflow: ellipsis" in css


def test_ai_session_history_header_actions_are_koto_buttons():
    root = _repo_root()
    template = (root / "web/templates/index.html").read_text(encoding="utf-8")
    sidebar = (root / "web/templates/_workspace_sidebar.html").read_text(
        encoding="utf-8"
    )
    component = (
        root / "web/src/workspace/components/koto-conversation-list.ts"
    ).read_text(encoding="utf-8")
    assert "_workspace_sidebar.html" in template
    assert 'id="wa-ai-session-list-view"' not in template
    assert sidebar.count('id="wa-ai-session-list-view"') == 1
    assert 'data-koto-shell-action="new"' in sidebar
    assert 'aria-label="刷新任务"' in component
    assert 'id="wa-session-list-composer-host"' not in template + component
    assert 'id="chatView"' not in template


def test_ai_session_history_clear_all_requires_confirmation():
    src = (
        _repo_root() / "web" / "src" / "workspace" / "conversation-list.ts"
    ).read_text(encoding="utf-8")

    assert "export async function clearAiSessions" in src
    assert "window.confirm(`确认清除全部 ${count} 条历史对话？此操作不可撤销。`)" in src
    assert "await deleteAiSessionRecord(session.id)" in src
    assert "_sessions = []" in src
    assert "_activeAiSessionId = ''" in src
    assert "_sessionActionsBusy = true" in src
    assert "_updateComponent()" in src
    assert "clearAiSessions," in src
    assert "registerFeatures({" in src


def test_completed_task_history_cards_are_readonly_and_collapsible():
    conversation_src = (
        _repo_root() / "web" / "src" / "workspace" / "conversation.ts"
    ).read_text(encoding="utf-8")
    task_src = (
        _repo_root() / "web" / "src" / "workspace" / "task-runner.ts"
    ).read_text(encoding="utf-8")
    recovery_src = (
        _repo_root() / "web" / "src" / "workspace" / "task-run-recovery.ts"
    ).read_text(encoding="utf-8")
    css = (
        _repo_root() / "web" / "static" / "css" / "workspace-task-flow.css"
    ).read_text(encoding="utf-8")

    assert (
        "function applyTaskHistoryMetadata(element: HTMLElement | null, turn: WATurn): void"
        in conversation_src
    )
    assert "turn.task_card_snapshot" in conversation_src
    assert "import { restoreTaskRunCard } from './task-runner';" in conversation_src
    assert "workspaceApi.restoreTaskRunCard" not in conversation_src
    assert (
        "!taskTurnIsTerminal(turn) && workspaceApi.restoreTaskRunCard"
        not in conversation_src
    )
    assert "function taskTurnIsTerminal(" not in conversation_src
    assert "element.dataset.taskMemorySummary = memorySummary" in conversation_src
    assert "syncTaskInteractionSummary(element)" in conversation_src
    assert "workspaceApi.syncTaskInteractionSummary" not in conversation_src
    assert "const markTaskRunCardAsHistory = (" in recovery_src
    assert "card.dataset.historyStatus = historyStatus || 'history'" in recovery_src
    assert "process.removeAttribute('open')" in recovery_src
    assert "process.dataset.historyCollapsed = 'true'" in recovery_src
    assert "statusEl.textContent = statusText" in recovery_src
    assert "function markTaskRunCardAsHistory" not in task_src
    assert (
        "#wa-ai-messages .wa-task-run.is-compact.is-history-snapshot .wa-task-header"
        in css
    )
    assert '.wa-task-history-badge[data-status="completed"]' in css
