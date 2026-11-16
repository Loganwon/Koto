"""Current task facts for model context; full history stays in the task store."""

import json

MAX_CHARACTERS = 24000


def _size(value):
    return len(json.dumps(value, ensure_ascii=False))


def _bounded(value, maximum):
    if _size(value) <= maximum:
        return value
    return {
        "truncated": True,
        "characters": _size(value),
        "keys": list(value)[:24] if isinstance(value, dict) else [],
        "read_tool": {"name": "read_task", "arguments": {}},
    }


def _fit(context, maximum):
    if _size(context) <= maximum:
        return context
    # The complete immutable requirements/receipts remain in read_task. Retain
    # pending request identity even when its text needs explicit retrieval.
    context["context_truncated"] = True
    for key in sorted(context, key=lambda k: _size(context[k]), reverse=True):
        if key in {"id", "phase", "expected_outputs", "user_requests"}:
            continue
        if _size(context[key]) > 500:
            context[key] = _bounded(context[key], 500)
        if _size(context) <= maximum:
            break
    if _size(context) > maximum and isinstance(context.get("user_requests"), list):
        for request in context["user_requests"]:
            if len(request["message"]) > 150:
                request["message"] = request["message"][:150]
                request["truncated"] = True
        if _size(context) > maximum:
            context["request_count"] = len(context["user_requests"])
            context["user_requests"] = context["user_requests"][-30:]
    return context


def build(state):
    from .user_requests import context as request_context

    keys = (
        "id",
        "goal",
        "phase",
        "constraints",
        "expected_outputs",
        "plan",
        "review",
        "contract_revision",
        "ui_plan_revision",
        "task_contract",
        "contract_required",
        "output_limits",
        "workbook_schemas",
        "content_checks",
        "native_content_checks",
    )
    context = {key: state[key] for key in keys if key in state}
    context = {key: _bounded(value, 6000) for key, value in context.items()}
    context["artifacts"] = state["artifacts"]
    context["user_requests"] = request_context(state)
    for request in context["user_requests"]:
        if len(request["message"]) > 500:
            request["message"] = request["message"][:500]
            request["truncated"] = True
    context["edits"] = [
        {
            key: edit[key]
            for key in (
                "fragment",
                "before",
                "after",
                "reason",
                "verified",
                "plan_revision",
            )
            if key in edit
        }
        for edit in state["edits"][-3:]
    ]
    analyses = state.get("analyses", [])
    context["analyses"] = [_bounded(value, 1800) for value in analyses[-6:]]
    context["analysis_count"] = len(analyses)
    context["analysis_index_tool"] = {"name": "list_query_results", "arguments": {}}
    plan = state.get("acceptance_plan")
    if plan:
        context["acceptance_plan"] = _bounded(
            {
                "key": plan["key"],
                "revision": plan["revision"],
                "files": {
                    name: value["checks"] for name, value in plan["files"].items()
                },
            },
            9000,
        )
    context["drafts"] = {
        name: {
            "id": draft["id"],
            "version": draft["version"],
            "validation": draft["result"].get("validation"),
            "read_tool": {"name": "read_draft", "arguments": {"file_name": name}},
        }
        for name, draft in state.get("drafts", {}).items()
    }
    context["full_state_tool"] = {"name": "read_task", "arguments": {}}
    return _fit(context, MAX_CHARACTERS)


def recovery_context(state, observation, references=(), calculations=()):
    result = {
        "task": build(state),
        "last_observation": _bounded(observation, 4000),
        "evidence": {
            "references": [_bounded(v, 600) for v in list(references)[-4:]],
            "calculations": _bounded(list(calculations)[-8:], 1000),
        },
        "full_state_tool": {"name": "read_task", "arguments": {}},
    }
    if _size(result) > 30000:
        result["last_observation"] = _bounded(observation, 1500)
        result["evidence"] = _bounded(result["evidence"], 1000)
    return result
