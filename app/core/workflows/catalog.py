# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Core workflow metadata catalog.

The web workflow API owns Flask routes, upload/download, and SSE transport. This
module owns the workflow definitions shown to clients so capability metadata and
Python executor ownership live under app/core together.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.core.workflows.skill_mapping import get_skill_ids_for_workflow


WORKFLOW_CATALOG: dict[str, dict[str, Any]] = {
    "cross_format_extractor": {
        "id": "cross_format_extractor",
        "name": "跨格式信息搬运",
        "icon": "📤",
        "description": "将 PDF/Word 文件中的指定字段批量提取，自动填入 Excel 模板",
        "long_desc": (
            "支持简历、发票、订单、报关单等各类格式。"
            "左侧拖入 N 个源文件，右侧拖入 Excel 模板，AI 自动识别字段并填报到对应列。"
        ),
        "params_schema": {
            "source_files": {"label": "源文件", "type": "file_list", "required": True, "accept": ".pdf,.docx,.doc,.txt"},
            "template_file": {"label": "Excel 模板（可选）", "type": "file", "required": False, "accept": ".xlsx,.xls"},
            "fields": {"label": "字段列表（逗号分隔，不用模板时填写）", "type": "text", "required": False},
        },
    },
    "data_format_cleaner": {
        "id": "data_format_cleaner",
        "name": "脏数据格式清洗",
        "icon": "🧹",
        "description": "用自然语言指令清洗 Excel 中格式混乱的日期、地址、编码等数据",
        "long_desc": (
            "先在 Excel 中选中要清洗的列，然后用中文描述清洗规则，"
            "AI 生成 pandas 代码在沙盒中执行，预览变更后一键回写。"
        ),
        "params_schema": {
            "csv_data": {"label": "表格数据（CSV 格式）", "type": "textarea", "required": True},
            "instruction": {"label": "清洗指令（例：统一日期格式为 YYYY-MM-DD）", "type": "text", "required": True},
        },
    },
    "questionnaire_filler": {
        "id": "questionnaire_filler",
        "name": "问卷自动填写",
        "icon": "📝",
        "description": "上传问题 Excel + 参考文档，AI 从参考文档中检索答案并自动填写",
        "long_desc": (
            "适用于安全合规问卷、RFP 响应、尽调问卷等场景。"
            "参考文档支持 PDF/Word/TXT，低置信度答案自动标黄提醒人工复核。"
        ),
        "params_schema": {
            "question_file": {"label": "问题 Excel 文件", "type": "file", "required": True, "accept": ".xlsx,.xls"},
            "reference_files": {"label": "参考文档", "type": "file_list", "required": True, "accept": ".pdf,.docx,.doc,.txt"},
            "question_col": {"label": "问题所在列标题（可选，默认自动识别）", "type": "text", "required": False},
            "answer_col": {"label": "答案写入列标题（可选，默认\"AI回答\"）", "type": "text", "required": False},
        },
    },
    "comm_digest": {
        "id": "comm_digest",
        "name": "沟通纪要生成",
        "icon": "📧",
        "description": "从邮件、群聊、会议纪要中提取参与者、决策、待办，生成结构化纪要",
        "long_desc": (
            "支持邮件(.eml)、聊天记录、会议纪要等多种输入。"
            "AI 提取参与者、时间线、决策事项、待办任务，"
            "输出 DOCX 纪要文档、彩色 Excel 待办表或 Markdown 报告。"
        ),
        "params_schema": {
            "texts": {"label": "直接粘贴文本（可选）", "type": "textarea", "required": False},
            "files": {"label": "上传文件（可选）", "type": "file_list", "required": False, "accept": ".txt,.eml,.docx,.pdf,.md"},
            "output_mode": {
                "label": "输出格式",
                "type": "select",
                "required": False,
                "options": [
                    {"value": "auto", "label": "自动（有文件→DOCX，纯文本→Excel）"},
                    {"value": "docx", "label": "DOCX 纪要文档"},
                    {"value": "excel", "label": "Excel 待办表格"},
                    {"value": "markdown", "label": "Markdown 报告"},
                ],
                "default": "auto",
            },
            "output_lang": {
                "label": "输出语言",
                "type": "select",
                "required": False,
                "options": [{"value": "zh", "label": "中文"}, {"value": "en", "label": "English"}],
                "default": "zh",
            },
        },
    },
    "doc_smart_compare": {
        "id": "doc_smart_compare",
        "name": "文档智能对比",
        "icon": "🔍",
        "description": "两份文档语义对比，自动选择 Word 标注或 HTML 报告输出",
        "long_desc": (
            "上传原始文档和对比版本，AI 逐条款语义比对差异。"
            "原件为 .docx 时输出 Track Changes + 批注标注；"
            "其他格式输出可视化 HTML 比对报告。高风险变更自动预警。"
        ),
        "params_schema": {
            "file_a": {"label": "原始文档", "type": "file", "required": True, "accept": ".docx,.doc,.pdf,.txt"},
            "file_b": {"label": "对比文档", "type": "file", "required": True, "accept": ".docx,.doc,.pdf,.txt"},
            "output_mode": {
                "label": "输出格式",
                "type": "select",
                "required": False,
                "options": [
                    {"value": "auto", "label": "自动（DOCX 原件→标注，其他→HTML）"},
                    {"value": "docx", "label": "Word 标注（需 .docx 原件）"},
                    {"value": "html", "label": "HTML 比对报告"},
                ],
                "default": "auto",
            },
        },
    },
    "data_fill_report": {
        "id": "data_fill_report",
        "name": "数据填报",
        "icon": "📋",
        "description": "将 Excel 数据自动填入 Word/PPT 模板的对应位置",
        "long_desc": (
            "上传数据 Excel + Word/PPT 模板，AI 智能匹配占位符与数据列，"
            "批量替换生成成品文档。支持 {{字段}}、<<字段>>、[字段] 等占位符格式。"
        ),
        "params_schema": {
            "data_file": {"label": "数据文件", "type": "file", "required": True, "accept": ".xlsx,.xls,.csv"},
            "template_file": {"label": "模板文件", "type": "file", "required": True, "accept": ".docx,.pptx"},
            "instruction": {"label": "填写说明（可选）", "type": "text", "required": False},
        },
    },
    "contract_clause_matrix": {
        "id": "contract_clause_matrix",
        "name": "合同条款提取",
        "icon": "⚖️",
        "description": "从多份合同中提取关键条款，生成风险着色的对比矩阵",
        "long_desc": (
            "上传 1-10 份合同，AI 提取付款、违约、知产、终止等条款，"
            "生成风险等级着色的 Excel 矩阵，快速识别高风险条款。"
        ),
        "params_schema": {
            "contract_files": {"label": "合同文件", "type": "file_list", "required": True, "accept": ".docx,.pdf,.txt"},
            "custom_clauses": {"label": "额外条款类型（逗号分隔，可选）", "type": "text", "required": False},
        },
    },
    "multi_file_synthesis_report": {
        "id": "multi_file_synthesis_report",
        "name": "多文档综合报告",
        "icon": "📚",
        "description": "综合分析 2-10 份文档，生成结构化 Word 研究报告",
        "long_desc": (
            "上传多份研报、论文或报告，AI 逐份提取核心发现，"
            "交叉分析共同主题与矛盾点，生成含执行摘要的结构化 DOCX 报告。"
        ),
        "params_schema": {
            "source_files": {"label": "源文件", "type": "file_list", "required": True, "accept": ".pdf,.docx,.txt,.md"},
            "report_title": {"label": "报告标题（可选）", "type": "text", "required": False},
            "focus": {"label": "分析重点（可选）", "type": "text", "required": False},
        },
    },
    "pptx_data_refresh": {
        "id": "pptx_data_refresh",
        "name": "PPT 数据刷新",
        "icon": "🔄",
        "description": "用新 Excel 数据更新现有 PPT 中的数字和文本",
        "long_desc": (
            "月报/周报 PPT 里的数据需要更新？"
            "上传 PPT + 新 Excel，AI 自动匹配并替换旧数据，保留原始格式。"
        ),
        "params_schema": {
            "pptx_file": {"label": "现有 PPT", "type": "file", "required": True, "accept": ".pptx"},
            "data_file": {"label": "新数据", "type": "file", "required": True, "accept": ".xlsx,.xls,.csv"},
            "instruction": {"label": "更新说明（可选）", "type": "text", "required": False},
        },
    },
    "doc_ai_review": {
        "id": "doc_ai_review",
        "name": "AI 文档审阅",
        "icon": "✏️",
        "description": "AI 审阅 Word 文档，在右侧批注栏添加修改建议",
        "long_desc": (
            "上传 Word 文档，选择审阅重点（语法/逻辑/语气/完整性），"
            "AI 逐段审阅后以 Word 批注形式输出建议，可直接在 Word 中处理。"
        ),
        "params_schema": {
            "doc_file": {"label": "Word 文档", "type": "file", "required": True, "accept": ".docx"},
            "review_focus": {
                "label": "审阅重点",
                "type": "select",
                "required": False,
                "options": [
                    {"value": "all", "label": "全面审阅"},
                    {"value": "grammar", "label": "语法纠错"},
                    {"value": "logic", "label": "逻辑连贯性"},
                    {"value": "tone", "label": "语气措辞"},
                    {"value": "completeness", "label": "内容完整性"},
                ],
                "default": "all",
            },
        },
    },
    "data_anomaly_report": {
        "id": "data_anomaly_report",
        "name": "数据异常检测",
        "icon": "🔬",
        "description": "扫描 Excel/CSV 中的缺失值、重复行、格式混乱和异常数值",
        "long_desc": (
            "上传数据文件，AI 自动检测缺失值、重复行、格式混用、数值异常（3σ 法则），"
            "生成着色标注的数据表 + 异常汇总报告。支持完全离线运行。"
        ),
        "params_schema": {
            "data_file": {"label": "数据文件", "type": "file", "required": True, "accept": ".xlsx,.xls,.csv"},
        },
    },
    "source_grounded_qa": {
        "id": "source_grounded_qa",
        "name": "文档溯源问答",
        "icon": "📖",
        "mode": "chat",
        "description": "仅基于文档内容回答问题，每条结论标注来源段落",
        "long_desc": "上传文档后提问，AI 严格基于文档内容作答，每条结论标注原文段落编号和引用，无文档依据时明确标注「文档未涉及」。",
    },
    "faq_generate": {
        "id": "faq_generate",
        "name": "FAQ 自动生成",
        "icon": "❓",
        "mode": "chat",
        "description": "从文档中自动生成 8-12 条常见问题与解答",
        "long_desc": "分析文档内容，从用户/读者视角生成 8-12 条高频问题及专业解答，适用于产品手册、政策文件、培训资料等场景。",
    },
    "timeline_extract": {
        "id": "timeline_extract",
        "name": "时间线提取",
        "icon": "📅",
        "mode": "chat",
        "description": "从文档中提取所有时间节点，生成按时间排序的事件线",
        "long_desc": "自动扫描文档中的日期、时间点和时间段，按时间顺序排列，标注事件、影响和关联关系，适用于项目记录、合同、历史资料等。",
    },
    "briefing_doc_gen": {
        "id": "briefing_doc_gen",
        "name": "简报生成",
        "icon": "📋",
        "mode": "chat",
        "description": "从多份资料中提炼关键信息，生成管理层简报",
        "long_desc": "综合分析多份文档资料，提炼背景、核心发现、关键数据、风险和建议，生成 500 字以内的管理层简报，适合向领导汇报。",
    },
    "key_info_extract": {
        "id": "key_info_extract",
        "name": "关键信息提取",
        "icon": "🔍",
        "mode": "chat",
        "description": "按指定维度从文档中批量提取结构化信息",
        "long_desc": "从文档中按人物、金额、日期、地点、决策等维度提取所有关键信息，标注出处和出现次数，适用于合同、报告、会议纪要等。",
    },
    "doc_translate": {
        "id": "doc_translate",
        "name": "全文翻译",
        "icon": "🌐",
        "mode": "chat",
        "description": "整篇文档专业翻译，保持原文结构和术语一致性",
        "long_desc": "保留原始段落、标题、表格格式，专业术语首次标注原文。中文→英文或英文→中文，附术语对照表。",
    },
    "study_quiz_gen": {
        "id": "study_quiz_gen",
        "name": "自测题生成",
        "icon": "🎓",
        "mode": "chat",
        "description": "从学习资料中自动生成自测题和答案解析",
        "long_desc": "根据教材、讲义或论文自动出题：选择题 + 判断题 + 简答题 + 综合题，含参考答案与详细解析，适合复习备考。",
    },
    "mind_map_gen": {
        "id": "mind_map_gen",
        "name": "思维导图生成",
        "icon": "🧠",
        "mode": "chat",
        "description": "从文档中提取知识结构，生成思维导图大纲",
        "long_desc": "将文档内容梳理为 3-4 层清晰的思维导图层级结构，标注节点间逻辑关系（因果/并列/递进），适合学习笔记和知识整理。",
    },
}


def list_workflow_definitions() -> list[dict[str, Any]]:
    """Return public workflow definitions without exposing mutable globals."""
    return [_with_related_skill_ids(workflow_id, workflow) for workflow_id, workflow in WORKFLOW_CATALOG.items()]


def get_workflow_definition(workflow_id: str) -> dict[str, Any] | None:
    normalized_id = str(workflow_id or "").strip()
    workflow = WORKFLOW_CATALOG.get(normalized_id)
    return _with_related_skill_ids(normalized_id, workflow) if workflow is not None else None


def is_chat_workflow(workflow_id: str) -> bool:
    workflow = WORKFLOW_CATALOG.get(str(workflow_id or "").strip())
    return bool(workflow and workflow.get("mode") == "chat")


def _with_related_skill_ids(workflow_id: str, workflow: dict[str, Any]) -> dict[str, Any]:
    public_workflow = deepcopy(workflow)
    related_skill_ids = get_skill_ids_for_workflow(workflow_id)
    if related_skill_ids:
        public_workflow["related_skill_ids"] = list(related_skill_ids)
    return public_workflow
