"""Information connector boundary and deterministic in-memory test connector."""

from __future__ import annotations

from threading import RLock
from typing import Any, Mapping, Protocol

from .contracts import (
    ConnectorBatch,
    ConnectorRecord,
    DataProduct,
    InformationQuery,
    TrustedSubjectContext,
)
from .query_templates import QueryTemplate


class InformationConnector(Protocol):
    def query(
        self,
        *,
        product: DataProduct,
        template: QueryTemplate,
        query: InformationQuery,
        subject: TrustedSubjectContext,
    ) -> ConnectorBatch: ...


class InformationConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, InformationConnector] = {}
        self._lock = RLock()

    def register(
        self, source_id: str, connector: InformationConnector, *, replace: bool = False
    ) -> None:
        if not callable(getattr(connector, "query", None)):
            raise ValueError("information connector must implement query")
        with self._lock:
            if source_id in self._connectors and not replace:
                raise ValueError(f"connector already exists: {source_id}")
            self._connectors[str(source_id)] = connector

    def require(self, source_id: str) -> InformationConnector:
        with self._lock:
            connector = self._connectors.get(str(source_id))
        if connector is None:
            raise KeyError(f"information connector unavailable: {source_id}")
        return connector


class MockInformationConnector:
    """A source-side filtering fixture; it never accepts SQL or callable predicates."""

    def __init__(self, records: Mapping[str, list[Mapping[str, Any]]]) -> None:
        self._records = {
            str(product_id): [dict(item) for item in items]
            for product_id, items in records.items()
        }
        self.fail_with: Exception | None = None
        self.calls: list[dict[str, Any]] = []

    def query(
        self,
        *,
        product: DataProduct,
        template: QueryTemplate,
        query: InformationQuery,
        subject: TrustedSubjectContext,
    ) -> ConnectorBatch:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append(
            {
                "product_id": product.product_id,
                "template_id": template.template_id,
                "tenant_id": subject.tenant_id,
                "principal_id": subject.principal_id,
                "parameters": dict(query.parameters),
                "projection": list(query.projection),
                "limit": query.limit,
            }
        )
        matched = []
        for raw in self._records.get(product.product_id, []):
            # Mock the same source-side row isolation required from production
            # connectors.  Unscoped rows fail closed instead of becoming global.
            if str(raw.get("_tenant_id") or "") != subject.tenant_id:
                continue
            record_scope = {
                str(item).strip()
                for item in raw.get("_organization_scope", ())
                if str(item).strip()
            }
            if record_scope and not record_scope.intersection(
                subject.organization_scope
            ):
                continue
            if any(raw.get(key) != value for key, value in query.parameters.items()):
                continue
            record_id = str(raw.get("_record_id") or raw.get("id") or len(matched) + 1)
            version = str(raw.get("_version") or "1")
            data = {field: raw.get(field) for field in query.projection if field in raw}
            matched.append(
                ConnectorRecord(record_id=record_id, version=version, data=data)
            )
            if len(matched) >= query.limit:
                break
        return ConnectorBatch(records=tuple(matched), source_version="mock-v1")


__all__ = [
    "InformationConnector",
    "InformationConnectorRegistry",
    "MockInformationConnector",
]
