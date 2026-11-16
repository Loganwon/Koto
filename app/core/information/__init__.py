"""Koto's governed information-management foundation."""

from .audit import InformationAuditSink, InMemoryInformationAuditSink
from .catalog import InformationCatalog, InformationCatalogError
from .connectors import (
    InformationConnector,
    InformationConnectorRegistry,
    MockInformationConnector,
)
from .contracts import (
    ConnectorBatch,
    ConnectorRecord,
    DataProduct,
    FieldPolicy,
    InformationClassification,
    InformationFreshness,
    InformationLineage,
    InformationQuery,
    InformationRecord,
    InformationResult,
    InformationSource,
    InformationStatus,
    PolicyDecision,
    PolicyOutcome,
    TrustedSubjectContext,
)
from .gateway import InformationGateway
from .policy import DefaultDenyInformationPolicy
from .query_templates import QueryTemplate, QueryTemplateError, QueryTemplateRegistry

__all__ = [
    "ConnectorBatch",
    "ConnectorRecord",
    "DataProduct",
    "DefaultDenyInformationPolicy",
    "FieldPolicy",
    "InMemoryInformationAuditSink",
    "InformationAuditSink",
    "InformationCatalog",
    "InformationCatalogError",
    "InformationClassification",
    "InformationConnector",
    "InformationConnectorRegistry",
    "InformationFreshness",
    "InformationGateway",
    "InformationLineage",
    "InformationQuery",
    "InformationRecord",
    "InformationResult",
    "InformationSource",
    "InformationStatus",
    "MockInformationConnector",
    "PolicyDecision",
    "PolicyOutcome",
    "QueryTemplate",
    "QueryTemplateError",
    "QueryTemplateRegistry",
    "TrustedSubjectContext",
]
