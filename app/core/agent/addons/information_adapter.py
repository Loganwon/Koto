"""Bridge governed Information Gateway results into the existing Retriever API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from app.core.agent.plugin_protocol import (
    EvidenceChunk,
    PluginProtocolError,
    RetrievalBatch,
    RetrievalRequest,
    RetrieverSpec,
)
from app.core.information import (
    InformationGateway,
    InformationQuery,
    TrustedSubjectContext,
)

SubjectResolver = Callable[[RetrievalRequest], TrustedSubjectContext]


@dataclass(frozen=True)
class InformationRetrieverAdapter:
    """An identity-aware, read-only Addon contribution backed by a data product."""

    addon_id: str
    name: str
    description: str
    version: str
    capabilities: tuple[str, ...]
    gateway: InformationGateway
    product_id: str
    template_id: str
    operation: str
    projection: tuple[str, ...]
    subject_resolver: SubjectResolver
    timeout_seconds: float = 30.0

    def spec(self) -> RetrieverSpec:
        return RetrieverSpec(
            name=self.name,
            description=self.description,
            handler=self._retrieve,
            source=f"plugin:{self.addon_id}",
            version=self.version,
            capabilities=self.capabilities,
            timeout_seconds=self.timeout_seconds,
        )

    def _retrieve(self, request: RetrievalRequest) -> RetrievalBatch:
        subject = self.subject_resolver(request)
        if not isinstance(subject, TrustedSubjectContext):
            raise PluginProtocolError(
                "information subject resolver returned an invalid context"
            )
        if (
            subject.tenant_id != request.tenant_id
            or subject.principal_id != request.principal_id
        ):
            raise PluginProtocolError(
                "information subject identity differs from the host retrieval request"
            )
        raw_parameters = request.filters.get("parameters") or {"query": request.query}
        if not isinstance(raw_parameters, dict):
            raise PluginProtocolError("information query parameters must be an object")
        result = self.gateway.execute(
            InformationQuery(
                product_id=self.product_id,
                operation=self.operation,
                template_id=self.template_id,
                parameters=raw_parameters,
                projection=self.projection,
                limit=request.top_k,
                output_mode="model",
            ),
            subject=subject,
        )
        if not result.ok:
            raise PluginProtocolError(
                "information query failed closed: "
                f"{result.error_code or result.status.value}"
            )
        chunks = tuple(
            EvidenceChunk(
                chunk_id=record.record_ref,
                text=json.dumps(
                    dict(record.data), ensure_ascii=False, separators=(",", ":")
                ),
                source_uri=f"information://{self.product_id}/{record.record_ref}",
                source_title=self.product_id,
                citation=(
                    f"{self.product_id}，记录 {record.record_ref}，"
                    f"截至 {result.freshness.observed_at if result.freshness else 'unknown'}"
                ),
                metadata={
                    "classification": record.classification.value,
                    "redacted_fields": list(record.redacted_fields),
                    "lineage_id": result.lineage.lineage_id if result.lineage else "",
                    "decision_id": result.policy.decision_id if result.policy else "",
                    "stale": bool(result.freshness and result.freshness.stale),
                },
                acl_tags=(
                    f"tenant:{subject.tenant_id}",
                    f"principal:{subject.principal_id}",
                ),
            )
            for record in result.records
        )
        return RetrievalBatch(
            provider_id=self.name,
            correlation_id=request.correlation_id,
            chunks=chunks,
        )


__all__ = ["InformationRetrieverAdapter", "SubjectResolver"]
