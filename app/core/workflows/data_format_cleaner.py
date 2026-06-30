# ══════════════════════════════════════════════════════════════
# data_format_cleaner.py — 脏数据格式清洗与标准化
#
# 用户场景：在 Excel 中选中一列或多列数据，输入自然语言指令
# （如"统一日期格式为 YYYY-MM-DD"），AI 生成 pandas 代码
# → 沙盒执行 → 返回清洗后数据 + 变更预览。
# ══════════════════════════════════════════════════════════════

from __future__ import annotations

import csv
import io
import json
import logging
import re
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

_CLEANING_SYSTEM_PROMPT = """你是一个专业的数据处理工程师。
用户会给你提供一份 CSV 格式的表格数据和一条自然语言清洗指令。
请编写可以直接运行的 Python (pandas) 代码完成清洗任务。

代码要求：
1. 使用 pandas 进行数据处理
2. 输入数据从变量 `df` 中读取（已经是 pandas DataFrame）
3. 将清洗后的 DataFrame 保存到变量 `df` 中（同名覆盖）
4. 代码的最后一行：df.to_csv('cleaned.csv', index=False)
5. 不要 import pandas（已预先导入），其他库需要 import
6. 不要调用 print()、plt.show() 等交互函数
7. 只输出代码，不要 markdown 代码块标记，不要任何解释

示例输入：
  清洗指令：将 date 列统一格式化为 YYYY-MM-DD
  数据样本：
    name,date,amount
    张三,2026/4/1,1000

示例代码输出：
  df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.strftime('%Y-%m-%d')
  df.to_csv('cleaned.csv', index=False)
"""


