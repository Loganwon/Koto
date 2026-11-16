"""Single governed execution boundary for all Koto information reads."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .audit import InformationAuditSink
from .catalog import InformationCatalog, InformationCatalogError
from .connectors import InformationConnectorRegistry
from .contracts import (
    InformationFreshness,
    InformationLineage,
    InformationQuery,
    InformationRecord,
    InformationResult,
    InformationStatus,
    TrustedSubjectContext,
)
from .masking import mask_value
from .policy import DefaultDenyInformationPolicy
from .query_templates import QueryTemplateError, QueryTemplateRegistry


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InformationGateway:
    def __init__(
        self,
        *,
        catalog: InformationCatalog,
        templates: QueryTemplateRegistry,
        connectors: InformationConnectorRegistry,
        audit_sink: InformationAuditSink,
        policy: DefaultDenyInformationPolicy | None = None,
    ) -> None:
        if not callable(getattr(audit_sink, "append", None)):
            raise ValueError("information gateway requires an audit sink")
        self._catalog = catalog
        self._templates = templates
        self._connectors = connectors
        self._audit = audit_sink
        self._policy = policy or DefaultDenyInformationPolicy()

    def execute(
        self,
        query: InformationQuery,
        *,
        subject: TrustedSubjectContext,
    ) -> InformationResult:
        started_at = _utc_now()
        try:
            product = self._catalog.require_product(query.product_id)
            source = self._catalog.require_source(product.source_id)
            if source.status != "active":
                raise RuntimeError("information source is not active")
            if not source.read_only:
                raise RuntimeError("read gateway refuses a writable source")
            template = self._templates.require(product.product_id, query.template_id)
            approved_query = template.validate(query, product)
        except (
            InformationCatalogError,
            QueryTemplateError,
            KeyError,
            RuntimeError,
        ) as exc:
            result = InformationResult(
                status=InformationStatus.INVALID,
                product_id=query.product_id,
                error_code="query_not_admitted",
                message=str(exc),
            )
            return self._finalize(subject, query, result, started_at=started_at)

        decision = self._policy.decide(
            subject=subject,
            product=product,
            query=approved_query,
            field_policies=self._catalog.field_policies(product.product_id),
        )
        if not decision.allowed:
            result = InformationResult(
                status=InformationStatus.DENIED,
                product_id=product.product_id,
                policy=decision,
                error_code="policy_denied",
                message="information access denied by host policy",
            )
            return self._finalize(
                subject, approved_query, result, started_at=started_at
            )

        governed_query = InformationQuery(
            product_id=approved_query.product_id,
            operation=approved_query.operation,
            template_id=approved_query.template_id,
            parameters=approved_query.parameters,
            projection=decision.allowed_fields,
            limit=approved_query.limit,
            as_of=approved_query.as_of,
            consistency=approved_query.consistency,
            output_mode=approved_query.output_mode,
        )
        try:
            connector = self._connectors.require(source.source_id)
            batch = connector.query(
                product=product,
                template=template,
                query=governed_query,
                subject=subject,
            )
            records = []
            for item in batch.records[: governed_query.limit]:
                data: dict[str, Any] = {}
                redacted: list[str] = []
                for field_name in decision.allowed_fields:
                    if field_name not in item.data:
                        continue
                    strategy = decision.masking.get(field_name, "none")
                    data[field_name] = mask_value(item.data[field_name], strategy)
                    if strategy != "none":
                        redacted.append(field_name)
                version_suffix = f"@{item.version}" if item.version else ""
                records.append(
                    InformationRecord(
                        record_ref=(
                            f"{source.source_id}:{item.record_id}{version_suffix}"
                        ),
                        data=data,
                        classification=product.classification,
                        redacted_fields=tuple(redacted),
                    )
                )
            lineage = InformationLineage(
                lineage_id=f"lin-{uuid.uuid4()}",
                source_id=source.source_id,
                product_id=product.product_id,
                template_id=template.template_id,
                source_version=batch.source_version,
                transformation_ids=("projection", "field_policy", "masking"),
            )
            freshness = InformationFreshness(
                observed_at=batch.observed_at,
                source_version=batch.source_version,
                stale=self._is_stale(
                    batch.observed_at,
                    max_age_seconds=product.freshness_sla_seconds,
                ),
            )
            result = InformationResult(
                status=InformationStatus.SUCCESS,
                product_id=product.product_id,
                records=tuple(records),
                freshness=freshness,
                policy=decision,
                lineage=lineage,
                next_page_token=("more" if batch.truncated else None),
            )
        except Exception:
            result = InformationResult(
                status=InformationStatus.UNAVAILABLE,
                product_id=product.product_id,
                policy=decision,
                error_code="source_unavailable",
                message="information source is unavailable",
            )
        return self._finalize(subject, governed_query, result, started_at=started_at)

    def _finalize(
        self,
        subject: TrustedSubjectContext,
        query: InformationQuery,
        result: InformationResult,
        *,
        started_at: str,
    ) -> InformationResult:
        try:
            self._emit_audit(subject, query, result, started_at=started_at)
        except Exception:
            # A successful read must never escape without a durable audit event.
            return InformationResult(
                status=InformationStatus.UNAVAILABLE,
                product_id=query.product_id,
                policy=result.policy,
                error_code="audit_unavailable",
                message="information audit service is unavailable",
            )
        return result

    @staticmethod
    def _is_stale(observed_at: str, *, max_age_seconds: int) -> bool:
        if max_age_seconds == 0:
            return False
        try:
            observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            age = (
                datetime.now(timezone.utc) - observed.astimezone(timezone.utc)
            ).total_seconds()
            return age > max_age_seconds
        except Exception:
            return True

    def _emit_audit(
        self,
        subject: TrustedSubjectContext,
        query: InformationQuery,
        result: InformationResult,
        *,
        started_at: str,
    ) -> None:
        # Parameter values and record contents are deliberately excluded.
        self._audit.append(
            {
                "event": "information.query.completed",
                "started_at": started_at,
                "completed_at": _utc_now(),
                "tenant_id": subject.tenant_id,
                "principal_id": subject.principal_id,
                "purpose_code": subject.purpose_code,
                "task_id": subject.task_id,
                "request_id": subject.request_id,
                "correlation_id": subject.correlation_id,
                "product_id": query.product_id,
                "operation": query.operation,
                "template_id": query.template_id,
                "parameter_names": sorted(query.parameters),
                "requested_fields": list(query.projection),
                "status": result.status.value,
                "error_code": result.error_code,
                "record_count": len(result.records),
                "decision_id": result.policy.decision_id if result.policy else "",
                "lineage_id": result.lineage.lineage_id if result.lineage else "",
            }
        )


__all__ = ["InformationGateway"]
