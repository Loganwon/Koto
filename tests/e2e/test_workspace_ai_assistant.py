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


def _sse_body(events: list[dict]) -> str:
    return "".join(
        f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        for event in events
    )


@pytest.mark.e2e
class TestWorkspaceAiAssistantSmoke:
    def test_workspace_ai_panel_shell_loads(self, e2e_page, console_errors, e2e_base_url):
        resp = _goto(e2e_page, f"{e2e_base_url}/workspace")
        e2e_page.wait_for_timeout(THINK_MEDIUM)
        if resp and resp.status >= 400:
            pytest.skip("Workspace editor page not available")

        e2e_page.locator("#wa-ai").wait_for(timeout=PAGE_TIMEOUT)
        e2e_page.locator("#wa-user-input").wait_for(timeout=PAGE_TIMEOUT)
        e2e_page.locator("#wa-send-btn").wait_for(timeout=PAGE_TIMEOUT)
        e2e_page.locator("#wa-ai-messages").wait_for(timeout=PAGE_TIMEOUT)

        assert e2e_page.locator("#wa-ai-route-info").count() > 0
        assert _real_errors(console_errors) == [], f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_ai_send_message_renders_mocked_whitebox_task_card(self, e2e_page, console_errors, e2e_base_url):
        captured = {}
        sse_events = [
            {"type": "run.started", "run_id": "browser_smoke", "seq": 1, "payload": {"mode": "whitebox_v1"}},
            {"type": "plan.created", "run_id": "browser_smoke", "seq": 2, "payload": {"summary": "准备处理任务。"}},
            {"type": "step.started", "run_id": "browser_smoke", "seq": 3, "step_id": "execute", "payload": {"title": "处理中"}},
            {"type": "run.finished", "run_id": "browser_smoke", "seq": 4, "payload": {"summary": "模拟任务已完成", "completed_task": True}},
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

        e2e_page.route("**/api/editor/ai/task-stream", fulfill_task_stream)

        resp = _goto(e2e_page, f"{e2e_base_url}/workspace")
        e2e_page.wait_for_timeout(THINK_MEDIUM)
        if resp and resp.status >= 400:
            pytest.skip("Workspace editor page not available")

        e2e_page.locator("#wa-user-input").fill("总结当前文件")
        e2e_page.locator("#wa-send-btn").click()

        task_card = e2e_page.locator(".wa-task-run").first
        task_card.wait_for(timeout=PAGE_TIMEOUT)
        e2e_page.wait_for_timeout(THINK_SHORT)

        summary = task_card.locator("[data-role='summary']").inner_text()
        assert "模拟任务已完成" in summary
        assert captured["payload"]["task"] == "总结当前文件"
        assert isinstance(captured["payload"].get("history"), list)
        assert _real_errors(console_errors) == [], f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_ai_task_card_renders_step_result_rollups_in_browser(self, e2e_page, console_errors, e2e_base_url):
        sse_events = [
            {"type": "run.started", "run_id": "browser_step_result", "seq": 1, "payload": {"mode": "whitebox_v1"}},
            {"type": "plan.created", "run_id": "browser_step_result", "seq": 2, "payload": {"summary": "准备处理任务。"}},
            {"type": "step.started", "run_id": "browser_step_result", "seq": 3, "step_id": "context", "payload": {"title": "读取显式上下文"}},
            {"type": "step.result", "run_id": "browser_step_result", "seq": 4, "step_id": "context", "payload": {"title": "读取显式上下文", "summary": "已整理 1 份上下文片段。", "status": "completed", "snippet_count": 1}},
            {"type": "step.started", "run_id": "browser_step_result", "seq": 5, "step_id": "execute", "payload": {"title": "模型规划并调用工具"}},
            {"type": "step.result", "run_id": "browser_step_result", "seq": 6, "step_id": "execute", "payload": {"title": "模型工具执行完成", "summary": "已完成第 1 轮工具执行。", "status": "completed", "round": 1}},
            {"type": "run.finished", "run_id": "browser_step_result", "seq": 7, "payload": {"summary": "模拟任务已完成", "completed_task": True}},
        ]

        e2e_page.route(
            "**/api/editor/ai/task-stream",
            lambda route: route.fulfill(status=200, content_type="text/event-stream", body=_sse_body(sse_events)),
        )

        resp = _goto(e2e_page, f"{e2e_base_url}/workspace")
        e2e_page.wait_for_timeout(THINK_MEDIUM)
        if resp and resp.status >= 400:
            pytest.skip("Workspace editor page not available")

        e2e_page.locator("#wa-user-input").fill("总结当前文件")
        e2e_page.locator("#wa-send-btn").click()

        task_card = e2e_page.locator(".wa-task-run").first
        task_card.wait_for(timeout=PAGE_TIMEOUT)
        e2e_page.wait_for_function(
            """() => {
                const card = document.querySelector('.wa-task-run');
                return !!card && /已整理 1 份上下文片段/.test(card.textContent || '') && /已完成第 1 轮工具执行/.test(card.textContent || '');
            }""",
            timeout=PAGE_TIMEOUT,
        )

        card_text = task_card.inner_text()
        assert "已整理 1 份上下文片段" in card_text
        assert "已完成第 1 轮工具执行" in card_text
        assert "模拟任务已完成" in card_text
        assert _real_errors(console_errors) == [], f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_ai_task_card_shows_refresh_state_when_file_changes(self, e2e_page, console_errors, e2e_base_url):
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
            {"type": "run.started", "run_id": "browser_refresh", "seq": 1, "payload": {"mode": "whitebox_v1"}},
            {"type": "plan.created", "run_id": "browser_refresh", "seq": 2, "payload": {"summary": "准备刷新文件。"}},
            {"type": "step.started", "run_id": "browser_refresh", "seq": 3, "step_id": "execute", "payload": {"title": "模型规划并调用工具"}},
            {"type": "file.changed", "run_id": "browser_refresh", "seq": 4, "step_id": "execute", "payload": {"path": "report.txt", "file_path": "report.txt", "file_type": "txt", "operation": "annotate_file", "summary": "已更新 report.txt。", "annotations_added": 1, "supported": True}},
            {"type": "step.result", "run_id": "browser_refresh", "seq": 5, "step_id": "execute", "payload": {"title": "模型工具执行完成", "summary": "已写回 report.txt 并刷新前端视图。", "status": "completed", "file_change_count": 1, "file_changes": [{"path": "report.txt", "operation": "annotate_file", "summary": "已更新 report.txt。"}]}},
            {"type": "run.finished", "run_id": "browser_refresh", "seq": 6, "payload": {"summary": "模拟刷新已完成", "completed_task": True}},
        ]

        e2e_page.route("**/api/v1/workspace/open_file_by_path", fulfill_open_file)
        e2e_page.route(
            "**/api/editor/ai/task-stream",
            lambda route: route.fulfill(status=200, content_type="text/event-stream", body=_sse_body(sse_events)),
        )

        resp = _goto(e2e_page, f"{e2e_base_url}/workspace")
        e2e_page.wait_for_timeout(THINK_MEDIUM)
        if resp and resp.status >= 400:
            pytest.skip("Workspace editor page not available")

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
        e2e_page.wait_for_function(
            """() => {
                return /Mock content version 2/.test(document.body.textContent || '');
            }""",
            timeout=PAGE_TIMEOUT,
        )

        assert open_counts.get("report.txt", 0) >= 2
        card_text = task_card.inner_text()
        assert "report.txt" in card_text
        assert "模拟刷新已完成" in card_text
        assert "已刷新" not in card_text
        assert _real_errors(console_errors) == [], f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_ai_history_survives_file_switch_within_runtime_session(self, e2e_page, console_errors, e2e_base_url):
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
                        {"type": "run.started", "run_id": f"browser_smoke_{idx}", "seq": 1, "payload": {"mode": "whitebox_v1"}},
                        {"type": "plan.created", "run_id": f"browser_smoke_{idx}", "seq": 2, "payload": {"summary": "准备处理任务。"}},
                        {"type": "run.finished", "run_id": f"browser_smoke_{idx}", "seq": 3, "payload": {"summary": summary, "completed_task": True}},
                    ]
                ),
            )

        e2e_page.route("**/api/v1/workspace/open_file_by_path", fulfill_open_file)
        e2e_page.route("**/api/editor/ai/task-stream", fulfill_task_stream)

        resp = _goto(e2e_page, f"{e2e_base_url}/workspace")
        e2e_page.wait_for_timeout(THINK_MEDIUM)
        if resp and resp.status >= 400:
            pytest.skip("Workspace editor page not available")

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
        assert e2e_page.locator(".wa-task-run [data-role='plan']").first.inner_text() == "准备处理任务。"

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
        assert any(item.get("role") == "user" and item.get("content") == "先分析文档A" for item in second_history)
        assert any(item.get("role") == "assistant" and item.get("content") == "模拟任务1已完成" for item in second_history)
        assert _real_errors(console_errors) == [], f"JS errors: {_real_errors(console_errors)}"
