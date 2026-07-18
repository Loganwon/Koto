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
    page.add_init_script("window.__KOTO_E2E__ = true")
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
    # File-task rendering tests must not inherit the developer's persisted
    # local-model choice.  A tools-disabled local model correctly blocks write
    # tasks before the mocked stream is opened, which would make these UI tests
    # depend on unrelated machine state.
    page.route(
        "**/api/local-model/status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"success": True, "mode": "cloud", "cloud_provider": "deepseek"}
            ),
        ),
    )
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
            e2e_page.locator(
                'link[rel="stylesheet"][href*="workspace-task-flow.css"]'
            ).count()
            == 1
        )
        assert (
            e2e_page.locator(
                'link[rel="stylesheet"][href*="workspace-task-results.css"]'
            ).count()
            == 1
        )
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
        trigger = e2e_page.locator("#wa-model-menu-trigger")
        assert e2e_page.locator("#wa-model-mode-toggle").count() == 1
        assert trigger.count() == 1
        assert deepseek.count() == 1
        assert local.count() == 1
        assert trigger.get_attribute("aria-expanded") == "false"

        # The selected mode is persisted between sessions.  Re-selecting the
        # already active option is deliberately a no-op, so the request
        # contract must depend on the actual initial state rather than test
        # process history.
        initially_deepseek = deepseek.evaluate(
            "(element) => element.classList.contains('active')"
        )
        trigger.click()
        assert trigger.get_attribute("aria-expanded") == "true"
        deepseek.click()
        e2e_page.wait_for_function(
            """() => document.querySelector('#wa-model-mode-deepseek-btn')
                ?.classList.contains('active')""",
            timeout=PAGE_TIMEOUT,
        )
        trigger.click()
        local.click()
        e2e_page.wait_for_function(
            """() => document.querySelector('#wa-model-mode-local-btn')
                ?.classList.contains('active')""",
            timeout=PAGE_TIMEOUT,
        )

        expected_modes = (["deepseek"] if not initially_deepseek else []) + ["local"]
        assert captured_modes == expected_modes
        assert trigger.get_attribute("aria-expanded") == "false"
        assert "本地" in trigger.inner_text()
        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_model_menu_stays_in_viewport_with_ui_zoom(
        self, e2e_page, console_errors, e2e_base_url
    ):
        e2e_page.set_viewport_size({"width": 1040, "height": 300})
        _open_workspace_ai(e2e_page, e2e_base_url)
        e2e_page.evaluate("document.body.style.zoom = '1.2'")

        trigger = e2e_page.locator("#wa-model-menu-trigger")
        trigger.click()
        geometry = e2e_page.evaluate("""() => {
                const trigger = document.querySelector('#wa-model-menu-trigger');
                const menu = document.querySelector('#wa-model-mode-menu');
                const triggerRect = trigger.getBoundingClientRect();
                const menuRect = menu.getBoundingClientRect();
                return {
                    triggerLeft: triggerRect.left,
                    left: menuRect.left,
                    right: menuRect.right,
                    top: menuRect.top,
                    bottom: menuRect.bottom,
                    width: menuRect.width,
                    viewportWidth: window.innerWidth,
                    viewportHeight: window.innerHeight,
                    placement: menu.dataset.placement,
                };
            }""")

        assert geometry["left"] >= 7
        assert geometry["right"] <= geometry["viewportWidth"] - 7
        assert geometry["top"] >= 7
        assert geometry["bottom"] <= geometry["viewportHeight"] - 7
        expected_left = min(
            geometry["triggerLeft"],
            geometry["viewportWidth"] - geometry["width"] - 8,
        )
        assert abs(geometry["left"] - expected_left) <= 2
        assert geometry["placement"] == "top"
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

        e2e_page.evaluate("""() => {
                let workbench = document.getElementById('wa-task-workbench');
                if (!workbench) {
                    workbench = document.createElement('section');
                    workbench.id = 'wa-task-workbench';
                    workbench.className = 'wa-task-workbench wa-inline-task-workbench';
                    workbench.textContent = '历史任务流程';
                    document.getElementById('wa-ai-messages').appendChild(workbench);
                }
                workbench.hidden = false;
                workbench.style.display = 'block';
            }""")
        assert e2e_page.locator("#wa-task-workbench").is_visible()

        e2e_page.locator("#wa-user-input").fill("总结当前文件")
        e2e_page.locator("#wa-send-btn").click()

        task_card = e2e_page.locator(".wa-task-run").first
        task_card.wait_for(timeout=PAGE_TIMEOUT)
        e2e_page.wait_for_timeout(THINK_SHORT)

        summary = task_card.locator("[data-role='summary']").inner_text()
        assert "模拟任务已完成" in summary
        assert e2e_page.locator("#wa-task-workbench").is_hidden()
        assert task_card.locator("[data-role='process']").is_visible()
        assert "is-workbench-projected" not in (task_card.get_attribute("class") or "")
        assert captured["payload"]["task"] == "总结当前文件"
        assert isinstance(captured["payload"].get("history"), list)
        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_system_shortcut_bypasses_model_route_and_uses_chat_stream(
        self, e2e_page, console_errors, e2e_base_url
    ):
        captured = {"route_intent_calls": 0}

        def unexpected_route_intent(route):
            captured["route_intent_calls"] += 1
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "route": "file_task"}),
            )

        def fulfill_chat_stream(route):
            try:
                captured["chat_payload"] = json.loads(route.request.post_data or "{}")
            except Exception:
                captured["chat_payload"] = {}
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=_sse_body(
                    [
                        {"type": "token", "content": "系统动作已接收"},
                    ]
                ),
            )

        e2e_page.route("**/api/workspace/ai/route-intent", unexpected_route_intent)
        e2e_page.route("**/api/chat/stream", fulfill_chat_stream)
        _open_workspace_ai(e2e_page, e2e_base_url)

        e2e_page.locator("#wa-user-input").fill("打开微信")
        e2e_page.locator("#wa-send-btn").click()

        assistant = e2e_page.locator(".wa-msg.ai").last
        assistant.wait_for(timeout=PAGE_TIMEOUT)
        e2e_page.wait_for_function(
            """() => Array.from(document.querySelectorAll('.wa-msg.ai'))
                .some((element) => element.textContent.includes('系统动作已接收'))""",
            timeout=PAGE_TIMEOUT,
        )

        assert captured["route_intent_calls"] == 0
        assert captured["chat_payload"]["locked_task"] == "SYSTEM"
        assert (
            captured["chat_payload"]["workspace_route_intent"]["route"]
            == "system_action"
        )
        assert (
            captured["chat_payload"]["workspace_route_intent"]["route_source"]
            == "frontend_deterministic_system"
        )
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
                "payload": {
                    "summary": "读取来源并生成结果文件。",
                    "steps": [
                        {"title": "读取 source.txt"},
                        {"title": "生成 output.txt"},
                    ],
                },
            },
            {
                "type": "supervisor.status",
                "run_id": "browser_step_result",
                "seq": 3,
                "step_id": "plan",
                "payload": {
                    "stage": "planned",
                    "summary": "监管检查通过，允许继续执行。",
                },
            },
            {
                "type": "model.call.started",
                "run_id": "browser_step_result",
                "seq": 4,
                "payload": {
                    "round": 1,
                    "summary": "内部模型轮次。",
                },
            },
            {
                "type": "read.changed",
                "run_id": "browser_step_result",
                "seq": 5,
                "step_id": "context",
                "payload": {"path": "source.txt"},
            },
            {
                "type": "tool.started",
                "run_id": "browser_step_result",
                "seq": 6,
                "step_id": "execute",
                "payload": {
                    "tool_name": "write_text_file",
                    "tool_title": "写入结果文件",
                    "tool_use_id": "write_1",
                    "tool_args": '{"content":"INTERNAL_SECRET"}',
                },
            },
            {
                "type": "tool.finished",
                "run_id": "browser_step_result",
                "seq": 7,
                "step_id": "execute",
                "payload": {
                    "tool_name": "write_text_file",
                    "tool_title": "写入结果文件",
                    "tool_use_id": "write_1",
                    "success": True,
                    "result_preview": "已写入 output.txt",
                },
            },
            {
                "type": "file.changed",
                "run_id": "browser_step_result",
                "seq": 8,
                "step_id": "execute",
                "payload": {
                    "path": "output.txt",
                    "change_type": "created",
                },
            },
            {
                "type": "step.result",
                "run_id": "browser_step_result",
                "seq": 9,
                "step_id": "execute",
                "payload": {
                    "title": "模型工具执行完成",
                    "summary": "已完成第 1 轮工具执行。",
                    "status": "completed",
                },
            },
            {
                "type": "check.finished",
                "run_id": "browser_step_result",
                "seq": 10,
                "step_id": "check",
                "payload": {
                    "passed": True,
                    "status": "verified",
                    "summary": "核验通过。",
                },
            },
            {
                "type": "run.finished",
                "run_id": "browser_step_result",
                "seq": 11,
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
                return /模拟任务已完成/.test(text)
                    && /读取来源并生成结果文件/.test(text)
                    && /source\.txt/.test(text)
                    && /output\.txt/.test(text);
            }""",
            timeout=PAGE_TIMEOUT,
        )

        card_text = task_card.evaluate("(el) => el.textContent || ''")
        assert "查看执行详情" in card_text
        assert "读取文件" in card_text
        assert "模拟任务已完成" in card_text
        assert "读取 source.txt" in card_text
        assert "生成 output.txt" in card_text
        assert "写入结果文件" in card_text
        assert "INTERNAL_SECRET" not in card_text
        assert "第 1 轮" not in card_text
        assert "监管检查通过" not in card_text
        assert "核验通过。" not in card_text
        stage_items = task_card.locator("[data-role='stage-overview'] [data-stage-id]")
        assert stage_items.count() == 5
        assert (
            "分析需求" in task_card.locator("[data-role='stage-overview']").inner_text()
        )
        assert (
            "制定计划" in task_card.locator("[data-role='stage-overview']").inner_text()
        )
        assert (
            "正在处理" in task_card.locator("[data-role='stage-overview']").inner_text()
        )
        assert (
            "检查结果" in task_card.locator("[data-role='stage-overview']").inner_text()
        )
        assert (
            "交付结果" in task_card.locator("[data-role='stage-overview']").inner_text()
        )
        assert (
            task_card.locator("[data-role='stage-progress-count']").inner_text()
            == "5/5"
        )
        assert task_card.locator("[data-role='process']").evaluate("el => !el.open")
        final_report_style = task_card.locator("[data-role='final-report']").evaluate(
            """el => {
                const style = getComputedStyle(el);
                return {
                    borderTopStyle: style.borderTopStyle,
                    contentLineHeight: getComputedStyle(
                        el.querySelector('.wa-task-final-report-content')
                    ).lineHeight,
                };
            }"""
        )
        assert final_report_style["borderTopStyle"] == "solid"
        assert final_report_style["contentLineHeight"] != "normal"
        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_ai_task_stage_overview_updates_during_stream(
        self, e2e_page, console_errors, e2e_base_url
    ):
        _mock_file_task_route(e2e_page)
        _open_workspace_ai(e2e_page, e2e_base_url)

        e2e_page.evaluate("""() => {
                const card = window.WA.taskFlowTestHarness.makeRunCard(null);
                document.getElementById('wa-ai-messages').appendChild(card);
                window.__kotoStageCard = card;
                window.__kotoEmitStageEvent = (type, payload, stepId) => {
                    window.WA.taskFlowTestHarness.processEvent(card, {
                        type,
                        run_id: 'stage_overview_live',
                        task_id: 'task_stage_overview_live',
                        step_id: stepId || undefined,
                        payload: payload || {},
                    });
                };
                window.__kotoEmitStageEvent('run.started', { mode: 'whitebox_v1' });
                window.__kotoEmitStageEvent('task.classified', {
                    task_family: 'analyze',
                    operation_kind: 'read',
                    output_mode: 'answer',
                });
            }""")

        card = e2e_page.locator(".wa-task-run[data-task-run-id='stage_overview_live']")
        card.wait_for(timeout=PAGE_TIMEOUT)
        assert "done" in card.locator("[data-stage-id='route']").get_attribute("class")
        assert "pending" in card.locator("[data-stage-id='plan']").get_attribute(
            "class"
        )
        assert (
            card.locator("[data-role='stage-current-label']").inner_text() == "分析需求"
        )

        e2e_page.evaluate("""() => {
                window.__kotoRealDateNow = Date.now;
                Date.now = () => window.__kotoRealDateNow() + 65000;
            }""")
        e2e_page.wait_for_function(
            """() => {
                const card = window.__kotoStageCard;
                return !!card
                    && /处理耗时较长/.test(
                        card.querySelector('[data-role="status"]')?.textContent || ''
                    );
            }""",
            timeout=PAGE_TIMEOUT,
        )
        heartbeat_text = (
            card.locator(".wa-task-row[data-role='task-heartbeat']").text_content()
            or ""
        )
        assert "任务仍在运行" in heartbeat_text
        assert "秒" not in heartbeat_text
        assert card.locator("[data-role='status']").is_visible()
        e2e_page.evaluate("""() => {
                Date.now = window.__kotoRealDateNow;
                window.__kotoEmitStageEvent('plan.created', {
                    summary: '先读取文件，再整理关键结论。',
                    steps: [{ title: '读取文件' }, { title: '整理结论' }],
                }, 'plan');
            }""")
        assert card.locator(".wa-task-row[data-role='task-heartbeat']").count() == 0

        assert "running" in card.locator("[data-stage-id='plan']").get_attribute(
            "class"
        )
        assert (
            card.locator("[data-role='stage-current-label']").inner_text() == "制定计划"
        )
        assert (
            "先读取文件"
            in card.locator("[data-role='stage-current-detail']").inner_text()
        )
        assert card.locator("[data-role='stage-progress-count']").inner_text() == "1/5"
        assert card.locator("[data-role='status']").is_hidden()

        e2e_page.evaluate("""() => {
                window.__kotoEmitStageEvent('plan.checked', {
                    passed: true,
                    summary: '内部边界检查通过。',
                }, 'plan');
                window.__kotoEmitStageEvent('supervisor.status', {
                    stage: 'planned',
                    summary: '内部监管检查通过。',
                }, 'plan');
            }""")
        assert (
            "先读取文件"
            in card.locator("[data-role='stage-current-detail']").inner_text()
        )

        e2e_page.evaluate("""() => window.__kotoEmitStageEvent('model.call.started', {
                round: 1,
                model_mode: 'deepseek',
            }, 'execute')""")
        assert "done" in card.locator("[data-stage-id='plan']").get_attribute("class")
        assert "running" in card.locator("[data-stage-id='execute']").get_attribute(
            "class"
        )
        assert (
            card.locator("[data-role='stage-current-label']").inner_text() == "正在处理"
        )
        assert (
            "AI 正在分析内容"
            in card.locator("[data-role='stage-current-detail']").inner_text()
        )
        assert card.locator("[data-role='stage-progress-count']").inner_text() == "2/5"

        e2e_page.evaluate("""() => {
                window.__kotoEmitStageEvent('model.call.finished', {
                    success: true,
                    tool_call_count: 1,
                }, 'execute');
                window.__kotoEmitStageEvent('tool.started', {
                    tool_name: 'write_text_file',
                    tool_title: '写入结果文件',
                    tool_use_id: 'stage_write_1',
                }, 'execute');
                window.__kotoEmitStageEvent('tool.finished', {
                    tool_name: 'write_text_file',
                    tool_title: '写入结果文件',
                    tool_use_id: 'stage_write_1',
                    success: true,
                }, 'execute');
            }""")
        assert card.locator("[data-role='stage-current-detail']").inner_text() == (
            "正在写入结果文件"
        )

        e2e_page.evaluate("""() => window.__kotoEmitStageEvent('file.changed', {
                path: 'workspace/output.txt',
                file_path: 'workspace/output.txt',
                change_type: 'created',
            }, 'execute')""")
        assert card.locator("[data-role='stage-current-detail']").inner_text() == (
            "已创建 output.txt"
        )
        assert (
            card.locator("[data-role='plan']").evaluate(
                "el => getComputedStyle(el).borderTopStyle"
            )
            == "solid"
        )
        assert (
            card.locator("[data-role='steps'] .wa-task-step").first.evaluate(
                "el => getComputedStyle(el).borderLeftStyle"
            )
            == "solid"
        )
        assert (
            card.locator("[data-role='steps'] .wa-task-row").first.evaluate(
                "el => getComputedStyle(el).borderTopStyle"
            )
            == "solid"
        )

        e2e_page.evaluate("""() => window.__kotoEmitStageEvent('check.started', {
                title: '正在核验结果与文件变更',
            }, 'check')""")
        assert "done" in card.locator("[data-stage-id='execute']").get_attribute(
            "class"
        )
        assert "running" in card.locator("[data-stage-id='check']").get_attribute(
            "class"
        )
        assert (
            card.locator("[data-role='stage-current-label']").inner_text() == "检查结果"
        )
        assert (
            "正在核验"
            in card.locator("[data-role='stage-current-detail']").inner_text()
        )
        assert card.locator("[data-role='stage-progress-count']").inner_text() == "3/5"

        e2e_page.evaluate("""() => window.__kotoEmitStageEvent('run.finished', {
                summary: '任务已完成，结果已核验。',
                completed_task: true,
            }, 'check')""")
        assert card.locator("[data-role='stage-progress-count']").inner_text() == "5/5"
        assert (
            card.locator("[data-role='stage-current-label']").inner_text() == "流程完成"
        )
        assert card.locator("[data-role='stage-overview'] .done").count() == 5
        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_ai_task_stream_disconnect_shows_one_stable_sync_warning(
        self, e2e_page, console_errors, e2e_base_url
    ):
        _mock_file_task_route(e2e_page)
        e2e_page.route(
            "**/api/test-task-stream-disconnect",
            lambda route: route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=_sse_body(
                    [
                        {
                            "type": "run.started",
                            "run_id": "disconnect_notice",
                            "task_id": "task_disconnect_notice",
                            "seq": 1,
                            "payload": {"mode": "whitebox_v1"},
                        }
                    ]
                ),
            ),
        )
        e2e_page.route(
            "**/api/tasks/task_disconnect_notice/stream?**",
            lambda route: route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=_sse_body(
                    [
                        {
                            "type": "run.finished",
                            "run_id": "disconnect_notice",
                            "task_id": "task_disconnect_notice",
                            "seq": 2,
                            "payload": {
                                "summary": "任务进度已重新连接。",
                                "completed_task": True,
                            },
                        }
                    ]
                ),
            ),
        )
        _open_workspace_ai(e2e_page, e2e_base_url)

        e2e_page.evaluate("""() => {
                const card = window.WA.taskFlowTestHarness.makeRunCard(null);
                document.getElementById('wa-ai-messages').appendChild(card);
                window.__kotoDisconnectCard = card;
                window.WA.taskFlowTestHarness.streamTaskFlow(
                    card,
                    '/api/test-task-stream-disconnect',
                    {},
                    'GET'
                ).catch(() => {});
            }""")

        card = e2e_page.locator(".wa-task-run[data-task-run-id='disconnect_notice']")
        card.wait_for(timeout=PAGE_TIMEOUT)
        e2e_page.wait_for_function(
            """() => /进度同步中断/.test(
                window.__kotoDisconnectCard
                    ?.querySelector('[data-role="status"]')
                    ?.textContent || ''
            )""",
            timeout=PAGE_TIMEOUT,
        )
        reconnect_rows = card.locator(".wa-task-row[data-role='stream-reconnect']")
        assert reconnect_rows.count() == 1
        reconnect_text = reconnect_rows.text_content() or ""
        assert "同步中断" in reconnect_text
        assert "后台任务状态已保留" in reconnect_text
        assert "恢复连接" not in reconnect_text
        assert card.locator("[data-role='status']").is_visible()
        retry_button = card.locator("[data-task-stream-retry]")
        assert retry_button.count() == 1
        retry_button.click()
        e2e_page.wait_for_function(
            """() => /任务进度已重新连接/.test(
                window.__kotoDisconnectCard
                    ?.querySelector('[data-role="summary"]')
                    ?.textContent || ''
            )""",
            timeout=PAGE_TIMEOUT,
        )
        assert card.locator("[data-role='task-primary-action']").is_hidden()
        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_workspace_ai_task_primary_action_handles_confirmation_and_cancel(
        self, e2e_page, console_errors, e2e_base_url
    ):
        _mock_file_task_route(e2e_page)
        _open_workspace_ai(e2e_page, e2e_base_url)

        e2e_page.evaluate("""() => {
                window.__kotoResumeDetails = null;
                window.WA.resumePersistedTaskArtifact = (details) => {
                    window.__kotoResumeDetails = details;
                    return Promise.resolve(true);
                };
                const waitingCard = window.WA.taskFlowTestHarness.makeRunCard(null);
                document.getElementById('wa-ai-messages').appendChild(waitingCard);
                window.__kotoWaitingCard = waitingCard;
                window.WA.taskFlowTestHarness.processEvent(waitingCard, {
                    type: 'run.started',
                    run_id: 'primary_waiting',
                    task_id: 'task_primary_waiting',
                    payload: { mode: 'whitebox_v1' },
                });
                window.WA.taskFlowTestHarness.processEvent(waitingCard, {
                    type: 'run.finished',
                    run_id: 'primary_waiting',
                    task_id: 'task_primary_waiting',
                    payload: {
                        runtime: {
                            terminal_status: 'awaiting_confirmation',
                        },
                        completed_task: false,
                        summary: '第一步已完成，等待确认。',
                        next_action_artifact: {
                            action_label: '确认并继续',
                            resume_request: {
                                task_id: 'task_primary_waiting',
                                task: '继续下一步',
                                options: {
                                    workflow_checkpoint: {
                                        policy: 'confirm_each_step',
                                    },
                                },
                            },
                        },
                    },
                });

                const runningCard = window.WA.taskFlowTestHarness.makeRunCard(null);
                document.getElementById('wa-ai-messages').appendChild(runningCard);
                window.__kotoRunningCard = runningCard;
                window.WA.taskFlowTestHarness.processEvent(runningCard, {
                    type: 'run.started',
                    run_id: 'primary_running',
                    task_id: 'task_primary_running',
                    payload: { mode: 'whitebox_v1' },
                });
            }""")

        waiting_card = e2e_page.locator(
            ".wa-task-run[data-task-run-id='primary_waiting']"
        )
        waiting_card.wait_for(timeout=PAGE_TIMEOUT)
        primary_resume = waiting_card.locator(
            "[data-role='task-primary-action'] [data-task-artifact-resume]"
        )
        assert primary_resume.count() == 1
        assert primary_resume.inner_text() == "确认并继续"
        assert (
            waiting_card.locator(
                "[data-role='summary'] [data-task-artifact-resume]"
            ).count()
            == 0
        )
        assert waiting_card.locator("[data-role='cancel']").count() == 0
        primary_resume.click()
        e2e_page.wait_for_function(
            """() => window.__kotoResumeDetails?.taskId === 'task_primary_waiting'""",
            timeout=PAGE_TIMEOUT,
        )
        assert primary_resume.is_disabled()

        running_card = e2e_page.locator(
            ".wa-task-run[data-task-run-id='primary_running']"
        )
        running_card.wait_for(timeout=PAGE_TIMEOUT)
        cancel_button = running_card.locator(
            "[data-role='task-primary-action'] [data-role='cancel']"
        )
        assert cancel_button.count() == 1
        cancel_button.click()
        e2e_page.wait_for_function(
            """() => window.__kotoRunningCard?.dataset.taskTerminalStatus === 'cancelled'""",
            timeout=PAGE_TIMEOUT,
        )
        assert running_card.locator("[data-role='task-primary-action']").is_hidden()
        assert "任务已被取消" in (
            running_card.locator("[data-role='summary']").text_content() or ""
        )
        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    @pytest.mark.parametrize(
        ("terminal_status", "expected_title", "expected_detail"),
        [
            ("quality_gate_failed", "任务未完成", "失败原因"),
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
        assert "查看执行详情" in process.inner_text()
        assert process.evaluate("el => !el.open")

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

    def test_workspace_ai_completed_task_persists_and_restores_one_result_card(
        self, e2e_page, console_errors, e2e_base_url
    ):
        summary_text = "browser final answer is canonical"
        artifact_name = "browser_history.txt"
        persisted_payloads: list[dict] = []

        def capture_workspace_turn(request):
            if "/workspace-turn" not in request.url or request.method != "POST":
                return
            try:
                persisted_payloads.append(json.loads(request.post_data or "{}"))
            except json.JSONDecodeError:
                persisted_payloads.append({})

        e2e_page.on("request", capture_workspace_turn)
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
                "type": "file.changed",
                "run_id": "browser_history_restore",
                "seq": 4,
                "step_id": "execute",
                "payload": {
                    "path": artifact_name,
                    "file_path": artifact_name,
                    "file_type": "txt",
                    "change_type": "created",
                },
            },
            {
                "type": "step.result",
                "run_id": "browser_history_restore",
                "seq": 5,
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
                "seq": 6,
                "payload": {
                    "summary": summary_text,
                    "completed_task": True,
                    "status": "completed",
                    "artifact_result": {
                        "status": "completed",
                        "artifacts": [
                            {
                                "path": f"workspace/{artifact_name}",
                                "type": "txt",
                                "title": artifact_name,
                            }
                        ],
                    },
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
            """() => window.WA?.getWorkspaceSessionId?.() || ''"""
        )
        assert session_id and not str(session_id).startswith("workspace_runtime_")

        e2e_page.locator("#wa-user-input").fill("生成一份任务总结")
        e2e_page.locator("#wa-send-btn").click()
        e2e_page.wait_for_function(
            """([summaryText, artifactName]) => {
                const summary = document.querySelector('.wa-task-run:not([data-history-snapshot="true"]) [data-role="summary"]');
                const report = summary && summary.querySelector('[data-role="final-report"]');
                const artifact = summary && summary.querySelector('[data-role="artifact-summary"]');
                const context = summary && summary.querySelector('[data-role="task-context"]');
                const actions = summary && summary.querySelector('.wa-task-actions');
                const children = summary ? Array.from(summary.children) : [];
                return !!summary
                    && !!report
                    && report.textContent.includes(summaryText)
                    && summary.querySelectorAll('[data-role="final-report"]').length === 1
                    && summary.querySelectorAll('.wa-task-completion-banner').length === 0
                    && summary.querySelectorAll('[data-role="artifact-summary"]').length === 1
                    && artifact.querySelectorAll('li').length === 1
                    && artifact.textContent.includes(artifactName)
                    && summary.querySelectorAll('[data-role="task-context"]').length === 1
                    && context.querySelectorAll('[data-role="task-understanding"]').length === 1
                    && summary.querySelectorAll(':scope > [data-role="task-understanding"]').length === 0
                    && children.indexOf(report) < children.indexOf(artifact)
                    && children.indexOf(artifact) < children.indexOf(context)
                    && (!actions || children.indexOf(context) < children.indexOf(actions));
            }""",
            arg=[summary_text, artifact_name],
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
                    return assistant ? {
                        schema: data.schema_version,
                        entry_schema: assistant.schema_version,
                        has_structure: !!assistant.test_structure,
                        has_snapshot: !!assistant.task_card_snapshot,
                    } : null;
                }""",
                [session_id, summary_text],
            )
            if (
                persisted
                and persisted.get("schema") == 2
                and persisted.get("entry_schema") == 2
                and persisted.get("has_structure")
                and persisted.get("has_snapshot")
            ):
                break
            e2e_page.wait_for_timeout(250)

        assert persisted
        assert persisted["schema"] == 2
        assert persisted["entry_schema"] == 2
        assert persisted["has_structure"] is True
        assert persisted["has_snapshot"] is True, persisted_payloads

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
        history_card = e2e_page.locator(
            '.wa-task-run[data-history-snapshot="true"]'
        ).filter(has_text=summary_text)
        history_card.wait_for(timeout=PAGE_TIMEOUT)
        restored_state = history_card.evaluate(
            """(host, [summaryText, artifactName]) => {
                const summary = host.querySelector('[data-role="summary"]');
                const report = summary && summary.querySelector('[data-role="final-report"]');
                const artifact = summary && summary.querySelector('[data-role="artifact-summary"]');
                const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
                const summaryLocations = [];
                let node = walker.nextNode();
                while (node) {
                    if ((node.textContent || '').includes(summaryText)) {
                        const parent = node.parentElement;
                        summaryLocations.push({
                            role: parent && parent.getAttribute('data-role'),
                            className: parent && parent.className,
                            text: node.textContent,
                        });
                    }
                    node = walker.nextNode();
                }
                return {
                    summaryOccurrences: (host.textContent || '').split(summaryText).length - 1,
                    summaryLocations,
                    reportCount: summary ? summary.querySelectorAll('[data-role="final-report"]').length : 0,
                    reportHasSummary: !!report && report.textContent.includes(summaryText),
                    artifactCount: summary ? summary.querySelectorAll('[data-role="artifact-summary"]').length : 0,
                    artifactItemCount: artifact ? artifact.querySelectorAll('li').length : 0,
                    artifactHasName: !!artifact && artifact.textContent.includes(artifactName),
                    contextCount: summary ? summary.querySelectorAll('[data-role="task-context"]').length : 0,
                    historyNoteCount: summary ? summary.querySelectorAll('[data-role="history-note"]').length : 0,
                    structureCount: host.querySelectorAll('.wa-history-test-structure').length,
                    fallbackAnswerCount: host.querySelectorAll('.wa-task-final-answer').length,
                    completionBannerCount: host.querySelectorAll('.wa-task-completion-banner').length,
                };
            }""",
            [summary_text, artifact_name],
        )
        assert restored_state["summaryOccurrences"] == 1, restored_state[
            "summaryLocations"
        ]
        assert restored_state["reportCount"] == 1
        assert restored_state["reportHasSummary"] is True
        assert restored_state["artifactCount"] == 1
        assert restored_state["artifactItemCount"] == 1
        assert restored_state["artifactHasName"] is True
        assert restored_state["contextCount"] == 1
        assert restored_state["historyNoteCount"] == 0
        assert restored_state["structureCount"] == 0
        assert restored_state["fallbackAnswerCount"] == 0
        assert restored_state["completionBannerCount"] == 0

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
        assert "补充图表" in layout["cardText"]
        assert "正在将已生成图表写入 Word" in layout["cardText"]
        assert "chart2_product_mix.png" in layout["cardText"]
        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"
