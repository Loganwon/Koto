from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_runtime import FileTaskRuntime


def test_file_task_runtime_keeps_explicit_readonly_request_out_of_write_loop():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "", workspace_root=".")
    request = FileTaskRequest(
        task="读取并简要说明 VERSION 文件的内容；只读取，不要修改或创建任何文件。",
        target_path="VERSION",
        files=[FileTaskFile(path="VERSION", name="VERSION", type="txt", target=True)],
    )

    classification = runtime._classify_request(request, request.files)
    details = classification.public_dict()

    assert runtime._has_readonly_write_negation(request.task) is True
    assert runtime._has_write_intent(request.task) is False
    assert classification.write_intent is False, details
    assert classification.output_mode != "write", details
    assert "readonly_write_negation" in classification.reason_codes, details


def test_file_task_runtime_followup_existing_docx_write_allows_source_file_protection():
    runtime = FileTaskRuntime(
        tool_executor=lambda name, args: "",
        model_client=lambda **kwargs: {"content": "ok", "tool_calls": []},
        workspace_root=".",
    )
    request = FileTaskRequest(
        task=(
            "请继续优化 workspace/koto_frontend_fulltest_report_20260614.docx："
            "只追加一句风险声明，保留已有表格不变，保存同一个 DOCX。"
            "不要修改 workspace/koto_frontend_fulltest_sales_20260614.xlsx "
            "和 workspace/koto_frontend_fulltest_notes_20260614.docx。"
        ),
        run_id="followup_existing_docx_write_with_source_protection",
        files=[
            FileTaskFile(
                path="workspace/koto_frontend_fulltest_sales_20260614.xlsx",
                name="koto_frontend_fulltest_sales_20260614.xlsx",
                type="xlsx",
            ),
            FileTaskFile(
                path="workspace/koto_frontend_fulltest_notes_20260614.docx",
                name="koto_frontend_fulltest_notes_20260614.docx",
                type="docx",
            ),
        ],
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "improve",
                "previous_task_output_mode": "write",
            }
        },
    )

    normalized = runtime._request_with_inferred_target_path(request)
    context_files = runtime._context_files(normalized)
    classification = runtime._classify_request(normalized, context_files)
    details = classification.public_dict()

    assert (
        normalized.target_path
        == "workspace/koto_frontend_fulltest_report_20260614.docx"
    )
    assert classification.output_mode == "write", details
    assert classification.write_intent is True, details
    assert classification.target_file_type == "docx", details
    assert classification.task_family != "table_transfer", details
    assert classification.operation_kind != "write_table", details
    assert classification.selected_recipe != "xlsx_table_to_docx", details
    assert "readonly_write_negation" not in classification.reason_codes, details
    assert any(
        file_info.target
        and file_info.path == "workspace/koto_frontend_fulltest_report_20260614.docx"
        for file_info in context_files
    )


def test_file_task_runtime_target_repair_allows_generic_source_file_protection():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "")
    target_path = "workspace/koto_complex_task_test/service_agreement_full_test.docx"
    task = (
        "核验不通过：请直接修复这个目标文件，保留已有正确分析并补全全文，"
        "创建三个真实 Word 表格。不要修改另外三个源文件，写入后核验目标文件。"
    )
    request = FileTaskRequest(
        task=task,
        target_path=target_path,
        files=[
            FileTaskFile(path="service_agreement_v1.docx", name="service_agreement_v1.docx", type="docx"),
            FileTaskFile(path="service_agreement_v2.docx", name="service_agreement_v2.docx", type="docx"),
            FileTaskFile(path="renewal_budget.xlsx", name="renewal_budget.xlsx", type="xlsx"),
            FileTaskFile(path=target_path, name="service_agreement_full_test.docx", type="docx", target=True),
        ],
    )

    classification = runtime._classify_request(request, request.files)
    details = classification.public_dict()

    assert runtime._has_readonly_write_negation(task) is False
    assert runtime._has_write_intent(task) is True
    assert classification.write_intent is True, details
    assert classification.output_mode == "write", details
    assert "readonly_write_negation" not in classification.reason_codes, details


