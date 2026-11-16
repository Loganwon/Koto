from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.core.agent.addons import (
    AddonBinding,
    AddonRegistrationStore,
    AddonRuntime,
    AddonTaskRequest,
    refresh_addon_runtime,
    register_addon_factory,
    set_addon_runtime,
    set_addon_store,
)
from app.core.agent.addons.bootstrap import clear_addon_factories
from app.core.agent.kernel import ToolSpec
from app.core.agent.plugin_protocol import (
    RETRIEVAL_BATCH_JSON_SCHEMA,
    RETRIEVAL_REQUEST_JSON_SCHEMA,
    EvidenceChunk,
    PluginAdmissionPolicy,
    PluginHealth,
    PluginHealthStatus,
    PluginHostContext,
    PluginPermission,
    PluginProtocolError,
    PluginTransport,
    RetrievalBatch,
    RetrieverSpec,
    manifest_from_dict,
)


@pytest.fixture(autouse=True)
def _reset_global_runtime():
    set_addon_runtime(None)
    set_addon_store(None)
    clear_addon_factories()
    yield
    set_addon_runtime(None)
    set_addon_store(None)
    clear_addon_factories()


def _payload(contributions: list[dict], *, addon_id: str = "com.test.office") -> dict:
    return {
        "schema_version": "1.0",
        "plugin_id": addon_id,
        "version": "1.0.0",
        "api_version": "1",
        "name": "Office Add-on",
        "description": "Task routing fixture.",
        "publisher": "Koto Test",
        "runtime": {"transport": "in_process", "entrypoint": "test:Addon"},
        "permissions": ["database.read"],
        "contributions": contributions,
        "dependencies": [],
        "limits": {
            "max_timeout_seconds": 20,
            "max_result_bytes": 4096,
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


def _tool_contribution(name: str, capability: str) -> dict:
    return {
        "id": name,
        "kind": "tool",
        "name": name,
        "description": f"Run {name}.",
        "capabilities": [capability],
        "permissions": ["database.read"],
        "read_only": True,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
        "timeout_seconds": 10,
    }


class _Addon:
    def __init__(self, manifest, tools=(), retrievers=()):
        self._manifest = manifest
        self._tools = tuple(tools)
        self._retrievers = tuple(retrievers)
        self.initialized = False
        self.stopped = False

    @property
    def manifest(self):
        return self._manifest

    def tool_specs(self):
        return self._tools

    def retriever_specs(self):
        return self._retrievers

    def initialize(self, context):
        assert context.plugin_id == self._manifest.plugin_id
        self.initialized = True

    def health(self):
        return PluginHealth(PluginHealthStatus.HEALTHY)

    def shutdown(self):
        self.stopped = True


def _host_and_policy(addon_id: str):
    permissions = frozenset({PluginPermission.DATABASE_READ})
    host = PluginHostContext(
        plugin_id=addon_id,
        granted_permissions=permissions,
        config={},
        declared_secret_names=frozenset(),
        secret_resolver=lambda _name: "",
        emit_audit=lambda _event: None,
    )
    policy = PluginAdmissionPolicy(
        granted_permissions=permissions,
        allowed_transports=frozenset({PluginTransport.IN_PROCESS}),
    )
    return host, policy


def _admit_office_addon(runtime: AddonRuntime):
    entries = [
        ("legal_contract_lookup", "legal.contract.lookup"),
        ("business_background_lookup", "business.background.lookup"),
        ("bank_account_lookup", "bank.account.lookup"),
        ("office_document_reader", "document.read"),
    ]
    manifest = manifest_from_dict(
        _payload([_tool_contribution(name, cap) for name, cap in entries])
    )
    specs = tuple(
        ToolSpec(
            name=item.name,
            description=item.description,
            input_schema=item.input_schema,
            handler=lambda invocation_context, query: {"answer": query},
            source=f"plugin:{manifest.plugin_id}",
            version=manifest.version,
            capabilities=item.capabilities,
            read_only=True,
            timeout_seconds=10,
            requires_invocation_context=True,
        )
        for item in manifest.contributions
    )
    addon = _Addon(manifest, tools=specs)
    host, policy = _host_and_policy(manifest.plugin_id)
    runtime.admit(
        addon,
        host_context=host,
        policy=policy,
        bindings=(
            AddonBinding(
                "legal_contract_lookup",
                task_types=("CHAT", "LEGAL"),
                intent_patterns=("合同", "条款"),
                priority=90,
            ),
            AddonBinding(
                "business_background_lookup",
                task_types=("CHAT", "BUSINESS"),
                intent_patterns=("工商", "企业背景"),
                priority=85,
            ),
            AddonBinding(
                "bank_account_lookup",
                task_types=("CHAT", "DATABASE"),
                intent_patterns=("账户", "客户记录"),
                priority=80,
            ),
            AddonBinding(
                "office_document_reader",
                task_types=("FILE_GEN", "DOC_ANNOTATE"),
                file_types=("docx", "pdf", "xlsx"),
                priority=75,
            ),
        ),
    )
    return addon


@pytest.mark.parametrize(
    ("task_request", "expected"),
    [
        (AddonTaskRequest("CHAT", "对比这份合同的历史条款"), "legal_contract_lookup"),
        (
            AddonTaskRequest("BUSINESS", "调查企业背景和工商信息"),
            "business_background_lookup",
        ),
        (AddonTaskRequest("DATABASE", "核对客户账户记录"), "bank_account_lookup"),
        (
            AddonTaskRequest("DOC_ANNOTATE", "读取附件", file_types=("docx",)),
            "office_document_reader",
        ),
    ],
)
def test_addon_runtime_routes_business_and_file_tasks(task_request, expected):
    runtime = AddonRuntime()
    _admit_office_addon(runtime)

    plan = runtime.plan(task_request)

    assert expected in plan.tool_names
    assert plan.addon_ids == ("com.test.office",)


def test_file_binding_requires_an_actual_matching_file_type():
    runtime = AddonRuntime()
    _admit_office_addon(runtime)

    no_file = runtime.plan(AddonTaskRequest("DOC_ANNOTATE", "读取附件"))
    wrong_file = runtime.plan(
        AddonTaskRequest("DOC_ANNOTATE", "读取附件", file_types=("png",))
    )

    assert "office_document_reader" not in no_file.tool_names
    assert "office_document_reader" not in wrong_file.tool_names


def test_one_contribution_can_have_multiple_independent_routing_bindings():
    manifest = manifest_from_dict(
        _payload([_tool_contribution("document_lookup", "document.lookup")])
    )
    contribution = manifest.contributions[0]
    spec = ToolSpec(
        name=contribution.name,
        description=contribution.description,
        input_schema=contribution.input_schema,
        handler=lambda invocation_context, query: {"answer": query},
        source=f"plugin:{manifest.plugin_id}",
        version=manifest.version,
        capabilities=contribution.capabilities,
        read_only=True,
        timeout_seconds=10,
        requires_invocation_context=True,
    )
    runtime = AddonRuntime()
    host, policy = _host_and_policy(manifest.plugin_id)
    runtime.admit(
        _Addon(manifest, tools=(spec,)),
        host_context=host,
        policy=policy,
        bindings=(
            AddonBinding(
                "document_lookup",
                task_types=("LEGAL",),
                intent_patterns=("合同",),
            ),
            AddonBinding(
                "document_lookup",
                task_types=("DOC_ANNOTATE",),
                file_types=("pdf",),
            ),
        ),
    )

    legal = runtime.plan(AddonTaskRequest("LEGAL", "分析合同"))
    document = runtime.plan(
        AddonTaskRequest("DOC_ANNOTATE", "读取附件", file_types=("pdf",))
    )

    assert legal.tool_names == ("document_lookup",)
    assert document.tool_names == ("document_lookup",)


def test_disable_removes_addon_from_planning_but_keeps_lifecycle_explicit():
    runtime = AddonRuntime()
    addon = _admit_office_addon(runtime)
    runtime.set_enabled("com.test.office", False)

    plan = runtime.plan(AddonTaskRequest("CHAT", "查询合同条款"))

    assert plan.matched is False
    assert plan.rejected["com.test.office"] == "disabled"
    assert addon.stopped is False
    assert runtime.tool_specs() == ()


def test_shutdown_is_terminal_until_addon_is_admitted_again():
    runtime = AddonRuntime()
    addon = _admit_office_addon(runtime)
    runtime.shutdown("com.test.office")

    assert addon.stopped is True
    assert runtime.tool_specs() == ()
    with pytest.raises(PluginProtocolError, match="must be admitted again"):
        runtime.set_enabled("com.test.office", True)


def test_unknown_binding_fails_before_addon_initialization():
    manifest = manifest_from_dict(
        _payload([_tool_contribution("legal_lookup", "legal.lookup")])
    )
    addon = _Addon(manifest)
    host, policy = _host_and_policy(manifest.plugin_id)

    with pytest.raises(PluginProtocolError, match="undeclared"):
        AddonRuntime().admit(
            addon,
            host_context=host,
            policy=policy,
            bindings=(AddonBinding("missing_tool", task_types=("LEGAL",)),),
        )

    assert addon.initialized is False


def test_retrieval_requires_identity_and_uses_only_planned_retrievers():
    contribution = {
        "id": "legal_history",
        "kind": "retriever",
        "name": "legal_history",
        "description": "Retrieve historical legal evidence.",
        "capabilities": ["legal.history.retrieve"],
        "permissions": ["database.read"],
        "read_only": True,
        "input_schema": dict(RETRIEVAL_REQUEST_JSON_SCHEMA),
        "output_schema": dict(RETRIEVAL_BATCH_JSON_SCHEMA),
        "timeout_seconds": 10,
    }
    manifest = manifest_from_dict(
        _payload([contribution], addon_id="com.test.legal-rag")
    )

    def retrieve(request):
        return RetrievalBatch(
            provider_id="legal_history",
            correlation_id=request.correlation_id,
            chunks=(
                EvidenceChunk(
                    chunk_id="law-1",
                    text="历史判例事实",
                    source_uri="law://case/1",
                    source_title="判例一",
                    citation="判例一，第2页",
                    acl_tags=(f"tenant:{request.tenant_id}",),
                ),
            ),
        )

    spec = RetrieverSpec(
        name="legal_history",
        description=contribution["description"],
        handler=retrieve,
        source=f"plugin:{manifest.plugin_id}",
        version=manifest.version,
        capabilities=("legal.history.retrieve",),
        timeout_seconds=10,
    )
    runtime = AddonRuntime()
    host, policy = _host_and_policy(manifest.plugin_id)
    runtime.admit(
        _Addon(manifest, retrievers=(spec,)),
        host_context=host,
        policy=policy,
        bindings=(
            AddonBinding(
                "legal_history",
                task_types=("LEGAL",),
                intent_patterns=("历史判例",),
            ),
        ),
    )
    plan = runtime.plan(AddonTaskRequest("LEGAL", "对比历史判例"))

    with pytest.raises(PluginProtocolError, match="tenant_id"):
        runtime.retrieve(
            plan,
            query="历史判例",
            tenant_id="",
            principal_id="u1",
            correlation_id="corr-1",
        )
    batches = runtime.retrieve(
        plan,
        query="历史判例",
        tenant_id="bank-a",
        principal_id="u1",
        correlation_id="corr-1",
    )

    assert plan.retriever_names == ("legal_history",)
    assert batches[0].chunks[0].citation == "判例一，第2页"


def test_retriever_timeout_is_enforced_at_runtime():
    contribution = {
        "id": "slow_history",
        "kind": "retriever",
        "name": "slow_history",
        "description": "Slow retrieval fixture.",
        "capabilities": ["legal.history.retrieve"],
        "permissions": ["database.read"],
        "read_only": True,
        "input_schema": dict(RETRIEVAL_REQUEST_JSON_SCHEMA),
        "output_schema": dict(RETRIEVAL_BATCH_JSON_SCHEMA),
        "timeout_seconds": 0.02,
    }
    manifest = manifest_from_dict(
        _payload([contribution], addon_id="com.test.slow-rag")
    )

    def retrieve(request):
        time.sleep(0.2)
        return RetrievalBatch(
            provider_id="slow_history",
            correlation_id=request.correlation_id,
            chunks=(),
        )

    runtime = AddonRuntime()
    host, policy = _host_and_policy(manifest.plugin_id)
    runtime.admit(
        _Addon(
            manifest,
            retrievers=(
                RetrieverSpec(
                    name="slow_history",
                    description="Slow retrieval fixture.",
                    handler=retrieve,
                    source=f"plugin:{manifest.plugin_id}",
                    version=manifest.version,
                    capabilities=("legal.history.retrieve",),
                    timeout_seconds=0.02,
                ),
            ),
        ),
        host_context=host,
        policy=policy,
        bindings=(
            AddonBinding(
                "slow_history",
                task_types=("LEGAL",),
                intent_patterns=("历史",),
            ),
        ),
    )
    plan = runtime.plan(AddonTaskRequest("LEGAL", "查询历史"))
    started = time.monotonic()

    with pytest.raises(PluginProtocolError, match="timed out"):
        runtime.retrieve(
            plan,
            query="历史",
            tenant_id="bank-a",
            principal_id="u1",
            correlation_id="corr-timeout",
        )

    assert time.monotonic() - started < 0.15


def test_addon_runtime_has_no_skill_dependency():
    addon_dir = Path("app/core/agent/addons")
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in addon_dir.glob("*.py")
    )

    assert "app.core.skills" not in source
    assert "SkillManager" not in source


def test_registration_store_keeps_connection_data_declarative(tmp_path):
    manifest_payload = _payload(
        [_tool_contribution("legal_lookup", "legal.lookup")],
        addon_id="com.test.registered",
    )
    store = AddonRegistrationStore(tmp_path / "addons.json")

    record = store.register(
        manifest_payload,
        bindings=(
            {
                "contribution_name": "legal_lookup",
                "task_types": ["LEGAL"],
                "intent_patterns": ["合同"],
                "priority": 80,
            },
        ),
        granted_permissions=("database.read",),
    )

    assert record["state"] == "registered"
    assert record["enabled"] is False
    assert record["tools"] == ["legal_lookup"]
    persisted = store.get_record("com.test.registered")
    assert persisted["manifest"]["plugin_id"] == "com.test.registered"
    assert "secret_values" not in persisted


def test_bootstrap_admits_enabled_trusted_factory_into_agent_runtime(tmp_path):
    addon_id = "com.test.bootstrapped"
    manifest_payload = _payload(
        [_tool_contribution("legal_lookup", "legal.lookup")],
        addon_id=addon_id,
    )
    store = AddonRegistrationStore(tmp_path / "addons.json")
    store.register(
        manifest_payload,
        bindings=(
            {
                "contribution_name": "legal_lookup",
                "task_types": ["LEGAL"],
                "intent_patterns": ["合同"],
                "priority": 80,
            },
        ),
        granted_permissions=("database.read",),
    )
    store.set_enabled(addon_id, True)
    set_addon_store(store)

    def factory(manifest, _config):
        contribution = manifest.contributions[0]
        return _Addon(
            manifest,
            tools=(
                ToolSpec(
                    name=contribution.name,
                    description=contribution.description,
                    input_schema=contribution.input_schema,
                    handler=lambda invocation_context, query: {"answer": query},
                    source=f"plugin:{manifest.plugin_id}",
                    version=manifest.version,
                    capabilities=contribution.capabilities,
                    read_only=True,
                    timeout_seconds=10,
                    requires_invocation_context=True,
                ),
            ),
        )

    register_addon_factory(addon_id, factory)
    report = refresh_addon_runtime(store=store)
    from app.core.agent.addons import get_addon_runtime

    runtime = get_addon_runtime()
    plan = runtime.plan(AddonTaskRequest("LEGAL", "检查合同"))

    from app.core.agent.tool_profiles import build_tool_registry

    unplanned_registry, _ = build_tool_registry(profile_name="core")
    planned_registry, _ = build_tool_registry(
        profile_name="core", addon_tool_names=plan.tool_names
    )

    assert report.admitted == (addon_id,)
    assert plan.tool_names == ("legal_lookup",)
    assert "legal_lookup" not in {
        item["name"] for item in unplanned_registry.get_definitions()
    }
    assert "legal_lookup" in {
        item["name"] for item in planned_registry.get_definitions()
    }
    assert store.public_record(addon_id)["state"] == "admitted"

    # Simulate a second Gunicorn worker changing the shared registry.  The
    # next runtime access in this worker must observe the new revision.
    second_worker_store = AddonRegistrationStore(store.path)
    previous_revision = store.revision()
    second_worker_store.set_enabled(addon_id, False)
    assert second_worker_store.revision() == previous_revision + 1

    refreshed = get_addon_runtime()
    disabled_plan = refreshed.plan(AddonTaskRequest("LEGAL", "检查合同"))
    assert disabled_plan.matched is False
    assert refreshed.catalog_snapshot()["total"] == 0
