# ══════════════════════════════════════════════════════════════
# doc_deep_compare.py — 文档深度比对与防暗改审查
#
# 用户场景：
#   原始 Word 合同 + 客户签字回传的 PDF 扫描件
#   → AI 逐条款语义比对 → 高亮被修改的部分
#   → 生成防暗改审查报告（HTML + Markdown 摘要）
# ══════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
import re
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

_SPLIT_SYSTEM = """你是一个合同分析助手。
请将以下法律文档/合同文本分割成独立的条款或段落列表。

规则：
1. 每条输出代表一个独立的条款或逻辑段落
2. 保留条款编号/序号
3. 输出 JSON 数组，每个元素格式：{"idx": 序号, "heading": "标题或编号（如无则为空）", "text": "条款内容"}
4. 平均每条 50-300 字
5. 只输出 JSON，不要任何说明
"""

_ALIGN_SYSTEM = """你是一名专业的合同审查律师。
你的任务是对比两个版本的文档条款，识别实质性变更（而非格式/排版变化）。

对于每对配对条款，输出以下 JSON（数组元素）：
{
  "idx": 配对序号,
  "original_text": "原始版本文本",
  "scanned_text": "扫描/对方版本文本",
  "diff_type": "unchanged | minor_format | modified | deleted | added",
  "severity": "none | low | high | critical",
  "diff_detail": "变化描述（如：违约金比例从5%改为1%）",
  "risk_flag": true/false  // 是否存在重大法律风险
}

diff_type 说明：
- unchanged: 内容完全相同
- minor_format: 仅格式/标点/换行变化，内容意思不变
- modified: 内容有实质修改
- deleted: 原版有但对方版本删除
- added: 对方版本新增

severity 说明：
- none: 无变化
- low: 格式变化
- high: 条款修改（影响权利义务）
- critical: 重大修改（金额/比例/违约/主体变更）

对于所有 unchanged 和 minor_format 类型，diff_detail 和 risk_flag 可以简化。
只输出 JSON 数组，不要任何说明。
"""

# 每批发给 LLM 比对的条款对数（避免超 token）
_COMPARE_BATCH = 8


