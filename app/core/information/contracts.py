"""Transport-neutral contracts for Koto's governed information layer."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identifier(value: str, *, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _ID_RE.fullmatch(normalized):
        raise ValueError(f"{label} must be a stable lowercase identifier")
    return normalized


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(str(value).strip() for value in values if str(value).strip())
    )


def _freeze_value(value: Any) -> Any:
    """Detach caller-owned values and prevent post-admission mutation."""

    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_value(item) for item in value)
    return copy.deepcopy(value)


class InformationClassification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class InformationStatus(str, Enum):
    SUCCESS = "success"
    DENIED = "denied"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


class PolicyOutcome(str, Enum):
    ALLOW = "allow"
    ALLOW_WITH_REDACTION = "allow_with_redaction"
    DENY = "deny"


@dataclass(frozen=True)
class TrustedSubjectContext:
    """Host-derived identity and purpose; never populated from model arguments."""

    tenant_id: str
    principal_id: str
    purpose_code: str
    roles: tuple[str, ...] = ()
    organization_scope: tuple[str, ...] = ()
    clearance: InformationClassification = InformationClassification.INTERNAL
    task_id: str = ""
    request_id: str = ""
    correlation_id: str = ""
    authenticated_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        for label, value in (
            ("tenant_id", self.tenant_id),
            ("principal_id", self.principal_id),
            ("purpose_code", self.purpose_code),
        ):
            if not str(value or "").strip():
                raise ValueError(f"trusted subject requires {label}")
        object.__setattr__(self, "tenant_id", str(self.tenant_id).strip())
        object.__setattr__(self, "principal_id", str(self.principal_id).strip())
        object.__setattr__(self, "purpose_code", str(self.purpose_code).strip())
        object.__setattr__(self, "roles", _unique(self.roles))
        object.__setattr__(self, "organization_scope", _unique(self.organization_scope))
        object.__setattr__(self, "clearance", InformationClassification(self.clearance))


@dataclass(frozen=True)
class InformationSource:
    source_id: str
    source_type: str
    owner: str
    read_only: bool = True
    environment: str = "production"
    region: str = ""
    connection_ref: str = ""
    status: str = "active"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_id", _identifier(self.source_id, label="source_id")
        )
        if not str(self.source_type or "").strip() or not str(self.owner or "").strip():
            raise ValueError("information source requires source_type and owner")
        if self.status not in {"active", "degraded", "disabled"}:
            raise ValueError("information source status is invalid")


@dataclass(frozen=True)
class DataProduct:
    product_id: str
    source_id: str
    entity_type: str
    owner: str
    classification: InformationClassification
    supported_operations: tuple[str, ...]
    query_templates: tuple[str, ...]
    freshness_sla_seconds: int = 300
    default_limit: int = 20
    max_limit: int = 100

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "product_id", _identifier(self.product_id, label="product_id")
        )
        object.__setattr__(
            self, "source_id", _identifier(self.source_id, label="source_id")
        )
        if not str(self.entity_type or "").strip() or not str(self.owner or "").strip():
            raise ValueError("data product requires entity_type and owner")
        operations = tuple(item.lower() for item in _unique(self.supported_operations))
        templates = tuple(
            _identifier(item, label="query_template")
            for item in _unique(self.query_templates)
        )
        if not operations or not templates:
            raise ValueError("data product requires operations and query templates")
        if not 1 <= int(self.default_limit) <= int(self.max_limit) <= 10_000:
            raise ValueError("data product limits are invalid")
        if int(self.freshness_sla_seconds) < 0:
            raise ValueError("freshness_sla_seconds cannot be negative")
        object.__setattr__(
            self, "classification", InformationClassification(self.classification)
        )
        object.__setattr__(self, "supported_operations", operations)
        object.__setattr__(self, "query_templates", templates)


@dataclass(frozen=True)
class FieldPolicy:
    product_id: str
    field_name: str
    classification: InformationClassification
    masking: str = "none"
    allowed_purposes: tuple[str, ...] = ()
    allowed_roles: tuple[str, ...] = ()
    model_visible: bool = True
    exportable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "product_id", _identifier(self.product_id, label="product_id")
        )
        field_name = str(self.field_name or "").strip()
        if not field_name:
            raise ValueError("field policy requires field_name")
        if self.masking not in {
            "none",
            "full",
            "last4",
            "account_partial",
            "document_id_partial",
            "phone_partial",
            "name_partial",
            "hash",
        }:
            raise ValueError(f"unsupported masking strategy: {self.masking}")
        object.__setattr__(self, "field_name", field_name)
        object.__setattr__(
            self, "classification", InformationClassification(self.classification)
        )
        object.__setattr__(self, "allowed_purposes", _unique(self.allowed_purposes))
        object.__setattr__(self, "allowed_roles", _unique(self.allowed_roles))


@dataclass(frozen=True)
class InformationQuery:
    product_id: str
    operation: str
    template_id: str
    parameters: Mapping[str, Any]
    projection: tuple[str, ...] = ()
    limit: int = 0
    as_of: str = ""
    consistency: str = "bounded_staleness"
    output_mode: str = "model"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "product_id", _identifier(self.product_id, label="product_id")
        )
        object.__setattr__(
            self, "template_id", _identifier(self.template_id, label="template_id")
        )
        operation = str(self.operation or "").strip().lower()
        if not operation:
            raise ValueError("information query requires operation")
        if not isinstance(self.parameters, Mapping):
            raise ValueError("information query parameters must be an object")
        if any(
            str(key).lower() in {"sql", "query_sql", "statement"}
            for key in self.parameters
        ):
            raise ValueError("information query cannot contain SQL")
        if int(self.limit) < 0:
            raise ValueError("information query limit cannot be negative")
        if self.output_mode not in {"model", "ui", "export"}:
            raise ValueError("information query output_mode is invalid")
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "parameters", _freeze_value(self.parameters))
        object.__setattr__(self, "projection", _unique(self.projection))
        object.__setattr__(self, "limit", int(self.limit))


@dataclass(frozen=True)
class ConnectorRecord:
    record_id: str
    data: Mapping[str, Any]
    version: str = ""
    observed_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if not str(self.record_id or "").strip():
            raise ValueError("connector record requires record_id")
        if not isinstance(self.data, Mapping):
            raise ValueError("connector record data must be an object")
        object.__setattr__(self, "record_id", str(self.record_id).strip())
        object.__setattr__(self, "data", _freeze_value(self.data))


@dataclass(frozen=True)
class ConnectorBatch:
    records: tuple[ConnectorRecord, ...]
    source_version: str = ""
    observed_at: str = field(default_factory=_utc_now)
    truncated: bool = False

    def __post_init__(self) -> None:
        if not all(isinstance(item, ConnectorRecord) for item in self.records):
            raise ValueError("connector batch contains invalid records")


@dataclass(frozen=True)
class PolicyDecision:
    decision_id: str
    outcome: PolicyOutcome
    allowed_fields: tuple[str, ...] = ()
    masking: Mapping[str, str] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.outcome is not PolicyOutcome.DENY

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", PolicyOutcome(self.outcome))
        object.__setattr__(self, "allowed_fields", _unique(self.allowed_fields))
        object.__setattr__(self, "masking", _freeze_value(self.masking))
        object.__setattr__(self, "reasons", _unique(self.reasons))


@dataclass(frozen=True)
class InformationRecord:
    record_ref: str
    data: Mapping[str, Any]
    classification: InformationClassification
    redacted_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", _freeze_value(self.data))
        object.__setattr__(
            self, "classification", InformationClassification(self.classification)
        )
        object.__setattr__(self, "redacted_fields", _unique(self.redacted_fields))


@dataclass(frozen=True)
class InformationFreshness:
    observed_at: str
    source_version: str = ""
    stale: bool = False


@dataclass(frozen=True)
class InformationLineage:
    lineage_id: str
    source_id: str
    product_id: str
    template_id: str
    source_version: str
    transformation_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class InformationResult:
    status: InformationStatus
    product_id: str
    records: tuple[InformationRecord, ...] = ()
    freshness: InformationFreshness | None = None
    policy: PolicyDecision | None = None
    lineage: InformationLineage | None = None
    next_page_token: str | None = None
    error_code: str = ""
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status is InformationStatus.SUCCESS


__all__ = [
    "ConnectorBatch",
    "ConnectorRecord",
    "DataProduct",
    "FieldPolicy",
    "InformationClassification",
    "InformationFreshness",
    "InformationLineage",
    "InformationQuery",
    "InformationRecord",
    "InformationResult",
    "InformationSource",
    "InformationStatus",
    "PolicyDecision",
    "PolicyOutcome",
    "TrustedSubjectContext",
]
