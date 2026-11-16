"""Host-owned completion facts, independent of an assistant's final answer."""

from companion.file_actions import FileActions
from .content_metrics import artifact_metrics
from .output_limits import validate_metrics


def completion_status(broker):
    state = broker.store.get(broker.task)
    missing = sorted(set(state["expected_outputs"]) - state["artifacts"].keys())
    unfinished = [s["id"] for s in state["plan"] if s["status"] != "completed"]
    invalid, verified = [], []
    for name, receipt in state["artifacts"].items():
        try:
            actual = FileActions.receipt(broker.outputs / name, "verify")
            if not receipt.get("verified") or actual["sha256"] != receipt["sha256"]:
                invalid.append(
                    {"file_name": name, "reason": "结果已变化或没有已验证回执。"}
                )
                continue
            metrics = artifact_metrics(broker.outputs / name)
            limits = state.get("output_limits", {}).get(name)
            if limits and name in state["expected_outputs"]:
                quality = validate_metrics(metrics, limits)
                if not quality["passed"]:
                    invalid.append(
                        {"file_name": name, "reason": " ".join(quality["violations"])}
                    )
                    continue
            verified.append(
                {"file_name": name, "sha256": actual["sha256"], "metrics": metrics}
            )
        except Exception as error:
            invalid.append(
                {
                    "file_name": name,
                    "reason": type(error).__name__ + ": 无法读回验证交付。",
                }
            )
    pending = []
    from .content_checks import body_text, violations

    for name in state.get("content_checks", {}):
        if name not in state["expected_outputs"] or name not in state["artifacts"]:
            continue
        try:
            errors = violations(broker, name, body_text(broker.outputs / name))
        except Exception as error:
            errors = [type(error).__name__ + ": 无法检查交付正文。"]
        if errors:
            invalid.append({"file_name": name, "reason": "；".join(errors)})
    for name, schema in state.get("workbook_schemas", {}).items():
        if name not in state["expected_outputs"] or name not in state["artifacts"]:
            continue
        from .workbook_contracts import path_violations

        try:
            errors = path_violations(broker.outputs / name, schema)
        except Exception as error:
            errors = [type(error).__name__ + ": 无法检查表格结构。"]
        if errors:
            invalid.append({"file_name": name, "reason": "；".join(errors)})
    if getattr(broker, "edit_allowed", False):
        pending = sorted(set(broker.document.fragments) - broker.processed_fragments())
    review = bool(state["review"])
    uncertain = state["phase"] == "uncertain"
    return {
        "ready": not (
            missing or unfinished or invalid or pending or review or uncertain
        ),
        "missing_outputs": missing,
        "unfinished_steps": unfinished,
        "invalid_outputs": invalid,
        "saved_output_metrics": verified,
        "unprocessed_fragments": pending,
        "awaiting_review": review,
        "uncertain": uncertain,
        "completion_recorded": state["phase"] == "complete",
    }


def incomplete_message(facts):
    parts = []
    if facts["missing_outputs"]:
        parts.append("还缺少：" + "、".join(facts["missing_outputs"]))
    if facts["invalid_outputs"]:
        parts.append(
            "需要重新核对："
            + "、".join(v["file_name"] for v in facts["invalid_outputs"])
        )
    if facts["unfinished_steps"] or facts["unprocessed_fragments"]:
        parts.append("还有处理步骤未完成")
    return "任务尚未完成，进度已保留。" + (
        "；".join(parts) + "。" if parts else "交付的最终核对尚未完成。"
    )


class CompletionSupervisor:
    """Continue an authorized execution, without turning follow-up questions into writes."""

    def __init__(self, broker, max_nudges=2):
        self.broker = broker
        self.initial = broker.store.get(broker.task)
        self.nudges = 0
        self.max_nudges = max_nudges
        self.exhausted = False

    def committed(self):
        broker = self.broker
        state = broker.store.get(broker.task)
        return bool(
            (broker.turn.number == 1 and state["expected_outputs"])
            or broker.turn.interaction in ("start", "continue")
            or broker.turn.writes
            or state.get("contract_revision", 0)
            != self.initial.get("contract_revision", 0)
            or state.get("output_limits", {}) != self.initial.get("output_limits", {})
            or state.get("workbook_schemas", {})
            != self.initial.get("workbook_schemas", {})
            or state.get("content_checks", {}) != self.initial.get("content_checks", {})
        )

    def inspect_final(self):
        broker = self.broker
        state = broker.store.get(broker.task)
        if (
            broker.turn.mode == "read"
            or broker.turn.write_denied
            or not broker.permitted()
            or broker.turn.blocked_error
            or state["review"]
            or state["phase"] in ("complete", "uncertain")
            or not self.committed()
        ):
            return None
        facts = completion_status(broker)
        if self.nudges >= self.max_nudges:
            self.exhausted = True
            broker.store.event(broker.task, "completion_incomplete", facts)
            return None
        self.nudges += 1
        broker.store.event(
            broker.task, "completion_continued", {"attempt": self.nudges, **facts}
        )
        return facts
