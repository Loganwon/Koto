# ══════════════════════════════════════════════════════════════
# workflow_api.py — 工作流 Skill 统一 API 端点
#
# 蓝图路由:
#   GET  /api/workflow/list     — 返回所有可用工作流描述
#   POST /api/workflow/execute  — 执行工作流（SSE 流式响应）
#   POST /api/workflow/upload   — 上传工作流输入文件（返回临时路径）
# ══════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, send_file, stream_with_context

logger = logging.getLogger(__name__)

workflow_bp = Blueprint("workflow", __name__)

# ── 工作流注册表 ───────────────────────────────────────────────────────────────

_WORKFLOW_REGISTRY = {
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
    # ── Prompt-only (chat) workflows ──────────────────────────────────────
    # These have no Python executor; activation sends the prompt through the
    # normal AI chat pathway with file context.
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


@workflow_bp.route("/api/workflow/list", methods=["GET"])
def workflow_list():
    """返回所有可用工作流的描述信息。"""
    return jsonify({
        "success": True,
        "workflows": list(_WORKFLOW_REGISTRY.values()),
    })


@workflow_bp.route("/api/workflow/execute", methods=["POST"])
def workflow_execute():
    """
    执行工作流，返回 SSE 流式响应。

    Request JSON:
    {
        "workflow_id": "cross_format_extractor",
        "params": {
            "source_files": ["/tmp/abc/file1.pdf", ...],
            "template_file": "/tmp/abc/template.xlsx",
            ...
        }
    }

    SSE events: status | progress | step_start | step_done | code |
                output | diff | error | done
    """
    data = request.get_json(silent=True) or {}
    workflow_id = (data.get("workflow_id") or "").strip()
    params = data.get("params") or {}

    if not workflow_id:
        return jsonify({"success": False, "error": "缺少 workflow_id 参数"}), 400

    if workflow_id not in _WORKFLOW_REGISTRY:
        return jsonify({"success": False, "error": f"未知的工作流: {workflow_id}"}), 404

    # Chat-mode workflows run through normal AI chat, not the execute endpoint
    if _WORKFLOW_REGISTRY[workflow_id].get("mode") == "chat":
        return jsonify({"success": False, "error": f"工作流 {workflow_id} 为对话模式，请通过聊天发送"}), 400

    executor = _get_executor(workflow_id)
    if executor is None:
        return jsonify({"success": False, "error": f"工作流 {workflow_id} 加载失败"}), 500

    def generate():
        yield from executor.run(params)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@workflow_bp.route("/api/workflow/upload", methods=["POST"])
def workflow_upload():
    """
    上传工作流输入文件到临时目录，返回文件路径供后续 execute 调用。

    支持多文件上传（multipart/form-data, 字段名 files[]）。
    返回: {"success": True, "paths": ["/tmp/koto_wf_xxx/file.pdf", ...]}
    """
    uploaded_files = request.files.getlist("files[]") or request.files.getlist("file")
    if not uploaded_files:
        return jsonify({"success": False, "error": "没有收到文件"}), 400

    # 每次上传创建独立的临时目录（以 session 或 uuid 为 key）
    session_id = request.form.get("session_id") or str(uuid.uuid4())[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"koto_wf_{session_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    for f in uploaded_files:
        if not f.filename:
            continue
        # 安全处理文件名
        safe_name = Path(f.filename).name
        dest = tmp_dir / safe_name
        try:
            f.save(str(dest))
            saved_paths.append(str(dest))
        except Exception as e:
            logger.warning(f"[WorkflowAPI] 文件保存失败: {e}")

    return jsonify({"success": True, "paths": saved_paths, "session_id": session_id})


@workflow_bp.route("/api/workflow/download", methods=["GET"])
def workflow_download():
    """
    下载工作流产出文件（docx/pptx/xlsx 等）。

    Query params:
        path — 临时目录中的文件绝对路径
    """
    path = request.args.get("path", "").strip()
    if not path:
        return jsonify({"error": "缺少 path 参数"}), 400

    file_path = Path(path)
    if not file_path.exists():
        return jsonify({"error": "文件不存在"}), 404

    # 安全校验：只允许下载 temp 目录下 koto_wf_ 前缀的文件
    try:
        resolved = file_path.resolve()
        tmp_root = Path(tempfile.gettempdir()).resolve()
        if not str(resolved).startswith(str(tmp_root)):
            return jsonify({"error": "无权访问该路径"}), 403
        if "koto_wf_" not in resolved.parts[-2] if len(resolved.parts) >= 2 else "":
            return jsonify({"error": "无权访问该路径"}), 403
    except Exception:
        return jsonify({"error": "路径校验失败"}), 403

    return send_file(
        str(resolved),
        as_attachment=True,
        download_name=resolved.name,
    )


# ── 工作流实例工厂 ─────────────────────────────────────────────────────────────

def _get_executor(workflow_id: str):
    """按 workflow_id 返回对应的 WorkflowExecutor 实例。"""
    try:
        if workflow_id == "cross_format_extractor":
            from app.core.workflows.cross_format_extractor import CrossFormatExtractor
            return CrossFormatExtractor()
        if workflow_id == "data_format_cleaner":
            from app.core.workflows.data_format_cleaner import DataFormatCleaner
            return DataFormatCleaner()
        if workflow_id == "questionnaire_filler":
            from app.core.workflows.questionnaire_filler import QuestionnaireFiller
            return QuestionnaireFiller()
        if workflow_id == "doc_smart_compare":
            from app.core.workflows.doc_smart_compare import DocSmartCompare
            return DocSmartCompare()
        if workflow_id == "comm_digest":
            from app.core.workflows.comm_digest import CommDigest
            return CommDigest()
        if workflow_id == "data_fill_report":
            from app.core.workflows.data_fill_report import DataFillReport
            return DataFillReport()
        if workflow_id == "contract_clause_matrix":
            from app.core.workflows.contract_clause_matrix import ContractClauseMatrix
            return ContractClauseMatrix()
        if workflow_id == "multi_file_synthesis_report":
            from app.core.workflows.multi_file_synthesis_report import MultiFileSynthesisReport
            return MultiFileSynthesisReport()
        if workflow_id == "pptx_data_refresh":
            from app.core.workflows.pptx_data_refresh import PptxDataRefresh
            return PptxDataRefresh()
        if workflow_id == "doc_ai_review":
            from app.core.workflows.doc_ai_review import DocAIReview
            return DocAIReview()
        if workflow_id == "data_anomaly_report":
            from app.core.workflows.data_anomaly_report import DataAnomalyReport
            return DataAnomalyReport()
    except Exception as e:
        logger.error(f"[WorkflowAPI] 加载执行器失败 {workflow_id}: {e}")
    return None
