from __future__ import annotations

import json

import pytest
from flask import Flask


def test_core_profile_exposes_fixed_tools_without_external_extensions():
    from app.core.agent.tool_profiles import build_tool_registry

    registry, report = build_tool_registry(profile_name="core")
    names = {item["name"] for item in registry.get_definitions()}

    assert report.profile == "core"
    assert report.tool_count == len(names)
    assert {"read_file", "write_file", "web_search", "calculate"} <= names
    assert "load_data" not in names
    assert "run_python_code" not in names
    assert not any(name.startswith("skill_") for name in names)
    assert report.contributor_tool_counts == {}


def test_core_is_the_only_agent_tool_profile():
    from app.core.agent.tool_profiles import get_tool_profile, profile_names

    assert profile_names() == ("core",)
    with pytest.raises(ValueError, match="expected one of: core"):
        get_tool_profile("legacy_full")


def test_core_profile_composes_admitted_addons_without_legacy_adapter(monkeypatch):
    from app.core.agent import addons
    from app.core.agent.kernel import ToolSpec
    from app.core.agent.tool_profiles import build_tool_registry

    spec = ToolSpec(
        name="external_contract_search",
        description="Search contract evidence",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=lambda query: {"answer": query},
        source="plugin:com.bank.legal",
        capabilities=("legal.lookup",),
        read_only=True,
    )
    monkeypatch.setattr(
        addons,
        "get_addon_runtime",
        lambda: type(
            "Runtime",
            (),
            {"tool_specs": lambda self, names=None: (spec,) if names else ()},
        )(),
    )

    registry, report = build_tool_registry(
        profile_name="core",
        addon_tool_names=("external_contract_search",),
    )
    names = {item["name"] for item in registry.get_definitions()}

    assert "external_contract_search" in names
    assert report.contributor_tool_counts["addons"] == 1
    assert "skills" not in report.contributor_tool_counts


def test_create_agent_is_deterministic_kernel_by_default(monkeypatch):
    import app.core.agent.kernel_agent as kernel_agent
    from app.core.agent import factory
    from app.core.agent.tool_registry import ToolRegistry
    from app.core.llm import model_selection, provider_factory

    observed = {}
    fake_provider = object()

    class FakeKernelAgent:
        def __init__(self, **kwargs):
            observed.update(kwargs)

    monkeypatch.setattr(
        model_selection, "get_configured_cloud_provider", lambda: "fake"
    )
    monkeypatch.setattr(
        model_selection,
        "get_configured_cloud_model",
        lambda **kwargs: "fake-model",
    )
    monkeypatch.setattr(
        provider_factory,
        "get_llm_provider",
        lambda **kwargs: fake_provider,
    )
    monkeypatch.setattr(kernel_agent, "KernelAgent", FakeKernelAgent)
    monkeypatch.setattr(factory, "_configure_output_validator", lambda *args: None)
    monkeypatch.setattr(factory, "_build_registry", lambda **kwargs: ToolRegistry())
    agent = factory.create_agent()

    assert isinstance(agent, FakeKernelAgent)
    assert observed["llm_provider"] is fake_provider
    assert observed["model_id"] == "fake-model"


def test_agent_stream_uses_one_production_runtime(monkeypatch):
    from app.core.agent import kernel_agent_service
    from app.core.agent.types import AgentStep, AgentStepType
    from web.services.chat_stream.agent_handler import handle_agent_task

    calls = {"factory": 0, "saved": 0}

    class FakeAgent:
        def run(self, **kwargs):
            yield AgentStep(AgentStepType.ANSWER, "完成")

    class SessionManager:
        def append_and_save(self, *args):
            calls["saved"] += 1

    def fake_get_kernel_agent(**kwargs):
        calls["factory"] += 1
        assert kwargs["tool_profile"] == "core"
        return FakeAgent()

    monkeypatch.setattr(kernel_agent_service, "get_kernel_agent", fake_get_kernel_agent)
    app = Flask(__name__)
    with app.test_request_context("/"):
        response = handle_agent_task(
            "AGENT",
            "session",
            "处理任务",
            [],
            "cloud",
            "router",
            None,
            SessionManager(),
            app.logger,
            lambda *args, **kwargs: None,
            lambda payload: f"data: {json.dumps(payload, ensure_ascii=False)}\n\n",
        )
        body = response.get_data(as_text=True)

    assert calls == {"factory": 1, "saved": 1}
    assert '"engine": "kernel"' in body
    assert "完成" in body
    assert "LangGraph" not in body


def test_local_mode_addon_task_uses_local_kernel_agent(monkeypatch):
    from app.core.agent import kernel_agent_service
    from app.core.agent.types import AgentStep, AgentStepType
    from app.core.shared import llm_helpers
    from web.services.chat_stream.agent_handler import handle_agent_task

    observed = {}

    class FakeAgent:
        def run(self, **kwargs):
            observed["run"] = kwargs
            yield AgentStep(AgentStepType.ANSWER, "本地 Addon 完成")

    class SessionManager:
        def append_and_save(self, *args):
            pass

    monkeypatch.setattr(llm_helpers, "is_ollama_alive", lambda: True)
    monkeypatch.setattr(
        kernel_agent_service,
        "get_kernel_agent",
        lambda **kwargs: observed.update(
            profile=kwargs["tool_profile"], local=kwargs["local"]
        )
        or FakeAgent(),
    )
    addon_plan = {
        "addon_ids": ["com.bank.legal"],
        "tool_names": ["legal_lookup"],
    }
    app = Flask(__name__)
    with app.test_request_context("/"):
        response = handle_agent_task(
            "AGENT",
            "session",
            "核对合同",
            [],
            "local",
            "addon",
            addon_plan,
            SessionManager(),
            app.logger,
            lambda *args, **kwargs: None,
            lambda payload: f"data: {json.dumps(payload, ensure_ascii=False)}\n\n",
        )
        body = response.get_data(as_text=True)

    assert observed["profile"] == "core"
    assert observed["local"] is True
    assert observed["run"]["addon_tool_names"] == ("legal_lookup",)
    assert "本地 Addon 完成" in body
