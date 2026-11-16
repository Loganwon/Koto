"""Versioned working drafts. Rejected model context cannot resurrect an old draft."""

import hashlib
import json
from pathlib import Path
from .execution_errors import ToolDiagnosticError


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def content_id(args):
    return fingerprint({k: args.get(k) for k in ("file_name", "format", "sections")})[
        :24
    ]


def contract_id(state, name):
    return fingerprint(
        {
            "revision": state.get("ui_plan_revision", 0),
            "limits": state.get("output_limits", {}).get(name),
            "checks": state.get("content_checks", {}).get(name),
        }
    )


def current(broker, name):
    state = broker.store.get(broker.task)
    draft = state.get("drafts", {}).get(name)
    return draft if draft and draft["contract"] == contract_id(state, name) else None


def remember(broker, args, result, *, supersedes=None):
    name = args.get("file_name") or result.get("validation", {}).get("file_name")
    state = broker.store.get(broker.task)
    if not name or name not in state["expected_outputs"]:
        return result
    arguments = {
        "file_name": name,
        "format": args["format"],
        "sections": args["sections"],
    }
    identity = content_id(arguments)
    old = current(broker, name)
    version = (
        old["version"] + 1
        if old and old["id"] != identity
        else old["version"] if old else 1
    )
    result = {**result, "draft_id": identity, "draft_version": version}
    if result.get("next_tool"):
        result["next_tool"] = {
            **result["next_tool"],
            "arguments": {**result["next_tool"]["arguments"], "draft_id": identity},
        }
    rejected = list(old.get("superseded", [])) if old else []
    failed = list(old.get("failed", [])) if old else []
    if result.get("validation", {}).get("passed") is False:
        failed.append(identity)
    if supersedes and content_id({**supersedes, "file_name": name}) != identity:
        rejected.append(content_id({**supersedes, "file_name": name}))
        rejected.extend(failed)
    record = {
        "id": identity,
        "version": version,
        "contract": contract_id(state, name),
        "arguments": arguments,
        "result": result,
        "superseded": [v for v in dict.fromkeys(rejected) if v != identity][-40:],
        "failed": list(dict.fromkeys(failed))[-40:],
    }
    broker.store.change(broker.task, drafts={**state.get("drafts", {}), name: record})
    broker.store.event(
        broker.task,
        "draft_saved",
        {
            "file_name": name,
            "draft_id": identity,
            "version": version,
            "validation": result.get("validation"),
        },
    )
    return result


def replacement(broker, args):
    draft = current(broker, args.get("file_name"))
    if draft and content_id(args) in draft.get("superseded", []):
        return {
            "tool": "measure_content",
            "arguments": draft["arguments"],
            "result": draft["result"],
        }
    return None


def require_current(broker, name, args):
    if name not in {"create_word", "create_presentation"}:
        return
    draft = current(broker, args["file_name"])
    if not draft:
        if args.get("draft_id"):
            raise ToolDiagnosticError(
                "草稿合同已变化，请重新测量。", {"code": "stale_draft"}
            )
        return
    proposed = {
        "file_name": args["file_name"],
        "format": "docx" if name == "create_word" else "pptx",
        "sections": args["sections"],
    }
    if (
        args.get("draft_id")
        and args["draft_id"] != draft["id"]
        or content_id(proposed) in draft.get("superseded", [])
    ):
        raise ToolDiagnosticError(
            "这份草稿已被修复版本替代，请采用当前草稿。",
            {
                "code": "stale_draft",
                "draft_id": draft["id"],
                "next_tool": draft["result"].get("next_tool"),
                "current_draft": draft["arguments"],
            },
        )


def measure(broker, args):
    from .content_metrics import proposed_metrics
    from .output_limits import draft_validation

    metrics = proposed_metrics(
        "create_word" if args["format"] == "docx" else "create_presentation",
        args,
    )
    validation = draft_validation(
        broker.store.get(broker.task),
        args.get("file_name"),
        metrics,
        args["format"],
    )
    if (
        validation is None
        and args.get("file_name") in broker.store.get(broker.task)["expected_outputs"]
    ):
        validation = {
            "file_name": args["file_name"],
            "passed": True,
            "violations": [],
        }
    result = {"metrics": metrics}
    if validation:
        from .content_checks import violations

        text = "\n".join(s["heading"] + "\n" + s["text"] for s in args["sections"])
        errors = violations(broker, validation["file_name"], text)
        if errors:
            validation = {
                **validation,
                "passed": False,
                "violations": [*validation["violations"], *errors],
                "next_action": "同时满足字数、事实及来源验收后再生成。保留准确required_phrases与来源名，可重新组织各页。",
            }
        result["validation"] = validation
        if validation["passed"]:
            import hashlib

            action = hashlib.sha256(
                json.dumps(args, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()[:20]
            file_name = validation["file_name"]
            result["next_tool"] = {
                "name": (
                    "create_word" if args["format"] == "docx" else "create_presentation"
                ),
                "arguments": {
                    "action_id": "measured-" + action,
                    "file_name": file_name,
                    "title": Path(file_name).stem,
                    "sections": args["sections"],
                },
                "reason": "拟稿已满足计数约束，可用此完全相同的内容创建，仍需通过写入核对。不要继续重测。",
            }
    broker.store.event(
        broker.task,
        "content_measured",
        {"metrics": metrics, "validation": validation},
    )
    return remember(broker, args, result)
