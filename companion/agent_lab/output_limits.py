"""Typed, durable output constraints. No interpretation of free-text requests."""


def merge_limits(state, limits):
    result = dict(state.get("output_limits", {}))
    for item in limits:
        name = item["file_name"]
        if name not in state["expected_outputs"]:
            raise ValueError("字数约束必须属于当前交付清单。")
        fields = {k: v for k, v in item.items() if k != "file_name"}
        if not fields:
            raise ValueError("每份交付至少提供一项明确约束。")
        if name.lower().endswith(".docx"):
            if set(fields) - {"max_body_characters"}:
                raise ValueError("DOCX只接受正文总字数约束。")
        elif name.lower().endswith(".pptx"):
            if set(fields) - {
                "max_slide_body_characters",
                "exact_slide_count",
                "min_slide_count",
                "max_slide_count",
            }:
                raise ValueError("PPTX只接受逐页正文及页数约束。")
        else:
            raise ValueError("当前字数约束支持DOCX和PPTX。")
        previous = dict(result.get(name, {}))
        count_fields = {"exact_slide_count", "min_slide_count", "max_slide_count"}
        if count_fields.intersection(fields):
            for key in count_fields:
                previous.pop(key, None)
        merged = {**previous, **fields}
        minimum, maximum = merged.get("min_slide_count", 1), merged.get(
            "max_slide_count", 20
        )
        if (
            minimum > maximum
            or not minimum <= merged.get("exact_slide_count", minimum) <= maximum
        ):
            raise ValueError("页数上下限或精确页数互相矛盾。")
        result[name] = merged
    return result


def validate_metrics(metrics, limits):
    violations = []
    total = metrics.get("body_characters_including_headings_and_tables")
    maximum = limits.get("max_body_characters")
    if maximum is not None and total is not None and total > maximum:
        violations.append(
            f"Word正文{total}字，上限{maximum}字，至少缩短{total - maximum}字。"
        )
    counts = metrics.get("slide_body_characters", [])
    maximum = limits.get("max_slide_body_characters")
    if maximum is not None:
        for i, count in enumerate(counts, 1):
            if count > maximum:
                violations.append(
                    f"第{i}页正文{count}字，上限{maximum}字，至少缩短{count - maximum}字。"
                )
    exact = limits.get("exact_slide_count")
    count = metrics.get("slide_count")
    if count is not None and (
        count < limits.get("min_slide_count", 0)
        or count > limits.get("max_slide_count", 20)
    ):
        violations.append(
            f"幻灯片{count}页，要求{limits.get('min_slide_count', 1)}至{limits.get('max_slide_count', 20)}页。"
        )
    if exact is not None and metrics.get("slide_count") != exact:
        violations.append(f"幻灯片{metrics.get('slide_count')}页，要求{exact}页。")
    return {
        "passed": not violations,
        "violations": violations,
        "next_action": (
            "修改实际超限正文，保留数据、限定和引用，再测量新草稿。"
            if violations
            else "本次计数满足已登记约束。生成时须使用同一份内容，生成后重新读取实际交付核对。"
        ),
    }


def draft_validation(state, name, metrics, format=None):
    limits = state.get("output_limits", {})
    if not name and format:
        candidates = [
            n
            for n in state["expected_outputs"]
            if n in limits and n.lower().endswith("." + format)
        ]
        if len(candidates) == 1:
            name = candidates[0]
    return (
        {"file_name": name, **validate_metrics(metrics, limits[name])}
        if name in limits
        else None
    )
