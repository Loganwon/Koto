from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.core.agent.kernel import (
    ToolCall,
    ToolCatalog,
    ToolErrorCode,
    ToolExecutor,
    ToolSpec,
)
from app.core.agent.plugin_protocol import (
    RETRIEVAL_BATCH_JSON_SCHEMA,
    RETRIEVAL_REQUEST_JSON_SCHEMA,
    AddonInvocationContext,
    ContributionKind,
    DataClassification,
    EvidenceChunk,
    PluginAdmissionController,
    PluginAdmissionPolicy,
    PluginHostContext,
    PluginManifestV1,
    PluginPermission,
    PluginProtocolError,
    PluginTransport,
    RetrievalBatch,
    RetrievalRequest,
    RetrieverSpec,
    manifest_digest,
    manifest_from_dict,
    manifest_to_dict,
)


def _manifest_payload(*, kind: str = "tool", name: str = "example_lookup") -> dict:
    return {
        "schema_version": "1.0",
        "plugin_id": "com.example.connector",
        "version": "1.2.3",
        "api_version": "1",
        "name": "Example Connector",
        "description": "Protocol conformance fixture.",
        "publisher": "Example Publisher",
        "runtime": {
            "transport": "in_process",
            "entrypoint": "example.connector:Plugin",
        },
        "permissions": ["database.read"],
        "contributions": [
            {
                "id": "lookup",
                "kind": kind,
                "name": name,
                "description": "Look up evidence.",
                "capabilities": ["knowledge.lookup"],
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
        ],
        "dependencies": [],
        "limits": {
            "max_timeout_seconds": 30,
            "max_result_bytes": 2048,
            "max_concurrency": 2,
            "max_rag_chunks": 4,
        },
        "data_policy": {
            "accepts": ["internal"],
            "emits": ["internal"],
            "persistence": "none",
            "retention_days": 0,
            "tenant_isolation": True,
            "sends_data_external": False,
        },
        "config_schema": {
            "type": "object",
            "properties": {"index": {"type": "string"}},
            "required": ["index"],
            "additionalProperties": False,
        },
        "secret_names": [],
    }


def _tool(
    manifest: PluginManifestV1, *, handler=lambda query: {"answer": query}
) -> ToolSpec:
    contribution = manifest.contributions[0]

    def context_handler(*, invocation_context, query):
        invocation_context.require_identity()
        return handler(query)

    return ToolSpec(
        name=contribution.name,
        description=contribution.description,
        input_schema=contribution.input_schema,
        handler=context_handler,
        source=f"plugin:{manifest.plugin_id}",
        version=manifest.version,
        capabilities=contribution.capabilities,
        read_only=contribution.read_only,
        timeout_seconds=10,
        requires_invocation_context=True,
    )


def _invocation_context(**overrides) -> AddonInvocationContext:
    values = {
        "tenant_id": "tenant-a",
        "principal_id": "employee-7",
        "purpose_code": "customer_service",
        "correlation_id": "correlation-1",
    }
    values.update(overrides)
    return AddonInvocationContext(**values)


def _policy(**overrides) -> PluginAdmissionPolicy:
    values = {
        "granted_permissions": frozenset({PluginPermission.DATABASE_READ}),
        "allowed_transports": frozenset({PluginTransport.IN_PROCESS}),
    }
    values.update(overrides)
    return PluginAdmissionPolicy(**values)


def test_manifest_roundtrip_and_digest_are_stable() -> None:
    manifest = manifest_from_dict(_manifest_payload())

    assert isinstance(manifest, PluginManifestV1)
    assert manifest.plugin_id == "com.example.connector"
    assert manifest.contributions[0].kind is ContributionKind.TOOL
    assert manifest_from_dict(manifest_to_dict(manifest)) == manifest
    assert manifest_digest(manifest) == manifest_digest(
        manifest_from_dict(copy.deepcopy(manifest_to_dict(manifest)))
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data.update({"unknown": True}), "Additional properties"),
        (
            lambda data: data["permissions"].append("database.admin"),
            "database.admin",
        ),
        (
            lambda data: data["runtime"].update(
                {"transport": "http", "entrypoint": "http://example.test/plugin"}
            ),
            "HTTPS",
        ),
        (
            lambda data: data.update({"secret_names": ["api_key"]}),
            "secrets.use",
        ),
    ],
)
def test_manifest_rejects_undeclared_or_unsafe_contracts(mutation, message) -> None:
    payload = _manifest_payload()
    mutation(payload)

    with pytest.raises((PluginProtocolError, ValueError), match=message):
        manifest_from_dict(payload)


