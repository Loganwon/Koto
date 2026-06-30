# ══════════════════════════════════════════════════════════════
# doc_smart_compare.py — 文档智能对比
#
# 合并原 doc_deep_compare + contract_diff_markup
#
# 用户场景：
#   上传两份文档（合同、报告等），AI 语义对比差异。
#   输出可选：
#     - "docx": Word Track Changes + 批注标注（需要原件为 .docx）
#     - "html": 可视化 HTML 比对报告（任意格式均可）
#     - "auto": 原件是 .docx 则输出 DOCX 标注，否则 HTML
# ══════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
import re
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

# ── LLM 指令 ─────────────────────────────────────────────────────────────────

_SPLIT_SYSTEM = """你是一个合同分析助手。
请将以下法律文档/合同文本分割成独立的条款或段落列表。

规则：
1. 每条输出代表一个独立的条款或逻辑段落
2. 保留条款编号/序号
3. 输出 JSON 数组，每个元素格式：{"idx": 序号, "heading": "标题或编号（如无则为空）", "text": "条款内容"}
4. 平均每条 50-300 字
5. 只输出 JSON，不要任何说明
"""

_COMPARE_SYSTEM = """你是一名专业的合同审查律师。
你的任务是对比两个版本的文档条款，识别实质性变更（而非格式/排版变化）。

对于每对配对条款，输出以下 JSON（数组元素）：
{
  "原文片段": "原始版本文本",
  "修改建议": "对方版本文本",
  "修改原因": "diff_type(unchanged|minor_format|modified|deleted|added) + severity(none|low|high|critical) + 变化描述",
  "diff_type": "unchanged | minor_format | modified | deleted | added",
  "severity": "none | low | high | critical",
  "risk_flag": true/false
}

只输出 JSON 数组，不要任何说明。"""

_COMPARE_BATCH = 8


