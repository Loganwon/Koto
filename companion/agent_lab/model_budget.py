"""One turn budget for execution, requirement compilation and review calls."""

from contextvars import ContextVar
import time

from companion.contracts import CompanionError, OperationCancelled

_active = ContextVar("koto_model_budget", default=None)


def activate(turn, record):
    return _active.set((turn, record))


def reset(token):
    _active.reset(token)


def charge(turn, kind, record=None):
    with turn.budget_lock:
        if turn.cancelled.is_set():
            raise OperationCancelled("已停止，未继续调用模型。")
        if time.monotonic() >= turn.deadline:
            raise CompanionError("本轮执行窗口已到，模型进度已保留。")
        if turn.model_requests_total >= turn.max_model_requests:
            turn.blocked_error = "本轮执行、规划和验收的模型总预算已到，进度已保留。"
            raise CompanionError(turn.blocked_error)
        turn.model_requests_total += 1
        if kind == "planning":
            turn.auxiliary_model_calls += 1
        event = {
            "turn": turn.number,
            "kind": kind,
            "total": turn.model_requests_total,
            "limit": turn.max_model_requests,
        }
    if record:
        record(event)


def charge_planning():
    active = _active.get()
    if active:
        charge(active[0], "planning", active[1])


def planning_result(result, seconds, error=None):
    active = _active.get()
    if active:
        choice = (result or {}).get("choices", [{}])[0]
        active[1](
            {
                "turn": active[0].number,
                "kind": "planning_result",
                "seconds": round(seconds, 3),
                "finish_reason": choice.get("finish_reason"),
                "visible_characters": len(
                    (choice.get("message") or {}).get("content") or ""
                ),
                "model": (result or {}).get("model"),
                "usage": (result or {}).get("usage", {}),
                "error_type": type(error).__name__ if error else None,
            }
        )