def test_file_task_runtime_frontend_target_repair_ignores_confirmation_negation():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "")
    target_name = "service_agreement_full_test_20260628.docx"
    task = (
        "核验不通过：当前目标文件 service_agreement_full_test_20260628.docx 只有 44 个段落、0 个 Word 表格，"
        "内容在“预算表原始数据”处中断，缺少完整预算分析、风险矩阵、谈判建议和最终核验结论。"
        "请直接修复这个目标文件，保留已有正确分析并补全全文；必须创建至少 3 个真实 Word 表格。"
        "不要修改另外三个源文件，不要中途询问确认；写入后请核验目标文件的段落数、表格数和章节完整性。"
    )
    source_dir = "C:/Users/12524/Desktop/Koto/workspace/koto_complex_task_test"
    request = FileTaskRequest(
        task=task,
        target_path=target_name,
        files=[
            FileTaskFile(path=f"{source_dir}/service_agreement_v1.docx", name="service_agreement_v1.docx", type="docx"),
            FileTaskFile(path=f"{source_dir}/service_agreement_v2.docx", name="service_agreement_v2.docx", type="docx"),
            FileTaskFile(path=f"{source_dir}/renewal_budget.xlsx", name="renewal_budget.xlsx", type="xlsx"),
            FileTaskFile(path=f"{source_dir}/{target_name}", name=target_name, type="docx"),
            FileTaskFile(path=target_name, name=target_name, type="docx", target=True),
        ],
    )

    classification = runtime._classify_request(request, request.files)
    details = classification.public_dict()

    assert runtime._has_readonly_write_negation(task) is False
    assert runtime._has_write_intent(task) is True
    assert classification.write_intent is True, details
    assert classification.output_mode == "write", details
    assert classification.selected_recipe != "multi_file_compare_readonly", details
    assert "readonly_write_negation" not in classification.reason_codes, details


def test_file_task_runtime_frontend_basename_target_resolves_to_attached_path():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "")
    target_name = "service_agreement_full_test_20260628.docx"
    target_path = (
        "C:/Users/12524/Desktop/Koto/workspace/koto_complex_task_test/"
        "service_agreement_full_test_20260628.docx"
    )
    request = FileTaskRequest(
        task=(
            "请继续在目标文件 service_agreement_full_test_20260628.docx 末尾追加"
            "“二次前端完整任务核验”章节，写入后核验完成状态。"
        ),
        target_path=target_name,
        files=[
            FileTaskFile(
                path="C:/Users/12524/Desktop/Koto/workspace/koto_complex_task_test/service_agreement_v1.docx",
                name="service_agreement_v1.docx",
                type="docx",
            ),
            FileTaskFile(
                path=target_path,
                name=target_name,
                type="docx",
            ),
            FileTaskFile(path=target_name, name=target_name, type="docx", target=True),
        ],
    )

    normalized = runtime._request_with_inferred_target_path(request)
    context_files = runtime._context_files(normalized)
    target_files = [file_info for file_info in context_files if file_info.target]

    assert normalized.target_path == target_path
    assert len(target_files) == 1
    assert target_files[0].path == target_path


def test_file_task_runtime_frontend_docx_table_append_stays_write_mode():
    runtime = FileTaskRuntime(
        tool_executor=lambda name, args: "",
        workspace_root="C:/Users/12524/Desktop/Koto",
    )
    task = (
        "文件任务测试：请读取 workspace/koto_complex_task_test/renewal_budget.xlsx，"
        "并在 workspace/koto_complex_task_test/service_agreement_full_test_20260628.docx "
        "末尾追加“质量门修复闭环 20260629-0004”小节。"
        "必须调用真实表格写入能力，新增一个 Word 表格，表格两列为“核验项目”和“核验结论”，至少三行数据；"
        "不要只写文字段落。不要修改源 xlsx，不要中途询问确认；"
        "写入后核验目标 DOCX 表格总数至少为 5，并在前端输出完成状态。"
    )
    request = FileTaskRequest(task=task)

    normalized = runtime._request_with_inferred_target_path(request)
    context_files = runtime._context_files(normalized)
    classification = runtime._classify_request(normalized, context_files)
    details = classification.public_dict()

    assert runtime._has_write_intent(task) is True
    assert runtime._has_readonly_write_negation(task) is False
    assert normalized.target_path.endswith(
        "workspace/koto_complex_task_test/service_agreement_full_test_20260628.docx"
    )
    assert classification.write_intent is True, details
    assert classification.output_mode == "write", details
    assert classification.selected_recipe in {
        "xlsx_table_to_docx",
        "docx_report_table_write",
    }, details
    assert "readonly_write_negation" not in classification.reason_codes, details


