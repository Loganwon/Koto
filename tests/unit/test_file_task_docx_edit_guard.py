import json

from app.core.agent.file_task_docx_edit_guard import (
    local_docx_edit_block_message,
    tool_args_docx_paragraph_count,
)


def test_tool_args_docx_paragraph_count_handles_json_list_and_content():
    assert (
        tool_args_docx_paragraph_count(
            {"paragraphs": json.dumps([{"text": "A"}, {"text": "B"}])}
        )
        == 2
    )
    assert tool_args_docx_paragraph_count({"content": "single paragraph"}) == 1
    assert tool_args_docx_paragraph_count({}) == 0
    assert tool_args_docx_paragraph_count({"paragraphs": "not json"}) == 1


def test_local_docx_edit_block_message_blocks_multi_paragraph_rewrite():
    block = local_docx_edit_block_message(
        task_text="只追加一句风险声明，保留已有表格不变。",
        tool_name="write_docx_content",
        tool_args={
            "paragraphs": json.dumps(
                [{"text": "Risk Review"}, {"text": "Overall risk level: Moderate."}]
            )
        },
    )

    assert "DOCX 局部编辑" in block
    assert "insert_docx_paragraph" in block


def test_local_docx_edit_block_message_allows_non_matching_or_single_paragraph():
    assert (
        local_docx_edit_block_message(
            task_text="创建新的 DOCX 报告。",
            tool_name="write_docx_content",
            tool_args={"paragraphs": json.dumps([{"text": "A"}, {"text": "B"}])},
        )
        == ""
    )
    assert (
        local_docx_edit_block_message(
            task_text="append one sentence and preserve existing table",
            tool_name="write_docx_content",
            tool_args={"paragraphs": json.dumps([{"text": "One sentence."}])},
        )
        == ""
    )
    assert (
        local_docx_edit_block_message(
            task_text="append one sentence and preserve existing table",
            tool_name="insert_docx_paragraph",
            tool_args={"paragraphs": json.dumps([{"text": "A"}, {"text": "B"}])},
        )
        == ""
    )
