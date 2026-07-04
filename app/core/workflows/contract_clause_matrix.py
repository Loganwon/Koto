# ══════════════════════════════════════════════════════════════
# contract_clause_matrix.py — 合同条款提取矩阵
#
# 用户场景：
#   上传一份或多份合同（Word/PDF/TXT），
#   AI 逐份提取关键条款（付款、责任、知产、终止、违约金等）
#   生成风险着色的结构化 Excel 矩阵。
# ══════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
import uuid as _uuid
from typing import Any

from app.core.workflow_engine import (
    WorkflowExecutor,
    sse_error,
    sse_output,
    sse_progress,
    sse_step_done,
    sse_step_start,
)

logger = logging.getLogger(__name__)

_MAX_DOC_CHARS = 8000

_DEFAULT_CLAUSE_TYPES = [
    "付款条款",
    "责任限制",
    "知识产权",
    "终止条款",
    "管辖法律",
    "违约金",
    "保密条款",
    "争议解决",
]

_EXTRACT_SYSTEM = """你是一名专业的合同审查律师。
请从以下合同文本中提取指定类型的条款内容，并评估每条的风险等级。

输出 JSON 对象，key 为条款类型名（与提供的列表完全一致），value 格式：
{
  "clause_text": "条款原文摘要（50-200字）",
  "risk_level": "low | medium | high | critical",
  "notes": "简短风险说明（一句话）"
}

如果合同中未找到该类型条款，value 设为：
{"clause_text": "未找到", "risk_level": "none", "notes": ""}

只输出 JSON 对象，不要任何说明或 markdown 代码块。"""