def test_file_task_runtime_frontend_xlsx_sheet_to_docx_table_does_not_target_source():
    runtime = FileTaskRuntime(
        tool_executor=lambda name, args: "",
        workspace_root="C:/Users/12524/Desktop/Koto",
    )
    task = (
        "文件任务测试：请读取 workspace/koto_complex_task_test/renewal_budget.xlsx，"
        "并在 workspace/koto_complex_task_test/service_agreement_full_test_20260628.docx "
        "末尾追加“最终闭环表格核验 20260629-0011”小节。"
        "必须新增一个真实 Word 表格；请把 renewal_budget.xlsx 的 Budget 工作表写入目标 DOCX 表格。"
        "不要修改源 xlsx，不要中途询问确认；"
        "写入后核验目标 DOCX 表格总数至少为 5，并在前端输出完成状态。"
    )
    request = FileTaskRequest(task=task)

    normalized = runtime._request_with_inferred_target_path(request)
    context_files = runtime._context_files(normalized)
    classification = runtime._classify_request(normalized, context_files)
    details = classification.public_dict()

    assert normalized.target_path.endswith(
        "workspace/koto_complex_task_test/service_agreement_full_test_20260628.docx"
    )
    assert runtime._has_write_intent(task) is True
    assert classification.write_intent is True, details
    assert classification.output_mode == "write", details
    assert classification.target_file_type == "docx", details
    assert classification.selected_recipe == "xlsx_table_to_docx", details
    assert classification.operation_kind == "write_table", details
    assert classification.selected_recipe != "spreadsheet_cell_write", details
    assert "readonly_write_negation" not in classification.reason_codes, details


def test_file_task_runtime_keeps_generated_artifact_followup_readonly():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "")
    task = (
        "继续基于刚才生成的 koto_complex_task_report_20260617_1345.md，"
        "不要修改 koto_task_smoke.txt。请读取这份报告，用三条中文要点确认它是否覆盖了五个验收维度。"
    )
    request = FileTaskRequest(
        task=task,
        target_path="workspace/_codex_frontend_task_tests/koto_task_smoke.txt",
        files=[
            FileTaskFile(
                path="workspace/_codex_frontend_task_tests/koto_complex_task_report_20260617_1345.md",
                name="koto_complex_task_report_20260617_1345.md",
                type="md",
            )
        ],
    )

    classification = runtime._classify_request(request, request.files)

    assert runtime._has_write_intent(task) is False
    assert classification.write_intent is False
    assert classification.output_mode == "answer"


def test_file_task_runtime_followup_question_can_create_new_artifact():
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "")
    request = FileTaskRequest(
        task=(
            "请基于当前打开的 koto_task_smoke.txt 生成一个很短的 Markdown 文件，"
            "保存为 Markdown 文件：workspace/_codex_frontend_task_tests/koto_target_metadata_smoke_20260617_c.md。"
            "内容只写一条：本文件验证统一 AI 工作区、白盒任务步骤、任务完成后的汇报。"
        ),
        target_path="workspace/_codex_frontend_task_tests/koto_task_smoke.txt",
        files=[
            FileTaskFile(
                path="workspace/_codex_frontend_task_tests/koto_task_smoke.txt",
                name="koto_task_smoke.txt",
                type="txt",
                target=True,
            )
        ],
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "question",
            }
        },
    )

    normalized = runtime._request_with_inferred_target_path(request)
    classification = runtime._classify_request(
        normalized, runtime._context_files(normalized)
    )

    assert (
        normalized.target_path
        == "workspace/_codex_frontend_task_tests/koto_target_metadata_smoke_20260617_c.md"
    )
    assert classification.write_intent is True
    assert classification.output_mode == "write"
    assert "followup_question_new_artifact" in classification.reason_codes
    assert "diagnostic_request" not in classification.reason_codes
    assert "diagnostic_overrode_write_intent" not in classification.reason_codes


def test_file_task_runtime_followup_feedback_messages_are_not_framed_as_new_task():
    runtime = FileTaskRuntime(
        tool_executor=lambda name, args: "", model_client=lambda **kwargs: {}
    )
    request = FileTaskRequest(
        task="为什么这次结果不好？",
        run_id="followup_feedback_demo",
        current_file=FileTaskFile(
            path="translation.docx", name="translation.docx", type="docx"
        ),
        target_path="translation.docx",
        history=[
            {"role": "user", "content": "根据原文审校这个译稿"},
            {"role": "assistant", "content": "已生成第一版审校结果"},
        ],
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "question",
                "user_feedback": "为什么这次结果不好？",
                "previous_run_id": "run_prev_001",
                "previous_task_summary": "已生成第一版审校结果",
                "previous_user_request": "根据原文审校这个译稿",
                "previous_task_request": "根据原文审校这个译稿",
                "previous_task_mode": "doc_annotate_bridge",
                "previous_completed_task": "true",
            }
        },
    )

    messages = runtime._build_messages(request, [], [request.current_file])
    system = runtime._build_system_prompt(request, [request.current_file])
    content = messages[-1]["content"]

    assert "用户正在对上一轮文件任务结果提出反馈" in content
    assert '"followup_context"' in content
    assert '"previous_run_id": "run_prev_001"' in content
    assert '"followup_action": "question"' in content
    assert '"previous_task_summary": "已生成第一版审校结果"' in content
    assert "不要把这条消息当成新的文件执行任务" in content
    assert "不要默认把它当作全新的执行任务" in system
    assert "不要调用写入工具" in system


