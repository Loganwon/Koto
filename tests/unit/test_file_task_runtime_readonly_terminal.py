import json

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_runtime import FileTaskRuntime


def test_file_task_runtime_readonly_summary_surfaces_model_answer():
    model_answer = "文档摘要：这份文档说明了产品规划、市场竞争和销售预测。"

    def fake_model(**kwargs):
        return {"content": model_answer, "tool_calls": []}

    request = FileTaskRequest(
        task="总结这个文档",
        run_id="summary_demo",
        files=[
            FileTaskFile(
                path="雷鸟访谈问题.docx",
                name="雷鸟访谈问题.docx",
                type="docx",
                content="产品和市场规划。未来产品形态、竞争策略、销售预测。",
            )
        ],
    )
    events = list(
        FileTaskRuntime(
            tool_executor=lambda name, args: "", model_client=fake_model
        ).run(request)
    )
    event_types = [event.type for event in events]
    run_started = events[0]
    plan_created = next(event for event in events if event.type == "plan.created")
    model_message = next(
        event for event in events if event.payload.get("tool_name") == "model_message"
    )
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert event_types[0] == "run.started"
    assert "task.classified" in event_types
    assert "plan.checked" in event_types
    assert event_types.index("plan.checked") < event_types.index("plan.created")
    assert run_started.payload["output_mode"] == "answer"
    assert plan_created.payload["summary"] == "准备处理 1 个文件。"
    assert model_message.payload["result_preview"] == model_answer
    assert check_finished.payload["passed"] is True
    assert check_finished.payload["summary"] == "已完成只读任务，没有产生文件写入。"
    assert run_finished.payload["summary"] == model_answer
    assert run_finished.payload["completed_task"] is True


def test_file_task_runtime_readonly_docx_blank_model_gets_visible_fallback_answer():
    responses = [
        {
            "content": "先读取 Word。",
            "tool_calls": [
                {
                    "name": "read_docx_content",
                    "args": {"path": "雷鸟访谈问题.docx"},
                }
            ],
        },
        {"content": "", "tool_calls": []},
        {"content": "", "tool_calls": []},
    ]

    def fake_model(**kwargs):
        return responses.pop(0) if responses else {"content": "", "tool_calls": []}

    def fake_executor(tool_name, args):
        if tool_name == "parse_file_to_text":
            return "雷鸟访谈问题：产品路线、渠道、供应链、融资规划。"
        if tool_name == "read_docx_content":
            return json.dumps(
                {
                    "paragraphs": [
                        {"text": "请说明雷鸟产品路线和新品节奏。", "style": "Normal"},
                        {
                            "text": "请解释渠道策略、供应链风险和融资计划。",
                            "style": "Normal",
                        },
                    ],
                    "tables": [],
                    "total_paragraphs": 2,
                    "total_tables": 0,
                },
                ensure_ascii=False,
            )
        if tool_name == "verify_task_completion":
            return json.dumps(
                {"passed": True, "summary": "已检测到 DOCX 写入。"}, ensure_ascii=False
            )
        raise AssertionError(f"unexpected tool call: {tool_name}")

    request = FileTaskRequest(
        task="分析这个docx",
        run_id="readonly_docx_blank_model",
        files=[
            FileTaskFile(
                path="雷鸟访谈问题.docx",
                name="雷鸟访谈问题.docx",
                type="docx",
            )
        ],
    )
    events = list(
        FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model).run(
            request
        )
    )
    answer_guard = next(
        event
        for event in events
        if event.payload.get("tool_name") == "readonly_answer_guard"
    )
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert "必须直接输出分析结果" in answer_guard.payload["result_preview"]
    assert check_finished.payload["passed"] is True
    assert check_finished.payload["summary"] == "已完成只读任务，没有产生文件写入。"
    assert run_finished.payload["completed_task"] is True
    assert (
        "## 文件内容总结" in run_finished.payload["summary"]
        or "## 文章总结" in run_finished.payload["summary"]
    )
    assert "核心观点" in run_finished.payload["summary"]
    assert "论证脉络" in run_finished.payload["summary"]
    assert "总体概括" in run_finished.payload["summary"]
    assert "文章首先提出" in run_finished.payload["summary"]
    assert "已完成文件读取" not in run_finished.payload["summary"]
    assert "Word 内容包含 2 段文本、0 个表格" not in run_finished.payload["summary"]
    assert "模型未再请求工具调用" not in run_finished.payload["summary"]


