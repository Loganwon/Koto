from app.core.agent import file_task_classification_signals as signals_module
from app.core.agent.file_task_classification_signals import build_classification_signals
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest


def test_classification_signals_collects_intent_and_semantic_markers():
    request = FileTaskRequest(
        task="分析这个xlsx财务数据的问题，并将数据做成图，然后把问题和图加入docx",
        target_path="report.docx",
        files=[
            FileTaskFile(path="financial.xlsx", name="financial.xlsx", type="xlsx"),
            FileTaskFile(path="report.docx", name="report.docx", type="docx", target=True),
        ],
    )

    signals = build_classification_signals(
        classification_task=request.task,
        classification_request=request,
        files=request.files,
        is_docx_annotation_request=lambda _request: False,
        is_docx_clear_review_request=lambda _request: False,
    )

    assert signals.write_intent is True
    assert signals.raw_write_intent is True
    assert signals.readonly_write_negation is False
    assert signals.file_types == {"xlsx", "docx"}
    assert signals.target_file_type == "docx"
    assert signals.chart_request is True
    assert signals.financial_request is True
    assert signals.docx_report_request is True


def test_classification_signals_compare_annotation_strips_generic_annotation(monkeypatch):
    monkeypatch.setattr(
        signals_module,
        "matched_native_capability_names",
        lambda _request: ["annotate_file", "compare_docx_and_annotate"],
    )
    request = FileTaskRequest(
        task="对比这两份 DOCX 并标注不同之处",
        target_path="new.docx",
        files=[
            FileTaskFile(path="old.docx", name="old.docx", type="docx"),
            FileTaskFile(path="new.docx", name="new.docx", type="docx", target=True),
        ],
    )

    signals = build_classification_signals(
        classification_task=request.task,
        classification_request=request,
        files=request.files,
        is_docx_annotation_request=lambda _request: True,
        is_docx_clear_review_request=lambda _request: False,
    )

    assert signals.docx_compare_annotate_request is True
    assert signals.raw_docx_annotation_request is False
    assert signals.docx_annotation_request is False
    assert signals.matched_capabilities == ["compare_docx_and_annotate"]


def test_classification_signals_clear_review_strips_generic_annotation(monkeypatch):
    monkeypatch.setattr(
        signals_module,
        "matched_native_capability_names",
        lambda _request: ["read_docx_content", "annotate_file"],
    )
    request = FileTaskRequest(
        task="清除这个 Word 文档里的批注",
        target_path="draft.docx",
        files=[FileTaskFile(path="draft.docx", name="draft.docx", type="docx")],
    )

    signals = build_classification_signals(
        classification_task=request.task,
        classification_request=request,
        files=request.files,
        is_docx_annotation_request=lambda _request: False,
        is_docx_clear_review_request=lambda _request: True,
    )

    assert signals.clear_docx_review_request is True
    assert signals.matched_capabilities == ["read_docx_content"]