def test_file_task_runtime_followup_improve_is_framed_as_same_task_iteration():
    runtime = FileTaskRuntime(
        tool_executor=lambda name, args: "", model_client=lambda **kwargs: {}
    )
    request = FileTaskRequest(
        task="请继续优化上一轮任务结果",
        run_id="followup_improve_demo",
        target_path="report.docx",
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "improve",
                "user_feedback": "请继续优化上一轮任务结果",
                "previous_run_id": "run_prev_002",
                "previous_task_summary": "已写入初稿结论",
                "previous_task_request": "把结论写进 report.docx",
                "previous_task_mode": "whitebox_v1",
                "previous_task_family": "transform",
                "previous_task_operation_kind": "write",
                "previous_task_execution_mode": "generic_tool_loop",
                "previous_completed_task": "true",
            }
        },
    )

    messages = runtime._build_messages(request, [], [])
    system = runtime._build_system_prompt(request, [])
    content = messages[-1]["content"]

    assert "用户要求在上一轮文件任务结果基础上继续优化" in content
    assert '"followup_action": "improve"' in content
    assert '"previous_task_request": "把结论写进 report.docx"' in content
    assert '"previous_task_family": "transform"' in content
    assert '"previous_task_execution_mode": "generic_tool_loop"' in content
    assert "同一任务的后续处理回合" in content
    assert "同一任务的后续回合" in system
    assert "可以继续调用工具修正目标文件" in system


def test_file_task_runtime_followup_apply_is_framed_as_same_task_writeback():
    runtime = FileTaskRuntime(
        tool_executor=lambda name, args: "", model_client=lambda **kwargs: {}
    )
    request = FileTaskRequest(
        task="请把上一轮已经给出的建议直接应用到目标文件",
        run_id="followup_apply_demo",
        target_path="report.docx",
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "apply",
                "user_feedback": "请把上一轮已经给出的建议直接应用到目标文件",
                "previous_run_id": "run_prev_003",
                "previous_task_summary": "已给出结构调整和措辞修改建议",
                "previous_task_request": "分析这份建议书，看看有哪些地方需要修改",
                "previous_task_mode": "whitebox_v1",
                "previous_task_family": "analyze",
                "previous_task_execution_mode": "generic_tool_loop",
                "previous_task_output_mode": "hybrid",
                "previous_task_intent_can_apply": "true",
                "previous_task_intent_requires_confirmation": "true",
                "previous_completed_task": "true",
            }
        },
    )

    messages = runtime._build_messages(request, [], [])
    system = runtime._build_system_prompt(request, [])
    content = messages[-1]["content"]

    assert "用户要求把上一轮文件任务中已经给出的建议直接应用到目标文件" in content
    assert '"followup_action": "apply"' in content
    assert '"previous_task_output_mode": "hybrid"' in content
    assert '"previous_task_intent_can_apply": "true"' in content
    assert "同一任务的写回续跑" in system
    assert "这一轮应进入真实写回路径并产生 file.changed" in system


def test_file_task_runtime_classifies_followup_apply_from_previous_hybrid_as_write():
    def fake_model(**kwargs):
        return {"content": "开始应用上一轮建议", "tool_calls": []}

    request = FileTaskRequest(
        task="请直接应用上一轮建议",
        run_id="followup_apply_classification_demo",
        current_file=FileTaskFile(
            path="report.docx", name="report.docx", type="docx", content="现有内容"
        ),
        target_path="report.docx",
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "apply",
                "user_feedback": "请直接应用上一轮建议",
                "previous_task_mode": "whitebox_v1",
                "previous_task_family": "analyze",
                "previous_task_execution_mode": "generic_tool_loop",
                "previous_task_output_mode": "hybrid",
                "previous_task_intent_can_apply": "true",
                "previous_completed_task": "true",
            }
        },
    )

    events = list(
        FileTaskRuntime(
            tool_executor=lambda name, args: "", model_client=fake_model
        ).run(request)
    )
    run_started = events[0]

    assert run_started.payload["request_kind"] == "followup"
    assert run_started.payload["output_mode"] == "write"
    assert run_started.payload["task_family"] == "transform"
    assert run_started.payload["operation_kind"] == "write"
    assert run_started.payload["write_intent"] is True
    assert "followup_action:apply" in run_started.payload["reason_codes"]
    assert "followup_apply_write_intent" in run_started.payload["reason_codes"]


