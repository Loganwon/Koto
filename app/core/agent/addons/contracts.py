"""Host-owned task routing contracts for admitted Koto Addons.

Addon is the runtime name for a plugin package that has passed the versioned
plugin protocol. These contracts are independent from retired extension models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.core.agent.plugin_protocol import DataClassification


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(str(value).strip() for value in values if str(value).strip())
    )


@dataclass(frozen=True)
class AddonBinding:
    """Host routing metadata for one declared Addon contribution."""

    contribution_name: str
    task_types: tuple[str, ...] = ()
    intent_patterns: tuple[str, ...] = ()
    file_types: tuple[str, ...] = ()
    priority: int = 50

    def __post_init__(self) -> None:
        name = str(self.contribution_name or "").strip()
        if not name:
            raise ValueError("addon binding requires contribution_name")
        priority = int(self.priority)
        if not 0 <= priority <= 100:
            raise ValueError("addon binding priority must be between 0 and 100")
        object.__setattr__(self, "contribution_name", name)
        object.__setattr__(
            self, "task_types", tuple(item.upper() for item in _unique(self.task_types))
        )
        object.__setattr__(
            self,
            "intent_patterns",
            tuple(item.casefold() for item in _unique(self.intent_patterns)),
        )
        object.__setattr__(
            self, "file_types", tuple(item.lower() for item in _unique(self.file_types))
        )
        object.__setattr__(self, "priority", priority)


@dataclass(frozen=True)
class AddonTaskRequest:
    task_type: str
    user_input: str = ""
    required_capabilities: tuple[str, ...] = ()
    file_types: tuple[str, ...] = ()
    data_classification: DataClassification = DataClassification.INTERNAL
    read_only: bool | None = None
    max_contributions: int = 8
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        task_type = str(self.task_type or "CHAT").strip().upper()
        if int(self.max_contributions) < 1 or int(self.max_contributions) > 32:
            raise ValueError("max_contributions must be between 1 and 32")
        object.__setattr__(self, "task_type", task_type)
        object.__setattr__(self, "user_input", str(self.user_input or ""))
        object.__setattr__(
            self, "required_capabilities", _unique(self.required_capabilities)
        )
        object.__setattr__(
            self, "file_types", tuple(item.lower() for item in _unique(self.file_types))
        )
        object.__setattr__(
            self, "data_classification", DataClassification(self.data_classification)
        )
        object.__setattr__(self, "max_contributions", int(self.max_contributions))
        object.__setattr__(self, "context", dict(self.context))


@dataclass(frozen=True)
class AddonExecutionPlan:
    task_type: str
    data_classification: DataClassification = DataClassification.INTERNAL
    addon_ids: tuple[str, ...] = ()
    tool_names: tuple[str, ...] = ()
    retriever_names: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    matched_bindings: tuple[str, ...] = ()
    rejected: Mapping[str, str] = field(default_factory=dict)

    @property
    def matched(self) -> bool:
        return bool(self.tool_names or self.retriever_names)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "data_classification": self.data_classification.value,
            "matched": self.matched,
            "addon_ids": list(self.addon_ids),
            "tool_names": list(self.tool_names),
            "retriever_names": list(self.retriever_names),
            "capabilities": list(self.capabilities),
            "matched_bindings": list(self.matched_bindings),
            "rejected": dict(self.rejected),
        }

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "data_classification",
            DataClassification(self.data_classification),
        )


__all__ = ["AddonBinding", "AddonExecutionPlan", "AddonTaskRequest"]
