# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from typing import Any

from app.core.agent.file_task_runtime_utils import (
    _followup_has_prior_excel_docx_insert,
)


def financial_chart_docx_guidance(enabled: bool) -> str:
    if not enabled:
        return ""
    return (
        "Excel 财务预测图表写入 DOCX 任务规则：\n"
        "- 目标不是把原始 Excel 表格塞进 Word，而是生成“问题清单/分析结论 + 真实图表图片”。\n"
        "- 必须先审计 Excel：inspect_workbook_structure 或 audit_financial_workbook；必要时读取 P&L、产品线、Expenses、资本折旧等关键工作表。\n"
        "- 如果 pandas 读出的列名是 Unnamed，不要用 df.columns 找年份列；应扫描每一行，定位包含 2025E/2026E/2027E/2028E 等年份标签的 header row，再按这些列抽取指标。\n"
        "- 优先用 openpyxl/data_only=True 读取公式结果，并通过行标签匹配“收入合计、毛利合计、费用合计、净利润、销量”等指标；不要猜空列名。\n"
        "- 用 run_python_code 生成真实 PNG/JPG 图表，stdout 必须包含 KOTO_CREATED: <图片路径>；仅打印数据或错误栈不算完成。\n"
        "- 随后调用 write_docx_content 写入问题清单/分析结论，再调用 insert_image_into_docx 插入真实图片；没有 file.changed 不能结束。\n"
    )


def docx_compare_annotate_guidance(enabled: bool, docx_files: list[str]) -> str:
    if not enabled:
        return ""
    return (
        "DOCX 双文件对比标注任务规则：\n"
        f"- 待对比 DOCX：{', '.join(item for item in docx_files if item) or '已附加的两份 DOCX'}\n"
        "- 这是跨文件差异比较，不是单文档审校；不要调用 annotate_file 批改其中一份文稿，也不要创建独立的对比说明文档。\n"
        "- 目标是修改现有 DOCX：把 Word 原生批注写在 target_path 对应原文条款/段落旁边。\n"
        "- target_path 必须是用户要被标注的那份 DOCX；如果用户说“原文/原文件/当前文档/第一份文档上标注”，必须指向该文件。\n"
        "- 推荐流程：先调用 plan_docx_compare_annotations(original_path, revised_path, target_path) 定位目标文档里的可批注差异锚点；再根据候选差异生成 comments_json 数组，调用 write_docx_comments(path=target_path, comments_json=[...]) 写回原 DOCX。\n"
        "- comments_json 必须直接传数组对象，不要把数组转成需要转义的长字符串；每项必须使用候选中的原文片段/anchor 作为锚点；批注内容应简洁说明“另一版为：... 本版为：...”。\n"
        "- 合同任务的批注可补充“风险：...”和“建议：...”，但这些内容也必须作为 Word 批注写在目标合同原文旁边。\n"
        "- 仅当需要兜底时才使用 compare_docx_and_annotate 一步完成；优先让 AI 基于候选差异撰写批注内容后调用 write_docx_comments。\n"
        "- 完成后必须产生 file.changed，且 annotations_added > 0 才能声称已标注差异；对话框总结只概括批注数量和高风险类别。\n"
    )


