"""Reconcile semantic obligations without losing their human provenance.

The model proposes relations only. Host-owned slot ids, full coverage, literal
identity and newer-user replacement evidence are checked before atomic commit.
"""

import hashlib
import json

from companion.contracts import CompanionError, OperationCancelled
from .requirement_identity import consolidate, key

PROMPT = """只整理要求关系，不执行、不判交付、不从资料新增要求。current是本次已编译的原子要求，previous是同一文件仍有效的旧槽位。
相同含义、对象、范围、限定的条件合并到一槽；同主题但不同目标/措施/顺序/单位/确定性不能合并。members列current的id，retain列等义previous的slot_id。未被新反馈明确取消的旧条件必须retain，即使current漏编，也可members=[]保留。每个current id和每个previous slot_id必须出现且仅出现一次。
较新真实用户反馈明确改变或取消旧条件，才把旧槽放replaces，给turn和该消息中支持替换的确切连续quote。不是因为新稿难满足就删要求。新反馈只改风格不取消事实，只改负责人格式不取消其他限定。字面条件literal不同绝不能当等义合并，应引用真实较新反馈替换；禁止用普通主题替换字面要求。criteria里的旧措辞也可能由同一次新反馈替换，current中已失效的项列discard，不能塞进当前有效槽。
每个槽可有members、retain、replaces；纯删除槽允许members=[]、retain=[]但必须有replaces。discard只取消current项，同样需较新真实反馈且覆盖对应旧要求的时间。返回JSON：{"slots":[{"members":["current id"],"retain":["previous slot_id"],"replaces":[{"slot_id":"旧槽","turn":2,"quote":"真实替换指令"}]}],"discard":[{"id":"current id","turn":2,"quote":"真实替换指令"}]}。只列本文件，不返回自创要求或通过标记。"""


PROMPT += "\nslots每项的members、retain、replaces都必须是数组，空值写[]。不要复制previous整项；不返回check、status、requirement或自选slot_id。宿主负责槽号。"


def _slot_id(name, check):
    return "r:" + hashlib.sha256((name + ":" + key(check)).encode()).hexdigest()[:24]


def _replacement(value, old_turn, requests, field):
    if not isinstance(value, dict) or set(value) != {field, "turn", "quote"}:
        raise ValueError("替换关系字段无效。")
    if (
        type(value["turn"]) is not int
        or value["turn"] <= old_turn
        or not isinstance(value["quote"], str)
        or not value["quote"].strip()
        or not any(
            r["turn"] == value["turn"]
            and r.get("mode") != "read"
            and value["quote"] in r["message"]
            for r in requests
        )
    ):
        raise ValueError("替换必须指向较新真实用户的连续原句，不能凭空丢弃旧要求。")


def validate(raw, name, current, previous, requests, number):
    if not isinstance(raw, dict) or set(raw) != {"slots", "discard"}:
        raise ValueError("要求关系只允许slots和discard。")
    if not isinstance(raw["slots"], list) or not isinstance(raw["discard"], list):
        raise ValueError("要求关系必须为数组。")
    candidates = {c["id"]: c for c in current}
    old = {s["slot_id"]: s for s in previous if s["status"] == "active"}
    seen, seen_old, slots, retired = set(), set(), [], []
    for item in raw["discard"]:
        if not isinstance(item, dict) or item.get("id") not in candidates:
            raise ValueError("取消的当前要求编号无效。")
        cid = item["id"]
        _replacement(
            item,
            candidates[cid].get(
                "introduced_turn", candidates[cid].get("request_turn", 0)
            ),
            requests,
            "id",
        )
        if cid in seen:
            raise ValueError("当前要求关系重复。")
        seen.add(cid)
        retired.append(
            {"status": "replaced", "check": candidates[cid], "replacement": item}
        )
    for item in raw["slots"]:
        if isinstance(item, dict):
            # Empty edge lists and an echoed suggested id carry no authority.
            # Host ids and exhaustive relation coverage are checked below.
            item = {k: v for k, v in item.items() if k not in {"id", "slot_id"}}
            item = {"members": [], "retain": [], "replaces": [], **item}
        if (
            not isinstance(item, dict)
            or set(item) != {"members", "retain", "replaces"}
            or any(not isinstance(item[k], list) for k in item)
        ):
            raise ValueError(
                "槽位关系只能含members、retain、replaces三个数组；实际字段："
                + str(list(item) if isinstance(item, dict) else type(item).__name__)
            )
        members, retained = item["members"], item["retain"]
        if any(
            not isinstance(i, str) or i not in candidates or i in seen for i in members
        ):
            raise ValueError("当前要求编号重复或未知。")
        if len(set(members)) != len(members):
            raise ValueError("当前要求不能重复映射。")
        seen.update(members)
        if any(
            not isinstance(i, str) or i not in old or i in seen_old for i in retained
        ):
            raise ValueError("旧槽位重复或未知。")
        if len(set(retained)) != len(retained):
            raise ValueError("旧槽不能重复保留。")
        seen_old.update(retained)
        checks = [candidates[i] for i in members] + [old[i]["check"] for i in retained]
        literals = {c.get("literal") for c in checks}
        if len(literals) > 1:
            raise ValueError("字面与语义要求、不同字面条件不能作为等义槽合并。")
        target = None
        if checks:
            check = dict(old[retained[0]]["check"] if retained else checks[0])
            origins = []
            for c in checks:
                for origin in c.get(
                    "origins",
                    [{k: c[k] for k in ("id", "criterion", "request_turn") if k in c}],
                ):
                    if origin not in origins:
                        origins.append(origin)
            sid = retained[0] if retained else _slot_id(name, check)
            check.update(
                id=sid, slot_id=sid, origins=origins, requirement_key=key(check)
            )
            target = sid
            slots.append(
                {
                    "slot_id": sid,
                    "status": "active",
                    "check": check,
                    "created_turn": min(
                        [old[i]["created_turn"] for i in retained] or [number]
                    ),
                    "last_turn": max(
                        [old[i]["last_turn"] for i in retained]
                        + [
                            c.get("introduced_turn", c.get("request_turn", 0))
                            for c in checks
                        ]
                    ),
                }
            )
        if not checks and not item["replaces"]:
            raise ValueError("空槽没有有效要求或删除依据。")
        for replacement in item["replaces"]:
            if (
                not isinstance(replacement, dict)
                or replacement.get("slot_id") not in old
            ):
                raise ValueError("被替换的旧槽无效。")
            sid = replacement["slot_id"]
            if sid in seen_old:
                raise ValueError("旧槽不能同时保留和替换。")
            _replacement(replacement, old[sid]["last_turn"], requests, "slot_id")
            seen_old.add(sid)
            retired.append(
                {
                    **old[sid],
                    "status": "replaced",
                    "replacement": replacement,
                    "replaced_by": target,
                }
            )
    if seen != set(candidates) or seen_old != set(old):
        raise ValueError("要求关系遗漏当前项或未取消的旧槽，不能保存不完整要求。")
    if len({s["slot_id"] for s in slots}) != len(slots):
        raise ValueError("槽位标识重复。")
    return slots + retired


