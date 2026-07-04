from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_file_task_refresh_controller_treats_no_pending_refresh_as_noop():
    refresh_js = _read("web/src/workspace/task-refresh.ts")

    assert "return { ok: true, refreshed: false };" in refresh_js
    assert "const didRefresh = refreshResult ? refreshResult.refreshed : false;" in refresh_js
    assert "finalizeOptions.showRefreshingStatus && didRefresh" in refresh_js
    assert "options.setStatus(card, refreshOk ? '已刷新文件' : '文件刷新失败');" in refresh_js
    assert "WA.createFileTaskRefreshController = createFileTaskRefreshController;" in refresh_js


def test_file_task_refresh_normalizes_workspace_prefixed_paths():
    refresh_js = _read("web/src/workspace/task-refresh.ts")
    review_js = _read("web/src/workspace/docx-review-runtime.ts")

    assert "const rawPath = payload.path || payload.file_path || payload.output_path || payload.target_path;" in refresh_js
    assert "const path = normalizePath(rawPath || '') || rawPath;" in refresh_js
    assert "return normalizedPath.replace(/^\\//, '').replace(/^workspace\\//i, '');" in review_js