class DataFormatCleaner(WorkflowExecutor):
    """
    脏数据格式清洗工作流。

    params 期望字段:
        csv_data:    str       — CSV 格式的原始表格数据（来自 Univer Sheets 选区导出）
        instruction: str       — 自然语言清洗指令（如"统一日期格式为YYYY-MM-DD"）
        model_mode:  str       — "auto" | "local"（默认 "auto"）
    """

    WORKFLOW_ID = "data_format_cleaner"
    WORKFLOW_NAME = "脏数据格式清洗"

    def execute(self, params: dict, yield_event) -> Any:
        csv_data: str = (params.get("csv_data") or "").strip()
        instruction: str = (params.get("instruction") or "").strip()
        model_mode: str = params.get("model_mode") or "auto"

        if not csv_data:
            yield sse_error("请提供要清洗的表格数据（csv_data）")
            return
        if not instruction:
            yield sse_error("请提供清洗指令（instruction）")
            return

        # ── Step 1: 生成 pandas 清洗代码 ──────────────────────────────────────
        yield sse_step_start("gen_code", "🤖 生成数据清洗代码…")

        # 取前 30 行数据作为样本（避免 token 过多）
        sample_lines = csv_data.splitlines()[:32]
        sample_csv = "\n".join(sample_lines)

        code = self._generate_code(sample_csv, instruction, model_mode)
        if not code:
            yield sse_error("代码生成失败，请重试或换用更详细的指令")
            return

        yield sse_step_done("gen_code", "🤖 代码生成完成")
        # 将代码随 status 事件一起发给前端（方便预览）
        yield f"data: {json.dumps({'type': 'code', 'text': code}, ensure_ascii=False)}\n\n"

        # ── Step 2: 沙盒执行 ──────────────────────────────────────────────────
        yield sse_step_start("exec_code", "▶ 在沙盒中执行清洗代码…")
        exec_result = self._run_cleaning_code(code, csv_data)

        if exec_result.get("error"):
            stderr_snippet = (exec_result.get("stderr") or "")[:500]
            err_detail = exec_result["error"]
            if stderr_snippet:
                err_detail += f"\n{stderr_snippet}"
            yield sse_error(f"代码执行失败: {err_detail}")
            return

        cleaned_csv = exec_result.get("cleaned_csv", "")
        if not cleaned_csv:
            yield sse_error("沙盒执行没有产生输出，请检查代码")
            return

        yield sse_step_done("exec_code", "▶ 执行完成")

        # ── Step 3: 生成变更预览 ──────────────────────────────────────────────
        yield sse_step_start("diff_preview", "📊 生成变更预览…")
        diffs = self._diff_csv(csv_data, cleaned_csv)
        yield sse_step_done(
            "diff_preview",
            f"📊 共 {len(diffs)} 处变更" if diffs else "📊 数据无变化（已是标准格式）",
        )

        # ── Step 4: 输出结果 ──────────────────────────────────────────────────
        workbook = self._csv_to_workbook(cleaned_csv, diffs)
        yield sse_output("xlsx_data", workbook, f"清洗完成，{len(diffs)} 处改动")

        # 同时发出 diff 数据（方便前端高亮展示）
        if diffs:
            yield f"data: {json.dumps({'type': 'diff', 'changes': diffs[:100]}, ensure_ascii=False)}\n\n"

    # ── 辅助方法 ──────────────────────────────────────────────────────────────

    def _generate_code(self, sample_csv: str, instruction: str, model_mode: str) -> str:
        prompt = (
            f"清洗指令：{instruction}\n\n"
            f"数据样本（CSV 格式，完整数据列结构如下）：\n{sample_csv}\n\n"
            f"请根据以上指令，编写 pandas 清洗代码。"
        )
        try:
            raw = self.llm(
                prompt, system=_CLEANING_SYSTEM_PROMPT, model_mode=model_mode
            )
            # 去除可能残留的 markdown 代码块标记
            raw = re.sub(r"^```(?:python)?\s*\n?", "", raw.strip(), flags=re.MULTILINE)
            raw = raw.strip().strip("`").strip()
            return raw
        except Exception as e:
            logger.warning(f"[DataCleaner] 代码生成失败: {e}")
            return ""

    def _run_cleaning_code(self, code: str, csv_data: str) -> dict:
        """
        在沙盒中运行清洗代码。
        预先注入：import pandas as pd; df = pd.read_csv(io.StringIO(csv_data))
        运行后读取 cleaned.csv 文件。
        """
        try:
            import sys

            from app.core.sandbox import _run_in_tempdir

            # 预先写入原始数据为 input.csv，注入 DataFrame
            preamble = (
                "import pandas as pd\n"
                "import io\n"
                "_CSV_DATA = open('input.csv', 'r', encoding='utf-8').read()\n"
                "df = pd.read_csv(io.StringIO(_CSV_DATA))\n"
            )
            full_code = preamble + "\n" + code
            # 安全保底：如果 LLM 代码没有写 cleaned.csv，补一行
            if "cleaned.csv" not in full_code:
                full_code += "\ndf.to_csv('cleaned.csv', index=False)\n"

            # 写入 input.csv（通过在 tmpdir 运行时的 setup_code 方式）
            # 使用 _run_in_tempdir_with_files 模式
            import os
            import shutil
            import subprocess
            import tempfile

            tmpdir = tempfile.mkdtemp(prefix="koto_cleaner_")
            try:
                # 写入 CSV 数据
                input_csv_path = os.path.join(tmpdir, "input.csv")
                with open(input_csv_path, "w", encoding="utf-8") as f:
                    f.write(csv_data)

                # 写入执行脚本
                script_path = os.path.join(tmpdir, "clean.py")
                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(full_code)

                # 构建沙盒环境变量（去除敏感信息）
                from app.core.sandbox import _build_sandbox_env

                env = _build_sandbox_env(tmpdir)

                result = subprocess.run(
                    [sys.executable, script_path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=tmpdir,
                    env=env,
                )

                cleaned_csv_path = os.path.join(tmpdir, "cleaned.csv")
                cleaned_csv = ""
                if os.path.exists(cleaned_csv_path):
                    with open(cleaned_csv_path, "r", encoding="utf-8") as f:
                        cleaned_csv = f.read()

                return {
                    "cleaned_csv": cleaned_csv,
                    "stdout": result.stdout[:4096],
                    "stderr": result.stderr[:4096],
                    "error": (
                        None
                        if result.returncode == 0
                        else f"退出码 {result.returncode}"
                    ),
                }
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

        except subprocess.TimeoutExpired:
            return {
                "cleaned_csv": "",
                "stdout": "",
                "stderr": "",
                "error": "执行超时（30秒）",
            }
        except Exception as e:
            return {"cleaned_csv": "", "stdout": "", "stderr": "", "error": str(e)}

    def _diff_csv(self, original_csv: str, cleaned_csv: str) -> list[dict]:
        """比较原始和清洗后的 CSV，返回变更列表。"""
        diffs = []
        try:
            original_rows = list(csv.DictReader(io.StringIO(original_csv)))
            cleaned_rows = list(csv.DictReader(io.StringIO(cleaned_csv)))
            for r_idx, (orig, clean) in enumerate(zip(original_rows, cleaned_rows)):
                for col in orig.keys():
                    old_v = str(orig.get(col, ""))
                    new_v = str(clean.get(col, ""))
                    if old_v != new_v:
                        diffs.append(
                            {
                                "row": r_idx + 2,  # 1-based, 行1是表头
                                "column": col,
                                "old": old_v,
                                "new": new_v,
                            }
                        )
        except Exception as e:
            logger.warning(f"[DataCleaner] Diff 生成失败: {e}")
        return diffs

    def _csv_to_workbook(self, csv_data: str, diffs: list[dict]) -> dict:
        """将 CSV 转为 Univer IWorkbookData，变更单元格用黄色背景标注。"""
        import uuid as _uuid

        # 建立变更位置集合 (row, col)
        diff_positions: set[tuple] = set()
        try:
            reader = csv.DictReader(io.StringIO(csv_data))
            headers = reader.fieldnames or []
            col_idx = {h: i for i, h in enumerate(headers)}
            for d in diffs:
                row = d["row"] - 1  # convert to 0-based row index (0 = header)
                c = col_idx.get(d["column"], -1)
                if c >= 0:
                    diff_positions.add((row, c))
        except Exception:
            pass

        wb_id = str(_uuid.uuid4())[:8]
        sheet_id = "cleaned_data"
        cell_data: dict = {}

        highlight_style = {"bg": {"rgb": "#fff3cd"}}

        try:
            lines = csv_data.splitlines()
            reader = csv.reader(io.StringIO(csv_data))
            for r_idx, row_vals in enumerate(reader):
                row_cells: dict = {}
                is_header = r_idx == 0
                for c_idx, val in enumerate(row_vals):
                    cell: dict = {"v": val, "t": 1}
                    if is_header:
                        cell["s"] = {
                            "bl": 1,
                            "bg": {"rgb": "#1a73e8"},
                            "cl": {"rgb": "#ffffff"},
                        }
                    elif (r_idx, c_idx) in diff_positions:
                        cell["s"] = highlight_style
                    row_cells[str(c_idx)] = cell
                cell_data[str(r_idx)] = row_cells
        except Exception as e:
            logger.warning(f"[DataCleaner] Workbook 构建失败: {e}")

        return {
            "id": wb_id,
            "name": "清洗结果",
            "appVersion": "0.5.0",
            "sheetOrder": [sheet_id],
            "sheets": {
                sheet_id: {
                    "id": sheet_id,
                    "name": "清洗结果",
                    "rowCount": len(csv_data.splitlines()),
                    "columnCount": (
                        max(len(r.split(",")) for r in csv_data.splitlines())
                        if csv_data
                        else 1
                    ),
                    "cellData": cell_data,
                    "mergeData": [],
                }
            },
            "styles": {},
        }
