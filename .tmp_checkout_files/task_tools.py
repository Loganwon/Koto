from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.agent._pyc_restore import restore_current_module


restore_current_module(__file__, globals())


_compiled_run_python_in_sandbox = run_python_in_sandbox


def _best_effort_remove_tree(path: str) -> None:
    if not path or not os.path.isdir(path):
        return

    def _onerror(func, failed_path, _exc_info):
        try:
            os.chmod(failed_path, 0o666)
        except OSError:
            pass
        try:
            func(failed_path)
        except OSError:
            pass

    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return
    except OSError:
        try:
            shutil.rmtree(path, onerror=_onerror)
        except OSError as exc:
            logger.warning("[task_tools] Temp sandbox cleanup skipped for %s: %s", path, exc)


def run_python_in_sandbox(
    code: str,
    timeout: int = 30,
    task_files: Optional[List[Dict[str, str]]] = None,
):
    """Run sandboxed Python with best-effort temp cleanup on Windows.

    The compiled implementation used TemporaryDirectory() under a broad
    try/except, so a late cleanup WinError 32 could overwrite an otherwise
    successful execution with "Sandbox error: ...". This version keeps the
    existing staging/sync/marker behavior but never treats temp cleanup as a
    tool failure.
    """
    from app.core.sandbox import run_python

    resolved_task_files = _resolve_task_file_entries(task_files or [])
    tmpdir = tempfile.mkdtemp(prefix="koto-task-")

    try:
        staged_entries = _stage_task_files_for_sandbox(resolved_task_files, tmpdir)
        prepared_code = _prepend_task_file_context(code, staged_entries)
        result = run_python(prepared_code, timeout)
        result = _sync_staged_files_to_source(staged_entries, result)
        return _wrap_sandbox_result(result)
    except Exception as exc:
        return f"Sandbox error: {exc}"
    finally:
        _best_effort_remove_tree(tmpdir)


TaskToolsPlugin._code_execution.__globals__["run_python_in_sandbox"] = run_python_in_sandbox