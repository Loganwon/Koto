from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pytest
from flask import Flask, g, request

from app.api.plugin_protocol_routes import plugin_protocol_bp
from app.core.agent.addons import (
    AddonAuditStore,
    AddonRegistrationStore,
    AddonTaskRequest,
    get_addon_runtime,
    register_addon_factory,
    set_addon_runtime,
    set_addon_store,
)
from app.core.agent.addons.audit import set_addon_audit_store
from app.core.agent.addons.bootstrap import clear_addon_factories
from app.core.agent.kernel import ToolSpec
from app.core.agent.kernel_agent import KernelAgent
from app.core.agent.plugin_protocol import (
    RETRIEVAL_BATCH_JSON_SCHEMA,
    RETRIEVAL_REQUEST_JSON_SCHEMA,
    AddonInvocationContext,
    EvidenceChunk,
    PluginHealth,
    PluginHealthStatus,
    PluginProtocolError,
    RetrievalBatch,
    RetrieverSpec,
)
from app.core.agent.tool_profiles import build_tool_registry
from app.core.agent.types import AgentStepType

ADDON_ID = "com.test.bank-legal"


@pytest.fixture(autouse=True)
def _isolated_addon_state(tmp_path):
    store = AddonRegistrationStore(tmp_path / "addons.json")
    audit = AddonAuditStore(tmp_path / "addon-audit.sqlite")
    set_addon_store(store)
    set_addon_audit_store(audit)
    set_addon_runtime(None)
    clear_addon_factories()
    yield store
    set_addon_runtime(None)
    set_addon_store(None)
    set_addon_audit_store(None)
    clear_addon_factories()


def _tool_contribution(name: str, capability: str) -> dict[str, Any]:
    return {
        "id": name,
        "kind": "tool",
        "name": name,
        "description": f"Mock contribution {name}.",
        "capabilities": [capability],
        "permissions": ["database.read"],
        "read_only": True,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 1}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
        "timeout_seconds": 5,
    }


def _retriever_contribution() -> dict[str, Any]:
    return {
        "id": "mock_legal_history",
        "kind": "retriever",
        "name": "mock_legal_history",
        "description": "Retrieve tenant-scoped mock legal history.",
        "capabilities": ["legal.history.retrieve"],
        "permissions": ["database.read"],
        "read_only": True,
        "input_schema": dict(RETRIEVAL_REQUEST_JSON_SCHEMA),
        "output_schema": dict(RETRIEVAL_BATCH_JSON_SCHEMA),
        "timeout_seconds": 5,
    }


def _manifest() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plugin_id": ADDON_ID,
        "version": "1.0.0",
        "api_version": "1",
        "name": "Mock Bank Legal Addon",
        "description": "End-to-end Addon integration fixture.",
        "publisher": "Koto Test",
        "runtime": {"transport": "in_process", "entrypoint": "test:MockAddon"},
        "permissions": ["database.read"],
        "contributions": [
            _tool_contribution("mock_contract_lookup", "legal.contract.lookup"),
            _tool_contribution("mock_company_lookup", "business.company.lookup"),
            _retriever_contribution(),
        ],
        "dependencies": [],
        "limits": {
            "max_timeout_seconds": 10,
            "max_result_bytes": 16_384,
            "max_concurrency": 2,
            "max_rag_chunks": 8,
        },
        "data_policy": {
            "accepts": ["internal", "confidential"],
            "emits": ["internal"],
            "persistence": "none",
            "retention_days": 0,
            "tenant_isolation": True,
            "sends_data_external": False,
        },
        "config_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "secret_names": [],
    }


def _registration() -> dict[str, Any]:
    return {
        "manifest": _manifest(),
        "bindings": [
            {
                "contribution_name": "mock_contract_lookup",
                "task_types": ["CHAT", "LEGAL"],
                "intent_patterns": ["合同"],
                "priority": 90,
            },
            {
                "contribution_name": "mock_company_lookup",
                "task_types": ["BUSINESS"],
                "intent_patterns": ["企业背景"],
                "priority": 80,
            },
            {
                "contribution_name": "mock_legal_history",
                "task_types": ["CHAT", "LEGAL"],
                "intent_patterns": ["历史依据"],
                "priority": 85,
            },
        ],
        "granted_permissions": ["database.read"],
        "config": {},
        "secret_bindings": {},
    }