def test_admission_rejects_missing_grants_without_mutating_catalog() -> None:
    manifest = manifest_from_dict(_manifest_payload())
    catalog = ToolCatalog()
    controller = PluginAdmissionController(catalog, PluginAdmissionPolicy())

    report = controller.evaluate(
        manifest,
        tool_specs=[_tool(manifest)],
        config={"index": "customer"},
    )

    assert report.accepted is False
    assert "permissions not granted: database.read" in report.errors
    assert "host policy requires an audit sink" in report.errors
    assert catalog.names() == []


def test_admission_requires_exact_declared_tool_identity_and_source() -> None:
    manifest = manifest_from_dict(_manifest_payload())
    bad = ToolSpec(
        name="example_lookup",
        description="Look up evidence.",
        input_schema=manifest.contributions[0].input_schema,
        handler=lambda query: {"answer": query},
        source="core",
        version=manifest.version,
        capabilities=("knowledge.lookup",),
        read_only=True,
        requires_invocation_context=True,
    )

    report = PluginAdmissionController(ToolCatalog(), _policy()).evaluate(
        manifest,
        tool_specs=[bad],
        config={"index": "customer"},
    )

    assert report.accepted is False
    assert "source must be 'plugin:com.example.connector'" in " ".join(report.errors)


def test_database_tool_admission_requires_trusted_context_contract() -> None:
    manifest = manifest_from_dict(_manifest_payload())
    contribution = manifest.contributions[0]
    legacy = ToolSpec(
        name=contribution.name,
        description=contribution.description,
        input_schema=contribution.input_schema,
        handler=lambda query: {"answer": query},
        source=f"plugin:{manifest.plugin_id}",
        version=manifest.version,
        capabilities=contribution.capabilities,
        read_only=True,
    )

    report = PluginAdmissionController(
        ToolCatalog(), _policy(), audit_sink=lambda event: None
    ).evaluate(
        manifest,
        tool_specs=[legacy],
        config={"index": "customer"},
    )

    assert report.accepted is False
    assert "requires trusted invocation context" in " ".join(report.errors)


def test_admitted_tool_registers_atomically_and_validates_output() -> None:
    manifest = manifest_from_dict(_manifest_payload())
    catalog = ToolCatalog()
    audit_events = []
    controller = PluginAdmissionController(
        catalog, _policy(), audit_sink=audit_events.append
    )

    report = controller.register_tools(
        manifest,
        tool_specs=[_tool(manifest)],
        config={"index": "customer"},
    )
    success = ToolExecutor(catalog).invoke(
        ToolCall("example_lookup", {"query": "Koto"}),
        invocation_context=_invocation_context(),
    )

    assert report.accepted is True
    assert report.tool_names == ("example_lookup",)
    assert success.ok is True
    assert success.value == {"answer": "Koto"}
    assert [event["event"] for event in audit_events] == [
        "plugin.tool.started",
        "plugin.tool.succeeded",
    ]
    assert "query" not in audit_events[0]
    assert audit_events[0]["tenant_id"] == "tenant-a"
    assert audit_events[0]["principal_id"] == "employee-7"
    assert audit_events[0]["purpose_code"] == "customer_service"
    assert audit_events[0]["correlation_id"] == "correlation-1"