def followup_guidance(followup_context: dict[str, Any]) -> str:
    if str(followup_context.get("kind") or "").strip() != "review_last_task":
        return ""
    followup_action = str(
        followup_context.get("followup_action") or ""
    ).strip().lower()
    if followup_action == "apply":
        return (
            "当前输入是用户要求把上一轮文件任务中的建议直接应用到文件。这不是一个无关的新任务，而是同一任务的写回续跑。\n"
            "优先沿用上一轮的目标文件、分析建议、文件变更和约束；必要时只补充最少量上下文后直接执行写入。\n"
            "如果上一轮已经给出可应用建议，这一轮应进入真实写回路径并产生 file.changed；不要只重复建议文本。\n"
        )
    if followup_action == "improve":
        guidance = (
            "当前输入是用户要求围绕上一轮文件任务结果继续优化。这不是一个无关的新任务，而是同一任务的后续回合。\n"
            "先解释上一轮结果的不足和这次准备如何改进；如果确实需要，可以继续调用工具修正目标文件。"
            "优先沿用上一轮的目标、目标文件、失败点和约束，不要把上下文重置成新的独立任务。\n"
        )
        if _followup_has_prior_excel_docx_insert(followup_context):
            guidance += (
                "如果上一轮已经通过 insert_excel_as_docx_table 把 Excel 表格写入目标 DOCX，"
                "这轮继续优化时不要再次插入同一张表。"
                "优先补写摘要、说明、结论或修正已有文字；"
                "只有用户明确要求重插、替换或追加另一张表时，才再次插表。\n"
            )
        return guidance
    return (
        "当前输入是用户对上一轮文件任务结果的反馈或质问，不要默认把它当作全新的执行任务。\n"
        "先解释上一轮结果、指出可能的问题，并回答用户的追问。"
        "只有当用户明确要求重新修改文件、继续执行或调用工具时，才进入新的工具执行。"
        "如果当前只是反馈上一轮结果，不要调用写入工具，也不要伪造新的完成状态。\n"
    )


def followup_prompt_prefix(followup_context: dict[str, Any]) -> str:
    if str(followup_context.get("kind") or "").strip() != "review_last_task":
        return "请完成这个文件任务。"
    followup_action = str(
        followup_context.get("followup_action") or ""
    ).strip().lower()
    if followup_action == "apply":
        return (
            "用户要求把上一轮文件任务中已经给出的建议直接应用到目标文件。"
            "请把它视为同一任务的写回续跑，优先沿用上一轮建议、目标文件和已知约束，不要重新从头分析。"
        )
    if followup_action == "improve":
        prefix = (
            "用户要求在上一轮文件任务结果基础上继续优化。"
            "请把它视为同一任务的后续处理回合，先说明你准备如何改进，再继续处理。"
        )
        if _followup_has_prior_excel_docx_insert(followup_context):
            prefix += " 上一轮已经有实际 file.changed 记录表明目标 DOCX 插入过 Excel 表格；请先基于这些已写入结果判断缺口，不要重复同一插表。"
        return prefix
    return (
        "用户正在对上一轮文件任务结果提出反馈。"
        "请先回答上一轮结果为什么会这样、哪里可能有问题，以及是否需要重做。"
        "除非用户已经明确提出新的文件修改要求，否则不要把这条消息当成新的文件执行任务。"
    )


def single_docx_annotate_guidance(enabled: bool, target_docx: str) -> str:
    if not enabled:
        return ""
    return (
        "DOCX 审校/批注任务规则：\n"
        f"- 目标 DOCX：{target_docx}\n"
        "- 直接调用 annotate_file。对于 AI 生成批注的场景，传 path=<目标 DOCX>、requirement=<用户要求>，annotations 保持空数组即可。\n"
        "- 如果当前任务还附带 PDF 原文、分批继续执行信息或上一轮审校 follow-up，上述 annotate_file 会自动复用这些上下文；不要再绕开白盒工具循环。\n"
        "- 不要自己编造 annotations 的 range_start/range_end 去模拟 Word 定位；annotate_file 会负责分析、定位并把批注写回原文。\n"
        "- 如果目标是把意见直接写回 DOCX，不能只输出批注清单文本后结束。\n"
    )


def clear_docx_review_guidance(enabled: bool, target_docx: str) -> str:
    if not enabled:
        return ""
    return (
        "DOCX 批注/修订清理任务规则：\n"
        f"- 目标 DOCX：{target_docx}\n"
        "- 调用 clear_docx_review_marks。若用户只要求删除批注，scope 用 comments；若明确要求去掉修订或全部审阅标记，scope 用 revisions 或 all。\n"
        "- 不要调用 annotate_file 去重新生成批注，也不要走 doc_annotate_bridge。\n"
        "- 这是一个真实写回任务，完成后必须产生 file.changed。\n"
    )