@dataclass
class _MockAddonState:
    tool_queries: list[tuple[str, str]] = field(default_factory=list)
    retrieval_requests: list[Any] = field(default_factory=list)
    initialized: bool = False
    stopped: bool = False


class _MockAddon:
    def __init__(self, manifest, state: _MockAddonState):
        self._manifest = manifest
        self._state = state

    @property
    def manifest(self):
        return self._manifest

    def initialize(self, context):
        assert context.plugin_id == ADDON_ID
        self._state.initialized = True

    def health(self):
        return PluginHealth(PluginHealthStatus.HEALTHY, "mock ready")

    def shutdown(self):
        self._state.stopped = True

    def tool_specs(self):
        contributions = {
            item.name: item
            for item in self._manifest.contributions
            if item.kind.value == "tool"
        }

        def handler(name: str):
            def execute(invocation_context, query: str):
                invocation_context.require_identity()
                self._state.tool_queries.append((name, query))
                return {"answer": f"{name} matched: {query}"}

            return execute

        return tuple(
            ToolSpec(
                name=name,
                description=item.description,
                input_schema=item.input_schema,
                handler=handler(name),
                source=f"plugin:{ADDON_ID}",
                version=self._manifest.version,
                capabilities=item.capabilities,
                read_only=True,
                timeout_seconds=5,
                requires_invocation_context=True,
            )
            for name, item in contributions.items()
        )

    def retriever_specs(self):
        def retrieve(request):
            self._state.retrieval_requests.append(request)
            return RetrievalBatch(
                provider_id="mock_legal_history",
                correlation_id=request.correlation_id,
                chunks=(
                    EvidenceChunk(
                        chunk_id="case-2025-001",
                        text="历史合同约定争议适用甲方所在地法院。",
                        source_uri="mock-law://case/2025-001",
                        source_title="历史合同案例 2025-001",
                        citation="案例 2025-001，第 4 页",
                        score=0.93,
                        metadata={"document_type": "contract_case"},
                        acl_tags=(f"tenant:{request.tenant_id}",),
                    ),
                ),
            )

        return (
            RetrieverSpec(
                name="mock_legal_history",
                description="Retrieve tenant-scoped mock legal history.",
                handler=retrieve,
                source=f"plugin:{ADDON_ID}",
                version=self._manifest.version,
                capabilities=("legal.history.retrieve",),
                timeout_seconds=5,
            ),
        )


class _MockModelProvider:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return {
                "content": "先查询已准入的合同数据。",
                "tool_calls": [
                    {
                        "id": "mock-call-1",
                        "name": "mock_contract_lookup",
                        "args": {"query": "核对合同历史依据"},
                    }
                ],
            }
        return {"content": "合同核验完成，并保留历史依据引用。"}


def _client() -> Any:
    app = Flask(__name__)
    app.config.update(TESTING=True)
    app.register_blueprint(plugin_protocol_bp)
    return app.test_client()