def test_database_tool_denial_is_audited_without_executing_handler() -> None:
    manifest = manifest_from_dict(_manifest_payload())
    catalog = ToolCatalog()
    audit_events = []
    PluginAdmissionController(
        catalog, _policy(), audit_sink=audit_events.append
    ).register_tools(
        manifest,
        tool_specs=[_tool(manifest)],
        config={"index": "customer"},
    )

    result = ToolExecutor(catalog).invoke(ToolCall("example_lookup", {"query": "Koto"}))

    assert result.error_code is ToolErrorCode.POLICY_DENIED
    assert audit_events == [
        {
            "event": "plugin.tool.denied",
            "plugin_id": "com.example.connector",
            "plugin_version": "1.2.3",
            "manifest_sha256": manifest_digest(manifest),
            "contribution": "example_lookup",
            "permissions": ["database.read"],
            "correlation_id": "",
            "reason": "trusted_context_missing",
        }
    ]


def test_admitted_tool_fails_closed_on_invalid_or_oversized_output() -> None:
    manifest = manifest_from_dict(_manifest_payload())
    for handler, expected in (
        (lambda query: {"answer": 123}, "invalid output"),
        (lambda query: {"answer": "x" * 3000}, "exceeds 2048 bytes"),
    ):
        catalog = ToolCatalog()
        PluginAdmissionController(
            catalog, _policy(), audit_sink=lambda event: None
        ).register_tools(
            manifest,
            tool_specs=[_tool(manifest, handler=handler)],
            config={"index": "customer"},
        )

        result = ToolExecutor(catalog).invoke(
            ToolCall("example_lookup", {"query": "Koto"}),
            invocation_context=_invocation_context(),
        )

        assert result.ok is False
        assert result.error_code is ToolErrorCode.EXECUTION_ERROR
        assert expected in result.error_message


def test_admission_checks_dependencies_config_limits_and_collisions() -> None:
    payload = _manifest_payload()
    payload["dependencies"] = [
        {"plugin_id": "com.example.base", "min_version": "2.0.0"}
    ]
    manifest = manifest_from_dict(payload)
    catalog = ToolCatalog()
    catalog.register(_tool(manifest))
    policy = _policy(
        available_plugins={"com.example.base": "1.9.0"},
        max_result_bytes=1024,
    )

    report = PluginAdmissionController(catalog, policy).evaluate(
        manifest,
        tool_specs=[_tool(manifest)],
        config={},
    )

    combined = " ".join(report.errors)
    assert "max_result_bytes" in combined
    assert "below 2.0.0" in combined
    assert "config_schema" in combined
    assert "tool name collision" in combined


@pytest.mark.parametrize(
    ("installed", "minimum"),
    [
        ("2.0.0-alpha", "2.0.0"),
        ("2.0.0-alpha.2", "2.0.0-alpha.10"),
    ],
)
def test_dependency_semver_obeys_prerelease_precedence(installed, minimum) -> None:
    payload = _manifest_payload()
    payload["dependencies"] = [
        {"plugin_id": "com.example.base", "min_version": minimum}
    ]
    manifest = manifest_from_dict(payload)

    report = PluginAdmissionController(
        ToolCatalog(),
        _policy(available_plugins={"com.example.base": installed}),
        audit_sink=lambda event: None,
    ).evaluate(
        manifest,
        tool_specs=[_tool(manifest)],
        config={"index": "customer"},
    )

    assert report.accepted is False
    assert f"below {minimum}" in " ".join(report.errors)


