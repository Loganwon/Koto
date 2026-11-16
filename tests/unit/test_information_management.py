from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.core.agent.addons import InformationRetrieverAdapter
from app.core.agent.plugin_protocol import (
    AddonInvocationContext,
    PluginProtocolError,
    RetrievalRequest,
)
from app.core.information import (
    DataProduct,
    FieldPolicy,
    InformationCatalog,
    InformationCatalogError,
    InformationClassification,
    InformationConnectorRegistry,
    InformationGateway,
    InformationQuery,
    InformationSource,
    InformationStatus,
    InMemoryInformationAuditSink,
    MockInformationConnector,
    PolicyOutcome,
    QueryTemplate,
    QueryTemplateRegistry,
    TrustedSubjectContext,
)

SOURCE_ID = "core.customer-master"
PRODUCT_ID = "bank.customer.profile.v1"
TEMPLATE_ID = "customer_by_id"


def _build_information_stack(*, audit_sink=None):
    catalog = InformationCatalog()
    catalog.register_bundle(
        sources=(
            InformationSource(
                source_id=SOURCE_ID,
                source_type="database",
                owner="customer-data-team",
                read_only=True,
            ),
        ),
        products=(
            DataProduct(
                product_id=PRODUCT_ID,
                source_id=SOURCE_ID,
                entity_type="party",
                owner="customer-domain",
                classification=InformationClassification.CONFIDENTIAL,
                supported_operations=("lookup",),
                query_templates=(TEMPLATE_ID,),
                default_limit=1,
                max_limit=10,
            ),
        ),
        field_policies=(
            FieldPolicy(
                PRODUCT_ID,
                "display_name",
                InformationClassification.CONFIDENTIAL,
                allowed_purposes=("customer_service",),
                allowed_roles=("relationship_manager",),
                model_visible=True,
            ),
            FieldPolicy(
                PRODUCT_ID,
                "account_number",
                InformationClassification.RESTRICTED,
                masking="account_partial",
                allowed_purposes=("customer_service",),
                allowed_roles=("relationship_manager",),
                model_visible=True,
            ),
            FieldPolicy(
                PRODUCT_ID,
                "risk_level",
                InformationClassification.CONFIDENTIAL,
                allowed_purposes=("customer_service",),
                allowed_roles=("relationship_manager",),
                model_visible=True,
            ),
            FieldPolicy(
                PRODUCT_ID,
                "document_number",
                InformationClassification.RESTRICTED,
                masking="document_id_partial",
                allowed_purposes=("kyc_review",),
                allowed_roles=("kyc_officer",),
                model_visible=False,
            ),
        ),
    )
    templates = QueryTemplateRegistry()
    templates.register(
        QueryTemplate(
            template_id=TEMPLATE_ID,
            product_id=PRODUCT_ID,
            operation="lookup",
            allowed_parameters=("customer_id",),
            required_parameters=("customer_id",),
            allowed_projection=(
                "display_name",
                "account_number",
                "risk_level",
                "document_number",
            ),
            default_projection=("display_name", "risk_level"),
            max_limit=10,
        )
    )
    connector = MockInformationConnector(
        {
            PRODUCT_ID: [
                {
                    "_record_id": "C10293",
                    "_version": "42",
                    "_tenant_id": "bank-a",
                    "_organization_scope": ("branch-3101",),
                    "customer_id": "C10293",
                    "display_name": "示例企业",
                    "account_number": "6222000012345678",
                    "risk_level": "medium",
                    "document_number": "91310000123456789X",
                }
            ]
        }
    )
    connectors = InformationConnectorRegistry()
    connectors.register(SOURCE_ID, connector)
    audit = audit_sink or InMemoryInformationAuditSink()
    gateway = InformationGateway(
        catalog=catalog,
        templates=templates,
        connectors=connectors,
        audit_sink=audit,
    )
    return gateway, catalog, connector, audit


def _subject(**overrides):
    values = {
        "tenant_id": "bank-a",
        "principal_id": "employee-7",
        "purpose_code": "customer_service",
        "roles": ("relationship_manager",),
        "organization_scope": ("branch-3101",),
        "clearance": InformationClassification.RESTRICTED,
        "task_id": "task-1",
        "request_id": "request-1",
        "correlation_id": "correlation-1",
    }
    values.update(overrides)
    return TrustedSubjectContext(**values)


