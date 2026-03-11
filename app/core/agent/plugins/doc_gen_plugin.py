# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║   Koto  ─  Document Generation Plugin（文档生成 Agent 工具）     ║
╚══════════════════════════════════════════════════════════════════╝

注册以下 Agent 工具：

  create_word_document(doc_data)
    → 将 LLM 生成的结构化内容写入 .docx，返回下载路径

  create_pdf_document(doc_data)
    → 生成专业 PDF 文档（需要 reportlab），返回下载路径

  create_excel_report(doc_data)
    → 生成格式化 Excel 报表（支持多 Sheet + 合计行），返回下载路径

  create_presentation(doc_data)
    → 生成 PowerPoint 演示文稿，返回下载路径

工具的 doc_data 参数均接受同一种 JSON 结构，由 DocGenService.build_request() 解析。
LLM 只需按照 schema 输出 JSON，插件负责调用生成器并返回文件路径。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from app.core.agent.base import AgentPlugin

logger = logging.getLogger(__name__)

# 本地下载路由前缀（与 Flask web 端的 /download 路由保持一致）
_DOWNLOAD_PREFIX = "/download/doc_gen"


def _to_download_url(file_path: str) -> str:
    """将绝对路径转换为前端可访问的下载 URL。"""
    p = Path(file_path)
    return f"{_DOWNLOAD_PREFIX}/{p.name}"


