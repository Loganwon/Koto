"""Allowlisted logical query templates; raw SQL is never accepted."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .contracts import DataProduct, InformationQuery


class QueryTemplateError(ValueError):
    pass


@dataclass(frozen=True)
class QueryTemplate:
    template_id: str
    product_id: str
    operation: str
    allowed_parameters: tuple[str, ...]
    required_parameters: tuple[str, ...] = ()
    allowed_projection: tuple[str, ...] = ()
    default_projection: tuple[str, ...] = ()
    max_limit: int = 100

    def __post_init__(self) -> None:
        if not self.template_id or not self.product_id or not self.operation:
            raise QueryTemplateError("query template identity is incomplete")
        allowed = set(self.allowed_parameters)
        if not set(self.required_parameters).issubset(allowed):
            raise QueryTemplateError("required parameters must be allowed")
        if not set(self.default_projection).issubset(set(self.allowed_projection)):
            raise QueryTemplateError("default projection must be allowed")
        if int(self.max_limit) < 1:
            raise QueryTemplateError("query template max_limit must be positive")

    def validate(
        self, query: InformationQuery, product: DataProduct
    ) -> InformationQuery:
        if query.product_id != self.product_id or product.product_id != self.product_id:
            raise QueryTemplateError("query template belongs to another data product")
        if (
            query.operation != self.operation
            or query.operation not in product.supported_operations
        ):
            raise QueryTemplateError("query operation is not allowed")
        if self.template_id not in product.query_templates:
            raise QueryTemplateError("query template is absent from the data product")
        actual = set(query.parameters)
        unknown = sorted(actual - set(self.allowed_parameters))
        missing = sorted(set(self.required_parameters) - actual)
        if unknown:
            raise QueryTemplateError("unknown query parameters: " + ", ".join(unknown))
        if missing:
            raise QueryTemplateError("missing query parameters: " + ", ".join(missing))
        projection = query.projection or self.default_projection
        unknown_fields = sorted(set(projection) - set(self.allowed_projection))
        if unknown_fields:
            raise QueryTemplateError(
                "projection is not allowed: " + ", ".join(unknown_fields)
            )
        limit = query.limit or product.default_limit
        if limit > min(product.max_limit, self.max_limit):
            raise QueryTemplateError("query limit exceeds the approved maximum")
        return InformationQuery(
            product_id=query.product_id,
            operation=query.operation,
            template_id=query.template_id,
            parameters=query.parameters,
            projection=tuple(projection),
            limit=limit,
            as_of=query.as_of,
            consistency=query.consistency,
            output_mode=query.output_mode,
        )


class QueryTemplateRegistry:
    def __init__(self) -> None:
        self._templates: dict[tuple[str, str], QueryTemplate] = {}
        self._lock = RLock()

    def register(self, template: QueryTemplate, *, replace: bool = False) -> None:
        if not isinstance(template, QueryTemplate):
            raise QueryTemplateError("invalid query template")
        key = (template.product_id, template.template_id)
        with self._lock:
            if key in self._templates and not replace:
                raise QueryTemplateError(
                    f"query template already exists: {template.template_id}"
                )
            self._templates[key] = template

    def require(self, product_id: str, template_id: str) -> QueryTemplate:
        with self._lock:
            template = self._templates.get((str(product_id), str(template_id)))
        if template is None:
            raise QueryTemplateError(
                f"unknown query template: {product_id}:{template_id}"
            )
        return template


__all__ = ["QueryTemplate", "QueryTemplateError", "QueryTemplateRegistry"]
