# -*- coding: utf-8 -*-
from __future__ import annotations

import json


def test_verify_task_completion_rejects_missing_explicit_output_file() -> None:
    from app.core.agent.task_tools import verify_task_completion

    result = json.loads(
        verify_task_completion(
            task_description=(
                "读取 codex_context_dir/orders.csv，生成 optimized_restock_plan.csv "
                "和 optimized_operations_report.md。"
            ),
            file_states=json.dumps(
                [{"path": "optimized_restock_plan.csv", "exists": True, "modified": True}],
                ensure_ascii=False,
            ),
            file_changes=json.dumps(
                [{"path": "optimized_restock_plan.csv", "operation": "run_python_code"}],
                ensure_ascii=False,
            ),
        )
    )

    assert result["completed"] is False
    assert result["criteria_results"][0]["criterion"] == "explicit_output_files_present"
    assert "optimized_operations_report.md" in result["summary"]


def test_verify_task_completion_summarizes_multiple_docx_changes_on_target() -> None:
    from app.core.agent.task_tools import verify_task_completion

    result = json.loads(
        verify_task_completion(
            task_description="把 xlsx 表格加入 docx，并追加核验说明",
            file_states=json.dumps(
                [{"path": "report.docx", "exists": True, "modified": True}],
                ensure_ascii=False,
            ),
            file_changes=json.dumps(
                [
                    {
                        "path": "report.docx",
                        "operation": "write_docx_content",
                        "paragraphs_written": 2,
                    },
                    {
                        "path": "report.docx",
                        "operation": "insert_excel_as_docx_table",
                        "sheet": "Budget",
                        "rows_written": 4,
                        "columns_written": 5,
                    },
                ],
                ensure_ascii=False,
            ),
            target_path="report.docx",
        )
    )

    assert result["completed"] is True
    assert "文件已成功修改：report.docx" in result["summary"]
    assert "已写入 2 个段落" in result["summary"]
    assert "工作表“Budget”" in result["summary"]
    assert "4 行 × 5 列" in result["summary"]


def test_verify_task_completion_summarizes_multiple_docx_images_once() -> None:
    from app.core.agent.task_tools import verify_task_completion

    result = json.loads(
        verify_task_completion(
            task_description="把多张图表加入 docx",
            file_states=json.dumps(
                [{"path": "report.docx", "exists": True, "modified": True}],
                ensure_ascii=False,
            ),
            file_changes=json.dumps(
                [
                    {
                        "path": "report.docx",
                        "operation": "insert_image_into_docx",
                        "image_name": "chart1.png",
                        "images_inserted": 1,
                    },
                    {
                        "path": "report.docx",
                        "operation": "insert_image_into_docx",
                        "image_name": "chart2.png",
                        "images_inserted": 1,
                    },
                ],
                ensure_ascii=False,
            ),
            target_path="report.docx",
        )
    )

    assert result["completed"] is True
    assert "已插入 2 张图片" in result["summary"]
    assert "chart1.png、chart2.png" in result["summary"]
    assert result["summary"].count("已插入") == 1
