from __future__ import annotations

from app.core.editor_ai_pipeline import EditorAIPipeline


def test_editor_pipeline_preprocesses_file_task_without_extension_injection():
    result = EditorAIPipeline.preprocess(
        prompt="请总结这份合同",
        file_type="docx",
        output_mode="edit",
        base_system_instruction="BASE",
    )
    assert result.task_type == "FILE_GEN"
    assert "BASE" in result.system_instruction


def test_editor_pipeline_postprocess_restores_and_validates_text():
    result = EditorAIPipeline.postprocess(
        response_text="处理完成",
        mask_result=None,
        user_prompt="处理文档",
        file_type="docx",
    )
    assert result.text == "处理完成"
    assert result.validation_action in {"PASS", "WARN"}
