"""Action-status lookup is only exposed inside a trusted read scope."""

from types import SimpleNamespace

import pytest

from app.core.agent.kernel_agent import KernelAgent
from app.core.agent.tool_registry import ToolRegistry


@pytest.mark.parametrize(
    "operations,expected",
    [
        (None, set()),
        (("read",), {"ui_read_context", "ui_action_status"}),
        (("read", "edit"), {"ui_read_context", "ui_action_status", "ui_apply_edit"}),
    ],
)
def test_trusted_scope_limits_status_and_mutating_tool_exposure(operations, expected):
    calls = []
    provider = SimpleNamespace(
        generate_content=lambda **kwargs: calls.append(kwargs) or {"content": "done"}
    )
    registry = ToolRegistry()
    names = {"ui_read_context", "ui_action_status", "ui_apply_edit", "ui_save"}
    for name in names:
        registry.register_tool(
            name,
            lambda: "unused",
            read_only=name in {"ui_read_context", "ui_action_status"},
        )
    context = (
        None
        if operations is None
        else SimpleNamespace(frontend_document_scope={"allowed_operations": operations})
    )
    agent = KernelAgent(
        provider,
        registry,
        enable_pii_filter=False,
        enable_output_validation=False,
        use_tool_router=False,
        allow_model_fallback=False,
    )
    list(agent.run("test", record_task=False, addon_invocation_context=context))
    assert {tool["name"] for tool in calls[0]["tools"] or []} == expected


def test_injected_ledger_is_the_single_owner_when_agent_creates_a_task(
    tmp_path, monkeypatch
):
    from app.core.tasks import task_ledger

    ledger = task_ledger.TaskLedger(db_path=str(tmp_path / "tasks.sqlite"))
    monkeypatch.setattr(
        task_ledger,
        "get_ledger",
        lambda: pytest.fail("must not create a task in the global ledger"),
    )
    provider = SimpleNamespace(generate_content=lambda **kwargs: {"content": "done"})
    agent = KernelAgent(
        provider,
        enable_pii_filter=False,
        enable_output_validation=False,
        use_tool_router=False,
        allow_model_fallback=False,
    )
    steps = list(agent.run("test", task_ledger=ledger))
    task = ledger.get(steps[-1].metadata["task_id"])
    assert task is not None and task.status.value == "completed"
    assert ledger.get_kernel_checkpoint(task.task_id)["phase"] == "completed"