def test_mock_addon_complete_task_flow(_isolated_addon_state):
    state = _MockAddonState()
    client = _client()

    registered = client.post("/api/plugin-protocol/registrations", json=_registration())
    assert registered.status_code == 201
    assert registered.get_json()["addon"]["enabled"] is False
    assert get_addon_runtime().catalog_snapshot()["total"] == 0

    register_addon_factory(
        ADDON_ID,
        lambda manifest, _config: _MockAddon(manifest, state),
    )
    enabled = client.put(
        f"/api/plugin-protocol/registrations/{ADDON_ID}/enabled",
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.get_json()["runtime"]["admitted"] == [ADDON_ID]
    assert state.initialized is True

    runtime = get_addon_runtime()
    plan = runtime.plan(AddonTaskRequest("CHAT", "核对合同历史依据"))
    assert plan.addon_ids == (ADDON_ID,)
    assert plan.tool_names == ("mock_contract_lookup",)
    assert plan.retriever_names == ("mock_legal_history",)
    assert "mock_company_lookup" not in plan.tool_names

    batches = runtime.retrieve(
        plan,
        query="核对合同历史依据",
        tenant_id="bank-a",
        principal_id="employee-7",
        correlation_id="mock-task-1",
    )
    assert batches[0].chunks[0].citation == "案例 2025-001，第 4 页"
    assert batches[0].chunks[0].acl_tags == ("tenant:bank-a",)
    assert state.retrieval_requests[0].principal_id == "employee-7"

    unplanned_registry, _ = build_tool_registry(profile_name="core")
    planned_registry, report = build_tool_registry(
        profile_name="core", addon_tool_names=plan.tool_names
    )
    unplanned_names = {item["name"] for item in unplanned_registry.get_definitions()}
    planned_names = {item["name"] for item in planned_registry.get_definitions()}
    assert "mock_contract_lookup" not in unplanned_names
    assert "mock_contract_lookup" in planned_names
    assert "mock_company_lookup" not in planned_names
    assert report.contributor_tool_counts["addons"] == 1

    provider = _MockModelProvider()
    agent = KernelAgent(
        llm_provider=provider,
        tool_registry=planned_registry,
        model_id="mock-model",
        enable_pii_filter=False,
        enable_output_validation=False,
        use_tool_router=False,
        allow_model_fallback=False,
    )
    steps = list(
        agent.run(
            input_text="核对合同历史依据",
            session_id="mock-session",
            addon_tool_names=plan.tool_names,
            addon_plan=plan.to_dict(),
            addon_invocation_context=AddonInvocationContext(
                tenant_id="tenant-mock",
                principal_id="employee-mock",
                purpose_code="contract_review",
                correlation_id="mock-agent-run",
            ),
            record_task=False,
        )
    )

    assert [step.step_type for step in steps] == [
        AgentStepType.THOUGHT,
        AgentStepType.ACTION,
        AgentStepType.OBSERVATION,
        AgentStepType.ANSWER,
    ]
    assert steps[-1].content == "合同核验完成，并保留历史依据引用。"
    assert state.tool_queries == [("mock_contract_lookup", "核对合同历史依据")]
    first_call_tools = {item["name"] for item in provider.calls[0]["tools"]}
    assert "mock_contract_lookup" in first_call_tools
    assert "mock_company_lookup" not in first_call_tools
    assert ADDON_ID in provider.calls[0]["system_instruction"]
    assert '"ok":true' in provider.calls[1]["prompt"][-1]["content"]

    audit = client.get("/api/plugin-protocol/audit?limit=100").get_json()
    event_types = {event["event"] for event in audit["events"]}
    assert "plugin.tool.started" in event_types
    assert "plugin.tool.succeeded" in event_types
    assert "plugin.retriever.started" in event_types
    assert "plugin.retriever.succeeded" in event_types
    tool_started = next(
        event for event in audit["events"] if event["event"] == "plugin.tool.started"
    )
    assert tool_started["tenant_id"] == "tenant-mock"
    assert tool_started["principal_id"] == "employee-mock"
    assert tool_started["purpose_code"] == "contract_review"

    disabled = client.put(
        f"/api/plugin-protocol/registrations/{ADDON_ID}/enabled",
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    refreshed = get_addon_runtime()
    assert refreshed.plan(AddonTaskRequest("CHAT", "核对合同历史依据")).matched is False
    assert refreshed.tool_specs() == ()
    assert state.stopped is True


def test_mock_addon_retrieval_fails_closed_without_identity(_isolated_addon_state):
    state = _MockAddonState()
    client = _client()
    assert (
        client.post(
            "/api/plugin-protocol/registrations", json=_registration()
        ).status_code
        == 201
    )
    register_addon_factory(
        ADDON_ID,
        lambda manifest, _config: _MockAddon(manifest, state),
    )
    assert (
        client.put(
            f"/api/plugin-protocol/registrations/{ADDON_ID}/enabled",
            json={"enabled": True},
        ).status_code
        == 200
    )

    runtime = get_addon_runtime()
    plan = runtime.plan(AddonTaskRequest("CHAT", "核对合同历史依据"))
    with pytest.raises(PluginProtocolError, match="tenant_id"):
        runtime.retrieve(
            plan,
            query="核对合同历史依据",
            tenant_id="",
            principal_id="employee-7",
            correlation_id="mock-task-no-identity",
        )

    assert state.retrieval_requests == []


def test_chat_orchestrator_plans_mock_addon_and_injects_cited_evidence(
    _isolated_addon_state, monkeypatch
):
    from app.core.llm import provider_factory
    from app.core.services import graph_rag_service, rag_service
    from web.services.chat_stream.orchestrator import setup_chat_stream_context

    state = _MockAddonState()
    client = _client()
    assert (
        client.post(
            "/api/plugin-protocol/registrations", json=_registration()
        ).status_code
        == 201
    )
    register_addon_factory(
        ADDON_ID,
        lambda manifest, _config: _MockAddon(manifest, state),
    )
    assert (
        client.put(
            f"/api/plugin-protocol/registrations/{ADDON_ID}/enabled",
            json={"enabled": True},
        ).status_code
        == 200
    )

    monkeypatch.setattr(
        rag_service,
        "get_rag_service",
        lambda: type(
            "EmptyRag",
            (),
            {
                "stats": lambda self: {"initialized": False},
                "hybrid_retrieve": lambda self, *_args, **_kwargs: [],
            },
        )(),
    )
    monkeypatch.setattr(
        graph_rag_service.GraphRAGService,
        "retrieve",
        staticmethod(lambda *_args, **_kwargs: ""),
    )
    monkeypatch.setattr(provider_factory, "is_local_mode", lambda: False)

    class SessionManager:
        @staticmethod
        def load(_name):
            return []

        @staticmethod
        def load_full(_name):
            return []

    class SettingsManager:
        @staticmethod
        def get(_section, _key):
            return False

    class Utils:
        @staticmethod
        def sanitize_string(value):
            return value

    class WebSearcher:
        @staticmethod
        def needs_web_search(_text):
            return False

    app = Flask(__name__)
    payload = {
        "session": "mock-chat-session",
        "message": "核对合同历史依据",
        "locked_task": "CHAT",
        "locked_model": "cloud",
        # This must never override the identity resolved by the host.
        "tenant_id": "attacker-controlled-tenant",
    }
    with app.test_request_context("/api/chat/stream", method="POST", json=payload):
        g.request_id = "mock-web-request"
        result = setup_chat_stream_context(
            request,
            SessionManager(),
            SettingsManager(),
            logging.getLogger("mock-addon-orchestrator"),
            None,
            Utils,
            lambda: None,
            WebSearcher,
            lambda _text: "base system instruction",
            lambda: "fallback system instruction",
            lambda _text: "",
            {},
            {},
            lambda *_args, **_kwargs: "mock-model",
            lambda model_id: model_id,
            API_KEY="mock-api-key",
        )

    assert result["early_response"] is None
    context = result["context"]
    assert context["task_type"] == "AGENT"
    assert context["route_method"] == "🔌 Add-on"
    assert context["_addon_runtime_plan"]["tool_names"] == ["mock_contract_lookup"]
    assert context["_addon_runtime_plan"]["retriever_names"] == ["mock_legal_history"]
    assert "## Addon 检索证据" in context["system_instruction"]
    assert "历史合同案例 2025-001" in context["system_instruction"]
    assert "案例 2025-001，第 4 页" in context["system_instruction"]
    assert state.retrieval_requests[0].tenant_id == "local"
    assert state.retrieval_requests[0].principal_id == "local"
    assert state.retrieval_requests[0].correlation_id == "mock-web-request"
