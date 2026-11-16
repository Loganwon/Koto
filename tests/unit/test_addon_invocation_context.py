from __future__ import annotations

import logging

from flask import Flask, g

from app.core.agent.plugin_protocol import AddonInvocationContext, DataClassification
from web.services.chat_stream.agent_handler import handle_agent_task


def test_web_agent_injects_host_identity_outside_addon_plan(monkeypatch):
    captured = {}

    class FakeAgent:
        def run(self, **kwargs):
            captured.update(kwargs)
            return iter(())

    class FakeSessionManager:
        @staticmethod
        def append_and_save(*_args, **_kwargs):
            return None

    monkeypatch.setattr(
        "app.core.agent.kernel_agent_service.get_kernel_agent",
        lambda **_kwargs: FakeAgent(),
    )
    monkeypatch.setattr(
        "web.blueprints.auth.resolve_addon_identity",
        lambda: ("bank-a", "employee-7"),
    )
    app = Flask(__name__)
    with app.test_request_context("/api/chat/stream"):
        g.request_id = "request-42"
        response = handle_agent_task(
            "AGENT",
            "session-9",
            "查询客户",
            [],
            "cloud",
            "addon",
            {
                "addon_ids": ["com.bank.customer"],
                "tool_names": ["customer_lookup"],
                "data_classification": "restricted",
            },
            FakeSessionManager(),
            logging.getLogger("test.addon-context"),
            lambda *_args, **_kwargs: None,
            lambda payload: str(payload),
        )
        list(response.response)

    context = captured["addon_invocation_context"]
    assert isinstance(context, AddonInvocationContext)
    assert context.tenant_id == "bank-a"
    assert context.principal_id == "employee-7"
    assert context.purpose_code == "interactive_agent_task"
    assert context.request_id == "request-42"
    assert context.session_id == "session-9"
    assert context.correlation_id == "request-42"
    assert context.data_classification is DataClassification.RESTRICTED
    assert "invocation_context" not in captured["addon_plan"]
