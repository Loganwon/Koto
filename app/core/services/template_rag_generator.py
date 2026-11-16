# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Template RAG Generator — 基于模板 + RAG 知识库自动生成文档
==========================================================

根据模板文件（DOCX/PPTX/XLSX）+ 用户需求，从本地 RAG 知识库检索相关信息，
使用本地 Ollama LLM 自动填充模板，生成成果文档。

架构：
  1. 接收模板路径 + 用户需求描述
  2. RAG 检索相关知识库片段
  3. 解析模板结构（占位符/标签）
  4. LLM 根据 RAG 上下文填充模板
  5. 输出填充后的文档

支持模板格式：
  - DOCX: {{placeholder}} 占位符
  - PPTX: 幻灯片备注中的 {{placeholder}}
  - XLSX: 单元格中的 {{placeholder}}

用法：
    from app.core.services.template_rag_generator import TemplateRAGGenerator

    gen = TemplateRAGGenerator()
    result = gen.generate(
        template_path="templates/report_template.docx",
        user_query="生成2024年度销售报告",
        output_path="output/sales_report_2024.docx",
    )
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 占位符正则 ──────────────────────────────────────────────────────────────
_PLACEHOLDER_RE = re.compile(r"\{\{(.+?)\}\}")

# ── 默认 prompt 模板 ────────────────────────────────────────────────────────
_PROMPT_TEMPLATE = """你是一位专业的文档生成助手。根据知识库信息填充模板占位符。

## 知识库上下文
{rag_context}

## 用户需求
{user_query}

## 占位符列表（key 必须严格使用这些名称）
{placeholders}

要求：
- 内容基于知识库上下文；信息不足时用专业知识补充，不要编造来源
- 使用中文输出内容（除非需求明确要求其他语言）
- 标题类占位符简短，正文类占位符详细

输出规则（必须遵守）：
1. 只输出一个 JSON 对象，不要输出任何解释文字
2. 不要使用 markdown 代码块围栏（不要 ```json）
3. key 必须使用双引号，value 使用双引号字符串
4. key 只能从上面的占位符列表中选取，不要创造新的 key
5. 不要重复上面已给出的示例或格式说明文字
"""


# ── TemplateRAGGenerator ────────────────────────────────────────────────────


