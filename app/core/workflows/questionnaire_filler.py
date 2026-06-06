# ══════════════════════════════════════════════════════════════
# questionnaire_filler.py — 招投标/尽调问卷自动填写
#
# 用户场景：用户上传包含问题的 Excel 问卷，再上传
# N 份历史参考文档 → AI 从参考文档中检索 → 自动填写答案。
# ══════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.core.workflow_engine import (
    WorkflowExecutor,
    sse_error,
    sse_output,
    sse_progress,
    sse_status,
    sse_step_done,
    sse_step_start,
)

logger = logging.getLogger(__name__)

_ANSWER_SYSTEM = """你是一个专业的 RFP/问卷填写助手。
根据提供的参考文档片段，为以下问题提供精准、专业的回答。

规则：
1. 答案要直接、简洁，以专业第三人称表述
2. 如果参考文档中有明确回答，直接引用相关内容
3. 如果参考文档中没有明确答案，输出："[需要人工填写]"
4. 答案长度不超过 200 字
5. 不要重复问题本身
"""

# 每次调 LLM 批量回答的问题数（减少 API 调用次数）
_BATCH_QUESTIONS = 5


class QuestionnaireFiller(WorkflowExecutor):
    """
    问卷/RFP 自动填写工作流。

    params 期望字段:
        question_file:   str       — 问题 Excel 文件路径
        reference_files: List[str] — 参考文档路径列表
        question_col:    str       — 问题所在列标题（可选，默认自动识别）
        answer_col:      str       — 答案填入列标题（可选，默认新建"AI回答"列）
        model_mode:      str       — "auto" | "local"
    """

    WORKFLOW_ID = "questionnaire_filler"
    WORKFLOW_NAME = "问卷自动填写"

    def execute(self, params: dict, yield_event) -> Any:
        question_file: str = params.get("question_file") or ""
        reference_files: list[str] = params.get("reference_files") or []
        question_col: str = params.get("question_col") or ""
        answer_col: str = params.get("answer_col") or "AI回答"
        model_mode: str = params.get("model_mode") or "auto"

        if not question_file:
            yield sse_error("请提供问题 Excel 文件路径（question_file）")
            return

        # ── Step 1: 解析问题 Excel ─────────────────────────────────────────────
        yield sse_step_start("parse_questions", "📋 解析问题表格…")
        questions = self._parse_questions(question_file, question_col)
        if not questions:
            yield sse_error(
                "未能从 Excel 中识别到任何问题，请检查文件或指定 question_col 参数"
            )
            return
        yield sse_step_done("parse_questions", f"📋 识别到 {len(questions)} 个问题")

        # ── Step 2: 索引参考文档（临时 RAG）──────────────────────────────────
        yield sse_step_start(
            "index_refs", f"📚 索引 {len(reference_files)} 份参考文档…"
        )
        rag = self._build_temp_rag(reference_files)
        if rag is None and reference_files:
            yield sse_error("参考文档索引失败，将仅凭 LLM 自有知识作答（可能不准确）")
        yield sse_step_done("index_refs", "📚 参考文档索引完成")

        # ── Step 3: 逐批问题 RAG + LLM 回答 ─────────────────────────────────
        yield sse_step_start("answer_questions", f"🤖 回答 {len(questions)} 个问题…")
        answers: list[dict] = []
        total = len(questions)

        for batch_start in range(0, total, _BATCH_QUESTIONS):
            batch = questions[batch_start : batch_start + _BATCH_QUESTIONS]
            yield sse_progress(
                batch_start + len(batch),
                total,
                f"第 {batch_start+1}–{batch_start+len(batch)} 题",
            )

            # 对每题分别检索上下文（因为每题的语义焦点不同）
            for q in batch:
                context = self._retrieve_context(rag, q["question"], k=4) if rag else ""
                answer_data = self._answer_question(q["question"], context, model_mode)
                answers.append({**q, **answer_data})

        yield sse_step_done("answer_questions", f"🤖 {len(answers)} 个问题已回答")

        # ── Step 4: 构建输出工作簿 ────────────────────────────────────────────
        yield sse_step_start("build_output", "📊 生成结果表格…")
        workbook = self._build_workbook(question_file, answers, answer_col)
        yield sse_step_done("build_output", "📊 表格生成完成")
        yield sse_output("xlsx_data", workbook, f"问卷已填写（{len(answers)} 题）")

    # ── 辅助方法 ──────────────────────────────────────────────────────────────

    def _parse_questions(self, file_path: str, question_col: str) -> list[dict]:
        """
        从 Excel 中提取问题列表。
        尝试：1) 按 question_col 匹配列名；2) 关键词识别问题列。
        返回: [{row: int, question: str, other_cols: dict}]
        """
        try:
            from app.core.file.file_parser import parse_xlsx

            result = parse_xlsx(file_path, "")
            for sheet_id, sheet in result.get("sheets", {}).items():
                cell_data = sheet.get("cellData", {})

                # 统一键类型为整数（parse_xlsx 返回 int 键）
                def _int_key(d: dict) -> dict:
                    return {int(k): v for k, v in d.items()}

                cell_data_int = {int(r): _int_key(row) for r, row in cell_data.items()}
                row0 = cell_data_int.get(0, {})
                if not row0:
                    continue
                col_count = max(row0.keys()) + 1
                headers = {
                    c: str(row0.get(c, {}).get("v", "")) for c in range(col_count)
                }

                # 识别问题列
                q_col_idx: int | None = None
                if question_col:
                    for c_idx, h in headers.items():
                        if h.strip() == question_col.strip():
                            q_col_idx = c_idx
                            break
                if q_col_idx is None:
                    kws = ["问题", "题目", "问", "查询", "question", "query", "item"]
                    for c_idx, h in headers.items():
                        if any(k in h.lower() for k in kws):
                            q_col_idx = c_idx
                            break
                if q_col_idx is None:
                    best_col = max(
                        headers.keys(),
                        key=lambda c: sum(
                            1
                            for r in cell_data_int.values()
                            if str(r.get(c, {}).get("v", "")).strip()
                        ),
                    )
                    q_col_idx = best_col

                questions = []
                for r_idx in sorted(k for k in cell_data_int.keys() if k != 0):
                    row = cell_data_int[r_idx]
                    q_text = str(row.get(q_col_idx, {}).get("v", "")).strip()
                    if not q_text:
                        continue
                    other = {
                        headers[c]: str(row.get(c, {}).get("v", ""))
                        for c in range(col_count)
                        if c != q_col_idx and headers.get(c, "").strip()
                    }
                    questions.append(
                        {
                            "row": r_idx,
                            "question": q_text,
                            "question_col_idx": q_col_idx,
                            "other": other,
                            "headers": headers,
                        }
                    )
                return questions
        except Exception as e:
            logger.warning(f"[QuestionnaireFiller] 问题解析失败: {e}")
        return []

    def _build_temp_rag(self, file_paths: list[str]):
        """创建一个临时 RAG 索引，索引完成后返回 RAGService 实例。"""
        if not file_paths:
            return None
        try:
            import os
            import tempfile

            from app.core.services.rag_service import RAGService

            tmp_index_dir = tempfile.mkdtemp(prefix="koto_rag_")
            rag = RAGService(index_dir=tmp_index_dir, auto_load=False)
            for fp in file_paths:
                try:
                    rag.index_file(fp)
                    logger.info(f"[QuestionnaireFiller] 已索引: {fp}")
                except Exception as e:
                    logger.warning(f"[QuestionnaireFiller] 索引失败 {fp}: {e}")
            return rag
        except Exception as e:
            logger.warning(f"[QuestionnaireFiller] RAG 初始化失败: {e}")
            return None

    def _retrieve_context(self, rag, question: str, k: int = 4) -> str:
        """从 RAG 检索与问题相关的上下文片段。"""
        try:
            chunks = rag.hybrid_retrieve(question, k=k)
            parts = []
            for c in chunks:
                src = c.get("source", "")
                src_name = src.split("\\")[-1].split("/")[-1] if src else "文档"
                parts.append(f"[来源：{src_name}]\n{c['content']}")
            return "\n\n".join(parts)
        except Exception:
            try:
                chunks = rag.retrieve(question, k=k)
                return "\n\n".join(c.get("content", "") for c in chunks)
            except Exception as e:
                logger.warning(f"[QuestionnaireFiller] RAG 检索失败: {e}")
                return ""

    def _answer_question(self, question: str, context: str, model_mode: str) -> dict:
        """对单个问题用 RAG 上下文生成答案。"""
        ctx_section = (
            f"\n\n参考文档片段:\n---\n{context}\n---\n\n" if context else "\n\n"
        )
        prompt = (
            f"请回答以下问题：\n\n{question}"
            f"{ctx_section}"
            "请直接给出答案，不要重复问题。"
        )
        try:
            answer = self.llm(prompt, system=_ANSWER_SYSTEM, model_mode=model_mode)
            # 判断置信度（如果 RAG 没有上下文则标低置信）
            confidence = "high" if context else "low"
            if "[需要人工填写]" in answer:
                confidence = "low"
            return {"answer": answer.strip(), "confidence": confidence}
        except Exception as e:
            logger.warning(f"[QuestionnaireFiller] LLM 回答失败: {e}")
            return {"answer": "[LLM 调用失败，请重试]", "confidence": "low"}

    def _build_workbook(
        self,
        original_file: str,
        answers: list[dict],
        answer_col: str,
    ) -> dict:
        """
        重建 Excel 工作簿：保留原始数据，追加 AI 回答列。
        低置信度行用黄色背景标注，需要人工复核的行用橙色标注。
        """
        try:
            from app.core.file.file_parser import parse_xlsx

            xlsx_result = parse_xlsx(original_file, "")
        except Exception as e:
            logger.warning(
                f"[QuestionnaireFiller] 原始 Excel 读取失败: {e}, 重建空工作簿"
            )
            xlsx_result = {}

        import uuid as _uuid

        wb_id = str(_uuid.uuid4())[:8]
        sheet_id = "questionnaire"

        # 如果有原始工作簿数据，以第一个 sheet 为基准
        original_sheet = {}
        original_headers: dict[str, str] = {}
        original_col_count = 0

        for sid, sheet in (xlsx_result.get("sheets") or {}).items():
            cell_data = sheet.get("cellData", {})
            row0 = cell_data.get(0) or cell_data.get("0") or {}
            if row0:
                original_col_count = max((int(k) for k in row0.keys()), default=-1) + 1
                original_headers = {
                    str(c): str((row0.get(c) or row0.get(str(c)) or {}).get("v", ""))
                    for c in range(original_col_count)
                }
            original_sheet = cell_data
            break

        answer_col_idx = original_col_count  # 追加在末尾
        source_col_idx = original_col_count + 1

        # 合并颜色: 低置信度→黄, 需要人工→橙
        low_style = {"bg": {"rgb": "#fff3cd"}}
        manual_style = {"bg": {"rgb": "#ffe0b2"}}
        header_style = {"bl": 1, "bg": {"rgb": "#1a73e8"}, "cl": {"rgb": "#ffffff"}}

        # 重建 cell_data
        new_cell_data: dict = {}

        # 表头行：先复制原始表头，再追加 AI 回答列
        if original_sheet:
            header_row = dict(original_sheet.get(0) or original_sheet.get("0") or {})
        else:
            header_row = {}

        header_row[str(answer_col_idx)] = {"v": answer_col, "t": 1, "s": header_style}
        header_row[str(source_col_idx)] = {"v": "参考来源", "t": 1, "s": header_style}
        new_cell_data["0"] = header_row

        # 构建 row_key → answer 映射
        answer_map: dict[int, dict] = {a["row"]: a for a in answers}

        # 数据行
        max_row = max(
            (
                max((int(k) for k in original_sheet.keys()), default=0),
                max((a["row"] for a in answers), default=0),
            )
        )

        for r in range(1, max_row + 1):
            orig_row = dict(original_sheet.get(r) or original_sheet.get(str(r)) or {})
            ans_data = answer_map.get(r, {})
            answer_text = ans_data.get("answer", "")
            confidence = ans_data.get("confidence", "")

            if answer_text:
                cell_style = {}
                if "[需要人工填写]" in answer_text or "[LLM" in answer_text:
                    cell_style = manual_style
                elif confidence == "low":
                    cell_style = low_style

                ans_cell: dict = {"v": answer_text, "t": 1}
                if cell_style:
                    ans_cell["s"] = cell_style
                orig_row[str(answer_col_idx)] = ans_cell
                orig_row[str(source_col_idx)] = {"v": "", "t": 1}

            if orig_row:
                new_cell_data[str(r)] = orig_row

        return {
            "id": wb_id,
            "name": "问卷回答",
            "appVersion": "0.5.0",
            "sheetOrder": [sheet_id],
            "sheets": {
                sheet_id: {
                    "id": sheet_id,
                    "name": "问卷回答",
                    "rowCount": max_row + 1,
                    "columnCount": original_col_count + 2,
                    "cellData": new_cell_data,
                    "mergeData": [],
                }
            },
            "styles": {},
        }
