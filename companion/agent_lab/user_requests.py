"""Durable human requests survive model context recovery and cancellation."""

from companion.contracts import CompanionError


def pending(state):
    accepted = state.get("accepted_request_turn", 0)
    return [
        r
        for r in state.get("user_requests", [])
        if r["turn"] > accepted and r.get("mode") != "read"
    ]


def context(state):
    requests = state.get("user_requests", [])
    active = pending(state)
    recent = [r for r in requests if r not in active][-2:]
    # Preserve every unresolved request identity; long text remains addressable
    # in read_task/read_history instead of disappearing during model compaction.
    values = []
    for request in [*recent, *active]:
        values.append(
            {
                **request,
                "message": request["message"][:2000],
                "truncated": len(request["message"]) > 2000,
                "pending": request in active,
            }
        )
    return values


def acceptance(state):
    # Repeated confirmation in the same turn reuses the same reviewed scope;
    # the next real user turn starts after the durable accepted watermark.
    active = pending(state)
    if (
        state.get("phase") == "complete"
        and state.get("accepted_request_turn") == state["turn"]
    ):
        active = [
            r
            for r in state.get("user_requests", [])
            if r["turn"] > state.get("accepted_request_start_turn", 0)
            and r.get("mode") != "read"
        ]
    if len(active) > 30 or sum(len(r["message"]) for r in active) > 100000:
        raise CompanionError("未验收的反馈超过本版核对范围，任务尚未确认完成。")
    return active