class DocSmartCompare(WorkflowExecutor):
    """
    文档智能对比工作流（合并 doc_deep_compare + contract_diff_markup）。

    params 期望字段:
        file_a:       str — 原始文档路径
        file_b:       str — 对比文档路径
        output_mode:  str — "auto" | "docx" | "html"
        model_mode:   str — "auto" | "local"
    """

    WORKFLOW_ID = "doc_smart_compare"
    WORKFLOW_NAME = "文档智能对比"

    def execute(self, params: dict, yield_event) -> Any:
        file_a: str = params.get("file_a") or ""
        file_b: str = params.get("file_b") or ""
        output_mode: str = params.get("output_mode") or "auto"
        model_mode: str = params.get("model_mode") or "auto"

        if not file_a or not file_b:
            yield sse_error("请同时提供两份文档")
            return

        # 决定输出格式
        a_is_docx = file_a.lower().endswith(".docx")
        if output_mode == "auto":
            output_mode = "docx" if a_is_docx else "html"
        if output_mode == "docx" and not a_is_docx:
            output_mode = "html"  # 非 docx 原件无法标注

        # ── Step 1: 解析两份文档 ────────────────────────────────────
        yield sse_step_start("parse", "📄 解析文档…")
        text_a = self.parse_file(file_a)
        text_b = self.parse_file(file_b)
        if not text_a.strip() or not text_b.strip():
            yield sse_error("文档解析失败或内容为空")
            return
        yield sse_step_done(
            "parse", f"📄 原始 {len(text_a)} 字 ↔ 对比 {len(text_b)} 字"
        )

        # ── Step 2: 分割条款 ───────────────────────────────────────
        yield sse_step_start("split", "✂️ 分割条款…")
        clauses_a = self._split_clauses(text_a[:16000], model_mode)
        clauses_b = self._split_clauses(text_b[:16000], model_mode)
        yield sse_step_done(
            "split", f"✂️ 原始 {len(clauses_a)} 条 ↔ 对比 {len(clauses_b)} 条"
        )

        # ── Step 3: 语义比对 ──────────────────────────────────────
        yield sse_step_start("compare", "🔍 逐条款语义比对…")
        alignments = self._compare_clauses(
            clauses_a,
            clauses_b,
            model_mode,
            lambda cur, tot: (yield sse_progress(cur, tot, f"比对第 {cur}/{tot} 批")),
        )
        yield sse_step_done("compare", f"🔍 比对完成，共 {len(alignments)} 对条款")

        changes = [
            a
            for a in alignments
            if a.get("diff_type") not in ("unchanged", "minor_format")
        ]
        high_risk = [a for a in alignments if a.get("risk_flag")]

        if not changes:
            yield sse_output(
                "markdown",
                "# 比对结果\n\n两份文档内容一致，未发现实质性差异。",
                "无差异",
            )
            return

        # ── Step 4: 输出 ──────────────────────────────────────────
        if output_mode == "docx":
            yield from self._output_docx(
                file_a, alignments, changes, high_risk, model_mode
            )
        else:
            yield from self._output_html(alignments, changes, high_risk, model_mode)

    # ── DOCX 输出模式（Track Changes + 批注） ─────────────────────────

    def _output_docx(self, base_file, alignments, changes, high_risk, model_mode):
        yield sse_step_start("markup", "📝 写入文档标记…")
        output_path = self.save_output_file(".docx")
        shutil.copy2(base_file, str(output_path))

        # 将 alignments 转为 TrackChangesEditor 接受的格式
        annotations = []
        for a in alignments:
            dt = a.get("diff_type", "unchanged")
            if dt in ("unchanged", "minor_format"):
                continue
            orig = a.get("原文片段", "")
            modified = a.get("修改建议", "")
            reason = a.get("修改原因", "内容变更")
            if orig and modified:
                annotations.append(
                    {"原文片段": orig, "修改建议": modified, "修改原因": reason}
                )

        applied = 0
        try:
            from web.track_changes_editor import TrackChangesEditor

            editor = TrackChangesEditor("文档对比")
            result = editor.apply_hybrid_changes(str(output_path), annotations)
            applied = result.get("applied", 0)
        except Exception as e:
            logger.error("[DocCompare] DOCX 标记失败: %s", e)
            yield sse_error(f"文档标记失败: {e}")
            return

        yield sse_step_done("markup", f"📝 已标注 {applied} 处变更")

        summary = self._generate_summary(alignments, model_mode)
        yield sse_output(
            "docx_file",
            {"path": str(output_path), "filename": f"对比标注_{output_path.name}"},
            f"标注文档（{len(changes)} 处变更，{len(high_risk)} 处高风险）",
        )
        yield sse_output("markdown", summary, "变更摘要")

    # ── HTML 输出模式（可视化比对报告） ───────────────────────────────

    def _output_html(self, alignments, changes, high_risk, model_mode):
        yield sse_step_start("report", "📋 生成比对报告…")
        diff_html = self._generate_diff_html(alignments)
        summary = self._generate_summary(alignments, model_mode)
        yield sse_step_done("report", "📋 报告生成完成")

        yield sse_output(
            "html",
            diff_html,
            f"比对报告（{len(changes)} 处变更，{len(high_risk)} 处高风险）",
        )
        yield sse_output("markdown", summary, "变更摘要")

    # ── 条款分割 ──────────────────────────────────────────────────────

    def _split_clauses(self, text: str, model_mode: str) -> list[dict]:
        clauses = self._rule_split(text)
        if len(clauses) >= 3:
            return clauses
        prompt = f"请将以下文档分割为条款列表：\n\n{text}"
        try:
            result = self.llm_json(prompt, system=_SPLIT_SYSTEM, model_mode=model_mode)
            if isinstance(result, list) and result:
                return result
        except Exception as e:
            logger.warning("[DocCompare] LLM 分割失败: %s", e)
        return clauses if clauses else [{"idx": 0, "heading": "", "text": text}]

    def _rule_split(self, text: str) -> list[dict]:
        paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
        if len(paras) >= 3:
            return [{"idx": i, "heading": "", "text": p} for i, p in enumerate(paras)]
        sentences = [
            s.strip() for s in re.split(r"[。！？\.\!\?]", text) if len(s.strip()) > 20
        ]
        return [{"idx": i, "heading": "", "text": s} for i, s in enumerate(sentences)]

    # ── 条款比对 ──────────────────────────────────────────────────────

    def _compare_clauses(self, clauses_a, clauses_b, model_mode, progress_cb):
        max_len = max(len(clauses_a), len(clauses_b))
        pairs = []
        for i in range(max_len):
            orig = clauses_a[i] if i < len(clauses_a) else None
            comp = clauses_b[i] if i < len(clauses_b) else None
            pairs.append((orig, comp))

        alignments: list[dict] = []
        total_batches = (len(pairs) + _COMPARE_BATCH - 1) // _COMPARE_BATCH

        for bi in range(total_batches):
            try:
                next(progress_cb(bi + 1, total_batches))
            except StopIteration:
                pass
            batch = pairs[bi * _COMPARE_BATCH : (bi + 1) * _COMPARE_BATCH]
            alignments.extend(self._compare_batch(batch, model_mode))

        return alignments

    def _compare_batch(self, pairs, model_mode):
        formatted = []
        for i, (orig, comp) in enumerate(pairs):
            formatted.append(
                {
                    "pair_idx": i,
                    "original": orig["text"] if orig else "[已删除]",
                    "scanned": comp["text"] if comp else "[已删除]",
                }
            )
        prompt = f"请比较以下 {len(formatted)} 对条款，识别实质性变更：\n\n{json.dumps(formatted, ensure_ascii=False, indent=2)}"
        try:
            result = self.llm_json(
                prompt, system=_COMPARE_SYSTEM, model_mode=model_mode
            )
            if isinstance(result, list):
                return result
        except Exception as e:
            logger.warning("[DocCompare] 批量比较失败: %s", e)
        return [
            {
                "原文片段": (p[0]["text"] if p[0] else ""),
                "修改建议": (p[1]["text"] if p[1] else ""),
                "修改原因": "",
                "diff_type": "unchanged",
                "severity": "none",
                "risk_flag": False,
            }
            for p in pairs
        ]

    # ── HTML 报告 ─────────────────────────────────────────────────────

    def _generate_diff_html(self, alignments):
        severity_colors = {
            "critical": ("#fff3e0", "#e65100", "🚨"),
            "high": ("#fff8e1", "#f9a825", "⚠️"),
            "low": ("#f1f8e9", "#558b2f", "📝"),
            "none": ("#fafafa", "#9e9e9e", "✅"),
        }
        diff_labels = {
            "unchanged": "无变化",
            "minor_format": "格式变化",
            "modified": "内容修改",
            "deleted": "已删除",
            "added": "新增",
        }
        rows = []
        for a in alignments:
            dt = a.get("diff_type", "unchanged")
            if dt == "unchanged":
                continue
            sev = a.get("severity", "none")
            bg, border, icon = severity_colors.get(sev, severity_colors["none"])
            if a.get("risk_flag"):
                bg, border, icon = severity_colors["critical"]
            orig = self._esc(str(a.get("原文片段", "")))
            scan = self._esc(str(a.get("修改建议", "")))
            reason = a.get("修改原因", "")
            label = diff_labels.get(dt, dt)
            rows.append(
                f"""<div style="border-left:4px solid {border};background:{bg};margin:8px 0;padding:12px;border-radius:4px;">
  <div style="font-size:12px;color:{border};font-weight:bold;margin-bottom:6px;">{icon} {label}{' — ' + reason if reason else ''}</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
    <div><div style="font-size:11px;color:#666;margin-bottom:4px;">原始版本</div><div style="background:#fff;padding:8px;border-radius:3px;font-size:13px;">{orig}</div></div>
    <div><div style="font-size:11px;color:#666;margin-bottom:4px;">对比版本</div><div style="background:#fff;padding:8px;border-radius:3px;font-size:13px;">{scan}</div></div>
  </div></div>"""
            )
        if not rows:
            rows = [
                "<p style='text-align:center;color:#4caf50;padding:20px;'>✅ 未发现实质性变更</p>"
            ]
        changes_count = len(
            [
                a
                for a in alignments
                if a.get("diff_type") not in ("unchanged", "minor_format", None)
            ]
        )
        risk_count = len([a for a in alignments if a.get("risk_flag")])
        return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8"><style>body{{font-family:-apple-system,sans-serif;max-width:900px;margin:0 auto;padding:20px;color:#333;}}.summary{{background:#f5f5f5;padding:16px;border-radius:8px;margin-bottom:20px;}}.badge{{display:inline-block;padding:4px 12px;border-radius:20px;font-size:13px;font-weight:bold;margin:4px;}}</style></head><body>
