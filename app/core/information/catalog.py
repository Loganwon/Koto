"""Atomic, host-owned information source and data-product catalog."""

from __future__ import annotations

from threading import RLock
from typing import Iterable

from .contracts import DataProduct, FieldPolicy, InformationSource


class InformationCatalogError(ValueError):
    pass


class InformationCatalog:
    def __init__(self) -> None:
        self._sources: dict[str, InformationSource] = {}
        self._products: dict[str, DataProduct] = {}
        self._field_policies: dict[tuple[str, str], FieldPolicy] = {}
        self._lock = RLock()

    def register_bundle(
        self,
        *,
        sources: Iterable[InformationSource] = (),
        products: Iterable[DataProduct] = (),
        field_policies: Iterable[FieldPolicy] = (),
        replace: bool = False,
    ) -> None:
        source_items = tuple(sources)
        product_items = tuple(products)
        policy_items = tuple(field_policies)
        if not all(isinstance(item, InformationSource) for item in source_items):
            raise InformationCatalogError("bundle contains invalid information sources")
        if not all(isinstance(item, DataProduct) for item in product_items):
            raise InformationCatalogError("bundle contains invalid data products")
        if not all(isinstance(item, FieldPolicy) for item in policy_items):
            raise InformationCatalogError("bundle contains invalid field policies")

        with self._lock:
            next_sources = dict(self._sources)
            next_products = dict(self._products)
            next_policies = dict(self._field_policies)

            for source in source_items:
                if source.source_id in next_sources and not replace:
                    raise InformationCatalogError(
                        f"information source already exists: {source.source_id}"
                    )
                next_sources[source.source_id] = source
            for product in product_items:
                if product.source_id not in next_sources:
                    raise InformationCatalogError(
                        f"data product references unknown source: {product.source_id}"
                    )
                if product.product_id in next_products and not replace:
                    raise InformationCatalogError(
                        f"data product already exists: {product.product_id}"
                    )
                next_products[product.product_id] = product
            for policy in policy_items:
                if policy.product_id not in next_products:
                    raise InformationCatalogError(
                        f"field policy references unknown product: {policy.product_id}"
                    )
                key = (policy.product_id, policy.field_name)
                if key in next_policies and not replace:
                    raise InformationCatalogError(
                        f"field policy already exists: {policy.product_id}.{policy.field_name}"
                    )
                next_policies[key] = policy

            self._sources = next_sources
            self._products = next_products
            self._field_policies = next_policies

    def source(self, source_id: str) -> InformationSource | None:
        with self._lock:
            return self._sources.get(str(source_id))

    def product(self, product_id: str) -> DataProduct | None:
        with self._lock:
            return self._products.get(str(product_id))

    def require_source(self, source_id: str) -> InformationSource:
        source = self.source(source_id)
        if source is None:
            raise InformationCatalogError(f"unknown information source: {source_id}")
        return source

    def require_product(self, product_id: str) -> DataProduct:
        product = self.product(product_id)
        if product is None:
            raise InformationCatalogError(f"unknown data product: {product_id}")
        return product

    def field_policies(self, product_id: str) -> tuple[FieldPolicy, ...]:
        with self._lock:
            return tuple(
                policy
                for (candidate, _field), policy in self._field_policies.items()
                if candidate == str(product_id)
            )

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "sources": sorted(self._sources),
                "products": sorted(self._products),
                "field_policy_count": len(self._field_policies),
            }


__all__ = ["InformationCatalog", "InformationCatalogError"]