def test_file_task_runtime_readonly_article_summary_fallback_is_not_read_log():
    responses = [
        {
            "content": "先读取 Word。",
            "tool_calls": [
                {
                    "name": "read_docx_content",
                    "args": {"path": "humanise!_revised.docx"},
                }
            ],
        },
        {"content": "", "tool_calls": []},
    ]

    def fake_model(**kwargs):
        return responses.pop(0) if responses else {"content": "", "tool_calls": []}

    def fake_executor(tool_name, args):
        if tool_name == "read_docx_content":
            return json.dumps(
                {
                    "paragraphs": [
                        {
                            "text": "在艺术与科技的视阈下，我今天想要讨论一个有关身体的本体论命题，即技术如何改变艺术与身体的关系。我的论点是，在艺术性已获公认的电子游戏中，艺术与技术不是工具关系，而是共同生产关系。"
                        },
                        {
                            "text": "谈论这个的原因来自如今主流艺术-科技框架的制约。本雅明开创的思路将艺术与技术的关系视为单向因果：技术作用于艺术，改变接收方式、创作工具乃至灵晕。"
                        },
                        {
                            "text": "Vivian Sobchack 在 The Address of the Eye 中提出一种激进的电影现象学：电影本身有视觉主体性。电影身体观看世界，观众身体观看电影身体的观看。"
                        },
                        {
                            "text": "她诊断 1947 年的《湖中女郎》为失败，因为这部电影试图取消两个观看位置的分立，而这种分立恰恰是电影性观看的成立条件。"
                        },
                    ],
                    "tables": [],
                    "total_paragraphs": 4,
                    "total_tables": 0,
                },
                ensure_ascii=False,
            )
        raise AssertionError(f"unexpected tool call: {tool_name}")

    request = FileTaskRequest(
        task="总结这个文章",
        run_id="readonly_article_summary_fallback",
        files=[
            FileTaskFile(
                path="humanise!_revised.docx",
                name="humanise!_revised.docx",
                type="docx",
            )
        ],
    )

    events = list(
        FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model).run(
            request
        )
    )
    run_finished = events[-1]
    summary = run_finished.payload["summary"]

    assert run_finished.payload["completed_task"] is True
    assert "## 文章总结" in summary
    assert "总体概括" in summary
    assert "文章首先提出" in summary
    assert "核心观点" in summary
    assert "论证脉络" in summary
    assert "补充要点" in summary
    assert "艺术" in summary
    assert "技术" in summary
    assert "身体" in summary
    assert "电子游戏" in summary
    assert "已完成文件读取" not in summary
    assert "已读取内容：" not in summary
    assert "Word 内容包含" not in summary


def test_file_task_runtime_context_step_keeps_parse_file_to_text_results_as_snippets():
    def fake_executor(tool_name, args):
        if tool_name == "parse_file_to_text":
            return f"内容来自 {args['path']}"
        raise AssertionError(f"unexpected tool call: {tool_name}")

    def fake_model(**kwargs):
        return {"content": "已完成总结。", "tool_calls": []}

    request = FileTaskRequest(
        task="总结这两个文件",
        run_id="context_snippet_parse_demo",
        files=[
            FileTaskFile(
                path="financial-model.xlsx", name="financial-model.xlsx", type="xlsx"
            ),
            FileTaskFile(path="report.docx", name="report.docx", type="docx"),
        ],
    )

    events = list(
        FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model).run(
            request
        )
    )
    context_result = next(
        event
        for event in events
        if event.type == "step.result" and event.step_id == "context"
    )

    assert context_result.payload["status"] == "completed"
    assert context_result.payload["snippet_count"] == 2
    assert [item["source"] for item in context_result.payload["snippets"]] == [
        "financial-model.xlsx",
        "report.docx",
    ]
    assert context_result.payload["snippets"][0]["preview"].startswith(
        "内容来自 financial-model.xlsx"
    )