<h2>📋 文档比对报告</h2>
<div class="summary"><span class="badge" style="background:#ffcccc;color:#c62828;">⚠️ {changes_count} 处变更</span> <span class="badge" style="background:#ffe0b2;color:#e65100;">🚨 {risk_count} 处高风险</span></div>
{"".join(rows)}</body></html>"""

    # ── 摘要 ──────────────────────────────────────────────────────────

    def _generate_summary(self, alignments, model_mode):
        critical = [
            a
            for a in alignments
            if a.get("severity") in ("critical", "high") or a.get("risk_flag")
        ]
        if not critical:
            return "# 比对摘要\n\n✅ **未发现重大条款变更。**"
        summary_data = json.dumps(
            [
                {
                    "diff": a.get("修改原因", ""),
                    "original": str(a.get("原文片段", ""))[:100],
                    "changed_to": str(a.get("修改建议", ""))[:100],
                }
                for a in critical[:20]
            ],
            ensure_ascii=False,
            indent=2,
        )
        prompt = f"以下是 {len(critical)} 处重要变更：\n\n{summary_data}\n\n请用简洁中文 Markdown 总结主要变更、潜在风险和建议。"
        try:
            return self.llm(prompt, model_mode=model_mode)
        except Exception:
            lines = [f"# 比对摘要\n\n发现 **{len(critical)}** 处重要变更：\n"]
            for a in critical[:10]:
                lines.append(f"- {a.get('修改原因', '条款变更')}")
            return "\n".join(lines)

    @staticmethod
    def _esc(text):
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
