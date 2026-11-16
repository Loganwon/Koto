"""Synchronous transports must not turn a rejected Agent output into success."""

from types import SimpleNamespace

import pytest

from app.core.agent import kernel_agent_service as service
from app.core.agent.kernel import ValidationOutcome
from app.core.agent.types import AgentStep, AgentStepType


def test_legacy_blocked_answer_metadata_is_collected_as_failure(monkeypatch):
    agent = SimpleNamespace(
        run=lambda **kwargs: iter(
            [
                AgentStep(
                    AgentStepType.ANSWER,
                    "结果未通过验收",
                    metadata={"validation": {"blocked": True}},
                ),
            ]
        )
    )
    monkeypatch.setattr(service, "get_kernel_agent", lambda: agent)
    result = service.run_kernel_agent_collect("test", record_task=False)
    assert result["status"] == "failed" and result["error"]
    assert result["answer"] == result["result"] == "结果未通过验收"


def test_successful_repair_clears_prior_rejection_metadata(monkeypatch):
    from app.core.agent import kernel_agent as module

    class Validator:
        count = 0

        def validate(self, content, request):
            self.count += 1
            if self.count == 1:
                return ValidationOutcome.retry(content, "repair")
            return ValidationOutcome.accept("已通过验收")

    monkeypatch.setattr(module, "KotoOutputValidator", Validator)
    provider = SimpleNamespace(generate_content=lambda **kwargs: {"content": "draft"})
    agent = module.KernelAgent(
        provider,
        enable_pii_filter=False,
        use_tool_router=False,
        allow_model_fallback=False,
    )
    monkeypatch.setattr(service, "get_kernel_agent", lambda: agent)
    result = service.run_kernel_agent_collect("test", record_task=False)
    assert result["status"] == "success" and "error" not in result
    assert result["answer"] == "已通过验收"
    assert result["steps"][-1]["metadata"]["validation"]["accepted"] is True


@pytest.mark.parametrize("status", ["success", "failed", "cancelled", "blocked"])
def test_telegram_history_records_success_only_without_any_network(monkeypatch, status):
    from app.core.services.telegram_bot import TelegramBot

    saved = []
    displayed = []
    monkeypatch.setattr(service, "load_kernel_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        service,
        "run_kernel_agent_collect",
        lambda *args, **kwargs: {"status": status, "answer": "可显示的结果"},
    )
    monkeypatch.setattr(
        service, "save_kernel_history", lambda *args: saved.append(args)
    )
    offline_bot = SimpleNamespace(
        send_typing=lambda *args: None, send_text=lambda *args: displayed.append(args)
    )
    TelegramBot._handle_chat(offline_bot, 123, "test", "tester")
    assert displayed == [(123, "可显示的结果")]
    assert bool(saved) is (status == "success")
