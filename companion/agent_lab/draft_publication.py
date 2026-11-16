"""Bounded completion of a measured proposal through the normal write boundary."""


def recover_publication(broker, observation):
    result = observation.get("result", {})
    next_tool = result.get("next_tool", {})
    args = next_tool.get("arguments", {})
    state = broker.store.get(broker.task)
    if (
        observation.get("tool") != "measure_content"
        or result.get("validation", {}).get("passed") is not True
        or next_tool.get("name") not in {"create_word", "create_presentation"}
        or broker.turn.mode == "read"
        or state["review"]
        or args.get("file_name") not in state["expected_outputs"]
        or args.get("file_name") in state["artifacts"]
        or not broker.permitted()
    ):
        return observation
    broker.store.event(
        broker.task,
        "recovery_publication_requested",
        {
            "tool": next_tool["name"],
            "file_name": args["file_name"],
            "turn": broker.turn.number,
        },
    )
    outcome = broker.invoke(next_tool["name"], args)
    return {
        "tool": next_tool["name"],
        "arguments": args,
        "result": outcome,
        "recovery": "通过标准写入边界处理已授权的新文件；回执才代表完成。",
    }
