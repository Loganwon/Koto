"""Detect unchanged observations; propose bounded repairs without publishing them."""

import json

from companion.contracts import CompanionError
from companion.harness import validate


def signature(name, args):
    return name, json.dumps(args, sort_keys=True, ensure_ascii=False)


def before_call(broker, name, args, spec):
    if name not in ("measure_content", "calculate"):
        return None
    if name == "measure_content":
        from .drafts import replacement

        saved = replacement(broker, args)
        if saved:
            broker.turn.recovery_observation = saved
            return {
                "ok": True,
                **saved["result"],
                "proposed_revision": saved["arguments"],
                "notice": "旧稿已被替代；当前版本及计数已保留，请使用当前稿推进交付。",
            }
    observation = broker.pure_observations.get(signature(name, args))
    if not observation:
        return None
    observation["steps"].add(broker.turn.model_step)
    if len(observation["steps"]) < 3:
        return None
    validation = observation["result"].get("validation", {})
    repair = getattr(broker.verifier, "repair_draft", None)
    if (
        name == "measure_content"
        and validation.get("passed") is False
        and repair
        and broker.draft_repairs < 2
    ):
        broker.draft_repairs += 1
        revised = repair(broker.turn, args, broker.store.get(broker.task), validation)
        validate(revised, spec["parameters"])
        if not broker.permitted():
            raise CompanionError("草稿修复期间任务已停止，未生成文件。")
        measured = broker._run(name, revised)
        # Feed the actual failed proposal and host verdict into the second
        # bounded repair, instead of restarting from the original long draft.
        while (
            measured.get("validation", {}).get("passed") is False
            and broker.draft_repairs < 2
        ):
            broker.draft_repairs += 1
            revised = repair(
                broker.turn,
                revised,
                broker.store.get(broker.task),
                measured["validation"],
            )
            validate(revised, spec["parameters"])
            if not broker.permitted():
                raise CompanionError("草稿修复期间任务已停止，未生成文件。")
            measured = broker._run(name, revised)
        if measured.get("validation", {}).get("passed") is False:
            from .draft_layout import rebalance

            balanced = rebalance(revised, broker.store.get(broker.task))
            if balanced != revised:
                revised = balanced
                measured = broker._run(name, revised)
        broker.turn.recovery_observation = {
            "tool": name,
            "arguments": revised,
            "result": measured,
        }
        from .drafts import remember

        measured = remember(broker, revised, measured, supersedes=args)
        broker.turn.recovery_observation["result"] = measured
        broker.store.event(
            broker.task,
            "draft_revision_proposed",
            {
                "turn": broker.turn.number,
                "metrics": measured["metrics"],
                "validation": measured.get("validation"),
            },
        )
        return {
            "ok": True,
            "original_metrics": observation["result"].get("metrics"),
            "proposed_revision": revised,
            **measured,
            "notice": "原草稿未改变。这是局部修复建议及建议文本的真实计数，仅为提议，需正常写入核对。",
        }
    broker.turn.recovery_observation = {
        "tool": name,
        "arguments": args,
        "result": observation["result"],
    }
    broker.store.event(
        broker.task,
        "observation_loop",
        {"tool": name, "distinct_model_steps": len(observation["steps"])},
    )
    detail = (
        "请缩短或改变sections中的实际文字，再测量新草稿；不要重测同一份正文。"
        if name == "measure_content"
        else "请使用已有精确结果推进任务；只有表达式改变才需重新计算。"
    )
    raise CompanionError(
        "相同输入已得到确定结果，重复调用没有新进展。"
        + detail
        + "已有观察："
        + json.dumps(observation["result"], ensure_ascii=False)
    )


def after_call(broker, name, args, result):
    if name in ("measure_content", "calculate"):
        observed = broker.pure_observations.setdefault(
            signature(name, args), {"steps": set(), "result": result}
        )
        observed["steps"].add(broker.turn.model_step)
        observed["result"] = result
    if name == "query_data" and result.get("evidence_digest"):
        key = name, result["evidence_digest"]
        observed = broker.pure_observations.setdefault(
            key, {"steps": set(), "result": result}
        )
        observed["steps"].add(broker.turn.model_step)
        count = len(observed["steps"])
        if count >= 3:
            result = {
                **result,
                "progress_notice": "同一份查询内容已经出现三次。完整结果已保存，使用result_id导出或完成下一项交付；确需新信息时改变筛选条件，不重复改写等价SQL。",
            }
            broker.turn.recovery_observation = {
                "tool": name,
                "arguments": args,
                "result": result,
            }
            broker.store.event(
                broker.task,
                "observation_loop",
                {
                    "tool": name,
                    "distinct_model_steps": count,
                    "evidence_digest": key[1],
                },
            )
            if count >= 6:
                broker.turn.blocked_error = (
                    "query_data：相同资料内容反复查询，未推进交付。"
                )
    return result
