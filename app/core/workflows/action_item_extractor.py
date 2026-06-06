# ══════════════════════════════════════════════════════════════
# action_item_extractor.py — 碎片化沟通待办事项提取
#
# 用户场景：将微信聊天记录、邮件、会议纪要（多个文件或直接
# 粘贴文本）发给 AI → 提取所有待办、负责人、截止日期、状态。
# ══════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.workflow_engine import (
    WorkflowExecutor,
    sse_error,
    sse_output,
    sse_step_done,
    sse_step_start,
)

logger = logging.getLogger(__name__)

_EXTRACT_SYSTEM = """你是一个专业的项目管理助手，擅长从非结构化沟通记录中提取待办事项。

从输入的沟通记录中提取所有待办事项，对每条待办输出以下字段：
- task: 任务描述（清晰明确，不超过100字）
- owner: 负责人姓名/昵称（没有则为 null）
- deadline: 截止日期（格式 YYYY-MM-DD，没有则为 null）
- status: 任务状态（pending | in_progress | done | overdue 之一）
- priority: 优先级推断（high | medium | low 之一）
- source: 该待办来自哪一段文字的简短描述

请以 JSON 数组格式输出，不要任何 markdown 标记。
如果没有找到待办事项，返回空数组 []。
"""

_REPORT_SYSTEM = """你是一个项目管理助手。
将以下待办事项列表整理为一份清晰的中文周报/进度报告（Markdown 格式）。

报告结构：
# 待办事项汇总
## ⚠️ 高优先级（需立即处理）
- ...
## 📅 正常推进
- ...
## ✅ 已完成
- ...
## ❓ 待确认责任人
- ...

要求：
- 按优先级分组
- 每条待办格式：`- [责任人] 任务描述（截止日期）`
- 语言简洁专业
"""


