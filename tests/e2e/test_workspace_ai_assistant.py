"""
Playwright smoke tests for the workspace AI assistant task flow.

These tests exercise the real browser UI while mocking the whitebox task-stream
response so regressions in send-message wiring, task-card rendering, and route
payload shape are caught without depending on a live model.
"""

from __future__ import annotations

import json

import pytest

PAGE_TIMEOUT = 15_000
THINK_SHORT = 400
THINK_MEDIUM = 800

_BENIGN = [
    "WebSocket",
    "ws://",
    "wss://",
    "net::ERR_",
    "favicon.ico",
    "API key",
    "api key",
    "Failed to load resource",
    "ERR_CONNECTION_REFUSED",
]


def _is_benign(msg: str) -> bool:
    return any(pattern in msg for pattern in _BENIGN)


def _real_errors(errors: list[str]) -> list[str]:
    return [err for err in errors if not _is_benign(err)]


def _goto(page, url: str):
    try:
        return page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
    except Exception:
        return None


def _open_workspace_ai(page, base_url: str):
    resp = _goto(page, f"{base_url}/")
    page.wait_for_timeout(THINK_MEDIUM)
    if resp and resp.status >= 400:
        pytest.skip("Workspace editor page not available")
    page.wait_for_function(
        """() => window.WA
            && typeof window.WA.openInMainView === 'function'
            && typeof window.WA.newAiSession === 'function'""",
        timeout=PAGE_TIMEOUT,
    )
    page.evaluate("""() => window.WA.openInMainView()""")
    page.evaluate("""() => window.WA.newAiSession({ toast: false, focus: false })""")
    page.locator("#wa-user-input").wait_for(state="visible", timeout=PAGE_TIMEOUT)
    return resp


def _sse_body(events: list[dict]) -> str:
    return "".join(
        f"data: {json.dumps(event, ensure_ascii=False)}\n\n" for event in events
    )


def _mock_file_task_route(page):
    page.route(
        "**/api/workspace/ai/route-intent",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"ok": True, "route": "file_task", "reason": "mocked file task"},
                ensure_ascii=False,
            ),
        ),
    )