def test_file_task_runtime_diagnostic_question_with_write_words_stays_answer_only():
    request = FileTaskRequest(
        task="为什么这个任务会失败删除这里面所有修改批注",
        run_id="diagnostic_question_write_word_demo",
        current_file=FileTaskFile(
            path="translation.docx",
            name="translation.docx",
            type="docx",
            content="现有内容",
        ),
        target_path="translation.docx",
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "question",
                "user_feedback": "为什么这个任务会失败删除这里面所有修改批注",
                "previous_task_mode": "doc_annotate_bridge",
                "previous_task_family": "annotate",
                "previous_task_execution_mode": "annotate_tool_loop",
                "previous_task_output_mode": "write",
                "previous_completed_task": "true",
            }
        },
    )

    events = list(
        FileTaskRuntime(
            tool_executor=lambda name, args: "",
            model_client=lambda **kwargs: {
                "content": "先解释失败原因。",
                "tool_calls": [],
            },
        ).run(request)
    )
    run_started = events[0]

    assert run_started.payload["request_kind"] == "followup"
    assert run_started.payload["output_mode"] == "answer"
    assert run_started.payload["task_family"] == "analyze"
    assert run_started.payload["operation_kind"] == "read"
    assert run_started.payload["write_intent"] is False
    assert run_started.payload["docx_annotation_request"] is False
    assert "followup_action:question" in run_started.payload["reason_codes"]
    assert "diagnostic_request" in run_started.payload["reason_codes"]
    assert "diagnostic_overrode_write_intent" in run_started.payload["reason_codes"]
    assert (
        run_started.payload["intent_plan"]["recommended_strategy"]
        == "diagnose_then_answer"
    )


def test_file_task_runtime_followup_improve_carries_previous_file_changes_and_no_repeat_insert_guidance():
    runtime = FileTaskRuntime(
        tool_executor=lambda name, args: "", model_client=lambda **kwargs: {}
    )
    request = FileTaskRequest(
        task="请继续优化上一轮任务结果",
        run_id="followup_improve_insert_guard_demo",
        target_path="report.docx",
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "improve",
                "user_feedback": "请继续优化上一轮任务结果",
                "previous_task_summary": "已将工作表“P&L”的 50 行数据写入 Word 表格",
                "previous_task_request": "整理 xlsx 中的财务预测，并加入 docx",
                "previous_completed_task": "true",
                "previous_task_file_changes": [
                    {
                        "path": "report.docx",
                        "operation": "insert_excel_as_docx_table",
                        "sheet": "P&L",
                        "rows_written": 50,
                        "columns_written": 13,
                        "table_title": "利润表 (P&L)",
                    }
                ],
            }
        },
    )

    messages = runtime._build_messages(request, [], [])
    system = runtime._build_system_prompt(request, [])
    content = messages[-1]["content"]

    assert '"previous_task_file_changes": [' in content
    assert '"operation": "insert_excel_as_docx_table"' in content
    assert "不要重复同一插表" in content
    assert "不要再次插入同一张表" in system


def test_file_task_runtime_preserves_reasoning_content_in_followup_model_turn():
    calls = []

    def fake_model(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "content": "我先读取文件。",
                "reasoning_content": "reasoning token",
                "tool_calls": [
                    {
                        "id": "tool_read_1",
                        "name": "parse_file_to_text",
                        "args": {"path": "notes.txt"},
                    }
                ],
            }
        return {"content": "已完成摘要。", "tool_calls": []}

    def fake_executor(tool_name, args):
        assert tool_name == "parse_file_to_text"
        assert args == {"path": "notes.txt", "max_chars": 12000} or args == {
            "path": "notes.txt"
        }
        return "这是一段文件内容。"

    request = FileTaskRequest(
        task="总结这个文件",
        run_id="reasoning_followup",
        files=[
            FileTaskFile(
                path="notes.txt",
                name="notes.txt",
                type="txt",
                content="这是一段文件内容。",
            )
        ],
    )

    events = list(
        FileTaskRuntime(
            tool_executor=fake_executor, model_client=fake_model, max_rounds=2
        ).run(request)
    )

    assert events[-1].type == "run.finished"
    second_messages = calls[1]["messages"]
    model_turns = [
        msg
        for msg in second_messages
        if msg.get("role") == "model" and msg.get("tool_calls")
    ]
    assert model_turns
    assert model_turns[-1]["reasoning_content"] == "reasoning token"
