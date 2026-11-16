from dataclasses import fields
from pathlib import Path

from app.core.agent.file_task_contract import FileTaskClassification, FileTaskIntentPlan

ROOT = Path(__file__).resolve().parents[2]


def test_file_task_stream_delegates_ledger_and_progress_persistence() -> None:
    stream = (ROOT / "app" / "core" / "services" / "file_task_stream.py").read_text(
        encoding="utf-8"
    )

    assert len(stream.splitlines()) < 1000
    assert "from app.core.tasks.task_ledger import" not in stream
    assert "from app.core.tasks.progress_bus import" not in stream
    assert "ledger.mark_" not in stream
    assert "ledger.add_step" not in stream
    assert "persist_file_task_progress_event(" in stream


def test_file_task_stream_delegates_public_event_safety() -> None:
    stream = (ROOT / "app" / "core" / "services" / "file_task_stream.py").read_text(
        encoding="utf-8"
    )

    assert "def safe_editor_sse(" not in stream
    assert "def _safe_file_task_event_dict(" not in stream
    assert "from app.core.services.file_task_event_safety import" in stream
    assert "from web." not in stream


def test_task_dispatcher_uses_one_context_attachment_entrypoint() -> None:
    dispatcher = (ROOT / "web" / "src" / "workspace" / "task-dispatcher.ts").read_text(
        encoding="utf-8"
    )

    assert "buildTaskContextPackage(" not in dispatcher
    assert dispatcher.count("attachTaskContextPackage(") == 3


def test_file_tasks_use_kernel_without_a_second_execution_loop() -> None:
    agent_root = ROOT / "app" / "core" / "agent"
    adapter = (agent_root / "file_task_kernel_adapter.py").read_text(encoding="utf-8")

    assert not (agent_root / "file_task_execution_loop.py").exists()
    assert "KernelRuntime(" in adapter
    assert "for round_index in" not in adapter
    assert "while True" not in adapter


def test_runtime_phases_depend_on_real_owners_without_shared_import_barrel() -> None:
    runtime_root = ROOT / "app" / "core" / "agent" / "runtime"

    assert not (runtime_root / "shared.py").exists()
    for phase_name in (
        "plan_phase.py",
        "read_phase.py",
        "execute_phase.py",
        "verify_phase.py",
    ):
        source = (runtime_root / phase_name).read_text(encoding="utf-8")
        assert "from .shared import" not in source


def test_retired_semantic_file_task_routes_cannot_reenter_production() -> None:
    agent_root = ROOT / "app" / "core" / "agent"
    retired_modules = {
        "file_task_doc_annotate_request.py",
        "file_task_docx_review_intent.py",
        "file_task_classification_followup.py",
        "file_task_review_intent.py",
        "runtime/intent.py",
    }

    for module_name in retired_modules:
        assert not (agent_root / module_name).exists()

    production_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in agent_root.rglob("*.py")
        if "__pycache__" not in path.parts
    )
    for retired_symbol in (
        "matched_native_capability_names",
        "native_tool_gap_for_request",
        "docx_annotation_request",
        "raw_docx_annotation_request",
        "docx_annotation_has_contract",
        "matched_capabilities",
        "is_advisory_analysis_request",
        "is_diagnostic_request",
        "advisory_analysis_request",
        "_DOCX_OR_TABLE_WRITE_REQUEST_PATTERN",
        "_PPT_WRITE_REQUEST_PATTERN",
        "_EXPLICIT_FILE_MUTATION_PATTERN",
    ):
        assert retired_symbol not in production_source


def test_kernel_separates_write_permission_from_completion_requirement() -> None:
    contract = (ROOT / "app" / "core" / "agent" / "file_task_contract.py").read_text(
        encoding="utf-8"
    )
    adapter = (
        ROOT / "app" / "core" / "agent" / "file_task_kernel_adapter.py"
    ).read_text(encoding="utf-8")
    validation = (
        ROOT / "app" / "core" / "agent" / "file_task_validation.py"
    ).read_text(encoding="utf-8")

    assert "write_authorized: bool" in contract
    assert "write_required: bool" in contract
    assert "write_authorized" in adapter
    assert "write_required" in adapter
    assert "write_required=write_required" in adapter
    assert "classification.write_required" in validation


def test_legacy_write_intent_is_not_a_public_task_contract() -> None:
    classification_fields = {field.name for field in fields(FileTaskClassification)}
    plan_fields = {field.name for field in fields(FileTaskIntentPlan)}

    assert "write_intent" not in classification_fields
    assert "write_intent" not in plan_fields

    public_projection_sources = (
        ROOT / "app" / "core" / "agent" / "file_task_messages.py",
        ROOT / "app" / "core" / "agent" / "file_task_workflow_state.py",
        ROOT / "app" / "core" / "agent" / "file_task_whitebox.py",
        ROOT / "web" / "src" / "workspace" / "task-plan-presentation.ts",
        ROOT / "web" / "src" / "workspace" / "task-workbench-projection.ts",
    )
    for source_path in public_projection_sources:
        source = source_path.read_text(encoding="utf-8")
        if source_path.suffix == ".py":
            assert '"write_intent"' not in source
        else:
            assert "write_intent" not in source

    production_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "app" / "core" / "agent").rglob("*.py")
        if "__pycache__" not in path.parts
    )
    assert '"write_intent"' not in production_source