def reconcile(client, turn, store, task, state, files):
    ledger = dict(state.get("effective_requirements", {}).get("files", {}))
    for name, file in files.items():
        current = consolidate(file["checks"])
        previous = [s for s in ledger.get(name, []) if s["status"] == "active"]
        # A single initial obligation has no semantic relation to adjudicate.
        if not current and not any(
            g["kind"] == "superseded" for g in file.get("groups", [])
        ):
            raw = {
                "slots": [
                    {"members": [], "retain": [s["slot_id"]], "replaces": []}
                    for s in previous
                ],
                "discard": [],
            }
            slots = validate(
                raw, name, [], previous, state.get("user_requests", []), turn.number
            )
        elif len(current) <= 1 and not previous:
            raw = {
                "slots": [
                    {"members": [c["id"]], "retain": [], "replaces": []}
                    for c in current
                ],
                "discard": [],
            }
            slots = validate(
                raw, name, current, [], state.get("user_requests", []), turn.number
            )
        else:
            messages = [
                {"role": "system", "content": PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "file_name": name,
                            "current": current,
                            "previous": previous,
                            "requests": state.get("user_requests", []),
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
            for attempt in range(2):
                if turn.cancelled.is_set():
                    raise OperationCancelled("已停止，未保存要求关系。")
                response = client._request(
                    {
                        "model": client.config.model,
                        "messages": messages,
                        "temperature": 0,
                        "max_tokens": 6000,
                        "stream": False,
                        "response_format": {"type": "json_object"},
                    },
                    turn.cancelled,
                )
                try:
                    choice = response["choices"][0]
                    if choice["finish_reason"] != "stop":
                        raise ValueError("要求关系被截断。")
                    raw = json.loads(choice["message"]["content"])
                    slots = validate(
                        raw,
                        name,
                        current,
                        previous,
                        state.get("user_requests", []),
                        turn.number,
                    )
                    break
                except (ValueError, TypeError, KeyError, IndexError) as error:
                    store.event(
                        task,
                        "requirement_relations_rejected",
                        {
                            "file_name": name,
                            "error": str(error),
                            "attempt": attempt + 1,
                            "response": str(
                                response.get("choices", [{}])[0]
                                .get("message", {})
                                .get("content", "")
                            )[:24000],
                        },
                    )
                    attempted = (
                        response.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content")
                    )
                    if isinstance(attempted, str):
                        messages.append({"role": "assistant", "content": attempted})
                    messages.append(
                        {
                            "role": "user",
                            "content": str(error) + "修正关系JSON，不增删要求。",
                        }
                    )
            else:
                raise CompanionError("要求关系未完整建立，未执行新修改。")
        retired = [s for s in ledger.get(name, []) if s["status"] != "active"]
        ledger[name] = retired + slots
        file["checks"] = [s["check"] for s in slots if s["status"] == "active"]
    # Archived deliverables retain an audit ledger but are not reintroduced.
    return {"version": 1, "files": ledger, "turn": turn.number}