@pytest.mark.e2e
class TestWorkspaceAiAssistantSmoke:
    def test_workspace_ai_panel_shell_loads(
        self, e2e_page, console_errors, e2e_base_url
    ):
        _open_workspace_ai(e2e_page, e2e_base_url)

        e2e_page.locator("#wa-ai").wait_for(timeout=PAGE_TIMEOUT)
        e2e_page.locator("#wa-user-input").wait_for(timeout=PAGE_TIMEOUT)
        e2e_page.locator("#wa-send-btn").wait_for(timeout=PAGE_TIMEOUT)
        e2e_page.locator("#wa-ai-messages").wait_for(timeout=PAGE_TIMEOUT)

        assert e2e_page.locator("#wa-ai-route-info").count() > 0
        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_model_toggle_is_unique_and_switches_modes(
        self, e2e_page, console_errors, e2e_base_url
    ):
        captured_modes: list[str] = []

        def fulfill_model_switch(route):
            try:
                payload = json.loads(route.request.post_data or "{}")
            except json.JSONDecodeError:
                payload = {}
            captured_modes.append(str(payload.get("mode") or ""))
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "mode": payload.get("mode")}),
            )

        e2e_page.route("**/api/local-model/switch", fulfill_model_switch)
        _open_workspace_ai(e2e_page, e2e_base_url)

        deepseek = e2e_page.locator("#wa-model-mode-deepseek-btn")
        local = e2e_page.locator("#wa-model-mode-local-btn")
        assert e2e_page.locator("#wa-model-mode-toggle").count() == 1
        assert deepseek.count() == 1
        assert local.count() == 1

        # The selected mode is persisted between sessions.  Re-selecting the
        # already active option is deliberately a no-op, so the request
        # contract must depend on the actual initial state rather than test
        # process history.
        initially_deepseek = deepseek.evaluate(
            "(element) => element.classList.contains('active')"
        )
        deepseek.click()
        e2e_page.wait_for_function(
            """() => document.querySelector('#wa-model-mode-deepseek-btn')
                ?.classList.contains('active')""",
            timeout=PAGE_TIMEOUT,
        )
        local.click()
        e2e_page.wait_for_function(
            """() => document.querySelector('#wa-model-mode-local-btn')
                ?.classList.contains('active')""",
            timeout=PAGE_TIMEOUT,
        )

        expected_modes = (["deepseek"] if not initially_deepseek else []) + ["local"]
        assert captured_modes == expected_modes
        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_ai_send_message_renders_mocked_whitebox_task_card(
        self, e2e_page, console_errors, e2e_base_url
    ):
        captured = {}
        sse_events = [
            {
                "type": "run.started",
                "run_id": "browser_smoke",
                "seq": 1,
                "payload": {"mode": "whitebox_v1"},
            },
            {
                "type": "plan.created",
                "run_id": "browser_smoke",
                "seq": 2,
                "payload": {"summary": "准备处理任务。"},
            },
            {
                "type": "step.started",
                "run_id": "browser_smoke",
                "seq": 3,
                "step_id": "execute",
                "payload": {"title": "处理中"},
            },
            {
                "type": "run.finished",
                "run_id": "browser_smoke",
                "seq": 4,
                "payload": {"summary": "模拟任务已完成", "completed_task": True},
            },
        ]

        def fulfill_task_stream(route):
            body = route.request.post_data or "{}"
            try:
                captured["payload"] = json.loads(body)
            except Exception:
                captured["payload"] = {}
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=_sse_body(sse_events),
            )

        _mock_file_task_route(e2e_page)
        e2e_page.route("**/api/editor/ai/task-stream", fulfill_task_stream)

        _open_workspace_ai(e2e_page, e2e_base_url)

        e2e_page.locator("#wa-user-input").fill("总结当前文件")
        e2e_page.locator("#wa-send-btn").click()

        task_card = e2e_page.locator(".wa-task-run").first
        task_card.wait_for(timeout=PAGE_TIMEOUT)
        e2e_page.wait_for_timeout(THINK_SHORT)

        summary = task_card.locator("[data-role='summary']").inner_text()
        assert "模拟任务已完成" in summary
        assert captured["payload"]["task"] == "总结当前文件"
        assert isinstance(captured["payload"].get("history"), list)
        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_ai_task_card_renders_terminal_process_in_browser(
        self, e2e_page, console_errors, e2e_base_url
    ):
        sse_events = [
            {
                "type": "run.started",
                "run_id": "browser_step_result",
                "seq": 1,
                "payload": {"mode": "whitebox_v1"},
            },
            {
                "type": "plan.created",
                "run_id": "browser_step_result",
                "seq": 2,
                "payload": {"summary": "准备处理任务。"},
            },
            {
                "type": "step.started",
                "run_id": "browser_step_result",
                "seq": 3,
                "step_id": "context",
                "payload": {"title": "读取显式上下文"},
            },
            {
                "type": "step.result",
                "run_id": "browser_step_result",
                "seq": 4,
                "step_id": "context",
                "payload": {
                    "title": "读取显式上下文",
                    "summary": "已整理 1 份上下文片段。",
                    "status": "completed",
                    "snippet_count": 1,
                },
            },
            {
                "type": "step.started",
                "run_id": "browser_step_result",
                "seq": 5,
                "step_id": "execute",
                "payload": {"title": "模型规划并调用工具"},
            },
            {
                "type": "step.result",
                "run_id": "browser_step_result",
                "seq": 6,
                "step_id": "execute",
                "payload": {
                    "title": "模型工具执行完成",
                    "summary": "已完成第 1 轮工具执行。",
                    "status": "completed",
                    "round": 1,
                },
            },
            {
                "type": "run.finished",
                "run_id": "browser_step_result",
                "seq": 7,
                "payload": {"summary": "模拟任务已完成", "completed_task": True},
            },
        ]

        _mock_file_task_route(e2e_page)
        e2e_page.route(
            "**/api/editor/ai/task-stream",
            lambda route: route.fulfill(
                status=200, content_type="text/event-stream", body=_sse_body(sse_events)
            ),
        )

        _open_workspace_ai(e2e_page, e2e_base_url)

        e2e_page.locator("#wa-user-input").fill("总结当前文件")
        e2e_page.locator("#wa-send-btn").click()

        task_card = e2e_page.locator(".wa-task-run").first
        task_card.wait_for(timeout=PAGE_TIMEOUT)
        e2e_page.wait_for_function(
            """() => {
                const card = document.querySelector('.wa-task-run');
                const text = card && (card.textContent || '');
                return /模拟任务已完成/.test(text) && /执行过程/.test(text) && /完成核验/.test(text);
            }""",
            timeout=PAGE_TIMEOUT,
        )

        card_text = task_card.evaluate("(el) => el.textContent || ''")
        assert "执行过程" in card_text
        assert "读取文件" in card_text
        assert "完成核验" in card_text
        assert "模拟任务已完成" in card_text
        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    @pytest.mark.parametrize(
        ("terminal_status", "expected_title", "expected_detail"),
        [
            ("needs_attention", "需处理", "当前任务未完成"),
            ("context_summary_fallback", "需复核", "临时摘要"),
        ],
    )
    def test_workspace_ai_task_card_renders_incomplete_terminal_states(
        self,
        e2e_page,
        console_errors,
        e2e_base_url,
        terminal_status,
        expected_title,
        expected_detail,
    ):
        summary_text = "模型未返回完整答案，当前只保留临时结果。"
        sse_events = [
            {
                "type": "run.started",
                "run_id": f"browser_{terminal_status}",
                "seq": 1,
                "payload": {"mode": "whitebox_v1"},
            },
            {
                "type": "plan.created",
                "run_id": f"browser_{terminal_status}",
                "seq": 2,
                "payload": {"summary": "准备处理任务。"},
            },
            {
                "type": "run.finished",
                "run_id": f"browser_{terminal_status}",
                "seq": 3,
                "payload": {
                    "summary": summary_text,
                    "completed_task": False,
                    "runtime": {"terminal_status": terminal_status},
                },
            },
        ]

        _mock_file_task_route(e2e_page)
        e2e_page.route(
            "**/api/editor/ai/task-stream",
            lambda route: route.fulfill(
                status=200, content_type="text/event-stream", body=_sse_body(sse_events)
            ),
        )

        _open_workspace_ai(e2e_page, e2e_base_url)

        e2e_page.locator("#wa-user-input").fill("分析文件但模型返回不完整")
        e2e_page.locator("#wa-send-btn").click()

        task_card = e2e_page.locator(".wa-task-run").first
        task_card.wait_for(timeout=PAGE_TIMEOUT)
        e2e_page.wait_for_function(
            """([expectedTitle, expectedDetail, terminalStatus]) => {
                const card = document.querySelector('.wa-task-run');
                const text = card && (card.textContent || '');
                return !!card
                    && card.dataset.taskCompleted === 'false'
                    && card.dataset.taskTerminalStatus === terminalStatus
                    && text.includes(expectedTitle)
                    && text.includes(expectedDetail)
                    && !/任务完成/.test(text);
            }""",
            arg=[expected_title, expected_detail, terminal_status],
            timeout=PAGE_TIMEOUT,
        )

        card_text = task_card.evaluate("(el) => el.textContent || ''")
        assert expected_title in card_text
        assert expected_detail in card_text
        assert "任务完成" not in card_text
        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_ai_task_card_renders_supervisor_audit(
        self, e2e_page, console_errors, e2e_base_url
    ):
        supervisor_audit = {
            "version": "file_task_supervisor_audit_v1",
            "status": "warning",
            "risk_level": "low",
            "summary": "监管检查发现需要保守处理的风险，任务可继续但会加强核验。",
            "confidence": 0.42,
            "execution_allowed": True,
            "review_recommended": True,
            "warnings": ["任务识别置信度偏低，执行时需要保守处理。"],
            "required_actions": ["优先读取显式上下文，避免把模糊意图升级为写入。"],
            "reason_codes": ["supervisor_audit:v1", "low_classification_confidence"],
        }
        workflow_state = {
            "mainline": {
                "task_family": "analyze",
                "operation_kind": "read",
                "output_mode": "answer",
                "write_intent": False,
            },
            "supervisor_audit": supervisor_audit,
            "task_plan": {"mainline_locked": True, "steps": []},
        }
        sse_events = [
            {
                "type": "run.started",
                "run_id": "browser_supervisor",
                "seq": 1,
                "payload": {
                    "mode": "whitebox_v1",
                    "workflow_state": workflow_state,
                    "supervisor_audit": supervisor_audit,
                },
            },
            {
                "type": "supervisor.status",
                "run_id": "browser_supervisor",
                "seq": 2,
                "step_id": "plan",
                "payload": {
                    "stage": "planned",
                    "summary": supervisor_audit["summary"],
                    "mainline_locked": True,
                    "workflow_state": workflow_state,
                    "supervisor_audit": supervisor_audit,
                },
            },
            {
                "type": "task.classified",
                "run_id": "browser_supervisor",
                "seq": 3,
                "step_id": "plan",
                "payload": {
                    "classification": {
                        "task_family": "analyze",
                        "operation_kind": "read",
                        "output_mode": "answer",
                        "write_intent": False,
                        "confidence": 0.42,
                        "reason_codes": ["low_classification_confidence"],
                    },
                    "workflow_state": workflow_state,
                    "supervisor_audit": supervisor_audit,
                },
            },
            {
                "type": "run.finished",
                "run_id": "browser_supervisor",
                "seq": 4,
                "payload": {
                    "summary": "模拟监管任务已完成",
                    "completed_task": True,
                    "workflow_state": workflow_state,
                    "supervisor_audit": supervisor_audit,
                },
            },
        ]

        _mock_file_task_route(e2e_page)
        e2e_page.route(
            "**/api/editor/ai/task-stream",
            lambda route: route.fulfill(
                status=200, content_type="text/event-stream", body=_sse_body(sse_events)
            ),
        )

        _open_workspace_ai(e2e_page, e2e_base_url)

        e2e_page.locator("#wa-user-input").fill("总结当前文件")
        e2e_page.locator("#wa-send-btn").click()

        task_card = e2e_page.locator(".wa-task-run").first
        task_card.wait_for(timeout=PAGE_TIMEOUT)
        e2e_page.wait_for_function(
            """() => {
                const card = document.querySelector('.wa-task-run');
                const text = card && (card.textContent || '');
                return /监管需关注/.test(text) && /置信度 42%/.test(text) && /避免把模糊意图升级为写入/.test(text);
            }""",
            timeout=PAGE_TIMEOUT,
        )

        card_text = task_card.evaluate("(el) => el.textContent || ''")
        assert "监管需关注" in card_text
        assert "置信度 42%" in card_text
        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_ai_task_card_shows_refresh_state_when_file_changes(
        self, e2e_page, console_errors, e2e_base_url
    ):
        open_counts = {"report.txt": 0}

        def fulfill_open_file(route):
            body = route.request.post_data or "{}"
            try:
                payload = json.loads(body)
            except Exception:
                payload = {}
            requested_path = str(payload.get("path") or "report.txt")
            open_counts[requested_path] = open_counts.get(requested_path, 0) + 1
            version = open_counts[requested_path]
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "file_id": "browser_report_txt",
                        "file_type": "text",
                        "file_name": requested_path.split("/")[-1] or "report.txt",
                        "temp_path": requested_path,
                        "data": f"Mock content version {version}",
                    },
                    ensure_ascii=False,
                ),
            )

        sse_events = [
            {
                "type": "run.started",
                "run_id": "browser_refresh",
                "seq": 1,
                "payload": {"mode": "whitebox_v1"},
            },
            {
                "type": "plan.created",
                "run_id": "browser_refresh",
                "seq": 2,
                "payload": {"summary": "准备刷新文件。"},
            },
            {
                "type": "step.started",
                "run_id": "browser_refresh",
                "seq": 3,
                "step_id": "execute",
                "payload": {"title": "模型规划并调用工具"},
            },
            {
                "type": "file.changed",
                "run_id": "browser_refresh",
                "seq": 4,
                "step_id": "execute",
                "payload": {
                    "path": "report.txt",
                    "file_path": "report.txt",
                    "file_type": "txt",
                    "operation": "annotate_file",
                    "summary": "已更新 report.txt。",
                    "annotations_added": 1,
                    "supported": True,
                },
            },
            {
                "type": "step.result",
                "run_id": "browser_refresh",
                "seq": 5,
                "step_id": "execute",
                "payload": {
                    "title": "模型工具执行完成",
                    "summary": "已写回 report.txt 并刷新前端视图。",
                    "status": "completed",
                    "file_change_count": 1,
                    "file_changes": [
                        {
                            "path": "report.txt",
                            "operation": "annotate_file",
                            "summary": "已更新 report.txt。",
                        }
                    ],
                },
            },
            {
                "type": "run.finished",
                "run_id": "browser_refresh",
                "seq": 6,
                "payload": {"summary": "模拟刷新已完成", "completed_task": True},
            },
        ]

        _mock_file_task_route(e2e_page)
        e2e_page.route("**/api/v1/workspace/open_file_by_path", fulfill_open_file)
        e2e_page.route(
            "**/api/editor/ai/task-stream",
            lambda route: route.fulfill(
                status=200, content_type="text/event-stream", body=_sse_body(sse_events)
            ),
        )

        _open_workspace_ai(e2e_page, e2e_base_url)

        e2e_page.evaluate("""() => window.WA.openWorkspaceFile('report.txt')""")
        e2e_page.wait_for_function(
            """() => {
                const el = document.getElementById('wa-file-name');
                return !!el && /report\.txt/.test(el.textContent || '');
            }""",
            timeout=PAGE_TIMEOUT,
        )

        e2e_page.locator("#wa-user-input").fill("处理当前文件")
        e2e_page.locator("#wa-send-btn").click()

        task_card = e2e_page.locator(".wa-task-run").first
        task_card.wait_for(timeout=PAGE_TIMEOUT)
        for _ in range(30):
            if open_counts.get("report.txt", 0) >= 2:
                break
            e2e_page.wait_for_timeout(250)

        assert open_counts.get("report.txt", 0) >= 2
        card_text = task_card.evaluate("(el) => el.textContent || ''")
        assert "report.txt" in card_text
        assert "模拟刷新已完成" in card_text
        assert "已刷新" not in card_text
        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_ai_history_survives_file_switch_within_runtime_session(
        self, e2e_page, console_errors, e2e_base_url
    ):
        captured = {"payloads": []}

        def fulfill_open_file(route):
            body = route.request.post_data or "{}"
            try:
                payload = json.loads(body)
            except Exception:
                payload = {}
            requested_path = str(payload.get("path") or "untitled.txt")
            file_name = requested_path.split("/")[-1] or "untitled.txt"
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "file_id": f"browser_{file_name.replace('.', '_')}",
                        "file_type": "text",
                        "file_name": file_name,
                        "temp_path": requested_path,
                        "data": f"Mock content for {file_name}",
                    },
                    ensure_ascii=False,
                ),
            )

        def fulfill_task_stream(route):
            body = route.request.post_data or "{}"
            try:
                payload = json.loads(body)
            except Exception:
                payload = {}
            captured["payloads"].append(payload)
            idx = len(captured["payloads"])
            summary = f"模拟任务{idx}已完成"
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=_sse_body(
                    [
                        {
                            "type": "run.started",
                            "run_id": f"browser_smoke_{idx}",
                            "seq": 1,
                            "payload": {"mode": "whitebox_v1"},
                        },
                        {
                            "type": "plan.created",
                            "run_id": f"browser_smoke_{idx}",
                            "seq": 2,
                            "payload": {"summary": "准备处理任务。"},
                        },
                        {
                            "type": "run.finished",
                            "run_id": f"browser_smoke_{idx}",
                            "seq": 3,
                            "payload": {"summary": summary, "completed_task": True},
                        },
                    ]
                ),
            )

        _mock_file_task_route(e2e_page)
        e2e_page.route("**/api/v1/workspace/open_file_by_path", fulfill_open_file)
        e2e_page.route("**/api/editor/ai/task-stream", fulfill_task_stream)

        _open_workspace_ai(e2e_page, e2e_base_url)

        e2e_page.evaluate("""() => window.WA.openWorkspaceFile('doc-a.txt')""")
        e2e_page.wait_for_function(
            """() => {
                const el = document.getElementById('wa-file-name');
                return !!el && /doc-a\.txt/.test(el.textContent || '');
            }""",
            timeout=PAGE_TIMEOUT,
        )

        e2e_page.locator("#wa-user-input").fill("先分析文档A")
        e2e_page.locator("#wa-send-btn").click()
        e2e_page.wait_for_function(
            """() => {
                const nodes = Array.from(document.querySelectorAll('.wa-task-run [data-role="summary"]'));
                return nodes.some((node) => /模拟任务1已完成/.test(node.textContent || ''));
            }""",
            timeout=PAGE_TIMEOUT,
        )
        e2e_page.wait_for_function(
            """() => {
                const stepNodes = Array.from(document.querySelectorAll('.wa-task-run [data-role="plan"]'));
                return stepNodes.some((node) => /准备处理任务。/.test(node.textContent || ''));
            }""",
            timeout=PAGE_TIMEOUT,
        )

        e2e_page.evaluate("""() => window.WA.openWorkspaceFile('doc-b.txt')""")
        e2e_page.wait_for_function(
            """() => {
                const el = document.getElementById('wa-file-name');
                return !!el && /doc-b\.txt/.test(el.textContent || '');
            }""",
            timeout=PAGE_TIMEOUT,
        )

        messages_text = e2e_page.locator("#wa-ai-messages").inner_text()
        assert "先分析文档A" in messages_text
        assert "模拟任务1已完成" in messages_text
        assert e2e_page.locator(".wa-task-run").count() >= 1
        process = e2e_page.locator(".wa-task-run [data-role='process']").first
        assert "执行过程" in process.inner_text()

        e2e_page.locator("#wa-user-input").fill("继续基于刚才的结论处理文档B")
        e2e_page.locator("#wa-send-btn").click()
        e2e_page.wait_for_function(
            """() => {
                const nodes = Array.from(document.querySelectorAll('.wa-task-run [data-role="summary"]'));
                return nodes.some((node) => /模拟任务2已完成/.test(node.textContent || ''));
            }""",
            timeout=PAGE_TIMEOUT,
        )

        assert len(captured["payloads"]) >= 2
        first_payload = captured["payloads"][0]
        second_payload = captured["payloads"][1]
        second_history = second_payload.get("history") or []

        assert first_payload.get("session_id")
        assert second_payload.get("session_id") == first_payload.get("session_id")
        assert any(
            item.get("role") == "user" and item.get("content") == "先分析文档A"
            for item in second_history
        )
        assert any(
            item.get("role") == "assistant" and item.get("content") == "模拟任务1已完成"
            for item in second_history
        )
        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_ai_completed_task_persists_and_restores_final_answer_last(
        self, e2e_page, console_errors, e2e_base_url
    ):
        summary_text = "browser final answer is last"
        sse_events = [
            {
                "type": "run.started",
                "run_id": "browser_history_restore",
                "seq": 1,
                "payload": {"mode": "whitebox_v1"},
            },
            {
                "type": "plan.created",
                "run_id": "browser_history_restore",
                "seq": 2,
                "payload": {"summary": "准备处理任务。"},
            },
            {
                "type": "step.started",
                "run_id": "browser_history_restore",
                "seq": 3,
                "step_id": "execute",
                "payload": {"title": "执行处理"},
            },
            {
                "type": "step.result",
                "run_id": "browser_history_restore",
                "seq": 4,
                "step_id": "execute",
                "payload": {
                    "title": "执行处理",
                    "summary": "步骤完成，结果见总结与回答。",
                    "status": "completed",
                },
            },
            {
                "type": "run.finished",
                "run_id": "browser_history_restore",
                "seq": 5,
                "payload": {
                    "summary": summary_text,
                    "completed_task": True,
                    "status": "completed",
                },
            },
        ]

        _mock_file_task_route(e2e_page)
        e2e_page.route(
            "**/api/editor/ai/task-stream",
            lambda route: route.fulfill(
                status=200, content_type="text/event-stream", body=_sse_body(sse_events)
            ),
        )

        _open_workspace_ai(e2e_page, e2e_base_url)
        session_id = e2e_page.evaluate(
            """() => window._waSession && window._waSession()"""
        )
        assert session_id and not str(session_id).startswith("workspace_runtime_")

        e2e_page.locator("#wa-user-input").fill("生成一份任务总结")
        e2e_page.locator("#wa-send-btn").click()
        e2e_page.wait_for_function(
            """(summaryText) => {
                const summary = document.querySelector('.wa-task-run:not([data-history-snapshot="true"]) [data-role="summary"]');
                const report = summary && summary.querySelector('[data-role="final-report"]');
                return !!report
                    && report.textContent.includes(summaryText)
                    && summary.lastElementChild === report;
            }""",
            arg=summary_text,
            timeout=PAGE_TIMEOUT,
        )

        persisted = None
        for _ in range(30):
            persisted = e2e_page.evaluate(
                """async ([sessionId, summaryText]) => {
                    const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, { cache: 'no-store' });
                    if (!response.ok) return null;
                    const data = await response.json();
                    const history = Array.isArray(data.history) ? data.history : [];
                    const assistant = history.find((entry) => {
                        const parts = Array.isArray(entry.parts) ? entry.parts.join('\\n') : '';
                        return String(entry.role || '').toLowerCase() === 'model'
                            && String(parts || entry.content || '').includes(summaryText);
                    });
                    return assistant ? { schema: data.schema_version, entry_schema: assistant.schema_version, has_structure: !!assistant.test_structure } : null;
                }""",
                [session_id, summary_text],
            )
            if (
                persisted
                and persisted.get("schema") == 2
                and persisted.get("entry_schema") == 2
                and persisted.get("has_structure")
            ):
                break
            e2e_page.wait_for_timeout(250)

        assert persisted
        assert persisted["schema"] == 2
        assert persisted["entry_schema"] == 2
        assert persisted["has_structure"] is True

        _goto(e2e_page, f"{e2e_base_url}/")
        e2e_page.wait_for_function(
            """() => window.WA
                && typeof window.WA.openInMainView === 'function'
                && typeof window.WA.openAiSession === 'function'""",
            timeout=PAGE_TIMEOUT,
        )
        e2e_page.evaluate("""() => window.WA.openInMainView()""")
        e2e_page.evaluate(
            """(sessionId) => window.WA.openAiSession(sessionId, { force: true })""",
            session_id,
        )
        e2e_page.wait_for_function(
            """(summaryText) => {
                const host = document.querySelector('.wa-task-report-turn');
                const process = host && host.querySelector('.wa-task-process-report');
                const answer = host && host.querySelector('.wa-task-final-answer');
                if (!host || !process || !answer) return false;
                const children = Array.from(host.children);
                return answer.textContent.includes(summaryText)
                    && children.indexOf(process) >= 0
                    && children.indexOf(answer) > children.indexOf(process)
                    && host.lastElementChild === answer;
            }""",
            arg=summary_text,
            timeout=PAGE_TIMEOUT,
        )

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_ai_multichart_artifacts_render_as_grid_and_guard_is_readable(
        self, e2e_page, console_errors, e2e_base_url
    ):
        chart_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+tm0YAAAAASUVORK5CYII="
        final_summary = "仍有生成图表未插入 DOCX：chart2_product_mix.png"
        sse_events = [
            {
                "type": "run.started",
                "run_id": "browser_multichart_guard",
                "seq": 1,
                "payload": {"mode": "whitebox_v1"},
            },
            {
                "type": "plan.created",
                "run_id": "browser_multichart_guard",
                "seq": 2,
                "payload": {"summary": "准备生成多张财务图表并写入 Word。"},
            },
            {
                "type": "step.started",
                "run_id": "browser_multichart_guard",
                "seq": 3,
                "step_id": "execute",
                "payload": {"title": "执行代码生成图表"},
            },
            {
                "type": "tool.finished",
                "run_id": "browser_multichart_guard",
                "seq": 4,
                "step_id": "execute",
                "payload": {
                    "tool_name": "run_python_code",
                    "success": True,
                    "result_preview": "已生成 2 张图表",
                    "artifacts": [
                        {
                            "kind": "image",
                            "name": "chart1_revenue_profit_trend.png",
                            "mime_type": "image/png",
                            "data": chart_png,
                        },
                        {
                            "kind": "image",
                            "name": "chart2_product_mix.png",
                            "mime_type": "image/png",
                            "data": chart_png,
                        },
                        {
                            "kind": "image",
                            "name": "chart2_product_mix.png",
                            "mime_type": "image/png",
                            "data": chart_png,
                        },
                    ],
                },
            },
            {
                "type": "tool.finished",
                "run_id": "browser_multichart_guard",
                "seq": 5,
                "step_id": "execute",
                "payload": {
                    "tool_name": "image_insert_guard",
                    "success": False,
                    "result_preview": final_summary,
                    "pending_image_count": 1,
                },
            },
            {
                "type": "run.finished",
                "run_id": "browser_multichart_guard",
                "seq": 6,
                "payload": {
                    "summary": final_summary,
                    "completed_task": False,
                    "status": "quality_gate_failed",
                },
            },
        ]

        _mock_file_task_route(e2e_page)
        e2e_page.route(
            "**/api/editor/ai/task-stream",
            lambda route: route.fulfill(
                status=200, content_type="text/event-stream", body=_sse_body(sse_events)
            ),
        )

        _open_workspace_ai(e2e_page, e2e_base_url)

        e2e_page.locator("#wa-user-input").fill(
            "分析 xlsx 财务预测，生成多张图并加入 docx"
        )
        e2e_page.locator("#wa-send-btn").click()

        e2e_page.wait_for_function(
            """() => document.querySelectorAll('.wa-task-artifact-image').length >= 2""",
            timeout=PAGE_TIMEOUT,
        )
        e2e_page.wait_for_function(
            """() => /chart2_product_mix\\.png/.test(document.body.textContent || '')""",
            timeout=PAGE_TIMEOUT,
        )

        layout = e2e_page.evaluate("""() => {
                const host = document.querySelector('.wa-task-artifacts');
                const images = Array.from(document.querySelectorAll('.wa-task-artifact-image'));
                const card = document.querySelector('.wa-task-run');
                const hostStyle = host ? getComputedStyle(host) : null;
                const imageStyle = images[0] ? getComputedStyle(images[0]) : null;
                return {
                    imageCount: images.length,
                    display: hostStyle ? hostStyle.display : '',
                    gap: hostStyle ? hostStyle.gap : '',
                    objectFit: imageStyle ? imageStyle.objectFit : '',
                    aspectRatio: imageStyle ? imageStyle.aspectRatio : '',
                    cardText: card ? (card.textContent || '') : '',
                };
            }""")

        assert layout["imageCount"] == 2
        assert layout["display"] == "grid"
        assert layout["gap"] in {"10px", "10px 10px"}
        assert layout["objectFit"] == "contain"
        assert layout["aspectRatio"] == "16 / 10"
        assert "image_insert_guard" not in layout["cardText"]
        assert "chart2_product_mix.png" in layout["cardText"]
        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"
