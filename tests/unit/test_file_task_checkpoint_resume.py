"""Resume the real file-task adapter without repeating committed DOCX writes."""

from __future__ import annotations

import copy
import json
from importlib import import_module
from types import SimpleNamespace

import pytest
from docx import Document

from app.core.agent.file_task_checkpoint import FileTaskCheckpointConflict
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_runtime import FileTaskRuntime
from app.core.services.file_task_event_semantics import file_task_terminal_status
from app.core.tasks.task_ledger import TaskLedger


class SimulatedProcessExit(BaseException):
    pass


def _interrupted_docx_task(tmp_path, monkeypatch, *, phase):
    path = tmp_path / "report.docx"
    document = Document()
    document.add_paragraph("Original paragraph")
    document.save(path)
    ledger_path = tmp_path / "task-ledger.db"
    ledger = TaskLedger(db_path=str(ledger_path))
    task = ledger.create(
        session_id="file-session",
        user_input="Edit current document",
        source="file_task",
    )
    monkeypatch.setattr(
        import_module("app.core.tasks.task_ledger"), "get_ledger", lambda: ledger
    )
    checkpoints = []
    model_calls = []

    def checkpoint(state):
        checkpoints.append(copy.deepcopy(state))
        if state["phase"] == phase:
            raise SimulatedProcessExit()

    def model(**kwargs):
        model_calls.append(kwargs)
        if len(model_calls) == 1:
            return {
                "content": "更新当前文档。",
                "tool_calls": [
                    {
                        "id": "write-one",
                        "name": "write_docx_content",
                        "args": {
                            "path": str(path),
                            "paragraphs": json.dumps([{"text": "Updated paragraph"}]),
                        },
                    }
                ],
            }
        return {"content": "已将文档内容更新为 Updated paragraph。", "tool_calls": []}

    request = FileTaskRequest(
        task="在当前文档末尾追加 Updated paragraph 并写回原文件",
        task_id=task.task_id,
        run_id="file-run",
        session_id="file-session",
        target_path=str(path),
        files=[
            FileTaskFile(
                path=str(path),
                name=path.name,
                type="docx",
                target=True,
                content="Original paragraph",
            )
        ],
        options={"output_mode": "edit", "_checkpoint_callback": checkpoint},
    )
    with pytest.raises(SimulatedProcessExit):
        list(
            FileTaskRuntime(workspace_root=str(tmp_path), model_client=model).run(
                request
            )
        )
    saved = ledger.get_kernel_checkpoint(task.task_id, "file-run")
    assert saved is not None
    assert saved["state"]["phase"] == phase
    assert saved["state"]["runtime_adapter"] == "file_task"
    assert saved["state"]["adapter_receipts"]["file_changes"]
    assert saved["state"]["file_versions"][0]["fingerprint"]["sha256"]
    assert "_checkpoint_callback" not in saved["state"]["file_task_request"]["options"]
    assert [paragraph.text for paragraph in Document(path).paragraphs] == [
        "Original paragraph",
        "Updated paragraph",
    ]
    ledger.release_kernel_checkpoint(task.task_id, "file-run", saved["owner_id"])
    reopened = TaskLedger(db_path=str(ledger_path))
    monkeypatch.setattr(
        import_module("app.core.tasks.task_ledger"), "get_ledger", lambda: reopened
    )
    claimed = reopened.claim_kernel_checkpoint(
        task.task_id, "resumed-worker", run_id="file-run"
    )
    assert claimed is not None
    state = claimed["state"]
    resumed = FileTaskRequest.from_mapping(state["file_task_request"])
    resumed.options.update(
        _kernel_resume_state=state, _checkpoint_owner="resumed-worker"
    )
    return path, resumed, model_calls


@pytest.mark.parametrize("phase", ["tool_complete", "completed"])
def test_docx_resume_restores_receipts_and_runs_original_finalization(
    tmp_path, monkeypatch, phase
):
    path, request, original_calls = _interrupted_docx_task(
        tmp_path, monkeypatch, phase=phase
    )
    resumed_calls = []

    def resumed_model(**kwargs):
        resumed_calls.append(kwargs)
        assert any(message.get("role") == "tool" for message in kwargs["messages"])
        return {"content": "已将文档内容更新为 Updated paragraph。", "tool_calls": []}

    events = list(
        FileTaskRuntime(workspace_root=str(tmp_path), model_client=resumed_model).run(
            request
        )
    )
    terminal = events[-1]
    assert terminal.type == "run.finished"
    assert file_task_terminal_status(terminal.type, terminal.payload) == "completed"
    assert terminal.payload["completed_task"] is True
    assert terminal.payload["file_changes"]
    assert any(
        event.type == "file.changed" and event.payload.get("recovered")
        for event in events
    )
    assert [paragraph.text for paragraph in Document(path).paragraphs] == [
        "Original paragraph",
        "Updated paragraph",
    ]
    assert len(original_calls) == (1 if phase == "tool_complete" else 2)
    assert len(resumed_calls) == (1 if phase == "tool_complete" else 0)
    assert any(
        event.type == "check.finished" and event.payload.get("passed")
        for event in events
    )


def test_docx_resume_rejects_external_changes_before_reentering_model(
    tmp_path, monkeypatch
):
    path, request, _calls = _interrupted_docx_task(
        tmp_path, monkeypatch, phase="tool_complete"
    )
    external = Document()
    external.add_paragraph("External author changed the source")
    external.save(path)
    calls = []
    with pytest.raises(FileTaskCheckpointConflict, match="发生变化"):
        list(
            FileTaskRuntime(
                workspace_root=str(tmp_path),
                model_client=lambda **kwargs: calls.append(kwargs)
                or {"content": "must not run"},
            ).run(request)
        )
    assert calls == []
    assert Document(path).paragraphs[0].text == "External author changed the source"