class ActionItemExtractor(WorkflowExecutor):
    """
    碎片化沟通待办事项提取工作流。

    params 期望字段:
        texts:       List[str] — 直接输入的文本片段列表（聊天记录/邮件等）
        files:       List[str] — 文件路径列表（txt/docx/pdf）
        output_mode: str       — "excel" | "markdown"（默认 "excel"）
        model_mode:  str       — "auto" | "local"
    """

    WORKFLOW_ID = "action_item_extractor"
    WORKFLOW_NAME = "待办事项提取"

    def execute(self, params: dict, yield_event) -> Any:
        raw_texts: list[str] = params.get("texts") or []
        files: list[str] = params.get("files") or []
        output_mode: str = params.get("output_mode") or "excel"
        model_mode: str = params.get("model_mode") or "auto"

        all_texts: list[str] = list(raw_texts)

        # ── Step 1: 解析文件 ──────────────────────────────────────────────────
        if files:
            yield sse_step_start("parse_files", f"📂 解析 {len(files)} 个文件…")
            for fp in files:
                text = self.parse_file(fp)
                if text.strip():
                    fname = fp.split("\\")[-1].split("/")[-1]
                    all_texts.append(f"[文件: {fname}]\n{text}")
            yield sse_step_done(
                "parse_files", f"📂 文件解析完成，累计 {len(all_texts)} 段文本"
            )

        if not all_texts:
            yield sse_error("请提供至少一段文本（texts）或一个文件（files）")
            return

        # ── Step 2: LLM 提取待办 ──────────────────────────────────────────────
        yield sse_step_start("extract", "🤖 提取待办事项…")

        # 将所有文本合并，超长则分段处理
        combined = "\n\n---\n\n".join(all_texts)
        items = self._extract_items(combined, model_mode)

        yield sse_step_done(
            "extract",
            (
                f"🤖 提取到 {len(items)} 条待办事项"
                if items
                else "🤖 未找到明确的待办事项"
            ),
        )

        if not items:
            yield sse_output(
                "markdown", "# 待办事项汇总\n\n暂未发现明确的待办事项。", "提取结果"
            )
            return

        # ── Step 3: 生成报告/表格 ─────────────────────────────────────────────
        if output_mode == "markdown":
            yield sse_step_start("gen_report", "📝 生成进度报告…")
            report = self._generate_report(items, model_mode)
            yield sse_step_done("gen_report", "📝 报告生成完成")
            yield sse_output("markdown", report, f"待办报告（{len(items)} 条）")
        else:
            yield sse_step_start("build_output", "📊 生成任务表格…")
            workbook = self._build_workbook(items)
            yield sse_step_done("build_output", "📊 表格生成完成")
            yield sse_output("xlsx_data", workbook, f"待办事项（{len(items)} 条）")

    # ── 辅助方法 ──────────────────────────────────────────────────────────────

    def _extract_items(self, text: str, model_mode: str) -> list[dict]:
        """调用 LLM 提取结构化待办事项列表。分段处理超长文本。"""
        _MAX_CHARS = 12000
        segments = []
        if len(text) <= _MAX_CHARS:
            segments.append(text)
        else:
            # 按段落分割后按 _MAX_CHARS 合并
            paras = text.split("\n\n")
            current = ""
            for p in paras:
                if len(current) + len(p) > _MAX_CHARS:
                    if current:
                        segments.append(current)
                    current = p
                else:
                    current = (current + "\n\n" + p).strip()
            if current:
                segments.append(current)

        all_items: list[dict] = []
        for seg in segments:
            prompt = f"请从以下沟通记录中提取所有待办事项：\n\n{seg}"
            try:
                result = self.llm_json(
                    prompt, system=_EXTRACT_SYSTEM, model_mode=model_mode
                )
                if isinstance(result, list):
                    all_items.extend(result)
                elif isinstance(result, dict) and "items" in result:
                    all_items.extend(result["items"])
            except Exception as e:
                logger.warning(f"[ActionItem] 提取失败: {e}")

        return all_items

    def _generate_report(self, items: list[dict], model_mode: str) -> str:
        """用 LLM 将待办列表生成 Markdown 格式的进度报告。"""
        items_json = json.dumps(items, ensure_ascii=False, indent=2)
        prompt = f"以下是提取的待办事项列表（JSON 格式）：\n\n{items_json}\n\n请生成一份中文进度报告。"
        try:
            return self.llm(prompt, system=_REPORT_SYSTEM, model_mode=model_mode)
        except Exception as e:
            logger.warning(f"[ActionItem] 报告生成失败: {e}")
            return "# 待办事项汇总\n\n报告生成失败，请查看表格输出。"

    def _build_workbook(self, items: list[dict]) -> dict:
        """将待办事项列表转为 Univer IWorkbookData 格式。"""
        import uuid as _uuid

        wb_id = str(_uuid.uuid4())[:8]
        sheet_id = "action_items"

        columns = ["task", "owner", "deadline", "status", "priority", "source"]
        col_names_cn = {
            "task": "任务描述",
            "owner": "负责人",
            "deadline": "截止日期",
            "status": "状态",
            "priority": "优先级",
            "source": "来源",
        }
        # 状态/优先级颜色
        status_colors = {
            "overdue": "#ffcccc",
            "in_progress": "#d4edda",
            "pending": "#fff3cd",
            "done": "#e2e3e5",
        }
        priority_colors = {
            "high": "#ffcccc",
            "medium": "#fff3cd",
            "low": "#e2e3e5",
        }
        header_style = {"bl": 1, "bg": {"rgb": "#1a73e8"}, "cl": {"rgb": "#ffffff"}}

        cell_data: dict = {}
        # 表头
        row0: dict = {}
        for c, col in enumerate(columns):
            row0[str(c)] = {"v": col_names_cn[col], "t": 1, "s": header_style}
        cell_data["0"] = row0

        # 数据行
        for r, item in enumerate(items, start=1):
            row_cells: dict = {}
            for c, col in enumerate(columns):
                v = item.get(col) or ""
                cell: dict = {"v": str(v), "t": 1}
                # 状态列着色
                if col == "status" and str(v) in status_colors:
                    cell["s"] = {"bg": {"rgb": status_colors[str(v)]}}
                elif col == "priority" and str(v) in priority_colors:
                    cell["s"] = {"bg": {"rgb": priority_colors[str(v)]}}
                row_cells[str(c)] = cell
            cell_data[str(r)] = row_cells

        return {
            "id": wb_id,
            "name": "待办事项",
            "appVersion": "0.5.0",
            "sheetOrder": [sheet_id],
            "sheets": {
                sheet_id: {
                    "id": sheet_id,
                    "name": "待办事项",
                    "rowCount": len(items) + 1,
                    "columnCount": len(columns),
                    "cellData": cell_data,
                    "mergeData": [],
                }
            },
            "styles": {},
        }
