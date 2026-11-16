from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "app" / "core" / "agent"


def test_deprecated_read_evidence_facade_is_removed() -> None:
    assert not (AGENT_ROOT / "file_task_readonly_reconciliation.py").exists()


def test_runtime_uses_focused_evidence_modules_directly() -> None:
    adapter = (AGENT_ROOT / "file_task_kernel_adapter.py").read_text(encoding="utf-8")
    finalization = (AGENT_ROOT / "file_task_finalization.py").read_text(
        encoding="utf-8"
    )

    assert "from app.core.agent.file_task_evidence_guard import" in adapter
    assert not (AGENT_ROOT / "file_task_evidence_runtime.py").exists()
    assert "from app.core.agent.file_task_completion_gates import" not in adapter
    assert "from app.core.agent.file_task_completion_gates import" in finalization
    assert "file_task_readonly_reconciliation import" not in adapter
    assert "file_task_readonly_reconciliation import" not in finalization