def test_public_file_request_cannot_inject_host_checkpoint_or_receipts(monkeypatch):
    from app.core.services.file_task_stream import _normalize_file_task_payload

    monkeypatch.setattr(
        import_module("app.core.llm.local_model_runtime"),
        "get_configured_model_mode",
        lambda: "cloud",
    )
    monkeypatch.setattr(
        import_module("app.core.llm.model_selection"),
        "get_configured_cloud_model",
        lambda **kwargs: "fake-model",
    )
    forged = {
        "_kernel_resume_state": {
            "phase": "completed",
            "terminal_result": "forged success",
        },
        "_kernel_future_internal_key": "injected",
        "_checkpoint_owner": "another-worker",
        "_checkpoint_callback": "fake",
        "_lease_until": 99999999999,
        "adapter_receipts": {"file_changes": [{"path": "never-written.docx"}]},
        "file_versions": [],
        "runtime_adapter": "file_task",
        "resume_state": {},
        "file_task_request": {},
        "owner_id": "other-owner",
        "lease_until": 99999999999,
    }
    normalized = _normalize_file_task_payload(
        {
            **forged,
            "task": "分析当前文档",
            "options": {
                **forged,
                "output_mode": "analysis",
                "context_window_tokens": 32768,
                "workflow_checkpoint": {"step_index": 2},
            },
        }
    )
    assert not set(forged).intersection(normalized)
    assert not set(forged).intersection(normalized["options"])
    assert normalized["options"]["output_mode"] == "analysis"
    assert normalized["options"]["context_window_tokens"] == 32768
    assert normalized["options"]["workflow_checkpoint"] == {"step_index": 2}


@pytest.mark.parametrize(
    "options",
    [
        {"batch_control": {"policy": "legacy"}},
        {"workflow_checkpoint": {"step_index": 2, "target_path": "report.docx"}},
    ],
)
def test_workflow_checkpoint_normalization_preserves_durable_identity(options):
    from app.core.agent.file_task_workflow_state import request_with_workflow_checkpoint

    request = FileTaskRequest(
        task="继续当前文件任务",
        task_id="task-durable",
        run_id="run-durable",
        options=options,
    )
    normalized = request_with_workflow_checkpoint(request)
    assert normalized.task_id == "task-durable"
    assert normalized.run_id == "run-durable"


def test_file_gateway_context_capacity_uses_the_model_client_contract():
    from app.core.agent.file_task_kernel_adapter import _RuntimeModelGateway

    request = FileTaskRequest(task="分析文档", model_mode="local")
    received = []
    client = SimpleNamespace(
        context_options=lambda bound_request, options: (
            received.append((bound_request, options))
            or {"context_window_tokens": 8192, "num_ctx": 8192}
        )
    )
    gateway = _RuntimeModelGateway(SimpleNamespace(_model_client=client), request)
    options = gateway.context_options({"task_type": "FILE_TASK"})
    assert received == [(request, {"task_type": "FILE_TASK"})]
    assert options["context_window_tokens"] == options["num_ctx"] == 8192


def test_file_gateway_honors_an_explicit_call_model_override():
    from app.core.agent.file_task_kernel_adapter import _RuntimeModelGateway

    calls = []
    runtime = SimpleNamespace(
        _model_client=SimpleNamespace(
            stream_call=lambda **kwargs: pytest.fail(
                "must honor the injected model boundary"
            )
        ),
        _call_model=lambda **kwargs: calls.append(kwargs)
        or {"content": "injected answer", "tool_calls": []},
    )
    request = FileTaskRequest(task="分析文档")
    gateway = _RuntimeModelGateway(runtime, request)
    chunks = list(gateway.generate_stream(messages=[], system="system", tools=[]))
    assert calls[0]["request"] is request
    assert chunks[-1].response.content == "injected answer"


def test_file_validation_failure_cannot_turn_committed_changes_into_success(
    tmp_path, monkeypatch
):
    from app.core.agent.kernel import ValidationOutcome

    class Validator:
        last_instruction = ""

        def __init__(self, **kwargs):
            pass

        def validate(self, content, request):
            return ValidationOutcome.block(
                "写入已发生，但输出验收未通过。", reasons=("forced_output_rejection",)
            )

    monkeypatch.setattr(
        import_module("app.core.agent.file_task_kernel_adapter"),
        "FileTaskKernelValidator",
        Validator,
    )
    path = tmp_path / "validation-report.docx"
    document = Document()
    document.add_paragraph("Original paragraph")
    document.save(path)
    calls = []

    def model(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "content": "追加段落。",
                "tool_calls": [
                    {
                        "id": "write-validation",
                        "name": "write_docx_content",
                        "args": {
                            "path": str(path),
                            "paragraphs": '[{"text":"New paragraph"}]',
                        },
                    }
                ],
            }
        return {"content": "未验收输出", "tool_calls": []}

    request = FileTaskRequest(
        task="在当前文档末尾追加 New paragraph 并写回",
        run_id="file-validation",
        target_path=str(path),
        files=[
            FileTaskFile(
                path=str(path), type="docx", target=True, content="Original paragraph"
            )
        ],
        options={"output_mode": "write"},
    )
    events = list(
        FileTaskRuntime(workspace_root=str(tmp_path), model_client=model).run(request)
    )
    assert Document(path).paragraphs[-1].text == "New paragraph"
    assert any(event.type == "file.changed" for event in events)
    check = next(event for event in events if event.type == "check.finished")
    assert check.payload["passed"] is False
    assert check.payload["status"] == "validation_blocked"
    assert check.payload["failure"]["phase"] == "validation"
    assert events[-1].payload["completed_task"] is False
    assert file_task_terminal_status(events[-1].type, events[-1].payload) == "failed"
