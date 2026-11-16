"""One bounded continuation window after concrete, verified file progress."""

import time


def fingerprint(state):
    return (
        sorted(
            (k, v["sha256"]) for k, v in state["artifacts"].items() if v.get("verified")
        ),
        [
            (v.get("fragment"), v.get("after"))
            for v in state["edits"]
            if v.get("verified")
        ],
    )


def extend(broker, baseline, engine):
    turn = broker.turn
    if (
        not getattr(engine, "supports_progress_windows", False)
        or turn.mode == "read"
        or time.monotonic() < turn.deadline
        or turn.cancelled.is_set()
        or turn.write_denied
        or turn.blocked_error
        or getattr(turn, "progress_windows", 1) >= 2
        or turn.tool_calls >= broker.max_tools
        or getattr(turn, "model_calls", 0) >= engine.max_models
        or getattr(turn, "model_requests_total", 0)
        >= getattr(turn, "max_model_requests", 120)
    ):
        return False
    state = broker.store.get(broker.task)
    if (
        state["epoch"] != turn.epoch
        or state["phase"] == "uncertain"
        or state["review"]
        or fingerprint(state) == baseline
    ):
        return False
    turn.progress_windows = 2
    turn.deadline = time.monotonic() + 600
    turn.reset_model_context = True
    broker.pure_observations.clear()
    broker.store.event(
        broker.task,
        "execution_window_extended",
        {
            "turn": turn.number,
            "window": 2,
            "seconds": 600,
            "reason": "verified_progress",
            "outputs": list(state["artifacts"]),
        },
    )
    return True
