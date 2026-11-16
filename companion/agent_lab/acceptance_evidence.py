"""Derive semantic verdicts from explicit omissions and actual-file quotations."""


def checked(values, count, index, content):
    if not isinstance(values, list) or len(values) != count:
        raise ValueError("验收没有完整覆盖每项要求及未完成反馈。")
    indexes, results = set(), []
    for value in values:
        if (
            not isinstance(value, dict)
            or set(value) != {index, "applicable", "assertions", "reason"}
            or type(value[index]) is not int
            or value[index] not in range(count)
            or value[index] in indexes
            or type(value["applicable"]) is not bool
            or not isinstance(value["reason"], str)
            or not 1 <= len(value["reason"].strip()) <= 1000
            or not isinstance(value["assertions"], list)
        ):
            raise ValueError(
                "验收字段、索引或证据清单无效。不能返回独立status或覆盖判定字段。"
            )
        indexes.add(value[index])
        claims = value["assertions"]
        if (not value["applicable"] and claims) or (
            value["applicable"] and not 1 <= len(claims) <= 30
        ):
            raise ValueError("适用的内容要求必须逐项提供证据或具体遗漏。")
        for position, claim in enumerate(claims):
            if (
                not isinstance(claim, dict)
                or not {"requirement", "quote", "issue"} <= set(claim)
                or set(claim)
                - {"requirement", "quote", "issue", "reason", "applicable"}
                or any(
                    not isinstance(claim[k], str) or len(claim[k]) > 1000
                    for k in claim
                    if k != "applicable"
                )
                or not claim["requirement"].strip()
                or type(claim.get("applicable", True)) is not bool
                or (
                    claim.get("applicable", True)
                    and not claim["issue"].strip()
                    and not claim["quote"].strip()
                )
                or (
                    not claim.get("applicable", True)
                    and (claim["quote"] or claim["issue"])
                )
                or (claim["quote"] and claim["quote"] not in content)
            ):
                raise ValueError(
                    f"{index}={value[index]}的assertions[{position}]无效：符合项必须引用actual_content确切文字；缺失用issue；纯计数、原文操作等不适用子项用applicable=false且quote/issue都为空。不能增加status或覆盖字段。"
                )
        issues = [c["issue"] for c in claims if c["issue"].strip()]
        status = (
            "not_applicable"
            if not value["applicable"]
            else ("violated" if issues else "satisfied")
        )
        results.append(
            {
                **value,
                "status": status,
                "reason": "；".join(issues)[:1000] if issues else value["reason"],
            }
        )
    return results
