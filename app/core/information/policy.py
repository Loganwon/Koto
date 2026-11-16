"""Default-deny information access policy."""

from __future__ import annotations

import uuid
from typing import Sequence

from .contracts import (
    DataProduct,
    FieldPolicy,
    InformationClassification,
    InformationQuery,
    PolicyDecision,
    PolicyOutcome,
    TrustedSubjectContext,
)

_CLASSIFICATION_ORDER = {
    InformationClassification.PUBLIC: 0,
    InformationClassification.INTERNAL: 1,
    InformationClassification.CONFIDENTIAL: 2,
    InformationClassification.RESTRICTED: 3,
}


class DefaultDenyInformationPolicy:
    """Every visible field requires an explicit catalog policy."""

    def decide(
        self,
        *,
        subject: TrustedSubjectContext,
        product: DataProduct,
        query: InformationQuery,
        field_policies: Sequence[FieldPolicy],
    ) -> PolicyDecision:
        decision_id = f"pd-{uuid.uuid4()}"
        if (
            _CLASSIFICATION_ORDER[subject.clearance]
            < _CLASSIFICATION_ORDER[product.classification]
        ):
            return PolicyDecision(
                decision_id,
                PolicyOutcome.DENY,
                reasons=("subject_clearance_too_low",),
            )

        policies = {item.field_name: item for item in field_policies}
        allowed: list[str] = []
        masking: dict[str, str] = {}
        denied_reasons: list[str] = []
        for field_name in query.projection:
            policy = policies.get(field_name)
            if policy is None:
                denied_reasons.append(f"field_policy_missing:{field_name}")
                continue
            if (
                _CLASSIFICATION_ORDER[subject.clearance]
                < _CLASSIFICATION_ORDER[policy.classification]
            ):
                denied_reasons.append(f"field_clearance_too_low:{field_name}")
                continue
            if (
                policy.allowed_purposes
                and subject.purpose_code not in policy.allowed_purposes
            ):
                denied_reasons.append(f"purpose_not_allowed:{field_name}")
                continue
            if policy.allowed_roles and not set(subject.roles).intersection(
                policy.allowed_roles
            ):
                denied_reasons.append(f"role_not_allowed:{field_name}")
                continue
            if query.output_mode == "model" and not policy.model_visible:
                denied_reasons.append(f"not_model_visible:{field_name}")
                continue
            if query.output_mode == "export" and not policy.exportable:
                denied_reasons.append(f"not_exportable:{field_name}")
                continue
            allowed.append(field_name)
            if policy.masking != "none":
                masking[field_name] = policy.masking

        if not allowed:
            return PolicyDecision(
                decision_id,
                PolicyOutcome.DENY,
                reasons=tuple(denied_reasons or ("no_fields_allowed",)),
            )
        outcome = (
            PolicyOutcome.ALLOW_WITH_REDACTION
            if masking or denied_reasons
            else PolicyOutcome.ALLOW
        )
        return PolicyDecision(
            decision_id=decision_id,
            outcome=outcome,
            allowed_fields=tuple(allowed),
            masking=masking,
            reasons=tuple(denied_reasons),
        )


__all__ = ["DefaultDenyInformationPolicy"]