def _query(**overrides):
    values = {
        "product_id": PRODUCT_ID,
        "operation": "lookup",
        "template_id": TEMPLATE_ID,
        "parameters": {"customer_id": "C10293"},
        "projection": (
            "display_name",
            "account_number",
            "risk_level",
            "document_number",
        ),
        "limit": 1,
        "output_mode": "model",
    }
    values.update(overrides)
    return InformationQuery(**values)


def test_information_catalog_bundle_is_atomic():
    catalog = InformationCatalog()
    source = InformationSource("core.new-source", "database", "owner")

    with pytest.raises(InformationCatalogError, match="unknown product"):
        catalog.register_bundle(
            sources=(source,),
            field_policies=(
                FieldPolicy(
                    "bank.missing.v1",
                    "name",
                    InformationClassification.INTERNAL,
                ),
            ),
        )

    assert catalog.source(source.source_id) is None
    assert catalog.snapshot() == {
        "sources": [],
        "products": [],
        "field_policy_count": 0,
    }


def test_information_query_rejects_raw_sql():
    with pytest.raises(ValueError, match="cannot contain SQL"):
        _query(parameters={"sql": "select * from customer"})


def test_information_query_detaches_and_freezes_model_arguments():
    parameters = {"customer_id": "C10293", "options": ["current"]}
    query = _query(parameters=parameters)

    parameters["customer_id"] = "C99999"
    parameters["options"].append("mutated")

    assert query.parameters["customer_id"] == "C10293"
    assert query.parameters["options"] == ("current",)
    with pytest.raises(TypeError):
        query.parameters["customer_id"] = "C99999"


def test_gateway_applies_field_policy_masking_lineage_and_safe_audit():
    gateway, _catalog, connector, audit = _build_information_stack()

    result = gateway.execute(_query(), subject=_subject())

    assert result.status is InformationStatus.SUCCESS
    assert result.policy.outcome is PolicyOutcome.ALLOW_WITH_REDACTION
    assert result.policy.allowed_fields == (
        "display_name",
        "account_number",
        "risk_level",
    )
    assert result.policy.reasons == ("purpose_not_allowed:document_number",)
    assert result.records[0].record_ref == f"{SOURCE_ID}:C10293@42"
    assert result.records[0].data == {
        "display_name": "示例企业",
        "account_number": "6222********5678",
        "risk_level": "medium",
    }
    assert result.records[0].redacted_fields == ("account_number",)
    assert result.lineage.source_id == SOURCE_ID
    assert result.lineage.template_id == TEMPLATE_ID
    assert result.freshness.stale is False
    assert connector.calls[0]["projection"] == [
        "display_name",
        "account_number",
        "risk_level",
    ]
    assert connector.calls[0]["tenant_id"] == "bank-a"

    event = audit.events()[0]
    assert event["parameter_names"] == ["customer_id"]
    assert event["record_count"] == 1
    encoded = json.dumps(event, ensure_ascii=False)
    assert "C10293" not in encoded
    assert "6222000012345678" not in encoded
    assert "示例企业" not in encoded


def test_gateway_denies_before_connector_when_clearance_is_too_low():
    gateway, _catalog, connector, audit = _build_information_stack()

    result = gateway.execute(
        _query(),
        subject=_subject(clearance=InformationClassification.INTERNAL),
    )

    assert result.status is InformationStatus.DENIED
    assert result.error_code == "policy_denied"
    assert connector.calls == []
    assert audit.events()[0]["status"] == "denied"


@pytest.mark.parametrize(
    "subject",
    (
        _subject(tenant_id="bank-b"),
        _subject(organization_scope=("branch-9999",)),
    ),
)
def test_mock_connector_enforces_tenant_and_organization_row_scope(subject):
    gateway, _catalog, connector, _audit = _build_information_stack()

    result = gateway.execute(_query(), subject=subject)

    assert result.status is InformationStatus.SUCCESS
    assert result.records == ()
    assert connector.calls[0]["tenant_id"] == subject.tenant_id


