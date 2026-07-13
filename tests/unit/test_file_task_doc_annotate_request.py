from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskRequest,
)
from app.core.agent.file_task_doc_annotate_request import (
    docx_annotation_contract_for_request,
    docx_annotation_has_request_contract,
    is_docx_annotation_request,
    is_docx_clear_review_request,
)


def _docx_request(task: str, *, options=None) -> FileTaskRequest:
    return FileTaskRequest(
        task=task,
        target_path="draft.docx",
        files=[
            FileTaskFile(path="draft.docx", name="draft.docx", type="docx", target=True)
        ],
        options=options or {},
    )


def test_docx_annotation_request_accepts_explicit_review_intent():
    request = _docx_request(
        "Please annotate this document and add comments to the problematic parts."
    )

    assert is_docx_annotation_request(request) is True
    assert is_docx_clear_review_request(request) is False


def test_docx_annotation_request_skips_clear_review_requests():
    request = _docx_request("取消docx里面所有批注")

    assert is_docx_clear_review_request(request) is True
    assert is_docx_annotation_request(request) is False


def test_docx_annotation_request_skips_direct_rewrite_requests():
    request = _docx_request("润色这个docx并写回当前docx")

    assert is_docx_annotation_request(request) is False
    assert is_docx_clear_review_request(request) is False


def test_docx_annotation_request_skips_multi_docx_compare_requests():
    request = FileTaskRequest(
        task="对比这两份文件，找出他们有区别的地方标注出来",
        target_path="revised.docx",
        files=[
            FileTaskFile(path="source.docx", name="source.docx", type="docx"),
            FileTaskFile(
                path="revised.docx", name="revised.docx", type="docx", target=True
            ),
        ],
    )

    assert is_docx_annotation_request(request) is False


def test_docx_annotation_request_keeps_pdf_translation_batch_bridge_signal():
    request = FileTaskRequest(
        task="请根据原文 pdf 分段处理并批注译稿里翻译不准确的位置",
        target_path="translation.docx",
        files=[
            FileTaskFile(path="source.pdf", name="source.pdf", type="pdf"),
            FileTaskFile(
                path="translation.docx",
                name="translation.docx",
                type="docx",
                target=True,
            ),
        ],
    )

    assert is_docx_annotation_request(request) is True


def test_docx_annotation_request_respects_skip_option():
    request = _docx_request(
        "Please annotate this document and add comments.",
        options={"skip_doc_annotate_bridge": True},
    )

    assert is_docx_annotation_request(request) is False


def test_docx_annotation_contract_accepts_selected_bridge_recipe():
    request = _docx_request("继续优化批注")
    classification = FileTaskClassification(selected_recipe="single_docx_review_bridge")

    assert (
        docx_annotation_has_request_contract(request, request.files, classification)
        is True
    )


def test_docx_annotation_contract_accepts_followup_annotation_context():
    request = _docx_request(
        "继续优化上一轮结果",
        options={
            "followup_context": {
                "followup_action": "improve",
                "previous_task_family": "annotate",
            }
        },
    )
    classification = FileTaskClassification(docx_annotation_request=True)

    assert (
        docx_annotation_has_request_contract(request, request.files, classification)
        is True
    )


def test_docx_annotation_contract_rejects_non_docx_request():
    request = FileTaskRequest(
        task="Please annotate this document.",
        files=[FileTaskFile(path="source.pdf", name="source.pdf", type="pdf")],
    )
    classification = FileTaskClassification(selected_recipe="single_docx_review_bridge")

    assert (
        docx_annotation_has_request_contract(request, request.files, classification)
        is False
    )


def test_docx_annotation_contract_for_request_builds_classification_predicate():
    request = _docx_request("Please annotate this document and add comments.")
    predicate = docx_annotation_contract_for_request(request, request.files)

    assert predicate(FileTaskClassification()) is True
