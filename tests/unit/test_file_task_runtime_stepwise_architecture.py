from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "app" / "core" / "agent"


def test_file_task_runtime_has_one_kernel_execution_entry() -> None:
    runtime = (AGENT_ROOT / "runtime" / "read_phase.py").read_text(encoding="utf-8")
    adapter = (AGENT_ROOT / "file_task_kernel_adapter.py").read_text(encoding="utf-8")
    kernel = (AGENT_ROOT / "kernel" / "runtime.py").read_text(encoding="utf-8")

    assert "FileTaskKernelAdapter(self).stream(" in runtime
    assert "KernelRuntime(" in adapter
    assert "while True" not in adapter
    assert "for round_index in" not in adapter
    assert kernel.count("while True") == 1


def test_retired_file_task_execution_routes_stay_deleted() -> None:
    for name in (
        "file_task_execution_loop.py",
        "file_task_docx_stepwise.py",
        "file_task_doc_annotate_runner.py",
        "file_task_docx_stepwise_runner.py",
        "file_task_doc_annotate_fallback.py",
        "file_task_readonly_loop_guard.py",
        "file_task_guard_emission.py",
        "file_task_evidence_runtime.py",
        "file_task_intent_adjudicator.py",
    ):
        assert not (AGENT_ROOT / name).exists(), name


def test_file_task_phases_do_not_import_runtime_facade() -> None:
    for name in (
        "file_task_context_read.py",
        "file_task_kernel_adapter.py",
        "file_task_finalization.py",
        "file_task_planning.py",
    ):
        source = (AGENT_ROOT / name).read_text(encoding="utf-8")
        assert "from app.core.agent.file_task_runtime import" not in source
        assert "import app.core.agent.file_task_runtime" not in source


def test_file_task_planning_is_deterministic_before_kernel() -> None:
    planning = (AGENT_ROOT / "file_task_planning.py").read_text(encoding="utf-8")

    assert "_adjudicate_intent_if_needed" not in planning
    assert "_call_model(" not in planning
    assert "intent_adjudication: Dict[str, Any] = {}" in planning