def test_retriever_enforces_identity_tenant_acl_citation_and_chunk_budget() -> None:
    payload = _manifest_payload(kind="retriever", name="example_retriever")
    payload["contributions"][0]["input_schema"] = dict(RETRIEVAL_REQUEST_JSON_SCHEMA)
    payload["contributions"][0]["output_schema"] = dict(RETRIEVAL_BATCH_JSON_SCHEMA)
    payload["limits"]["max_rag_chunks"] = 2
    payload["data_policy"]["accepts"] = ["confidential"]
    manifest = manifest_from_dict(payload)
    contribution = manifest.contributions[0]

    def retrieve(request: RetrievalRequest) -> RetrievalBatch:
        return RetrievalBatch(
            provider_id="example_retriever",
            correlation_id=request.correlation_id,
            chunks=(
                EvidenceChunk(
                    chunk_id="chunk-1",
                    text="evidence",
                    source_uri="db://record/1",
                    source_title="Record 1",
                    citation="Record 1, field A",
                    score=0.9,
                    acl_tags=("tenant:t1",),
                ),
            ),
        )

    spec = RetrieverSpec(
        name=contribution.name,
        description=contribution.description,
        handler=retrieve,
        source=f"plugin:{manifest.plugin_id}",
        version=manifest.version,
        capabilities=contribution.capabilities,
        timeout_seconds=10,
    )
    audit_events = []
    controller = PluginAdmissionController(
        ToolCatalog(), _policy(), audit_sink=audit_events.append
    )
    admitted = controller.admit(
        manifest,
        retriever_specs=[spec],
        config={"index": "customer"},
    )
    report = admitted.report
    wrapped = admitted.retriever_specs[0]

    assert report.accepted is True
    batch = wrapped.handler(
        RetrievalRequest(
            "customer",
            top_k=2,
            tenant_id="t1",
            principal_id="u1",
            correlation_id="corr-1",
        )
    )
    assert batch.chunks[0].citation == "Record 1, field A"
    assert [event["event"] for event in audit_events[:2]] == [
        "plugin.retriever.started",
        "plugin.retriever.succeeded",
    ]
    with pytest.raises(PluginProtocolError, match="tenant_id"):
        wrapped.handler(RetrievalRequest("customer", top_k=1))
    with pytest.raises(PluginProtocolError, match="exceeds plugin limit"):
        wrapped.handler(
            RetrievalRequest("customer", top_k=3, tenant_id="t1", principal_id="u1")
        )


def test_external_restricted_data_and_database_without_tenant_isolation_fail_closed() -> (
    None
):
    payload = _manifest_payload()
    payload["data_policy"].update(
        {
            "accepts": [DataClassification.RESTRICTED.value],
            "tenant_isolation": False,
            "sends_data_external": True,
        }
    )
    manifest = manifest_from_dict(payload)

    report = PluginAdmissionController(ToolCatalog(), _policy()).evaluate(
        manifest,
        tool_specs=[_tool(manifest)],
        config={"index": "customer"},
    )

    combined = " ".join(report.errors)
    assert "tenant_isolation=true" in combined
    assert "restricted data externally" in combined


def test_retriever_cannot_publish_a_private_rag_payload_shape() -> None:
    manifest = manifest_from_dict(
        _manifest_payload(kind="retriever", name="example_retriever")
    )
    contribution = manifest.contributions[0]
    spec = RetrieverSpec(
        name=contribution.name,
        description=contribution.description,
        handler=lambda request: RetrievalBatch("example_retriever", ()),
        source=f"plugin:{manifest.plugin_id}",
        version=manifest.version,
        capabilities=contribution.capabilities,
    )

    report = PluginAdmissionController(
        ToolCatalog(), _policy(), audit_sink=lambda event: None
    ).evaluate(
        manifest,
        retriever_specs=[spec],
        config={"index": "customer"},
    )

    assert report.accepted is False
    assert "canonical retrieval input schema" in " ".join(report.errors)
    assert "canonical evidence batch schema" in " ".join(report.errors)


def test_host_context_only_resolves_manifest_declared_secret_bindings() -> None:
    context = PluginHostContext(
        plugin_id="com.example.connector",
        granted_permissions=frozenset({PluginPermission.SECRETS_USE}),
        config={},
        declared_secret_names=frozenset({"api_key"}),
        secret_resolver=lambda name: f"resolved:{name}",
        emit_audit=lambda event: None,
    )

    assert context.get_secret("api_key") == "resolved:api_key"
    with pytest.raises(PluginProtocolError, match="not declared"):
        context.get_secret("database_password")


def test_plugin_protocol_layer_is_transport_and_business_neutral() -> None:
    protocol_dir = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "core"
        / "agent"
        / "plugin_protocol"
    )
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in protocol_dir.glob("*.py")
    )

    import_lines = {
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith(("from ", "import "))
    }
    assert not any(line.startswith(("from web", "import web")) for line in import_lines)
    assert not any(
        line.startswith(("from flask", "import flask")) for line in import_lines
    )
    assert "app.core.agent.toolkits.builtin" not in source