class TemplateRAGGenerator:
    """基于模板 + RAG 的文档自动生成器。"""

    def __init__(
        self,
        model_id: Optional[str] = None,
        ollama_base_url: str = "http://127.0.0.1:11434",
    ):
        """
        参数:
            model_id        : Ollama 模型名称（默认：从用户配置读取）
            ollama_base_url : Ollama 服务地址
        """
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        if self._model_id:
            return self._model_id
        try:
            from app.core.llm.model_config import get_chat_model

            return get_chat_model()
        except Exception:
            return "qwen2.5:7b"

    # ── 核心生成方法 ────────────────────────────────────────────────────────

    def generate(
        self,
        template_path: str,
        user_query: str,
        output_path: Optional[str] = None,
        rag_k: int = 8,
        extra_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        根据模板 + RAG 知识库生成文档。

        参数:
            template_path : 模板文件路径（.docx / .pptx / .xlsx）
            user_query    : 用户需求描述（用于 RAG 检索 + LLM 理解）
            output_path   : 输出文件路径（默认：模板名_generated.ext）
            rag_k         : RAG 检索片段数
            extra_context : 额外上下文（直接注入，不走 RAG）

        返回:
            {
                "success": True/False,
                "output_path": "生成文件路径",
                "placeholders_filled": {"name": "content", ...},
                "rag_sources": ["file1.pdf", ...],
                "model_used": "qwen2.5:7b",
            }
        """
        template_path = str(template_path)
        if not os.path.exists(template_path):
            return {"success": False, "error": f"模板不存在: {template_path}"}

        ext = Path(template_path).suffix.lower()
        if ext not in (".docx", ".pptx", ".xlsx"):
            return {"success": False, "error": f"不支持的模板格式: {ext}"}

        # Step 1: 提取模板占位符
        placeholders = self._extract_placeholders(template_path, ext)
        if not placeholders:
            return {
                "success": False,
                "error": "模板中未找到占位符 {{placeholder}}",
                "hint": "请在模板中使用 {{变量名}} 格式标记需要填充的位置",
            }

        # Step 2: RAG 检索
        rag_context, rag_sources = self._retrieve_context(user_query, k=rag_k)
        if extra_context:
            rag_context = extra_context + "\n\n" + rag_context

        # Step 3: LLM 填充
        filled = self._llm_fill(placeholders, user_query, rag_context)
        if not filled:
            return {"success": False, "error": "LLM 填充失败，未返回有效结果"}

        # Step 4: 写入模板
        if not output_path:
            base = Path(template_path).stem
            output_path = str(Path(template_path).parent / f"{base}_generated{ext}")

        write_success = self._write_template(template_path, output_path, filled, ext)
        if not write_success:
            return {"success": False, "error": "写入模板失败"}

        return {
            "success": True,
            "output_path": output_path,
            "placeholders_filled": filled,
            "placeholder_count": len(placeholders),
            "rag_sources": rag_sources,
            "rag_chunks_used": len(rag_context.split("\n\n")) if rag_context else 0,
            "model_used": self.model_id,
        }

    # ── 占位符提取 ──────────────────────────────────────────────────────────

    def _extract_placeholders(self, file_path: str, ext: str) -> List[str]:
        """从模板文件中提取所有 {{placeholder}} 占位符。"""
        placeholders: List[str] = []
        seen = set()

        try:
            if ext == ".docx":
                from docx import Document

                doc = Document(file_path)
                for para in doc.paragraphs:
                    for match in _PLACEHOLDER_RE.findall(para.text):
                        ph = match.strip()
                        if ph and ph not in seen:
                            placeholders.append(ph)
                            seen.add(ph)
                for table in doc.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            for para in cell.paragraphs:
                                for match in _PLACEHOLDER_RE.findall(para.text):
                                    ph = match.strip()
                                    if ph and ph not in seen:
                                        placeholders.append(ph)
                                        seen.add(ph)

            elif ext == ".pptx":
                from pptx import Presentation

                prs = Presentation(file_path)
                for slide in prs.slides:
                    for shape in slide.shapes:
                        if shape.has_text_frame:
                            for match in _PLACEHOLDER_RE.findall(shape.text):
                                ph = match.strip()
                                if ph and ph not in seen:
                                    placeholders.append(ph)
                                    seen.add(ph)
                        if shape.has_table:
                            for row in shape.table.rows:
                                for cell in row.cells:
                                    for match in _PLACEHOLDER_RE.findall(cell.text):
                                        ph = match.strip()
                                        if ph and ph not in seen:
                                            placeholders.append(ph)
                                            seen.add(ph)

            elif ext == ".xlsx":
                from openpyxl import load_workbook

                wb = load_workbook(file_path, data_only=True)
                for sheet_name in wb.sheetnames:
                    ws = wb[sheet_name]
                    for row in ws.iter_rows():
                        for cell in row:
                            if cell.value and isinstance(cell.value, str):
                                for match in _PLACEHOLDER_RE.findall(cell.value):
                                    ph = match.strip()
                                    if ph and ph not in seen:
                                        placeholders.append(ph)
                                        seen.add(ph)

        except Exception as exc:
            logger.error("[TemplateRAG] 提取占位符失败: %s", exc)

        logger.info(
            "[TemplateRAG] 提取到 %d 个占位符: %s", len(placeholders), placeholders
        )
        return placeholders

    # ── RAG 检索 ────────────────────────────────────────────────────────────

    def _retrieve_context(self, query: str, k: int = 8) -> tuple:
        """从 RAG 知识库检索相关上下文。"""
        sources = []
        try:
            from app.core.services.rag_service import get_rag_service

            rag = get_rag_service()
            hits = rag.hybrid_retrieve(query, k=k, score_threshold=0.2)
            if not hits:
                return "（知识库中暂无相关信息）", []

            parts = []
            for i, hit in enumerate(hits):
                src = os.path.basename(hit.get("source", "unknown"))
                parts.append(
                    f"[来源: {src} | 相关度: {hit.get('score', 0):.2f}]\n{hit['content']}"
                )
                if src not in sources:
                    sources.append(src)

            return "\n\n---\n\n".join(parts), sources
        except Exception as exc:
            logger.warning("[TemplateRAG] RAG 检索失败: %s", exc)
            return "（RAG 检索暂时不可用）", []

    # ── LLM 填充 ────────────────────────────────────────────────────────────

    def _llm_fill(
        self,
        placeholders: List[str],
        user_query: str,
        rag_context: str,
    ) -> Dict[str, str]:
        """调用本地 Ollama LLM 为占位符生成填充内容。"""
        prompt = _PROMPT_TEMPLATE.format(
            rag_context=rag_context,
            user_query=user_query,
            placeholders="\n".join(f"- {p}" for p in placeholders),
        )

        try:
            import urllib.request

            payload = json.dumps(
                {
                    "model": self.model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.3},
                }
            ).encode("utf-8")

            req = urllib.request.Request(
                f"{self.ollama_base_url}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                content = result.get("message", {}).get("content", "")

            # 提取 JSON（兼容 markdown 围栏、解释文字、非严格格式）
            filled = self._parse_model_json(content)
            if not filled:
                logger.warning("[TemplateRAG] LLM 返回非 JSON，尝试逐行解析")
                filled = self._parse_line_pairs(content)

            # 兜底补齐缺失的占位符，确保模板中每个占位符都有内容
            return self._reconcile_filled(placeholders, filled, user_query)

        except Exception as exc:
            logger.error("[TemplateRAG] LLM 填充失败: %s", exc)
            return {}

    # ── 模板写入 ────────────────────────────────────────────────────────────

    # ── 占位符兜底补齐 ────────────────────────────────────────────────────

    def _reconcile_filled(
        self,
        placeholders: List[str],
        filled: Dict[str, str],
        user_query: str,
    ) -> Dict[str, str]:
        """确保每个占位符都有内容；小模型漏填时按语义兜底。"""
        result: Dict[str, str] = {}
        generic_value = ""
        if filled:
            values = [str(v) for v in filled.values() if str(v).strip()]
            if len(values) == 1:
                generic_value = values[0]

        for ph in placeholders:
            if ph in filled and str(filled[ph]).strip():
                result[ph] = str(filled[ph]).strip()
                continue
            key = ph.lower()
            if any(t in key for t in ("date", "time", "日期", "时间", "年月")):
                import datetime

                result[ph] = datetime.date.today().strftime("%Y-%m-%d")
            elif any(
                t in key
                for t in ("title", "name", "subject", "标题", "名称", "题目", "主题")
            ):
                result[ph] = generic_value or user_query.strip()[:40]
            elif any(t in key for t in ("summary", "摘要", "概述", "简介", "结论")):
                result[ph] = generic_value or (
                    user_query.strip()[:80] if user_query else "（内容待补充）"
                )
            else:
                result[ph] = generic_value or "（内容待补充，请人工校对）"

        return result

    # ── JSON 解析辅助 ───────────────────────────────────────────────────────────────

    def _parse_model_json(self, content: str) -> Dict[str, str]:
        """从 LLM 输出中稳健地提取 JSON 对象。"""
        if not content:
            return {}
        # 去掉 markdown 代码块围栏
        text = re.sub(r"```(?:json)?\s*", "", content).strip()
        text = re.sub(r"^```$", "", text, flags=re.MULTILINE).strip()

        # 用括号配平定位 JSON 对象
        start = text.find("{")
        while start != -1:
            depth = 0
            in_str = False
            esc = False
            end = -1
            for i in range(start, len(text)):
                ch = text[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end == -1:
                break
            candidate = text[start:end]
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return self._flatten_filled(parsed)
            except Exception:
                cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
                try:
                    parsed = json.loads(cleaned)
                    if isinstance(parsed, dict):
                        return self._flatten_filled(parsed)
                except Exception:
                    pass
            start = text.find("{", start + 1)
        return {}

    def _flatten_filled(self, parsed: Dict[str, Any]) -> Dict[str, str]:
        """将模型返回的嵌套 JSON 规范化为 {key: 字符串}。"""
        result: Dict[str, str] = {}
        for key, value in parsed.items():
            k = str(key).strip()
            if isinstance(value, dict):
                # 嵌套对象：优先取同名键，其次取第一个非空字符串值
                if k in value:
                    v = value[k]
                else:
                    v = ""
                    for vv in value.values():
                        if isinstance(vv, str) and vv.strip():
                            v = vv
                            break
                        if isinstance(vv, dict) and vv:
                            nested = self._flatten_filled(vv)
                            if nested:
                                v = next(iter(nested.values()))
                                break
                result[k] = str(v).strip()
            elif isinstance(value, list):
                result[k] = "\n".join(str(v) for v in value if str(v).strip())
            else:
                result[k] = str(value).strip()
        return result

    def _parse_line_pairs(self, content: str) -> Dict[str, str]:
        """逐行解析 key: value 形式的兑底方案。"""
        pairs: Dict[str, str] = {}
        for line in content.splitlines():
            line = line.strip().strip(",").strip()
            if not line or line.startswith(("```", "#", "*", "-", "{", "}")):
                continue
            m = re.match(r"^(.+?)\s*[:：]\s*(.+)$", line)
            if m:
                key = m.group(1).strip().strip("\"'").strip()
                value = m.group(2).strip().strip("\"'").rstrip(",")
                if key and value and key not in pairs:
                    pairs[key] = value
        return pairs

    def _write_template(
        self,
        template_path: str,
        output_path: str,
        filled: Dict[str, str],
        ext: str,
    ) -> bool:
        """将填充内容写入模板副本。"""
        try:
            import shutil

            shutil.copy2(template_path, output_path)

            if ext == ".docx":
                return self._write_docx(output_path, filled)
            elif ext == ".pptx":
                return self._write_pptx(output_path, filled)
            elif ext == ".xlsx":
                return self._write_xlsx(output_path, filled)
            return False
        except Exception as exc:
            logger.error("[TemplateRAG] 写入模板失败: %s", exc)
            return False

    def _write_docx(self, file_path: str, filled: Dict[str, str]) -> bool:
        """替换 DOCX 中的占位符。"""
        try:
            from docx import Document

            doc = Document(file_path)

            for para in doc.paragraphs:
                for ph, value in filled.items():
                    tag = f"{{{{{ph}}}}}"
                    if tag in para.text:
                        # 保留格式：替换第一个 run 中的文本
                        full_text = para.text
                        new_text = full_text.replace(tag, str(value))
                        if new_text != full_text:
                            for run in para.runs:
                                run.text = ""
                            if para.runs:
                                para.runs[0].text = new_text

            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for para in cell.paragraphs:
                            for ph, value in filled.items():
                                tag = f"{{{{{ph}}}}}"
                                if tag in para.text:
                                    full_text = para.text
                                    new_text = full_text.replace(tag, str(value))
                                    if new_text != full_text:
                                        for run in para.runs:
                                            run.text = ""
                                        if para.runs:
                                            para.runs[0].text = new_text

            doc.save(file_path)
            logger.info("[TemplateRAG] DOCX 已保存: %s", file_path)
            return True
        except Exception as exc:
            logger.error("[TemplateRAG] DOCX 写入失败: %s", exc)
            return False

    def _write_pptx(self, file_path: str, filled: Dict[str, str]) -> bool:
        """替换 PPTX 中的占位符。"""
        try:
            from pptx import Presentation

            prs = Presentation(file_path)

            for slide in prs.slides:
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for para in shape.text_frame.paragraphs:
                            for ph, value in filled.items():
                                tag = f"{{{{{ph}}}}}"
                                if tag in para.text:
                                    full_text = para.text
                                    new_text = full_text.replace(tag, str(value))
                                    if new_text != full_text:
                                        for run in para.runs:
                                            run.text = ""
                                        if para.runs:
                                            para.runs[0].text = new_text

            prs.save(file_path)
            logger.info("[TemplateRAG] PPTX 已保存: %s", file_path)
            return True
        except Exception as exc:
            logger.error("[TemplateRAG] PPTX 写入失败: %s", exc)
            return False

    def _write_xlsx(self, file_path: str, filled: Dict[str, str]) -> bool:
        """替换 XLSX 中的占位符。"""
        try:
            from openpyxl import load_workbook

            wb = load_workbook(file_path)

            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                for row in ws.iter_rows():
                    for cell in row:
                        if cell.value and isinstance(cell.value, str):
                            for ph, value in filled.items():
                                tag = f"{{{{{ph}}}}}"
                                if tag in cell.value:
                                    cell.value = cell.value.replace(tag, str(value))

            wb.save(file_path)
            logger.info("[TemplateRAG] XLSX 已保存: %s", file_path)
            return True
        except Exception as exc:
            logger.error("[TemplateRAG] XLSX 写入失败: %s", exc)
            return False

    # ── 预览模式 ────────────────────────────────────────────────────────────

    def preview(
        self,
        template_path: str,
        user_query: str,
        rag_k: int = 5,
    ) -> Dict[str, Any]:
        """
        预览模式：仅提取占位符 + RAG 检索 + LLM 填充，不写入文件。
        返回填充内容供前端预览。
        """
        ext = Path(template_path).suffix.lower()
        placeholders = self._extract_placeholders(template_path, ext)
        rag_context, rag_sources = self._retrieve_context(user_query, k=rag_k)
        filled = (
            self._llm_fill(placeholders, user_query, rag_context)
            if placeholders
            else {}
        )

        return {
            "success": True,
            "template_path": template_path,
            "placeholders": placeholders,
            "filled": filled,
            "rag_sources": rag_sources,
            "model_used": self.model_id,
        }
