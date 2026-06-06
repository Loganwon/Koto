from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_file_task_refresh_controller_treats_no_pending_refresh_as_noop():
    refresh_js = _read("web/static/js/workspace-ai-task-refresh.js")

    assert "return { ok: true, refreshed: false };" in refresh_js
    assert "const didRefresh = refreshResult && typeof refreshResult === 'object'" in refresh_js
    assert "finalizeOptions.showRefreshingStatus && didRefresh" in refresh_js
    assert "options.setStatus(card, refreshOk ? '已刷新文件' : '文件刷新失败');" in refresh_js