class DocGenPlugin(AgentPlugin):
    """Koto 文档生成 Agent 插件。支持 Word / PDF / Excel / PowerPoint。"""

    @property
    def name(self) -> str:
        return "DocGen"

    @property
    def description(self) -> str:
        return "生成专业品质的 Word / PDF / Excel / PowerPoint 文档"

    def get_tools(self) -> List[Dict[str, Any]]:
        # doc_data 的 JSON Schema（4 个工具共用，可选参数不强制）
        _DOC_DATA_SCHEMA = {
            "type": "OBJECT",
            "description": (
                "文档内容的结构化描述。必须包含 title 和 sections。\n\n"
                "**sections 中每个元素的 content_type 取值：**\n"
                "  - `heading`：章节标题，level=1/2/3 对应 H1/H2/H3\n"
                "  - `text`：正文段落，content 为字符串\n"
                "  - `table`：表格，content 为二维数组，首行为表头\n"
                "  - `bullet`：无序列表，content 为字符串数组\n"
                "  - `numbered`：有序列表，content 为字符串数组\n"
                "  - `code`：代码块，content 为字符串\n"
                "  - `quote`：引用块\n"
                "  - `page_break`：分页符\n\n"
                "**style_preset 取值：** `professional`（默认）/ `academic` / `minimal` / `colorful`\n\n"
                "**excel_sheets（Excel 专用，可选）：** 对象数组，每个对象含 name/title/"
                "column_headers/rows/add_totals_row。\n\n"
                "示例：\n"
                "{\n"
                '  "title": "2026年市场分析报告",\n'
                '  "author": "Koto AI",\n'
                '  "style_preset": "professional",\n'
                '  "sections": [\n'
                '    {"content_type": "heading", "content": "执行摘要", "level": 1},\n'
                '    {"content_type": "text",    "content": "本季度整体收入增长18%..."},\n'
                '    {"content_type": "table",   "content": [["指标","数值"],["收入","¥1,200万"]]},\n'
                '    {"content_type": "bullet",  "content": ["亮点1","亮点2"]}\n'
                "  ]\n"
                "}"
            ),
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "文档标题（必填）"
                },
                "author": {
                    "type": "STRING",
                    "description": "作者名称，默认为 Koto AI"
                },
                "subject": {
                    "type": "STRING",
                    "description": "文档主题/副标题"
                },
                "style_preset": {
                    "type": "STRING",
                    "description": "样式预设：professional / academic / minimal / colorful"
                },
                "sections": {
                    "type": "ARRAY",
                    "description": "文档内容块数组，每个元素含 content_type / content / level / caption"
                },
                "excel_sheets": {
                    "type": "ARRAY",
                    "description": "（Excel 专用）多 Sheet 定义数组"
                },
                "output_filename": {
                    "type": "STRING",
                    "description": "输出文件名（不含扩展名），留空则自动生成"
                },
                "pptx_layout": {
                    "type": "STRING",
                    "description": "（PPT 专用）幻灯片比例：widescreen（16:9）或 standard（4:3）"
                },
            },
            "required": ["title", "sections"]
        }

        return [
            {
                "name": "create_word_document",
                "func": self.create_word_document,
                "description": (
                    "将结构化内容生成为专业 Word (.docx) 文档。\n"
                    "支持：标题、正文段落、表格（带斑马条纹和彩色表头）、无序/有序列表、代码块、引用、图片、分页符。\n"
                    "适用于：报告、方案、合同、说明书、周报等需要富文本格式的文档。\n"
                    "生成后返回文件路径和下载链接。"
                ),
                "parameters": _DOC_DATA_SCHEMA,
            },
            {
                "name": "create_pdf_document",
                "func": self.create_pdf_document,
                "description": (
                    "将结构化内容生成为专业 PDF 文档（基于 reportlab）。\n"
                    "PDF 不可二次编辑，适合正式发布、存档或分享给外部。\n"
                    "支持中文内容（自动检测系统中文字体）。\n"
                    "适用于：正式报告、合同归档、简历、产品说明、白皮书等。\n"
                    "若需可编辑文档请使用 create_word_document。"
                ),
                "parameters": _DOC_DATA_SCHEMA,
            },
            {
                "name": "create_excel_report",
                "func": self.create_excel_report,
                "description": (
                    "将数据生成为格式化 Excel (.xlsx) 报表。\n"
                    "特性：彩色表头、斑马条纹、自适应列宽、冻结首行、可选合计行、支持多工作表。\n"
                    "适用于：数据汇总表、财务报表、销售数据、考勤记录、项目统计等。\n"
                    "提示：在 doc_data 中使用 excel_sheets 字段定义多个工作表；"
                    "若文档 sections 中含 table 类型内容也会自动提取为默认 Sheet。"
                ),
                "parameters": _DOC_DATA_SCHEMA,
            },
            {
                "name": "create_presentation",
                "func": self.create_presentation,
                "description": (
                    "将结构化内容生成为 PowerPoint (.pptx) 演示文稿。\n"
                    "规则：H1 标题自动创建新幻灯片，H2/正文/列表追加到当前幻灯片，表格独立成页。\n"
                    "适用于：汇报 PPT、产品介绍、培训材料、项目进展等场景。\n"
                    "提示：内容应多用标题+要点列表结构，正文不宜过长（每页建议不超过 6 个要点）。"
                ),
                "parameters": _DOC_DATA_SCHEMA,
            },
        ]

    # ──────────────────────────────────────────────────────────────────────────
    # 工具实现
    # ──────────────────────────────────────────────────────────────────────────

    def _get_service(self):
        from app.core.services.doc_gen_service import DocGenService
        return DocGenService()

    def _parse_doc_data(self, doc_data: Any) -> Dict:
        """接受 str（JSON）或 dict，统一转为 dict。"""
        if isinstance(doc_data, str):
            try:
                return json.loads(doc_data)
            except json.JSONDecodeError as e:
                raise ValueError(f"doc_data 不是合法 JSON: {e}")
        if isinstance(doc_data, dict):
            return doc_data
        raise TypeError(f"doc_data 类型不支持: {type(doc_data)}")

    def create_word_document(self, doc_data: Any) -> str:
        """生成 Word .docx 文档，返回文件路径和下载链接的 JSON 字符串。"""
        try:
            data   = self._parse_doc_data(doc_data)
            svc    = self._get_service()
            from app.core.services.doc_gen_service import DocGenService
            req    = DocGenService.build_request(data)
            path   = svc.generate_word(req)
            return json.dumps({
                "status": "success",
                "format": "docx",
                "file_path": path,
                "download_url": _to_download_url(path),
                "message": f"✅ Word 文档已生成：{Path(path).name}",
            }, ensure_ascii=False)
        except Exception as e:
            logger.exception("[DocGenPlugin] create_word_document 失败")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

    def create_pdf_document(self, doc_data: Any) -> str:
        """生成 PDF 文档，返回文件路径和下载链接的 JSON 字符串。"""
        try:
            data   = self._parse_doc_data(doc_data)
            svc    = self._get_service()
            from app.core.services.doc_gen_service import DocGenService
            req    = DocGenService.build_request(data)
            path   = svc.generate_pdf(req)
            return json.dumps({
                "status": "success",
                "format": "pdf",
                "file_path": path,
                "download_url": _to_download_url(path),
                "message": f"✅ PDF 文档已生成：{Path(path).name}",
            }, ensure_ascii=False)
        except ImportError:
            return json.dumps({
                "status": "error",
                "message": "reportlab 未安装，请运行: pip install reportlab>=4.0.0",
            }, ensure_ascii=False)
        except Exception as e:
            logger.exception("[DocGenPlugin] create_pdf_document 失败")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

    def create_excel_report(self, doc_data: Any) -> str:
        """生成 Excel .xlsx 报表，返回文件路径和下载链接的 JSON 字符串。"""
        try:
            data   = self._parse_doc_data(doc_data)
            svc    = self._get_service()
            from app.core.services.doc_gen_service import DocGenService
            req    = DocGenService.build_request(data)
            path   = svc.generate_excel(req)
            return json.dumps({
                "status": "success",
                "format": "xlsx",
                "file_path": path,
                "download_url": _to_download_url(path),
                "message": f"✅ Excel 报表已生成：{Path(path).name}",
            }, ensure_ascii=False)
        except Exception as e:
            logger.exception("[DocGenPlugin] create_excel_report 失败")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

    def create_presentation(self, doc_data: Any) -> str:
        """生成 PowerPoint .pptx，返回文件路径和下载链接的 JSON 字符串。"""
        try:
            data   = self._parse_doc_data(doc_data)
            svc    = self._get_service()
            from app.core.services.doc_gen_service import DocGenService
            req    = DocGenService.build_request(data)
            path   = svc.generate_presentation(req)
            return json.dumps({
                "status": "success",
                "format": "pptx",
                "file_path": path,
                "download_url": _to_download_url(path),
                "message": f"✅ PowerPoint 已生成：{Path(path).name}",
            }, ensure_ascii=False)
        except Exception as e:
            logger.exception("[DocGenPlugin] create_presentation 失败")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)
