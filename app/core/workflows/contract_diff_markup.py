# ══════════════════════════════════════════════════════════════
# contract_diff_markup.py — 合同差异标红批注
#
# 用户场景：
#   两份合同文件（原始 + 修改版），
#   AI 比对差异 → 在 Word 中添加 Track Changes + 批注。
#   输出一份标记了所有变更的 DOCX，用户可在 Word 审阅。
# ══════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
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

_ANALYZE_SYSTEM = """你是一名合同审查律师。
请分析以下变更列表，为每处变更评估风险并说明影响。

输入是修改对列表，每项包含 old（原文）和 new（新文）。

输出 JSON 数组，每个元素：
{{
  "原文片段": "被修改的原始文本（精确引用）",
  "修改建议": "修改后的新文本",
  "修改原因": "变更类型 + 风险等级(低/中/高/严重) + 简短说明"
}}

规则：
1. 原文片段必须与输入的 old 文本一致
2. 修改建议必须与输入的 new 文本一致
3. 修改原因说明这处变更的法律风险
4. 只输出 JSON 数组，不要任何其他内容"""

_BATCH_SIZE_ONLINE = 10
_BATCH_SIZE_LOCAL = 5


class ContractDiffMarkup(WorkflowExecutor):
    """
    合同差异标红批注工作流。

    params 期望字段:
        contract_a: str — 原始合同文件路径
        contract_b: str — 对比合同文件路径
        model_mode: str — "auto" | "local"
    """

    WORKFLOW_ID = "contract_diff_markup"
    WORKFLOW_NAME = "合同差异标注"

    def execute(self, params: dict, yield_event) -> Any:
        contract_a: str = params.get("contract_a") or ""
        contract_b: str = params.get("contract_b") or ""
        model_mode: str = params.get("model_mode") or "auto"

        if not contract_a or not contract_b:
            yield sse_error("请同时提供原始合同（contract_a）和对比合同（contract_b）")
            return

        # ── Step 1: 解析两份合同 ────────────────────────────────────
        yield sse_step_start("parse", "📄 解析合同文件…")
        text_a = self.parse_file(contract_a)
        text_b = self.parse_file(contract_b)
        if not text_a.strip() or not text_b.strip():
            yield sse_error("合同文件解析失败或内容为空")
            return
        yield sse_step_done("parse", f"📄 原始 {len(text_a)} 字 ↔ 对比 {len(text_b)} 字")

        # ── Step 2: 文本差异比对 ────────────────────────────────────
        yield sse_step_start("diff", "🔍 差异比对…")
        changes = self._compute_diff(text_a, text_b)
        if not changes:
            yield sse_output("markdown", "# 比对结果\n\n两份合同内容完全一致，未发现差异。", "无差异")
            return
        yield sse_step_done("diff", f"🔍 发现 {len(changes)} 处变更")

        # ── Step 3: LLM 分析变更语义 ───────────────────────────────
        yield sse_step_start("analyze", "🤖 AI 分析变更风险…")
        batch_size = _BATCH_SIZE_LOCAL if model_mode == "local" else _BATCH_SIZE_ONLINE
        annotations = self._analyze_changes(changes, model_mode, batch_size,
            lambda cur, tot: (yield sse_progress(cur, tot, f"分析第 {cur}/{tot} 批")))
        yield sse_step_done("analyze", f"🤖 分析完成，{len(annotations)} 条标注")

        # ── Step 4: 写入 DOCX 标记 ──────────────────────────────────
        yield sse_step_start("markup", "📝 写入文档标记…")

        # 确定基础文档：优先使用原始 DOCX
        base_file = contract_a
        if not contract_a.lower().endswith(".docx"):
            if contract_b.lower().endswith(".docx"):
                base_file = contract_b
            else:
                # 两份都不是 DOCX，无法直接标注
                yield sse_output("markdown", self._build_summary(annotations), "变更摘要（无法生成标注DOCX，因为源文件非Word格式）")
                return

        output_path = self.save_output_file(".docx")
        shutil.copy2(base_file, str(output_path))

        try:
            from web.track_changes_editor import TrackChangesEditor
            editor = TrackChangesEditor("合同审查")
            result = editor.apply_hybrid_changes(str(output_path), annotations)
            applied = result.get("applied", 0)
        except Exception as e:
            logger.error("[ContractDiff] 标记写入失败: %s", e)
            yield sse_error(f"文档标记失败: {e}")
            return

        yield sse_step_done("markup", f"📝 已标注 {applied} 处变更")

        # ── 输出 ─────────────────────────────────────────────────────
        summary = self._build_summary(annotations)
        yield sse_output(
            "docx_file",
            {"path": str(output_path), "filename": f"合同对比标注_{output_path.name}"},
            f"标注合同（{applied} 处变更）",
        )
        yield sse_output("markdown", summary, "风险摘要")

    # ── 辅助方法 ──────────────────────────────────────────────────────

    def _compute_diff(self, text_a: str, text_b: str) -> list[dict]:
        """计算文本差异，返回 [{old, new}] 列表。"""
        import difflib

        lines_a = text_a.splitlines()
        lines_b = text_b.splitlines()
        matcher = difflib.SequenceMatcher(None, lines_a, lines_b)

        changes = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "replace":
                old_text = "\n".join(lines_a[i1:i2]).strip()
                new_text = "\n".join(lines_b[j1:j2]).strip()
                if old_text and new_text and old_text != new_text:
                    changes.append({"old": old_text, "new": new_text})
            elif tag == "delete":
                old_text = "\n".join(lines_a[i1:i2]).strip()
                if old_text:
                    changes.append({"old": old_text, "new": "[已删除]"})
            elif tag == "insert":
                new_text = "\n".join(lines_b[j1:j2]).strip()
                if new_text:
                    changes.append({"old": "", "new": new_text})

        return changes

    def _analyze_changes(self, changes: list[dict], model_mode: str, batch_size: int, progress_cb) -> list[dict]:
        """批量调用 LLM 分析变更风险。"""
        all_annotations: list[dict] = []
        total_batches = (len(changes) + batch_size - 1) // batch_size

        for bi in range(total_batches):
            try:
                next(progress_cb(bi + 1, total_batches))
            except StopIteration:
                pass

            batch = changes[bi * batch_size: (bi + 1) * batch_size]
            batch_data = json.dumps(batch, ensure_ascii=False, indent=2)
            prompt = f"请分析以下 {len(batch)} 处合同变更：\n\n{batch_data}"

            try:
                result = self.llm_json(prompt, system=_ANALYZE_SYSTEM, model_mode=model_mode)
                if isinstance(result, list):
                    all_annotations.extend(result)
                    continue
            except Exception as e:
                logger.warning("[ContractDiff] LLM 分析失败: %s", e)

            # 回退：直接构造标注
            for c in batch:
                all_annotations.append({
                    "原文片段": c["old"][:200] if c["old"] else "",
                    "修改建议": c["new"][:200] if c["new"] else "",
                    "修改原因": "内容变更",
                })

        return all_annotations

    def _build_summary(self, annotations: list[dict]) -> str:
        """Markdown 风险摘要。"""
        lines = [
            "# 合同差异分析摘要\n",
            f"共发现 **{len(annotations)}** 处变更\n",
            "## 变更列表\n",
        ]
        for i, a in enumerate(annotations[:30], 1):
            reason = a.get("修改原因", "变更")
            orig = (a.get("原文片段", "") or "")[:50]
            lines.append(f"{i}. **{orig}…** — {reason}")

        if len(annotations) > 30:
            lines.append(f"\n_（共 {len(annotations)} 处，仅显示前 30 条）_")

        return "\n".join(lines)
