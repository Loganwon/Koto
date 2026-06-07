# ══════════════════════════════════════════════════════════════
# cross_format_extractor.py — 跨格式信息搬运与填报
#
# 用户场景：将 N 个 PDF/Word（简历/发票/订单）的指定字段
# 批量提取，按模板 Excel 的列标题自动填入汇总表。
# ══════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.workflow_engine import (
    WorkflowExecutor,
    sse_progress,
    sse_step_done,
    sse_step_start,
    sse_output,
    sse_status,
    sse_error,
)

logger = logging.getLogger(__name__)

# 每个文档发给 LLM 的最大字符数（避免超 token）
_MAX_DOC_CHARS = 6000
# 单次批量提取最多发送的文档数（Gemini Flash 1.5 上下文约 128K）
_BATCH_SIZE = 10


class CrossFormatExtractor(WorkflowExecutor):
    """
    跨格式信息搬运与 Excel 填报工作流。

    params 期望字段:
        source_files:  List[str]  — 待提取文档的绝对路径列表
        template_file: str        — 模板 Excel 文件的绝对路径（可选）
        fields:        List[str]  — 要提取的字段名列表（template_file 存在时可不传）
        model_mode:    str        — "auto" | "local"（默认 "auto"）
    """

    WORKFLOW_ID = "cross_format_extractor"
    WORKFLOW_NAME = "跨格式信息搬运"

    def execute(self, params: dict, yield_event) -> Any:
        source_files: list[str] = params.get("source_files") or []
        template_file: str = params.get("template_file") or ""
        fields: list[str] = params.get("fields") or []
        model_mode: str = params.get("model_mode") or "auto"

        if not source_files:
            yield sse_error("请至少提供一个源文件（source_files）")
            return

        # ── Step 1: 从模板获取字段列表 ────────────────────────────────────────
        yield sse_step_start("parse_template", "📋 解析模板字段…")
        if template_file and not fields:
            fields = self._extract_template_fields(template_file)
            if not fields:
                yield sse_error("无法从模板 Excel 中识别到任何列标题，请手动指定 fields 参数")
                return
        if not fields:
            yield sse_error("请提供要提取的字段列表（fields）或一个包含列标题的 Excel 模板")
            return

        yield sse_step_done("parse_template", f"📋 识别到 {len(fields)} 个字段: {', '.join(fields[:8])}{'…' if len(fields)>8 else ''}")

        # ── Step 2: 逐文件解析 + LLM 提取 ────────────────────────────────────
        yield sse_step_start("extract_fields", f"🔍 处理 {len(source_files)} 个文档…")
        rows: list[dict] = []
        total = len(source_files)
        for idx, fpath in enumerate(source_files):
            yield sse_progress(idx + 1, total, fpath.split("\\")[-1].split("/")[-1])
            doc_text = self.parse_file(fpath)
            if not doc_text.strip():
                logger.warning(f"[CrossFormat] 文件无文本内容: {fpath}")
                rows.append({f: None for f in fields})
                continue
            extracted = self._extract_fields_from_text(
                doc_text[:_MAX_DOC_CHARS], fields, model_mode
            )
            # 附加来源文件名
            extracted["_source_file"] = fpath.split("\\")[-1].split("/")[-1]
            rows.append(extracted)

        yield sse_step_done("extract_fields", f"🔍 已提取 {len(rows)} 条记录")

        # ── Step 3: 组装 Univer IWorkbookData ────────────────────────────────
        yield sse_step_start("build_output", "📊 生成结果表格…")
        # fields 可能由调用方传入字符串（逗号分隔），统一转为 list
        if isinstance(fields, str):
            fields = [f.strip() for f in fields.split(",") if f.strip()]
        workbook = self._build_workbook(fields, rows)
        yield sse_step_done("build_output", "📊 表格生成完成")

        # ── Step 4: 输出 ──────────────────────────────────────────────────────
        yield sse_output("xlsx_data", workbook, f"提取结果 ({len(rows)} 行)")

    # ── 辅助方法 ──────────────────────────────────────────────────────────────

    def _extract_template_fields(self, template_path: str) -> list[str]:
        """从 Excel 第一行提取列标题。"""
        try:
            from app.core.file.file_parser import parse_xlsx
            result = parse_xlsx(template_path, "")
            for sheet_id, sheet in result.get("sheets", {}).items():
                cell_data = sheet.get("cellData", {})
                if not cell_data:
                    logger.warning(f"[CrossFormat] sheet {sheet_id} cellData 为空")
                    continue
                # parse_xlsx returns integer keys (0, 1, 2...) not string keys
                row0 = cell_data.get(0) or cell_data.get("0") or {}
                if not row0:
                    # 尝试找第一个有数据的行作为表头（某些表格不从第0行开始）
                    sorted_rows = sorted(cell_data.keys(), key=lambda x: int(x))
                    if sorted_rows:
                        row0 = cell_data.get(sorted_rows[0], {})
                        logger.info(f"[CrossFormat] row0 为空，使用第 {sorted_rows[0]} 行作为表头")
                if not row0:
                    continue
                col_count = max((int(k) for k in row0.keys()), default=-1) + 1
                headers = []
                for c in range(col_count):
                    cell = row0.get(c) or row0.get(str(c)) or {}
                    v = cell.get("v", "") or cell.get("m", "") or ""
                    if str(v).strip():
                        headers.append(str(v).strip())
                if headers:
                    logger.info(f"[CrossFormat] 识别到表头: {headers}")
                    return headers
        except Exception as e:
            logger.warning(f"[CrossFormat] 模板解析失败: {e}", exc_info=True)
        return []

    def _extract_fields_from_text(
        self, text: str, fields: list[str], model_mode: str
    ) -> dict:
        """调用 LLM 从文本中按字段列表提取结构化数据。"""
        fields_json = json.dumps(fields, ensure_ascii=False)
        prompt = (
            f"你是一个精准的数据提取助手。请从以下文档内容中提取指定字段的值。\n\n"
            f"要提取的字段列表（JSON 格式）:\n{fields_json}\n\n"
            f"文档内容:\n---\n{text}\n---\n\n"
            f"以 JSON 格式输出，key 为字段名（与上方列表完全一致），value 为提取到的值。"
            f"如果在文档中找不到某字段，值设为 null。\n"
            f"只输出 JSON 对象，不要任何解释或 markdown 代码块。"
        )
        try:
            result = self.llm_json(prompt, model_mode=model_mode)
            if isinstance(result, dict):
                # 确保所有字段都出现在结果中
                return {f: result.get(f) for f in fields}
        except Exception as e:
            logger.warning(f"[CrossFormat] LLM 提取失败: {e}")
        return {f: None for f in fields}

    def _build_workbook(self, fields: list[str], rows: list[dict]) -> dict:
        """
        构建 Univer IWorkbookData 格式的工作簿（用于前端直接渲染）。
        """
        import uuid as _uuid

        wb_id = str(_uuid.uuid4())[:8]
        sheet_id = "extracted_data"

        # 表头行（row 0）
        all_cols = fields + ["_source_file"]
        cell_data: dict = {}

        # 样式：表头加粗蓝底白字
        header_style = {
            "bl": 1,
            "bg": {"rgb": "#1a73e8"},
            "cl": {"rgb": "#ffffff"},
        }

        row0: dict = {}
        for c, col_name in enumerate(all_cols):
            row0[str(c)] = {"v": col_name, "t": 1, "s": header_style}
        cell_data["0"] = row0

        # 数据行
        for r, row in enumerate(rows, start=1):
            row_cells: dict = {}
            for c, col_name in enumerate(all_cols):
                v = row.get(col_name)
                if v is None:
                    v = ""
                row_cells[str(c)] = {"v": str(v), "t": 1}
            cell_data[str(r)] = row_cells

        # 列宽（按字段名长度估算）
        col_widths = {}
        for c, col_name in enumerate(all_cols):
            col_widths[str(c)] = max(80, min(200, len(col_name) * 16))

        return {
            "id": wb_id,
            "name": "提取结果",
            "appVersion": "0.5.0",
            "sheetOrder": [sheet_id],
            "sheets": {
                sheet_id: {
                    "id": sheet_id,
                    "name": "提取结果",
                    "rowCount": len(rows) + 1,
                    "columnCount": len(all_cols),
                    "cellData": cell_data,
                    "columnData": col_widths,
                    "mergeData": [],
                }
            },
            "styles": {},
        }
