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


def test_file_task_runtime_readonly_pdf_page_range_ignores_frontend_short_preview():
    calls = []

    def fake_executor(tool_name, args):
        calls.append((tool_name, dict(args)))
        if tool_name == "parse_file_to_text":
            return (
                "[Page 19]\n第十一封信：感性冲动与形式冲动的张力。\n"
                "[Page 20]\n第十四封信：两种冲动在审美状态中相互作用。\n"
                "[Page 21]\n第十五封信：人只有在游戏时才完全是人。"
            )
        return ""

    def fake_model(**kwargs):
        return {
            "content": "第 19-21 页原文段落显示，席勒把游戏冲动置于感性冲动与形式冲动的调和处。",
            "tool_calls": [],
        }

    request = FileTaskRequest(
        task=(
            "请读取 OpenSpace PDF 第 19-21 页，围绕感性冲动、形式冲动、"
            "游戏冲动给出较长原文段落、页码和解读。"
        ),
        run_id="readonly_pdf_explicit_page_window",
        files=[
            FileTaskFile(
                path="schiller.pdf",
                name="schiller.pdf",
                type="pdf",
                content="版权页短预览，不包含第十五封信正文。",
            )
        ],
    )

    events = list(
        FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model).run(
            request
        )
    )

    parse_calls = [args for name, args in calls if name == "parse_file_to_text"]
    assert parse_calls
    assert parse_calls[0]["path"] == "schiller.pdf"
    assert parse_calls[0]["start_page"] == 19
    assert parse_calls[0]["end_page"] == 21
    assert not any(
        event.type == "tool.finished"
        and event.payload.get("tool_name") == "provided_file_context"
        for event in events
    )
    context_event = next(
        event
        for event in events
        if event.type == "tool.finished"
        and event.payload.get("tool_name") == "parse_file_to_text"
    )
    assert "第十五封信" in context_event.payload["result_preview"]


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
    assert check_finished.payload["passed"] is False
    assert check_finished.payload["status"] == "needs_attention"
    assert "临时摘要" in check_finished.payload["summary"]
    assert run_finished.payload["completed_task"] is False
    assert run_finished.payload["runtime"]["readonly_fallback_used"] is True
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


def test_file_task_runtime_readonly_investment_report_fallback_uses_risk_opportunity_analysis():
    responses = [
        {
            "content": "先读取 Word。",
            "tool_calls": [
                {
                    "name": "read_docx_content",
                    "args": {"path": "雷鸟创新-投资建议书.docx"},
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
                        {"text": "公司主营 AI 眼镜，拥有 MicroLED 光波导等核心技术。"},
                        {"text": "本轮融资后估值 18.5 亿元，投资金额 3000 万元。"},
                    ],
                    "tables": [
                        {
                            "rows": [
                                ["年份", "2024", "2025", "2030"],
                                ["全球AI眼镜销量", "234万台", "550万台", "10,000万台"],
                                ["国内实际销量", "5万台", "80万台", "3,000万台"],
                            ]
                        },
                        {
                            "rows": [
                                ["项目", "2025H1", "2024"],
                                ["营业收入", "13,172.52万元", "8,938.61万元"],
                                ["净利润", "-11,500.29万元", "-25,213.18万元"],
                                ["经营活动产生的现金流量净额", "-8,733.63万元", "-22,872万元"],
                                ["毛利率", "21.09%", "-1.12%"],
                            ]
                        },
                        {
                            "rows": [
                                ["前十大客户", "深圳市雷鸟网络传媒有限公司", "占总销售额53.55%"],
                                ["前十大供应商", "惠州TCL移动通信", "占总采购额47.31%"],
                            ]
                        },
                        {
                            "rows": [
                                ["盈利预测", "2027年乐观收入253,875万元", "净利润33,796万元"],
                                ["退出测算", "PS 8倍", "IRR 60%"],
                            ]
                        },
                    ],
                    "total_paragraphs": 2,
                    "total_tables": 4,
                },
                ensure_ascii=False,
            )
        raise AssertionError(f"unexpected tool call: {tool_name}")

    request = FileTaskRequest(
        task="分析这个一级市场投资报告，告诉我有什么风险和投资机会",
        run_id="readonly_investment_report_blank_model",
        files=[
            FileTaskFile(
                path="雷鸟创新-投资建议书.docx",
                name="雷鸟创新-投资建议书.docx",
                type="docx",
            )
        ],
    )

    events = list(
        FileTaskRuntime(tool_executor=fake_executor, model_client=fake_model).run(
            request
        )
    )
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]
    summary = run_finished.payload["summary"]

    assert check_finished.payload["passed"] is False
    assert check_finished.payload["status"] == "needs_attention"
    assert run_finished.payload["completed_task"] is False
    assert run_finished.payload["runtime"]["readonly_fallback_used"] is True
    assert "## 投资风险与机会分析" in summary
    assert "投资机会：" in summary
    assert "主要风险：" in summary
    assert "亏损、现金流和资金消耗仍是首要风险" in summary
    assert "13,172.52万元" in summary
    assert "-11,500.29万元" in summary
    assert "客户和供应商集中度较高" in summary
    assert "建议动作：" in summary
    assert "## 文件内容总结" not in summary


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
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]
    summary = run_finished.payload["summary"]

    assert check_finished.payload["passed"] is False
    assert check_finished.payload["status"] == "needs_attention"
    assert run_finished.payload["completed_task"] is False
    assert run_finished.payload["runtime"]["readonly_fallback_used"] is True
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


