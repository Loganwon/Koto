from app.core.agent.file_task_classification_contract import (
    build_intent_adjudication_contract_context,
    build_mainline_contract_context,
)
from app.core.agent.file_task_contract import FileTaskClassification


def test_intent_adjudication_contract_context_marks_readonly_guard():
    context = build_intent_adjudication_contract_context(
        "只读取这个文件并总结，不要修改文件"
    )

    assert context.readonly_write_negation is True
    assert context.global_readonly_write_negation is True
    assert context.artifact_creation_intent is False
    assert context.strong_write_intent is False


def test_intent_adjudication_contract_context_preserves_artifact_write_signal():
    context = build_intent_adjudication_contract_context(
        "请创建一个新的 docx 报告并保存为 summary.docx"
    )

    assert context.readonly_write_negation is False
    assert context.artifact_creation_intent is True
    assert context.strong_write_intent is True


def test_mainline_contract_context_builds_docx_annotation_anchor():
    context = build_mainline_contract_context(
        task_text="继续优化上一轮批注",
        explicit_output_mode="",
        readonly_write_negation=False,
        has_target_context=True,
        docx_annotation_has_contract=lambda classification: bool(
            classification.docx_annotation_request
        ),
        strong_write_intent=False,
    )
    classification = FileTaskClassification(docx_annotation_request=True)

    assert context.explicit_output_mode == ""
    assert context.has_target_context is True
    assert context.docx_annotation_has_contract(classification) is True


def test_mainline_contract_context_builds_write_anchor_from_explicit_mode():
    context = build_mainline_contract_context(
        task_text="优化这个 docx",
        explicit_output_mode="write",
        readonly_write_negation=False,
        has_target_context=True,
        docx_annotation_has_contract=lambda _classification: False,
        strong_write_intent=False,
    )
    classification = FileTaskClassification(write_intent=True)

    assert context.explicit_output_mode == "write"
    assert context.write_has_contract_anchor(classification) is True


def test_mainline_contract_context_builds_write_anchor_from_create_contract():
    context = build_mainline_contract_context(
        task_text="请创建一个新的 docx 报告并保存为 summary.docx",
        explicit_output_mode="",
        readonly_write_negation=False,
        has_target_context=False,
        docx_annotation_has_contract=lambda _classification: False,
        strong_write_intent=False,
    )
    classification = FileTaskClassification(write_intent=True)

    assert context.write_has_contract_anchor(classification) is True
