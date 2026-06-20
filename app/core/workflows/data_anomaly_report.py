# ══════════════════════════════════════════════════════════════
# data_anomaly_report.py — 数据异常检测报告
#
# 用户场景：
#   上传 Excel/CSV 文件，AI 扫描：
#   - 缺失值、重复行、格式不一致、数值异常
#   生成着色标注的数据 + 异常汇总表。
#   程序化检测为主，LLM 辅助解读（可完全离线运行）。
# ══════════════════════════════════════════════════════════════

from __future__ import annotations

import csv
import hashlib
import io
import logging
import math
import re
import uuid as _uuid
from collections import Counter, defaultdict
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


class DataAnomalyReport(WorkflowExecutor):
    """
    数据异常检测报告工作流。

    params 期望字段:
        data_file:  str — Excel 或 CSV 文件路径
        model_mode: str — "auto" | "local"
    """

    WORKFLOW_ID = "data_anomaly_report"
    WORKFLOW_NAME = "数据异常检测"

    def execute(self, params: dict, yield_event) -> Any:
        data_file: str = params.get("data_file") or ""
        model_mode: str = params.get("model_mode") or "auto"

        if not data_file:
            yield sse_error("请提供数据文件（data_file）")
            return

        # ── Step 1: 读取数据 ─────────────────────────────────────────
        yield sse_step_start("load", "📂 读取数据文件…")
        headers, rows = self._load_data(data_file)
        if not headers or not rows:
            yield sse_error("数据文件为空或无法解析")
            return
        yield sse_step_done("load", f"📂 已加载 {len(rows)} 行 × {len(headers)} 列")

        # ── Step 2: 缺失值检测 ──────────────────────────────────────
        yield sse_step_start("missing", "🔍 检测缺失值…")
        anomalies: list[dict] = []
        cell_marks: dict[tuple[int, int], str] = {}  # (row, col) → color

        missing = self._detect_missing(headers, rows)
        anomalies.extend(missing["anomalies"])
        cell_marks.update(missing["marks"])
        yield sse_step_done(
            "missing", f"🔍 缺失值: {len(missing['anomalies'])} 个问题列"
        )

        # ── Step 3: 重复行检测 ──────────────────────────────────────
        yield sse_step_start("duplicates", "🔍 检测重复行…")
        dups = self._detect_duplicates(headers, rows)
        anomalies.extend(dups["anomalies"])
        cell_marks.update(dups["marks"])
        yield sse_step_done("duplicates", f"🔍 重复行: {len(dups['anomalies'])} 组")

        # ── Step 4: 格式一致性 ──────────────────────────────────────
        yield sse_step_start("format", "🔍 检测格式一致性…")
        fmt = self._detect_format_issues(headers, rows)
        anomalies.extend(fmt["anomalies"])
        cell_marks.update(fmt["marks"])
        yield sse_step_done("format", f"🔍 格式问题: {len(fmt['anomalies'])} 列")

        # ── Step 5: 数值异常 ────────────────────────────────────────
        yield sse_step_start("outliers", "🔍 检测数值异常…")
        outliers = self._detect_outliers(headers, rows)
        anomalies.extend(outliers["anomalies"])
        cell_marks.update(outliers["marks"])
        yield sse_step_done("outliers", f"🔍 异常值: {len(outliers['anomalies'])} 个")

        # ── Step 6: LLM 解读（仅在线模式） ─────────────────────────
        llm_insights = ""
        if model_mode != "local" and anomalies:
            yield sse_step_start("llm", "🤖 AI 分析异常影响…")
            llm_insights = self._llm_interpret(anomalies[:20], headers, model_mode)
            yield sse_step_done("llm", "🤖 AI 分析完成")

        # ── Step 7: 构建输出 ────────────────────────────────────────
        yield sse_step_start("build", "📊 生成报告…")
        workbook = self._build_workbook(headers, rows, cell_marks, anomalies)
        summary = self._build_summary(anomalies, len(rows), len(headers), llm_insights)
        yield sse_step_done("build", "📊 报告生成完成")

        # ── 输出 ─────────────────────────────────────────────────────
        yield sse_output(
            "xlsx_data", workbook, f"数据检测结果（{len(anomalies)} 个异常）"
        )
        yield sse_output("markdown", summary, "检测摘要")

    # ── 数据加载 ──────────────────────────────────────────────────────

    def _load_data(self, file_path: str) -> tuple[list[str], list[list[str]]]:
        """读取 Excel 或 CSV，返回 (headers, rows)。"""
        ext = Path(file_path).suffix.lower()
        try:
            if ext in (".xlsx", ".xls"):
                return self._load_xlsx(file_path)
            elif ext == ".csv":
                return self._load_csv(file_path)
            else:
                return self._load_csv(file_path)
        except Exception as e:
            logger.warning("[AnomalyReport] 数据加载失败: %s", e)
            return [], []

    def _load_xlsx(self, path: str) -> tuple[list[str], list[list[str]]]:
        import openpyxl

        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        ws = wb.active
        if ws is None:
            return [], []
        all_rows = []
        for row in ws.iter_rows(values_only=True):
            all_rows.append([str(c) if c is not None else "" for c in row])
        wb.close()
        if not all_rows:
            return [], []
        return all_rows[0], all_rows[1:]

    def _load_csv(self, path: str) -> tuple[list[str], list[list[str]]]:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            all_rows = list(reader)
        if not all_rows:
            return [], []
        return all_rows[0], all_rows[1:]

    # ── 检测方法 ──────────────────────────────────────────────────────

    def _detect_missing(self, headers: list[str], rows: list[list[str]]) -> dict:
        """缺失值检测：统计每列空值率。"""
        anomalies = []
        marks: dict[tuple[int, int], str] = {}
        total = len(rows)
        if total == 0:
            return {"anomalies": anomalies, "marks": marks}

        for c, h in enumerate(headers):
            empty_count = sum(1 for r in rows if c >= len(r) or not str(r[c]).strip())
            rate = empty_count / total
            if rate > 0.05:
                anomalies.append(
                    {
                        "type": "缺失值",
                        "location": f"列 [{h}]",
                        "description": f"空值率 {rate:.1%}（{empty_count}/{total}）",
                        "severity": "high" if rate > 0.3 else "medium",
                    }
                )
                for ri, r in enumerate(rows):
                    if c >= len(r) or not str(r[c]).strip():
                        marks[(ri, c)] = "#ffcdd2"  # 红
        return {"anomalies": anomalies, "marks": marks}

    def _detect_duplicates(self, headers: list[str], rows: list[list[str]]) -> dict:
        """重复行检测。"""
        anomalies = []
        marks: dict[tuple[int, int], str] = {}
        hashes: dict[str, list[int]] = defaultdict(list)

        for ri, r in enumerate(rows):
            h = hashlib.md5("|".join(str(c) for c in r).encode(), usedforsecurity=False).hexdigest()
            hashes[h].append(ri)

        dup_groups = {h: idxs for h, idxs in hashes.items() if len(idxs) > 1}
        for _, idxs in dup_groups.items():
            anomalies.append(
                {
                    "type": "重复行",
                    "location": f"行 {', '.join(str(i+2) for i in idxs)}",
                    "description": f"{len(idxs)} 行完全相同",
                    "severity": "medium",
                }
            )
            for ri in idxs[1:]:  # 标记除第一行外的重复行
                for c in range(len(headers)):
                    marks[(ri, c)] = "#ffe0b2"  # 橙

        return {"anomalies": anomalies, "marks": marks}

    def _detect_format_issues(self, headers: list[str], rows: list[list[str]]) -> dict:
        """格式一致性检测（日期、电话、邮箱等）。"""
        anomalies = []
        marks: dict[tuple[int, int], str] = {}

        date_patterns = [
            (r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", "YYYY-MM-DD"),
            (r"\d{1,2}[-/]\d{1,2}[-/]\d{4}", "DD/MM/YYYY"),
            (r"\d{4}年\d{1,2}月\d{1,2}日", "YYYY年M月D日"),
        ]

        for c, h in enumerate(headers):
            col_vals = [str(r[c]).strip() if c < len(r) else "" for r in rows]
            non_empty = [v for v in col_vals if v]
            if len(non_empty) < 3:
                continue

            # 检查日期格式混用
            format_counts: Counter = Counter()
            for v in non_empty:
                for pat, label in date_patterns:
                    if re.fullmatch(pat, v):
                        format_counts[label] += 1
                        break

            if len(format_counts) > 1:
                desc = "、".join(f"{k}({v}个)" for k, v in format_counts.most_common())
                anomalies.append(
                    {
                        "type": "格式混用",
                        "location": f"列 [{h}]",
                        "description": f"日期格式混用: {desc}",
                        "severity": "medium",
                    }
                )
                # 标记非主流格式的单元格
                main_fmt = format_counts.most_common(1)[0][0]
                for ri, v in enumerate(col_vals):
                    for pat, label in date_patterns:
                        if re.fullmatch(pat, v) and label != main_fmt:
                            marks[(ri, c)] = "#fff9c4"  # 黄
                            break

        return {"anomalies": anomalies, "marks": marks}

    def _detect_outliers(self, headers: list[str], rows: list[list[str]]) -> dict:
        """数值异常检测（3σ 法则）。"""
        anomalies = []
        marks: dict[tuple[int, int], str] = {}

        for c, h in enumerate(headers):
            nums: list[tuple[int, float]] = []
            for ri, r in enumerate(rows):
                if c >= len(r):
                    continue
                try:
                    v = float(str(r[c]).replace(",", "").replace("，", "").strip())
                    if math.isfinite(v):
                        nums.append((ri, v))
                except (ValueError, TypeError):
                    continue

            if len(nums) < 5:
                continue

            values = [v for _, v in nums]
            mean = sum(values) / len(values)
            std = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
            if std == 0:
                continue

            outlier_rows = []
            for ri, v in nums:
                if abs(v - mean) > 3 * std:
                    outlier_rows.append((ri, v))
                    marks[(ri, c)] = "#e1bee7"  # 紫

            if outlier_rows:
                anomalies.append(
                    {
                        "type": "数值异常",
                        "location": f"列 [{h}]",
                        "description": f"{len(outlier_rows)} 个离群值（均值={mean:.2f}, σ={std:.2f}）",
                        "severity": "high" if len(outlier_rows) > 3 else "medium",
                    }
                )

        return {"anomalies": anomalies, "marks": marks}

    # ── LLM 解读 ──────────────────────────────────────────────────────

    def _llm_interpret(
        self, anomalies: list[dict], headers: list[str], model_mode: str
    ) -> str:
        """调用 LLM 解释异常的业务影响和修复建议。"""
        import json

        summary = json.dumps(anomalies, ensure_ascii=False, indent=2)
        cols = json.dumps(headers, ensure_ascii=False)
        prompt = (
            f"以下是对一份数据表（列: {cols}）进行质量检测后发现的异常：\n\n{summary}\n\n"
            "请用简洁的中文 Markdown 说明：\n"
            "1. 这些异常可能的业务影响\n"
            "2. 建议的修复步骤（按优先级排序）"
        )
        try:
            return self.llm(prompt, model_mode=model_mode)
        except Exception as e:
            logger.warning("[AnomalyReport] LLM 解读失败: %s", e)
            return ""

    # ── 构建输出 ──────────────────────────────────────────────────────

    def _build_workbook(
        self,
        headers: list[str],
        rows: list[list[str]],
        cell_marks: dict[tuple[int, int], str],
        anomalies: list[dict],
    ) -> dict:
        """构建两个 Sheet 的 Univer IWorkbookData。"""
        wb_id = str(_uuid.uuid4())[:8]

        # ── Sheet 1: 带标注的原始数据 ────────────────────────────────
        data_sheet_id = "annotated_data"
        cell_data_1: dict = {}

        header_style = {"bl": 1, "bg": {"rgb": "#1a73e8"}, "cl": {"rgb": "#ffffff"}}
        row0: dict = {}
        for c, h in enumerate(headers):
            row0[str(c)] = {"v": h, "t": 1, "s": header_style}
        cell_data_1["0"] = row0

        for ri, r in enumerate(rows):
            row_cells: dict = {}
            for c in range(len(headers)):
                v = r[c] if c < len(r) else ""
                cell: dict = {"v": str(v), "t": 1}
                if (ri, c) in cell_marks:
                    cell["s"] = {"bg": {"rgb": cell_marks[(ri, c)]}}
                row_cells[str(c)] = cell
            cell_data_1[str(ri + 1)] = row_cells

        # ── Sheet 2: 异常汇总 ────────────────────────────────────────
        summary_sheet_id = "anomaly_summary"
        summary_cols = ["类型", "位置", "描述", "严重程度"]
        cell_data_2: dict = {}

        row0_2: dict = {}
        for c, h in enumerate(summary_cols):
            row0_2[str(c)] = {"v": h, "t": 1, "s": header_style}
        cell_data_2["0"] = row0_2

        sev_colors = {
            "high": "#ffcdd2",
            "critical": "#ffcdd2",
            "medium": "#fff9c4",
            "low": "#c8e6c9",
        }
        for ri, a in enumerate(anomalies):
            sev = a.get("severity", "low")
            bg = sev_colors.get(sev, "#f5f5f5")
            cell_data_2[str(ri + 1)] = {
                "0": {"v": a.get("type", ""), "t": 1},
                "1": {"v": a.get("location", ""), "t": 1},
                "2": {"v": a.get("description", ""), "t": 1, "s": {"tb": 3}},
                "3": {"v": sev, "t": 1, "s": {"bg": {"rgb": bg}, "bl": 1}},
            }

        col_widths_1 = {
            str(c): max(80, min(160, len(h) * 14)) for c, h in enumerate(headers)
        }
        col_widths_2 = {"0": 80, "1": 100, "2": 250, "3": 80}

        return {
            "id": wb_id,
            "name": "数据异常检测",
            "appVersion": "0.5.0",
            "sheetOrder": [data_sheet_id, summary_sheet_id],
            "sheets": {
                data_sheet_id: {
                    "id": data_sheet_id,
                    "name": "数据（标注版）",
                    "rowCount": len(rows) + 1,
                    "columnCount": len(headers),
                    "cellData": cell_data_1,
                    "columnData": col_widths_1,
                    "mergeData": [],
                },
                summary_sheet_id: {
                    "id": summary_sheet_id,
                    "name": "异常汇总",
                    "rowCount": len(anomalies) + 1,
                    "columnCount": len(summary_cols),
                    "cellData": cell_data_2,
                    "columnData": col_widths_2,
                    "mergeData": [],
                },
            },
            "styles": {},
        }

    def _build_summary(
        self, anomalies: list[dict], total_rows: int, total_cols: int, llm_insights: str
    ) -> str:
        """Markdown 摘要。"""
        type_counts: Counter = Counter()
        for a in anomalies:
            type_counts[a.get("type", "其他")] += 1

        lines = [
            "# 数据异常检测摘要\n",
            f"- 数据规模: {total_rows} 行 × {total_cols} 列",
            f"- 检测到 **{len(anomalies)}** 个异常\n",
            "## 异常分布\n",
        ]
        icon_map = {"缺失值": "🔴", "重复行": "🟠", "格式混用": "🟡", "数值异常": "🟣"}
        for t, cnt in type_counts.most_common():
            lines.append(f"- {icon_map.get(t, '⚪')} {t}: {cnt} 个")

        if llm_insights:
            lines.append(f"\n## AI 分析\n\n{llm_insights}")

        return "\n".join(lines)