def test_file_task_runtime_readonly_argument_improvement_fallback_matches_task():
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
        task="分析这个文章内容，看看有没有值得优化的论点",
        run_id="readonly_argument_improvement_fallback",
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
    check_finished = next(event for event in events if event.type == "check.finished")
    summary = events[-1].payload["summary"]

    assert check_finished.payload["passed"] is False
    assert check_finished.payload["status"] == "needs_attention"
    assert events[-1].payload["completed_task"] is False
    assert events[-1].payload["runtime"]["readonly_fallback_used"] is True
    assert "## 论点优化建议" in summary
    assert "当前核心论点" in summary
    assert "值得优化的论点" in summary
    assert "具体修改建议" in summary
    assert "电子游戏" in summary
    assert "共同生产关系" in summary
    assert "## 文章总结" not in summary
    assert "总体概括" not in summary
    assert "已完成文件读取" not in summary


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
    fallback_step = next(
        event
        for event in events
        if event.type == "step.result"
        and event.payload.get("summary") == fallback_message.payload["result_preview"]
    )
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert run_started.payload["output_mode"] == "answer"
    assert plan_created.payload["summary"] == "准备处理 1 个文件和 1 段选区。"
    assert not any(event.type == "run.error" for event in events)
    assert fallback_message.payload["tool_name"] == "model_message"
    assert fallback_message.payload["model_unavailable"] is True
    assert fallback_step.payload["status"] == "needs_attention"
    assert check_finished.payload["passed"] is False
    assert check_finished.payload["status"] == "needs_attention"
    assert check_finished.payload["runtime"]["execution_path"] == "readonly_fallback"
    assert check_finished.payload["runtime"]["terminal_status"] == "needs_attention"
    assert check_finished.payload["runtime"]["model_unavailable"] is True
    assert check_finished.payload["runtime"]["readonly_fallback_used"] is True
    assert check_finished.payload["runtime"]["planner"] == {
        "backend": "",
        "source": "",
        "policy": "",
        "transport": "",
        "reason": "",
    }
    assert run_finished.payload["completed_task"] is False
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
    assert run_started.payload["intent_plan"]["can_apply"] is True
    assert run_started.payload["intent_plan"]["requires_confirmation"] is False
    assert run_started.payload["intent_plan"]["recommended_strategy"] == "analyze_then_optional_apply"
    assert (
        plan_created.payload["steps"][1]["description"]
        == "模型先读取文件并给出可应用的分析建议；当前轮不默认直接写入原文件。"
    )
    assert check_finished.payload["passed"] is True
    assert check_finished.payload["summary"] == model_answer
    assert run_finished.payload["summary"] == model_answer
    assert run_finished.payload["completed_task"] is True