def test_file_task_runtime_readonly_model_unavailable_summarizes_explicit_context():
    def unavailable_model(**kwargs):
        raise RuntimeError("cloud model unavailable")

    request = FileTaskRequest(
        task="将内容总结",
        run_id="readonly_context_fallback",
        selection="客户\t产品\t数量\n杭州新汇鑫光电有限公司\tLASER\t1",
        selection_source="雷鸟访谈问题.docx",
        files=[
            FileTaskFile(
                path="AI Agent.pptx",
                name="AI Agent.pptx",
                type="pptx",
                content="第一页介绍 AI Agent 的目标。第二页说明工具调用和任务执行流程。",
            )
        ],
    )

    events = list(
        FileTaskRuntime(
            tool_executor=lambda name, args: "", model_client=unavailable_model
        ).run(request)
    )
    run_started = events[0]
    plan_created = next(event for event in events if event.type == "plan.created")
    fallback_message = next(event for event in events if event.payload.get("fallback"))
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert run_started.payload["output_mode"] == "answer"
    assert plan_created.payload["summary"] == "准备处理 1 个文件和 1 段选区。"
    assert not any(event.type == "run.error" for event in events)
    assert fallback_message.payload["tool_name"] == "model_message"
    assert fallback_message.payload["model_unavailable"] is True
    assert check_finished.payload["passed"] is True
    assert check_finished.payload["status"] == "context_summary_fallback"
    assert check_finished.payload["runtime"] == {
        "execution_path": "readonly_fallback",
        "terminal_status": "context_summary_fallback",
        "model_unavailable": True,
        "readonly_fallback_used": True,
        "planner": {
            "backend": "",
            "source": "",
            "policy": "",
            "transport": "",
            "reason": "",
        },
    }
    assert run_finished.payload["completed_task"] is True
    assert run_finished.payload["runtime"] == check_finished.payload["runtime"]
    assert (
        "## 文件内容总结" in run_finished.payload["summary"]
        or "## 文章总结" in run_finished.payload["summary"]
    )
    assert "核心观点" in run_finished.payload["summary"]
    assert "论证脉络" in run_finished.payload["summary"]
    assert "模型暂不可用" in run_finished.payload["summary"]
    assert "已读取" in run_finished.payload["summary"]
    assert "AI Agent.pptx" in run_finished.payload["summary"]


def test_file_task_runtime_treats_advisory_analysis_about_modifications_as_hybrid_not_write():
    model_answer = "建议先调整市场进入顺序，再补充竞争壁垒与财务假设。"

    def fake_model(**kwargs):
        return {"content": model_answer, "tool_calls": []}

    request = FileTaskRequest(
        task="分析这个投资建议书，看看有哪些大方向需要修改的地方",
        run_id="advisory_analysis_demo",
        target_path="雷鸟创新-投资建议书.docx",
        files=[
            FileTaskFile(
                path="雷鸟创新-投资建议书.docx",
                name="雷鸟创新-投资建议书.docx",
                type="docx",
                target=True,
                content="业务概览、竞争格局、融资计划。",
            )
        ],
    )

    events = list(
        FileTaskRuntime(
            tool_executor=lambda name, args: "", model_client=fake_model, max_rounds=2
        ).run(request)
    )
    run_started = events[0]
    plan_created = next(event for event in events if event.type == "plan.created")
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert run_started.payload["output_mode"] == "hybrid"
    assert run_started.payload["task_family"] == "analyze"
    assert run_started.payload["operation_kind"] == "read"
    assert run_started.payload["write_intent"] is False
    assert (
        plan_created.payload["steps"][1]["description"]
        == "模型先读取文件并给出可应用的分析建议；当前轮不默认直接写入原文件。"
    )
    assert check_finished.payload["passed"] is True
    assert check_finished.payload["summary"] == model_answer
    assert run_finished.payload["summary"] == model_answer
    assert run_finished.payload["completed_task"] is True
