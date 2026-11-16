from app.core.agent.file_task_classification_policy import resolve_classification_policy
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest


def _resolve(
    request: FileTaskRequest,
    *,
    followup_context=None,
    resume_control=None,
    output_mode="",
    planner_policy="",
    planner_backend="",
    known_tool_gap=None,
):
    return resolve_classification_policy(
        classification_task=request.task,
        classification_request=request,
        files=request.files,
        followup_context=followup_context or {},
        resume_control=resume_control or {},
        explicit_output_mode=output_mode,
        planner_policy=planner_policy,
        planner_backend=planner_backend,
        known_tool_gap=known_tool_gap,
    )


def test_policy_collects_write_safety_and_file_facts_without_semantic_recipes():
    request = FileTaskRequest(
        task="分析这个xlsx财务数据的问题，并将数据做成图，然后把问题和图加入docx",
        target_path="report.docx",
        files=[
            FileTaskFile(path="financial.xlsx", name="financial.xlsx", type="xlsx"),
            FileTaskFile(
                path="report.docx", name="report.docx", type="docx", target=True
            ),
        ],
    )

    policy = _resolve(request)

    assert policy.write_signal is True
    assert policy.raw_write_signal is True
    assert policy.readonly_write_negation is False
    assert policy.file_types == {"xlsx", "docx"}
    assert policy.target_file_type == "docx"
    assert "write_required" in policy.reason_codes
    assert not hasattr(policy, "matched_capabilities")
    assert not hasattr(policy, "selected_recipe")


def test_policy_does_not_infer_target_type_from_task_language():
    request = FileTaskRequest(
        task="分析财务预测并创建一个docx报告",
        files=[FileTaskFile(path="forecast.xlsx", name="forecast.xlsx", type="xlsx")],
    )

    policy = _resolve(request)

    assert policy.target_file_type == ""
    assert policy.write_signal is True


def test_policy_marks_stepwise_pdf_docx_resume_as_required_write():
    request = FileTaskRequest(
        task="继续处理",
        target_path="summary.docx",
        files=[FileTaskFile(path="large.pdf", name="large.pdf", type="pdf")],
    )

    policy = _resolve(
        request,
        resume_control={
            "adapter": "generic_tool_loop",
            "policy": "confirm_each_step",
        },
    )

    assert policy.request_kind == "resume"
    assert policy.write_signal is True
    assert policy.raw_write_signal is True
    assert "workflow_checkpoint_resume" in policy.reason_codes
    assert "workflow_adapter:generic_tool_loop" in policy.reason_codes
    assert "stepwise_resume_forced_write_requirement" in policy.reason_codes


def test_policy_makes_plain_followup_question_diagnostic():
    request = FileTaskRequest(task="把上一轮的修改再解释一下")

    policy = _resolve(
        request,
        followup_context={"followup_action": "question"},
    )

    assert policy.request_kind == "followup"
    assert policy.diagnostic_request is True
    assert policy.write_signal is False
    assert "followup_question" in policy.reason_codes
    assert "diagnostic_request" in policy.reason_codes


def test_policy_allows_explicit_write_followup_question():
    request = FileTaskRequest(task="把上一轮内容直接写入文件")

    policy = _resolve(
        request,
        followup_context={"followup_action": "question"},
        output_mode="write",
    )

    assert policy.diagnostic_request is False
    assert policy.write_signal is True
    assert "followup_question_explicit_write" in policy.reason_codes


def test_policy_applies_previous_hybrid_followup():
    request = FileTaskRequest(task="应用刚才的建议")

    policy = _resolve(
        request,
        followup_context={
            "followup_action": "apply",
            "previous_task_output_mode": "hybrid",
        },
    )

    assert policy.write_signal is True
    assert "followup_apply_write_requirement" in policy.reason_codes
    assert "write_required" in policy.reason_codes


def test_explicit_answer_wins_over_followup_apply_context():
    request = FileTaskRequest(task="应用刚才的建议")

    policy = _resolve(
        request,
        followup_context={
            "followup_action": "apply",
            "previous_task_output_mode": "hybrid",
        },
        output_mode="answer",
    )

    assert policy.output_mode == "answer"
    assert policy.operation_kind == "read"
    assert policy.write_authorized is False
    assert policy.write_required is False
    assert "answer_mode_overrode_write_requirement" in policy.reason_codes
    assert "write_required" not in policy.reason_codes
    assert "write_optional" not in policy.reason_codes


def test_policy_readonly_negation_and_answer_mode_are_authoritative():
    readonly_request = FileTaskRequest(task="分析这份文件，不要写回文件")
    answer_request = FileTaskRequest(task="把结论写入文件")

    readonly_policy = _resolve(readonly_request)
    answer_policy = _resolve(answer_request, output_mode="answer")

    assert readonly_policy.write_signal is False
    assert "readonly_write_negation" in readonly_policy.reason_codes
    assert "write_required" not in readonly_policy.reason_codes
    assert answer_policy.write_signal is False
    assert "answer_mode_overrode_write_requirement" in answer_policy.reason_codes


def test_policy_adds_only_explicit_planner_and_tool_gap_facts():
    request = FileTaskRequest(task="读取 CAD 文件")

    policy = _resolve(
        request,
        planner_policy="native_only",
        planner_backend="native",
        known_tool_gap={"missing_capability": "read_cad_file"},
    )

    assert policy.known_gap_name == "read_cad_file"
    assert "planner_policy:native_only" in policy.reason_codes
    assert "planner_backend:native" in policy.reason_codes
    assert "native_tool_gap:read_cad_file" in policy.reason_codes


def test_positive_soft_edit_with_target_preserves_optional_kernel_write():
    request = FileTaskRequest(
        task="把这个 PPT 编辑得好看一点，做成专业高级的汇报风格",
        target_path="deck.pptx",
        files=[FileTaskFile(path="deck.pptx", name="deck.pptx", type="pptx")],
    )

    policy = _resolve(request)

    assert policy.output_mode == "hybrid"
    assert policy.write_authorized is True
    assert policy.write_required is False
    assert policy.operation_kind == "hybrid"
    assert "mainline_contract:keyword_write_demoted" in policy.reason_codes
    assert "mainline_contract:target_context_hybrid" in policy.reason_codes
    assert "write_optional" in policy.reason_codes
    assert "write_required" not in policy.reason_codes
    explicit = _resolve(request, output_mode="hybrid")
    assert explicit.output_mode == "hybrid" and explicit.write_authorized
    assert not explicit.write_required


def test_policy_keeps_imperative_report_polish_as_required_write():
    request = FileTaskRequest(
        task="润色这份报告，让表达更流畅专业",
        target_path="report.docx",
        files=[
            FileTaskFile(
                path="report.docx",
                name="report.docx",
                type="docx",
                target=True,
            )
        ],
    )

    policy = _resolve(request)

    assert policy.output_mode == "write"
    assert policy.write_authorized is True
    assert policy.write_required is True
    assert "mainline_contract:keyword_write_demoted" not in policy.reason_codes
    assert "write_required" in policy.reason_codes


def test_policy_keeps_target_scoped_file_copy_as_required_write():
    request = FileTaskRequest(
        task="Copy this PDF file to archive.pdf.",
        target_path="archive.pdf",
        files=[FileTaskFile(path="source.pdf", name="source.pdf", type="pdf")],
    )

    policy = _resolve(request)

    assert policy.output_mode == "write"
    assert policy.write_authorized is True
    assert policy.write_required is True
    assert "mainline_contract:keyword_write_demoted" not in policy.reason_codes