class ContractClauseMatrix(WorkflowExecutor):
    """
    合同条款提取矩阵工作流。

    params 期望字段:
        contract_files: List[str]  — 合同文件路径列表
        custom_clauses: str        — 额外条款类型（逗号分隔，可选）
        model_mode:     str        — "auto" | "local"
    """

    WORKFLOW_ID = "contract_clause_matrix"
    WORKFLOW_NAME = "合同条款提取矩阵"

    def execute(self, params: dict, yield_event) -> Any:
        files: list[str] = params.get("contract_files") or []
        custom: str = params.get("custom_clauses") or ""
        model_mode: str = params.get("model_mode") or "auto"

        if not files:
            yield sse_error("请至少上传一份合同文件（contract_files）")
            return

        # ── 构建条款类型列表 ──────────────────────────────────────────
        clause_types = list(_DEFAULT_CLAUSE_TYPES)
        if custom:
            extras = [
                c.strip() for c in custom.replace("，", ",").split(",") if c.strip()
            ]
            clause_types.extend(extras)

        # ── Step 1: 逐份解析 + LLM 提取 ─────────────────────────────
        yield sse_step_start("extract", f"📑 分析 {len(files)} 份合同…")
        all_rows: list[dict] = []
        filenames: list[str] = []

        for idx, fpath in enumerate(files):
            fname = fpath.split("\\")[-1].split("/")[-1]
            filenames.append(fname)
            yield sse_progress(idx + 1, len(files), fname)

            text = self.parse_file(fpath)
            if not text.strip():
                logger.warning("[ClauseMatrix] 文件无内容: %s", fpath)
                all_rows.append(
                    {
                        ct: {
                            "clause_text": "解析失败",
                            "risk_level": "none",
                            "notes": "",
                        }
                        for ct in clause_types
                    }
                )
                continue

            extracted = self._extract_clauses(
                text[:_MAX_DOC_CHARS], clause_types, model_mode
            )
            all_rows.append(extracted)

        yield sse_step_done("extract", f"📑 已分析 {len(all_rows)} 份合同")

        # ── Step 2: 构建结果表格 ─────────────────────────────────────
        yield sse_step_start("build", "📊 生成条款矩阵…")
        workbook = self._build_workbook(clause_types, filenames, all_rows)
        yield sse_step_done("build", "📊 矩阵生成完成")

        # ── Step 3: 生成风险摘要 ─────────────────────────────────────
        yield sse_step_start("summary", "📋 生成风险摘要…")
        summary = self._build_summary(clause_types, filenames, all_rows)
        yield sse_step_done("summary", "📋 摘要生成完成")

        # ── 输出 ─────────────────────────────────────────────────────
        risk_count = sum(
            1
            for row in all_rows
            for ct in clause_types
            if row.get(ct, {}).get("risk_level") in ("high", "critical")
        )
        yield sse_output(
            "xlsx_data",
            workbook,
            f"条款矩阵（{len(filenames)} 份合同，{risk_count} 处高风险）",
        )
        yield sse_output("markdown", summary, "风险摘要")

    # ── 辅助方法 ──────────────────────────────────────────────────────

    def _extract_clauses(
        self, text: str, clause_types: list[str], model_mode: str
    ) -> dict:
        """调用 LLM 提取各条款。"""
        types_json = json.dumps(clause_types, ensure_ascii=False)
        prompt = (
            f"请从以下合同中提取这些类型的条款：\n{types_json}\n\n"
            f"合同内容：\n---\n{text}\n---"
        )
        try:
            result = self.llm_json(
                prompt, system=_EXTRACT_SYSTEM, model_mode=model_mode
            )
            if isinstance(result, dict):
                return {
                    ct: result.get(
                        ct, {"clause_text": "未找到", "risk_level": "none", "notes": ""}
                    )
                    for ct in clause_types
                }
        except Exception as e:
            logger.warning("[ClauseMatrix] LLM 提取失败: %s", e)
        return {
            ct: {"clause_text": "提取失败", "risk_level": "none", "notes": ""}
            for ct in clause_types
        }

    def _build_workbook(
        self, clause_types: list[str], filenames: list[str], rows: list[dict]
    ) -> dict:
        """构建 Univer IWorkbookData。行=合同，列=条款类型。"""
        wb_id = str(_uuid.uuid4())[:8]
        sheet_id = "clause_matrix"

        # 风险等级 → 背景色
        risk_colors = {
            "critical": "#ffcdd2",  # 红
            "high": "#ffe0b2",  # 橙
            "medium": "#fff9c4",  # 黄
            "low": "#c8e6c9",  # 绿
            "none": "#f5f5f5",  # 灰
        }

        all_cols = ["合同文件"] + clause_types
        cell_data: dict = {}

        # 表头
        header_style = {"bl": 1, "bg": {"rgb": "#1a73e8"}, "cl": {"rgb": "#ffffff"}}
        row0: dict = {}
        for c, col_name in enumerate(all_cols):
            row0[str(c)] = {"v": col_name, "t": 1, "s": header_style}
        cell_data["0"] = row0

        # 数据行
        for r, (fname, row) in enumerate(zip(filenames, rows), start=1):
            row_cells: dict = {}
            row_cells["0"] = {"v": fname, "t": 1, "s": {"bl": 1}}
            for c, ct in enumerate(clause_types, start=1):
                info = row.get(ct, {})
                clause_text = info.get("clause_text", "")
                risk = info.get("risk_level", "none")
                notes = info.get("notes", "")
                display = clause_text
                if notes:
                    display = f"{clause_text}\n[{notes}]"
                bg = risk_colors.get(risk, "#f5f5f5")
                row_cells[str(c)] = {
                    "v": display,
                    "t": 1,
                    "s": {"bg": {"rgb": bg}, "tb": 3},  # tb=3: wrap text
                }
            cell_data[str(r)] = row_cells

        col_widths = {"0": 120}
        for c in range(1, len(all_cols)):
            col_widths[str(c)] = 200

        return {
            "id": wb_id,
            "name": "条款提取矩阵",
            "appVersion": "0.5.0",
            "sheetOrder": [sheet_id],
            "sheets": {
                sheet_id: {
                    "id": sheet_id,
                    "name": "条款矩阵",
                    "rowCount": len(rows) + 1,
                    "columnCount": len(all_cols),
                    "cellData": cell_data,
                    "columnData": col_widths,
                    "mergeData": [],
                }
            },
            "styles": {},
        }

    def _build_summary(
        self, clause_types: list[str], filenames: list[str], rows: list[dict]
    ) -> str:
        """生成 Markdown 风险摘要。"""
        lines = ["# 合同条款风险摘要\n"]
        risk_icon = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🟢",
            "none": "⚪",
        }

        for r, (fname, row) in enumerate(zip(filenames, rows)):
            lines.append(f"\n## {fname}\n")
            for ct in clause_types:
                info = row.get(ct, {})
                risk = info.get("risk_level", "none")
                notes = info.get("notes", "")
                icon = risk_icon.get(risk, "⚪")
                line = f"- {icon} **{ct}**: {risk}"
                if notes:
                    line += f" — {notes}"
                lines.append(line)

        return "\n".join(lines)