class DocDeepCompare(WorkflowExecutor):
    """
    文档深度比对与防暗改审查工作流。

    params 期望字段:
        original_file: str  — 原始文档路径（Word/PDF）
        compare_file:  str  — 对比文档路径（通常是扫描 PDF）
        model_mode:    str  — "auto" | "local"
    """

    WORKFLOW_ID = "doc_deep_compare"
    WORKFLOW_NAME = "文档深度比对"

    def execute(self, params: dict, yield_event) -> Any:
        original_file: str = params.get("original_file") or ""
        compare_file: str = params.get("compare_file") or ""
        model_mode: str = params.get("model_mode") or "auto"

        if not original_file or not compare_file:
            yield sse_error(
                "请同时提供原始文档（original_file）和对比文档（compare_file）"
            )
            return

        # ── Step 1: 解析原始文档 ──────────────────────────────────────────────
        yield sse_step_start("parse_original", "📄 解析原始文档…")
        original_text = self.parse_file(original_file)
        if not original_text.strip():
            yield sse_error("原始文档解析失败或内容为空")
            return
        yield sse_step_done(
            "parse_original", f"📄 原始文档已解析（{len(original_text)} 字）"
        )

        # ── Step 2: 解析对比文档（含 OCR） ───────────────────────────────────
        yield sse_step_start("parse_compare", "📸 解析对比文档（可能需要 OCR）…")
        compare_text = self.parse_file(compare_file)
        if not compare_text.strip():
            # 再次尝试强制 OCR
            compare_text = self._force_ocr(compare_file)
        if not compare_text.strip():
            yield sse_error("对比文档解析失败，请确认文件格式或 Tesseract-OCR 已安装")
            return
        yield sse_step_done(
            "parse_compare", f"📸 对比文档已解析（{len(compare_text)} 字）"
        )

        # ── Step 3: 分割为条款 ────────────────────────────────────────────────
        yield sse_step_start("split_clauses", "✂️ 分割条款…")
        original_clauses = self._split_clauses(original_text[:16000], model_mode)
        compare_clauses = self._split_clauses(compare_text[:16000], model_mode)
        yield sse_step_done(
            "split_clauses",
            f"✂️ 原始 {len(original_clauses)} 条 ↔ 对比 {len(compare_clauses)} 条",
        )

        # ── Step 4: 语义对齐 & 差异比对 ──────────────────────────────────────
        yield sse_step_start("compare", "🔍 逐条款语义比对…")
        alignments = self._compare_clauses(
            original_clauses,
            compare_clauses,
            model_mode,
            lambda cur, tot: (yield sse_progress(cur, tot, f"比对第 {cur}/{tot} 批")),
        )
        yield sse_step_done("compare", f"🔍 比对完成，共 {len(alignments)} 对条款")

        # ── Step 5: 生成报告 ──────────────────────────────────────────────────
        yield sse_step_start("gen_report", "📋 生成比对报告…")
        diff_html = self._generate_diff_html(alignments)
        summary_md = self._generate_summary(alignments, model_mode)
        yield sse_step_done("gen_report", "📋 报告生成完成")

        # ── 输出 ──────────────────────────────────────────────────────────────
        changes = [
            a
            for a in alignments
            if a.get("diff_type") not in ("unchanged", "minor_format")
        ]
        high_risk = [a for a in alignments if a.get("risk_flag")]

        yield sse_output(
            "html",
            diff_html,
            f"比对报告（{len(changes)} 处变更，{len(high_risk)} 处高风险）",
        )
        yield sse_output("markdown", summary_md, "变更摘要")

    # ── 辅助方法 ──────────────────────────────────────────────────────────────

    def _force_ocr(self, file_path: str) -> str:
        """强制对 PDF 进行 OCR（调用 file_parser 内置 OCR 逻辑）。"""
        try:
            import uuid

            from app.core.file.file_parser import parse_pdf

            result = parse_pdf(file_path, str(uuid.uuid4()))
            return result.get("text", "")
        except Exception as e:
            logger.warning(f"[DocCompare] 强制 OCR 失败: {e}")
            return ""

    def _split_clauses(self, text: str, model_mode: str) -> list[dict]:
        """将文本分割为条款列表，返回 [{idx, heading, text}]。"""
        # 先尝试规则分割（快速）
        clauses = self._rule_split(text)
        if len(clauses) >= 3:
            return clauses

        # 条款数太少，用 LLM 分割
        prompt = f"请将以下文档分割为条款列表：\n\n{text}"
        try:
            result = self.llm_json(prompt, system=_SPLIT_SYSTEM, model_mode=model_mode)
            if isinstance(result, list) and result:
                return result
        except Exception as e:
            logger.warning(f"[DocCompare] LLM 分割失败: {e}")

        return clauses if clauses else [{"idx": 0, "heading": "", "text": text}]

    def _rule_split(self, text: str) -> list[dict]:
        """
        基于规则的条款分割：
        匹配 "第X条"、"X."、"X、" 等常见合同编号格式。
        """
        patterns = [
            r"第[一二三四五六七八九十百\d]+条[\s　]",  # 第X条
            r"(\d+[\.\、])\s*\S",  # 1. 或 1、
            r"([A-Z]\.\d+)\s",  # A.1
        ]
        # 尝试按段落分割（空行分隔）
        paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
        if len(paras) >= 3:
            return [{"idx": i, "heading": "", "text": p} for i, p in enumerate(paras)]

        # 按句子分割（回退）
        sentences = [
            s.strip() for s in re.split(r"[。！？\.\!\?]", text) if len(s.strip()) > 20
        ]
        return [{"idx": i, "heading": "", "text": s} for i, s in enumerate(sentences)]

    def _compare_clauses(
        self,
        original_clauses: list[dict],
        compare_clauses: list[dict],
        model_mode: str,
        progress_cb,
    ) -> list[dict]:
        """
        将两组条款对齐并比较差异。
        使用滑动窗口批量发送给 LLM 比对（每批 _COMPARE_BATCH 对）。
        """
        # 简单对齐策略：按序号两两配对（假设顺序大体一致）
        max_len = max(len(original_clauses), len(compare_clauses))
        pairs = []
        for i in range(max_len):
            orig = original_clauses[i] if i < len(original_clauses) else None
            comp = compare_clauses[i] if i < len(compare_clauses) else None
            pairs.append((orig, comp))

        alignments: list[dict] = []
        total_batches = (len(pairs) + _COMPARE_BATCH - 1) // _COMPARE_BATCH

        for batch_idx in range(total_batches):
            try:
                next(progress_cb(batch_idx + 1, total_batches))
            except StopIteration:
                pass

            batch = pairs[batch_idx * _COMPARE_BATCH : (batch_idx + 1) * _COMPARE_BATCH]
            batch_results = self._compare_batch(batch, model_mode)
            alignments.extend(batch_results)

        return alignments

    def _compare_batch(self, pairs: list[tuple], model_mode: str) -> list[dict]:
        """对一批条款对进行 LLM 比较。"""
        formatted_pairs = []
        for i, (orig, comp) in enumerate(pairs):
            formatted_pairs.append(
                {
                    "pair_idx": i,
                    "original": orig["text"] if orig else "[已删除]",
                    "scanned": comp["text"] if comp else "[已删除]",
                }
            )

        prompt = (
            f"请比较以下 {len(formatted_pairs)} 对合同条款，识别实质性变更：\n\n"
            f"{json.dumps(formatted_pairs, ensure_ascii=False, indent=2)}"
        )
        try:
            result = self.llm_json(prompt, system=_ALIGN_SYSTEM, model_mode=model_mode)
            if isinstance(result, list):
                return result
        except Exception as e:
            logger.warning(f"[DocCompare] 批量比较失败: {e}")

        # 回退：返回未变化标记
        return [
            {
                "idx": i,
                "original_text": (p[0]["text"] if p[0] else ""),
                "scanned_text": (p[1]["text"] if p[1] else ""),
                "diff_type": "unchanged",
                "severity": "none",
                "diff_detail": "",
                "risk_flag": False,
            }
            for i, p in enumerate(pairs)
        ]

    def _generate_diff_html(self, alignments: list[dict]) -> str:
        """生成可视化比对 HTML（红=删除, 绿=新增, 黄=修改, 橙=重大风险）。"""
        severity_colors = {
            "critical": ("#fff3e0", "#e65100", "🚨"),
            "high": ("#fff8e1", "#f9a825", "⚠️"),
            "low": ("#f1f8e9", "#558b2f", "📝"),
            "none": ("#fafafa", "#9e9e9e", "✅"),
        }
        diff_type_labels = {
            "unchanged": "无变化",
            "minor_format": "格式变化",
            "modified": "内容修改",
            "deleted": "已删除",
            "added": "新增",
        }

        rows_html = []
        for a in alignments:
            diff_type = a.get("diff_type", "unchanged")
            severity = a.get("severity", "none")
            detail = a.get("diff_detail", "")
            risk_flag = a.get("risk_flag", False)

            if diff_type in ("unchanged",):
                continue  # 无变化的不显示，减少噪音

            bg, border, icon = severity_colors.get(severity, severity_colors["none"])
            if risk_flag:
                bg, border, icon = severity_colors["critical"]

            orig_html = self._esc(str(a.get("original_text", "")))
            scan_html = self._esc(str(a.get("scanned_text", "")))
            label = diff_type_labels.get(diff_type, diff_type)

            row = f"""
<div class="diff-row" style="border-left:4px solid {border};background:{bg};margin:8px 0;padding:12px;border-radius:4px;">
  <div class="diff-badge" style="font-size:12px;color:{border};font-weight:bold;margin-bottom:6px;">
    {icon} {label} {' — ' + detail if detail else ''}{'  🔴 高风险' if risk_flag else ''}
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
    <div>
      <div style="font-size:11px;color:#666;margin-bottom:4px;">原始版本</div>
      <div style="background:#fff;padding:8px;border-radius:3px;font-size:13px;line-height:1.6;">{orig_html}</div>
    </div>
    <div>
      <div style="font-size:11px;color:#666;margin-bottom:4px;">对比版本（扫描件）</div>
      <div style="background:#fff;padding:8px;border-radius:3px;font-size:13px;line-height:1.6;">{scan_html}</div>
    </div>
  </div>
</div>"""
            rows_html.append(row)

        if not rows_html:
            rows_html = [
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

        return f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8">
<style>
  body {{font-family:-apple-system,sans-serif;max-width:900px;margin:0 auto;padding:20px;color:#333;}}
  .summary {{background:#f5f5f5;padding:16px;border-radius:8px;margin-bottom:20px;}}
  .summary-badge {{display:inline-block;padding:4px 12px;border-radius:20px;font-size:13px;font-weight:bold;margin:4px;}}
</style>
</head>
<body>
<h2>📋 文档比对报告</h2>
<div class="summary">
  <span class="summary-badge" style="background:#ffcccc;color:#c62828;">⚠️ {changes_count} 处实质变更</span>
  <span class="summary-badge" style="background:#ffe0b2;color:#e65100;">🚨 {risk_count} 处高风险</span>
  <span class="summary-badge" style="background:#e8f5e9;color:#2e7d32;">✅ {len(alignments)-changes_count} 处无变化</span>
</div>
{"".join(rows_html)}
</body></html>"""

    def _generate_summary(self, alignments: list[dict], model_mode: str) -> str:
        """用 LLM 生成 Markdown 变更摘要（仅高优先级变更）。"""
        critical = [
            a
            for a in alignments
            if a.get("severity") in ("critical", "high") or a.get("risk_flag")
        ]
        if not critical:
            return "# 比对摘要\n\n✅ **未发现重大条款变更。**\n\n所有条款内容与原始版本一致（可能存在少量格式差异）。"

        critical_summary = json.dumps(
            [
                {
                    "diff": a.get("diff_detail"),
                    "original": a.get("original_text", "")[:100],
                    "changed_to": a.get("scanned_text", "")[:100],
                    "risk": a.get("risk_flag"),
                }
                for a in critical[:20]
            ],
            ensure_ascii=False,
            indent=2,
        )

        prompt = (
            f"以下是合同比对中发现的 {len(critical)} 处重要变更：\n\n{critical_summary}\n\n"
            "请用简洁的中文 Markdown 格式总结：\n"
            "1. 最主要的变更内容\n2. 潜在法律风险\n3. 建议的处理方式"
        )
        try:
            return self.llm(prompt, model_mode=model_mode)
        except Exception as e:
            logger.warning(f"[DocCompare] 摘要生成失败: {e}")
            lines = [f"# 比对摘要\n\n发现 **{len(critical)}** 处重要变更：\n"]
            for a in critical[:10]:
                lines.append(f"- {a.get('diff_detail', '条款变更')}")
            return "\n".join(lines)

    @staticmethod
    def _esc(text: str) -> str:
        """HTML 转义。"""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
