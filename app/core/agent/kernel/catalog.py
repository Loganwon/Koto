from __future__ import annotations

from threading import RLock
from typing import Dict, Iterable, List, Optional, Sequence

from .contracts import ToolSpec


class ToolRegistrationError(ValueError):
    """A catalog update was rejected without partially changing the catalog."""


class ToolCatalog:
    """Thread-safe canonical tool catalog with atomic batch registration."""

    def __init__(self) -> None:
        self._specs: Dict[str, ToolSpec] = {}
        self._lock = RLock()
        self._revision = 0

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def register(self, spec: ToolSpec, *, replace: bool = False) -> None:
        self.register_many([spec], replace=replace)

    def register_many(
        self, specs: Iterable[ToolSpec], *, replace: bool = False
    ) -> None:
        pending = list(specs)
        if not pending:
            return
        if not all(isinstance(spec, ToolSpec) for spec in pending):
            raise ToolRegistrationError("catalog only accepts ToolSpec instances")

        names = [spec.name for spec in pending]
        duplicate_names = sorted({name for name in names if names.count(name) > 1})
        if duplicate_names:
            raise ToolRegistrationError(
                f"duplicate tools in one registration batch: {', '.join(duplicate_names)}"
            )

        with self._lock:
            collisions = [name for name in names if name in self._specs]
            if collisions and not replace:
                raise ToolRegistrationError(
                    f"tools already registered: {', '.join(sorted(collisions))}"
                )
            updated = dict(self._specs)
            for spec in pending:
                updated[spec.name] = spec
            self._specs = updated
            self._revision += 1

    def get(self, name: str) -> Optional[ToolSpec]:
        with self._lock:
            return self._specs.get(str(name or ""))

    def require(self, name: str) -> ToolSpec:
        spec = self.get(name)
        if spec is None:
            raise KeyError(str(name or ""))
        return spec

    def definitions(
        self,
        *,
        allowlist: Optional[Sequence[str]] = None,
        capabilities: Optional[Sequence[str]] = None,
    ) -> List[dict]:
        allowed = set(allowlist) if allowlist is not None else None
        required_capabilities = set(capabilities or ())
        with self._lock:
            specs = list(self._specs.values())
        return [
            spec.llm_definition()
            for spec in specs
            if (allowed is None or spec.name in allowed)
            and (
                not required_capabilities
                or required_capabilities.intersection(spec.capabilities)
            )
        ]

    def names(self) -> List[str]:
        with self._lock:
            return list(self._specs)

    def __contains__(self, name: object) -> bool:
        with self._lock:
            return name in self._specs

    def __len__(self) -> int:
        with self._lock:
            return len(self._specs)
