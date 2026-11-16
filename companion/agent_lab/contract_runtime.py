"""Use the production acceptance compiler for file sessions and delivery changes."""

from pathlib import Path
from companion.contracts import CompanionError

from .task_requirements import TaskRequirements, install


def compile_contract(broker, outputs):
    state = broker.store.get(broker.task)
    selected = getattr(broker, "selected_sources", None)
    file_ids = (
        list(selected)
        if selected is not None
        else [e["id"] for e in broker.workspace.tree()["entries"]]
    )
    if len(file_ids) > 32:
        raise CompanionError(
            "请将本轮参考资料限定在32份以内，不能以截断清单冒充已核对全部资料。"
        )
    resources = []
    for file_id in file_ids[:32]:
        excerpt = broker.references.read(file_id, 0, 1500)
        from .source_observations import observe

        observe(broker, excerpt, "contract_preview")
        resources.append(
            {
                "id": file_id,
                "file_id": file_id,
                "name": Path(file_id).name,
                "revision": excerpt["version"],
                "excerpt": excerpt["text"],
            }
        )
    requests = state.get("user_requests", [])
    context = {
        "request": broker.turn.message,
        "previous_requests": [
            state["goal"],
            *[r["message"] for r in requests[:-1]][-6:],
        ],
        "previous_contract": state.get("task_contract"),
        "sources": resources,
        "explicit_ui_format_choices": [
            {"name": n, "format": Path(n).suffix.lstrip(".")} for n in outputs
        ],
    }
    compiler = TaskRequirements(
        broker.verifier.client.config, client=broker.verifier.client
    )
    try:
        contract = compiler.compile(
            context,
            {"deliveries": [{"kind": "create", "name": n} for n in outputs]},
            cancelled=broker.turn.cancelled,
        )
    except CompanionError:
        broker.store.event(
            broker.task, "task_contract_rejected", compiler.last_failure or {}
        )
        raise
    return contract, resources


def ensure(broker):
    state = broker.store.get(broker.task)
    if state.get("contract_required") or not state["expected_outputs"]:
        return
    contract, resources = compile_contract(broker, state["expected_outputs"])
    install(
        broker.store,
        broker.task,
        contract,
        resources,
        state.get("contract_revision", 0),
        broker.workspace,
    )


def revise(broker, outputs, updates):
    contract, resources = compile_contract(broker, outputs)
    install(
        broker.store,
        broker.task,
        contract,
        resources,
        updates["contract_revision"],
        broker.workspace,
        expected_outputs=outputs,
        updates=updates,
    )
