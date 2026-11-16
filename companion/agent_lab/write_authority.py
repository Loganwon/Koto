"""Recheck a denied mutation's scope without its prose or quality metrics."""

import json

from companion.contracts import CompanionError
from .user_requests import context


def recheck(client, turn, tool, arguments, state):
    scope = {
        k: arguments[k]
        for k in ("file_name", "file_id", "new_name", "fragment_id")
        if k in arguments
    }
    payload = {
        "model": client.config.model,
        "temperature": 0,
        "max_tokens": 500,
        "stream": False,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": '你只复核动作对象是否获真实用户授权，不评价内容、事实、字数、页数或格式质量。输入故意不提供拟稿正文。apply_edit修改原生正文，create_*生成文件，revise_office_text/revise_workbook仅修订本任务已有交付；不改原生正文不等于不许生成交付。最新用户要求及明确继续沿用的未完成反馈优先，旧只读轮次不构成永久禁令。只读模式禁止写。只返回JSON：{"authorized":true或false,"reason":"仅说明对象范围是否获授权"}。确认有权限不等于内容合格，也不执行动作。',
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "latest_user_message": turn.message,
                        "mode": turn.mode,
                        "interaction": turn.interaction,
                        "continued_user_requests": context(state),
                        "accepted_outputs": state["expected_outputs"],
                        "existing_outputs": list(state["artifacts"]),
                        "tool": tool,
                        "object": scope,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    response = client._request(payload, turn.cancelled)
    choice = response["choices"][0]
    try:
        value = json.loads(choice["message"]["content"])
        if (
            choice["finish_reason"] != "stop"
            or set(value) != {"authorized", "reason"}
            or type(value["authorized"]) is not bool
            or not isinstance(value["reason"], str)
        ):
            raise ValueError()
        return value
    except (ValueError, TypeError, KeyError) as error:
        raise CompanionError("动作范围复核未返回完整结果，未执行修改。") from error
