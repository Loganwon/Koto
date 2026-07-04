# ══════════════════════════════════════════════════════════════
# doc_ai_review.py — AI 文档审阅（修订模式）
#
# 用户场景：
#   上传一份 Word 文档，AI 按审阅重点（语法/逻辑/语气/完整性）
#   审阅后直接以 Word/WPS 原生修订写回文档，用户可立即看到并逐条接受/拒绝。
# ══════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
import shutil
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

_REVIEW_SYSTEM = """你是一名专业的文档审阅编辑。
请逐段审阅以下文本，指出需要修改的地方。

审阅重点: {focus_desc}

输出 JSON 数组，每个元素格式：
{{
  "原文片段": "需要修改的原文（精确引用，20-80字）",
  "修改建议": "修改后的文本",
  "修改原因": "简要说明原因（一句话）"
}}

规则：
1. 每段最多 {max_per_chunk} 条建议，只标注真正需要改的地方
2. 原文片段必须是文档中实际存在的连续文字
3. 无需修改则输出空数组 []
4. 只输出 JSON，不要任何说明"""

_FOCUS_DESC = {
    "all": "全面审阅（语法、逻辑、表达、完整性）",
    "grammar": "语法和标点符号纠错",
    "logic": "逻辑连贯性和论证严密性",
    "tone": "语气和措辞的专业性、得体性",
    "completeness": "内容完整性、是否有遗漏",
}


class DocAIReview(WorkflowExecutor):
    """
    AI 文档审阅工作流（修订模式）。

    params 期望字段:
        doc_file:     str — Word 文档路径
        review_focus: str — "all" | "grammar" | "logic" | "tone" | "completeness"
        model_mode:   str — "auto" | "local"
    """

    WORKFLOW_ID = "doc_ai_review"
    WORKFLOW_NAME = "AI 文档审阅"

    def execute(self, params: dict, yield_event) -> Any:
        doc_file: str = params.get("doc_file") or ""
        focus: str = params.get("review_focus") or "all"
        model_mode: str = params.get("model_mode") or "auto"

        if not doc_file:
            yield sse_error("请提供 Word 文档（doc_file）")
            return

        # ── Step 1: 解析文档 ─────────────────────────────────────────
        yield sse_step_start("parse", "📄 解析文档…")
        text = self.parse_file(doc_file)
        if not text.strip():
            yield sse_error("文档内容为空或解析失败")
            return
        yield sse_step_done("parse", f"📄 已解析（{len(text)} 字）")

        # ── Step 2: 分块审阅 ────────────────────────────────────────
        chunk_size = 1000 if model_mode == "local" else 2000
        max_per_chunk = 3 if model_mode == "local" else 5
        chunks = self._split_chunks(text, chunk_size)

        yield sse_step_start("review", f"🔍 审阅中（{len(chunks)} 段）…")
        all_annotations: list[dict] = []

        focus_desc = _FOCUS_DESC.get(focus, _FOCUS_DESC["all"])
        system = _REVIEW_SYSTEM.format(
            focus_desc=focus_desc, max_per_chunk=max_per_chunk
        )

        for idx, chunk in enumerate(chunks):
            yield sse_progress(idx + 1, len(chunks), f"审阅第 {idx+1}/{len(chunks)} 段")
            annotations = self._review_chunk(chunk, system, model_mode)
            all_annotations.extend(annotations)

        yield sse_step_done("review", f"🔍 审阅完成，共 {len(all_annotations)} 条建议")

        if not all_annotations:
            yield sse_output(
                "markdown",
                "# 审阅结果\n\n文档质量良好，未发现需要修改的地方。",
                "审阅完成",
            )
            return

        # ── Step 3: 写入修订到 DOCX ────────────────────────────────
        yield sse_step_start("annotate", "📝 写入修订…")
        output_path = self.save_output_file(".docx")
        shutil.copy2(doc_file, str(output_path))

        try:
            from web.track_changes_editor import TrackChangesEditor

            editor = TrackChangesEditor("Koto AI")
            result = editor.apply_tracked_changes(str(output_path), all_annotations)
            applied = result.get("applied", 0)
        except Exception as e:
            logger.error("[DocReview] 修订写入失败: %s", e)
            yield sse_error(f"修订写入失败: {e}")
            return

        yield sse_step_done("annotate", f"📝 已写入 {applied} 条修订")

        # ── Step 4: 生成摘要 ────────────────────────────────────────
        summary = self._build_summary(all_annotations, focus_desc, applied)

        # ── 输出 ─────────────────────────────────────────────────────
        yield sse_output(
            "docx_file",
            {"path": str(output_path), "filename": f"审阅_{output_path.name}"},
            f"审阅结果（{applied} 条修订）",
        )
        yield sse_output("markdown", summary, "审阅摘要")

    # ── 辅助方法 ──────────────────────────────────────────────────────

    def _split_chunks(self, text: str, max_size: int) -> list[str]:
        """按段落边界分块。"""
        paragraphs = text.split("\n")
        chunks: list[str] = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) > max_size and current:
                chunks.append(current.strip())
                current = p + "\n"
            else:
                current += p + "\n"
        if current.strip():
            chunks.append(current.strip())
        return chunks if chunks else [text[:max_size]]

    def _review_chunk(self, chunk: str, system: str, model_mode: str) -> list[dict]:
        """对一个文本块调用 LLM 审阅。"""
        prompt = f"请审阅以下文本：\n\n{chunk}"
        try:
            result = self.llm_json(prompt, system=system, model_mode=model_mode)
            if isinstance(result, list):
                return [a for a in result if isinstance(a, dict) and a.get("原文片段")]
        except Exception as e:
            logger.warning("[DocReview] LLM 审阅失败: %s", e)
        return []

    def _build_summary(
        self, annotations: list[dict], focus_desc: str, applied: int
    ) -> str:
        """生成 Markdown 审阅摘要。"""
        lines = [
            "# AI 文档审阅摘要\n",
            f"- 审阅重点: {focus_desc}",
            f"- 发现问题: {len(annotations)} 处",
            f"- 已写入修订: {applied} 条\n",
            "## 修改建议列表\n",
        ]
        for i, a in enumerate(annotations[:20], 1):
            orig = a.get("原文片段", "")[:60]
            reason = a.get("修改原因", "")
            lines.append(f"{i}. **{orig}…** — {reason}")

        if len(annotations) > 20:
            lines.append(f"\n_（共 {len(annotations)} 条，仅显示前 20 条）_")

        return "\n".join(lines)
