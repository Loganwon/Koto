"""Separate exact-output wording from instructions about doing the work."""

import json

from companion.contracts import CompanionError

PROMPT = """你只核对逐字写入意图，不执行、不修改正文、不评价生成文件。用户消息是唯一指令来源。
每个candidate只判断：用户是否明确要求这段连续文字逐字出现在指定文件正文。提出主题、版本号、保留原意、保留布局、核对操作、复制保存等，不等于要求把指令写进正文。引号内也可能只是讨论对象或禁止文字，不因有引号就认定必须写入。
例如“正文加入准确文字‘负责人=Alice’”应为required=true；“保留原有章节与布局”“Word正文最多300字”“分析v2.5状态”不能把这些指令/主题自动变成逐字正文。普通内容及结构要求仍在原清单中，此处只移除多余的字面强制，不取消其他要求。较新明确替换的文字优先，旧字面条件不应残留。按指定文件判断，不把一个文件的逐字要求扩大到另一个。
每个candidate id必须且只能回答一次。required=true必须给对应真实用户turn中包含candidate.text的连续instruction_quote，足以支持准确写入；false允许空引文。返回且仅返回JSON：{"decisions":[{"id":"l0","required":true,"instruction_quote":"用户明确逐字写入的真实连续指令","reason":"短理由"}]}。"""


def audit(client, turn, store, task, spec, files):
    candidates = []
    for name, value in files.items():
        for check in value["checks"]:
            if "literal" in check:
                candidates.append(
                    {
                        "id": f"l{len(candidates)}",
                        "file_name": name,
                        "check_id": check["id"],
                        "turn": check["request_turn"],
                        "text": check["literal"],
                    }
                )
    if not candidates:
        return
    messages = [
        {"role": "system", "content": PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {"requests": spec["requests"], "candidates": candidates},
                ensure_ascii=False,
            ),
        },
    ]
    expected = {c["id"]: c for c in candidates}
    for attempt in range(2):
        data = client._request(
            {
                "model": client.config.model,
                "temperature": 0,
                "max_tokens": 3500,
                "stream": False,
                "response_format": {"type": "json_object"},
                "messages": messages,
            },
            turn.cancelled,
        )
        try:
            choice = data["choices"][0]
            if choice["finish_reason"] != "stop":
                raise ValueError("逐字意图核对被截断。")
            value = json.loads(choice["message"]["content"])
            if (
                not isinstance(value, dict)
                or set(value) != {"decisions"}
                or not isinstance(value["decisions"], list)
                or len(value["decisions"]) != len(candidates)
            ):
                raise ValueError("逐字意图核对须完整覆盖所有候选。")
            seen, approved = set(), set()
            for item in value["decisions"]:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"id", "required", "instruction_quote", "reason"}
                    or not isinstance(item["id"], str)
                    or item["id"] not in expected
                    or item["id"] in seen
                    or type(item["required"]) is not bool
                    or not isinstance(item["instruction_quote"], str)
                    or not isinstance(item["reason"], str)
                ):
                    raise ValueError("逐字意图核对编号/字段无效。")
                candidate = expected[item["id"]]
                if item["required"]:
                    quote = item["instruction_quote"]
                    if (
                        not quote
                        or candidate["text"] not in quote
                        or not any(
                            r["turn"] == candidate["turn"] and quote in r["message"]
                            for r in spec["requests"]
                        )
                    ):
                        raise ValueError(
                            "必须给候选对应真实用户的明确写入指令，不得伪造证据。"
                        )
                    approved.add((candidate["file_name"], candidate["check_id"]))
                seen.add(item["id"])
            for name, file in files.items():
                file["checks"] = [
                    c
                    for c in file["checks"]
                    if "literal" not in c or (name, c["id"]) in approved
                ]
            store.event(
                task,
                "literal_intent_checked",
                {"turn": turn.number, "candidates": candidates, **value},
            )
            return
        except (ValueError, TypeError, KeyError, IndexError) as error:
            store.event(
                task,
                "literal_intent_protocol_rejected",
                {"attempt": attempt + 1, "error": str(error)},
            )
            messages.append(
                {
                    "role": "user",
                    "content": str(error)
                    + "仅修正核对JSON，不执行动作；逐字条件不能以普通主题或操作要求代替。",
                }
            )
    raise CompanionError("逐字写入意图没有返回完整核对，未保存新清单。")