def test_gateway_fails_closed_and_does_not_leak_connector_error():
    gateway, _catalog, connector, audit = _build_information_stack()
    connector.fail_with = RuntimeError("password=secret database host=db.internal")

    result = gateway.execute(_query(), subject=_subject())

    assert result.status is InformationStatus.UNAVAILABLE
    assert result.error_code == "source_unavailable"
    assert "secret" not in result.message
    assert "db.internal" not in json.dumps(audit.events(), ensure_ascii=False)


def test_gateway_does_not_release_records_when_audit_is_unavailable():
    class FailingAuditSink:
        def append(self, _event):
            raise RuntimeError("audit token=secret")

    gateway, _catalog, connector, _audit = _build_information_stack(
        audit_sink=FailingAuditSink()
    )

    result = gateway.execute(_query(), subject=_subject())

    assert connector.calls
    assert result.status is InformationStatus.UNAVAILABLE
    assert result.records == ()
    assert result.error_code == "audit_unavailable"
    assert "secret" not in result.message


def test_information_retriever_adapter_preserves_identity_acl_and_lineage():
    gateway, _catalog, _connector, _audit = _build_information_stack()

    def resolve(request):
        return _subject(
            tenant_id=request.tenant_id,
            principal_id=request.principal_id,
            correlation_id=request.correlation_id,
        )

    spec = InformationRetrieverAdapter(
        addon_id="com.bank.customer-data",
        name="bank_customer_lookup",
        description="Read a governed customer profile.",
        version="1.0.0",
        capabilities=("bank.customer.lookup",),
        gateway=gateway,
        product_id=PRODUCT_ID,
        template_id=TEMPLATE_ID,
        operation="lookup",
        projection=("display_name", "account_number", "risk_level"),
        subject_resolver=resolve,
    ).spec()
    batch = spec.handler(
        RetrievalRequest(
            query="客户 C10293",
            top_k=1,
            tenant_id="bank-a",
            principal_id="employee-7",
            correlation_id="retrieval-1",
            filters={"parameters": {"customer_id": "C10293"}},
        )
    )

    assert batch.provider_id == "bank_customer_lookup"
    assert batch.correlation_id == "retrieval-1"
    assert batch.chunks[0].acl_tags == (
        "tenant:bank-a",
        "principal:employee-7",
    )
    assert batch.chunks[0].metadata["lineage_id"].startswith("lin-")
    assert json.loads(batch.chunks[0].text)["account_number"] == "6222********5678"


def test_information_retriever_adapter_rejects_identity_substitution():
    gateway, _catalog, _connector, _audit = _build_information_stack()
    spec = InformationRetrieverAdapter(
        addon_id="com.bank.customer-data",
        name="bank_customer_lookup",
        description="Read a governed customer profile.",
        version="1.0.0",
        capabilities=("bank.customer.lookup",),
        gateway=gateway,
        product_id=PRODUCT_ID,
        template_id=TEMPLATE_ID,
        operation="lookup",
        projection=("display_name",),
        subject_resolver=lambda _request: _subject(tenant_id="bank-b"),
    ).spec()

    with pytest.raises(PluginProtocolError, match="differs"):
        spec.handler(
            RetrievalRequest(
                query="客户 C10293",
                tenant_id="bank-a",
                principal_id="employee-7",
            )
        )


def test_addon_invocation_context_requires_host_identity_and_purpose():
    with pytest.raises(PluginProtocolError, match="tenant_id"):
        AddonInvocationContext().require_identity()
    with pytest.raises(PluginProtocolError, match="purpose_code"):
        AddonInvocationContext(
            tenant_id="bank-a",
            principal_id="employee-7",
        ).require_identity()

    context = AddonInvocationContext(
        tenant_id="bank-a",
        principal_id="employee-7",
        purpose_code="customer_service",
        role_ids=("relationship_manager", "relationship_manager"),
    )
    context.require_identity()
    assert context.role_ids == ("relationship_manager",)


def test_information_core_does_not_depend_on_web_agent_or_llm_layers():
    root = Path(__file__).parents[2] / "app" / "core" / "information"
    forbidden = ("web", "flask", "app.core.agent", "app.core.llm")
    violations = []

    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.startswith(forbidden):
                    violations.append(f"{path.name}:{node.lineno}:{name}")

    assert violations == []
