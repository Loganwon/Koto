"""Fixed public office-task scenarios; these are not model-quality answers.

Plans drive the deterministic fixture provider only. Independent rules inspect
the actual persisted files and receipts after production runtime execution.
"""

from __future__ import annotations


def tool(name, **args):
    return {"name": name, "args": args}


def phase(prompt, steps, *, inputs=(), target="", mode="answer", answer="observed"):
    return {"prompt": prompt, "steps": steps, "inputs": list(inputs),
            "target": target, "mode": mode, "answer": answer}


def case(case_id, group, title, phases, checks, *, fault=""):
    return {"id": case_id, "group": group, "title": title, "phases": phases,
            "checks": checks, "fault": fault}


def rule(kind, **values):
    return {"kind": kind, **values}


def fixed_cases():
    read = lambda name: tool("parse_file_to_text", path="$ROOT/" + name)
    create = lambda name, text: tool("create_file", path="$ROOT/" + name, content=text)
    replace = lambda name, old, new, occurrence=1: tool(
        "replace_file_selection", path="$ROOT/" + name,
        original_selection=old, new_content=new, occurrence=occurrence,
    )
    append_docx = lambda name, text: tool(
        "write_docx_content", path="$ROOT/" + name, paragraphs=[{"text": text}],
    )
    update_cell = lambda name, value: tool(
        "write_sheet_data", path="$ROOT/" + name, sheet_name="Sheet1",
        updates=[{"row": 2, "col": 2, "value": value}],
    )
    append_slide = lambda name: tool(
        "add_pptx_slides", path="$ROOT/" + name,
        slides=[{"title": "后续行动", "content": ["12月31日前完成复核", "责任人：项目组"]}],
    )
    unchanged = rule("untouched_inputs")
    no_duplicates = lambda name, text: rule("text_count", file=name, text=text, count=1)
    cases = [
        case("R01", "read", "读取季度关键数字", [phase(
            "读取source.txt，回答季度营收和同比，写明来源，不要修改文件。",
            [read("source.txt")], inputs=["source.txt"],
        )], [unchanged, rule("answer_contains", values=["240", "20%", "source.txt"])]),
        case("R02", "read", "汇总CSV部门预算", [phase(
            "读取sales.csv，计算三个部门预算总和，写明万元和来源，不改文件。",
            [read("sales.csv")], inputs=["sales.csv"], answer="csv_sum",
        )], [unchanged, rule("answer_contains", values=["240", "万元", "sales.csv"])]),
        case("R03", "read", "读取Word原文与表格", [phase(
            "读取brief.docx，列出营收、同比和合同编号，保留原文档。",
            [tool("read_docx_content", path="$ROOT/brief.docx")], inputs=["brief.docx"],
        )], [unchanged, rule("answer_contains", values=["240", "20%", "KT-2026-12", "brief.docx"])]),
        case("R04", "read", "汇总Excel预算", [phase(
            "读取budget.xlsx的Sheet1，计算三个部门预算总额，单位万元，不改工作簿。",
            [tool("read_sheet_data", path="$ROOT/budget.xlsx", sheet_name="Sheet1")],
            inputs=["budget.xlsx"], answer="xlsx_sum",
        )], [unchanged, rule("answer_contains", values=["240", "万元", "budget.xlsx"])]),
        case("R05", "read", "读取演示文稿里程碑", [phase(
            "读取milestones.pptx，给出截止日与市场预算并标注来源，不改PPT。",
            [read("milestones.pptx")], inputs=["milestones.pptx"],
        )], [unchanged, rule("answer_contains", values=["2026-12-31", "40", "milestones.pptx"])]),
        case("R06", "read", "跨材料核对数字与日期", [phase(
            "同时读取source.txt和milestones.pptx，核对营收240万元与截止日期并引用两个来源。",
            [read("source.txt"), read("milestones.pptx")], inputs=["source.txt", "milestones.pptx"],
        )], [unchanged, rule("answer_contains", values=["240", "2026-12-31", "source.txt", "milestones.pptx"])]),
        case("M01", "modify", "只润色指定文本", [phase(
            "只把edit.txt中的‘我们希望通过这个项目，把团队的工作效率进行一个全面的提升。’改成‘本项目旨在提升团队工作效率。’，其余字节不变。",
            [replace("edit.txt", "我们希望通过这个项目，把团队的工作效率进行一个全面的提升。", "本项目旨在提升团队工作效率。")],
            inputs=["edit.txt"], target="edit.txt", mode="edit",
        )], [rule("exact_text", file="edit.txt", expected="标题保持不变\r\n本项目旨在提升团队工作效率。\r\n第二段保持不变。\r\n"), rule("only_target_changed", files=["edit.txt"])]),
        case("M02", "modify", "只替换第二处重复锚点", [phase(
            "duplicate.txt有两处‘待确认’，只把第二处改成‘已确认’，第一处及金额不动。",
            [replace("duplicate.txt", "待确认", "已确认", 2)], inputs=["duplicate.txt"], target="duplicate.txt", mode="edit",
        )], [rule("exact_text", file="duplicate.txt", expected="第一项：待确认，120万元\n第二项：已确认，80万元\n"), rule("only_target_changed", files=["duplicate.txt"])]),
        case("M03", "modify", "CSV单元范围修改", [phase(
            "只把sales.csv中市场预算40改为45万元，表头和其他部门不变。",
            [replace("sales.csv", "市场,40", "市场,45")], inputs=["sales.csv"], target="sales.csv", mode="edit",
        )], [rule("exact_text", file="sales.csv", expected="部门,金额(万元)\n产品,120\n运营,80\n市场,45\n"), rule("only_target_changed", files=["sales.csv"])]),
        case("M04", "modify", "Word追加并保留原格式", [phase(
            "在brief.docx末尾追加‘复核结论：2026-12-31前完成。’一次，原加粗段、标题和表格不变。",
            [append_docx("brief.docx", "复核结论：2026-12-31前完成。")], inputs=["brief.docx"], target="brief.docx", mode="edit",
        )], [rule("docx_prefix_preserved", file="brief.docx", extra=1), no_duplicates("brief.docx", "复核结论：2026-12-31前完成。"), rule("only_target_changed", files=["brief.docx"])]),
        case("M05", "modify", "Excel精确改单元格保公式样式", [phase(
            "仅将budget.xlsx的Sheet1!B2改为125，其他值、B5合计公式和B2填充格式不变。",
            [update_cell("budget.xlsx", 125)], inputs=["budget.xlsx"], target="budget.xlsx", mode="edit",
        )], [rule("xlsx_cell", file="budget.xlsx", cell="B2", value=125), rule("xlsx_scope", file="budget.xlsx", allowed=["B2"]), rule("only_target_changed", files=["budget.xlsx"])]),
        case("M06", "modify", "PPT追加行动页保原页面", [phase(
            "在milestones.pptx后追加一张后续行动页，写明12月31日前完成复核和责任人项目组，原幻灯片不变。",
            [append_slide("milestones.pptx")], inputs=["milestones.pptx"], target="milestones.pptx", mode="edit",
        )], [rule("pptx_prefix_preserved", file="milestones.pptx", extra=1), no_duplicates("milestones.pptx", "后续行动"), rule("only_target_changed", files=["milestones.pptx"])]),
        case("G01", "generate_followup", "生成Word后追加追改", [
            phase("读取source.txt，生成report.docx，保留来源和关键数字。", [read("source.txt"), create("report.docx", "季度报告\n来源：source.txt\n$OBSERVED")], inputs=["source.txt"], target="report.docx", mode="create"),
            phase("继续在刚生成的report.docx末尾追加‘后续行动：复核收入结构。’一次，不另建文档。", [append_docx("report.docx", "后续行动：复核收入结构。")], inputs=["report.docx"], target="report.docx", mode="edit"),
        ], [rule("contains", file="report.docx", values=["240", "20%", "source.txt"]), no_duplicates("report.docx", "后续行动：复核收入结构。"), rule("generated_outputs", files=["report.docx"])]),
        case("G02", "generate_followup", "生成Markdown后局部追改", [
            phase("读取source.txt，生成report.md，注明来源和原始数字。", [read("source.txt"), create("report.md", "# 初稿\n来源：source.txt\n$OBSERVED")], inputs=["source.txt"], target="report.md", mode="create"),
            phase("仅把刚生成report.md的标题‘初稿’改为‘季度结论’，保留来源数字，不另建文件。", [replace("report.md", "# 初稿", "# 季度结论")], inputs=["report.md"], target="report.md", mode="edit"),
        ], [rule("contains", file="report.md", values=["# 季度结论", "240", "20%", "source.txt"]), rule("generated_outputs", files=["report.md"])]),
        case("G03", "generate_followup", "生成预算CSV后追改", [
            phase("生成summary.csv，列部门和预算：产品120、运营80、市场40万元。", [create("summary.csv", "部门,金额(万元)\n产品,120\n运营,80\n市场,40\n")], target="summary.csv", mode="create"),
            phase("继续把summary.csv的市场预算改成45，保持其他两行不变。", [replace("summary.csv", "市场,40", "市场,45")], inputs=["summary.csv"], target="summary.csv", mode="edit"),
        ], [rule("csv_rows", file="summary.csv", expected=[["部门", "金额(万元)"], ["产品", "120"], ["运营", "80"], ["市场", "45"]]), rule("generated_outputs", files=["summary.csv"])]),
        case("G04", "generate_followup", "生成Excel后追改单元格", [
            phase("生成summary.xlsx，Sheet1列部门预算：产品120、运营80、市场40。", [create("summary.xlsx", "部门,金额\n产品,120\n运营,80\n市场,40")], target="summary.xlsx", mode="create"),
            phase("继续仅把刚生成summary.xlsx的B2改为125，其他数字保留。", [update_cell("summary.xlsx", 125)], inputs=["summary.xlsx"], target="summary.xlsx", mode="edit"),
        ], [rule("xlsx_cell", file="summary.xlsx", cell="B2", value=125), rule("xlsx_cell", file="summary.xlsx", cell="B3", value="80"), rule("generated_outputs", files=["summary.xlsx"])]),
        case("G05", "generate_followup", "生成PPT后补行动页", [
            phase("生成summary.pptx，标题季度汇报，写明营收240万元、同比20%。", [create("summary.pptx", "# 季度汇报\n- 营收240万元\n- 同比20%")], target="summary.pptx", mode="create"),
            phase("在刚生成summary.pptx追加后续行动页，原页数字不动，不另存副本。", [append_slide("summary.pptx")], inputs=["summary.pptx"], target="summary.pptx", mode="edit"),
        ], [rule("contains", file="summary.pptx", values=["240", "20%", "后续行动"]), no_duplicates("summary.pptx", "后续行动"), rule("generated_outputs", files=["summary.pptx"])]),
        case("G06", "generate_followup", "生成Word后两轮追改不重复", [
            phase("生成actions.docx，标题行动清单，正文第一项核对营收240万元。", [create("actions.docx", "行动清单\n第一项：核对营收240万元。")], target="actions.docx", mode="create"),
            phase("继续在actions.docx末尾增加第二项：核对同比20%。", [append_docx("actions.docx", "第二项：核对同比20%。")], inputs=["actions.docx"], target="actions.docx", mode="edit"),
            phase("继续在actions.docx末尾增加第三项：复核2026-12-31截止日。", [append_docx("actions.docx", "第三项：复核2026-12-31截止日。")], inputs=["actions.docx"], target="actions.docx", mode="edit"),
        ], [no_duplicates("actions.docx", "第一项：核对营收240万元。"), no_duplicates("actions.docx", "第二项：核对同比20%。"), no_duplicates("actions.docx", "第三项：复核2026-12-31截止日。"), rule("generated_outputs", files=["actions.docx"])]),
        case("E01", "recovery", "锚点不匹配时不覆盖", [phase(
            "尝试把edit.txt中的‘不存在的句子’替换为‘新句子’，找不到就说明未写入，不能重建文件。",
            [replace("edit.txt", "不存在的句子", "新句子")], inputs=["edit.txt"], target="edit.txt", mode="edit",
        )], [unchanged, rule("no_success_terminal"), rule("tool_failure_observed")]),
        case("E02", "recovery", "重复锚点越界不写", [phase(
            "尝试修改duplicate.txt中第三处‘待确认’，只有两处时应拒绝且不改原文件。",
            [replace("duplicate.txt", "待确认", "已确认", 3)], inputs=["duplicate.txt"], target="duplicate.txt", mode="edit",
        )], [unchanged, rule("no_success_terminal"), rule("tool_failure_observed")]),
        case("E03", "recovery", "缺失材料不编造结论", [phase(
            "读取missing.txt提取营收；若文件缺失就说明无法读取，不得虚构数字或创建文件。",
            [read("missing.txt")], inputs=["missing.txt"],
        )], [unchanged, rule("absent", file="missing.txt"), rule("answer_excludes", values=["营收240", "读取成功"]), rule("failure_evidence")]),
        case("E04", "recovery", "同名生成不覆盖已有文件", [phase(
            "尝试创建edit.txt写入新版本；同名已存在时应拒绝，保留原文件。",
            [create("edit.txt", "不应覆盖原文件")], inputs=["edit.txt"], target="edit.txt", mode="create",
        )], [unchanged, rule("no_success_terminal"), rule("tool_failure_observed")]),
        case("E05", "recovery", "持久化失败保留原Word", [phase(
            "在brief.docx追加‘追加内容’，若保存失败应保留原Word并报告失败。",
            [append_docx("brief.docx", "追加内容")], inputs=["brief.docx"], target="brief.docx", mode="edit",
        )], [unchanged, rule("no_success_terminal"), rule("tool_failure_observed")], fault="save_failure"),
        case("E06", "recovery", "提交后中断恢复不重复写", [phase(
            "在brief.docx末尾追加‘已恢复提交：复核完成。’；提交后中断恢复必须沿用原回执，不得再次追加。",
            [append_docx("brief.docx", "已恢复提交：复核完成。")], inputs=["brief.docx"], target="brief.docx", mode="edit",
        )], [rule("docx_prefix_preserved", file="brief.docx", extra=1), no_duplicates("brief.docx", "已恢复提交：复核完成。"), rule("resume_receipt"), rule("tool_name_call_count", name="write_docx_content", count=1), rule("only_target_changed", files=["brief.docx"])], fault="checkpoint_resume"),
    ]
    for item in cases:
        if item["group"] == "read":
            allowed = {
                "R01": ["240万元", "20%"], "R02": ["240万元"],
                "R03": ["240万元", "20%"], "R04": ["240万元"],
                "R05": ["40万元"], "R06": ["240万元", "20%", "40万元"],
            }[item["id"]]
            item["checks"].append(rule("grounded_numbers", values=allowed, dates=["2026-12-31"]))
        elif item["id"] in {"G01", "G02", "G05"}:
            name = {"G01": "report.docx", "G02": "report.md", "G05": "summary.pptx"}[item["id"]]
            item["checks"].append(rule("grounded_numbers", file=name, values=["240万元", "20%"], dates=["2026-12-31"]))
    return cases
