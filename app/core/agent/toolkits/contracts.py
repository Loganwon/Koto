"""Stable metadata contract shared by first-party toolkits."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolkitDescriptor:
    toolkit_id: str
    version: str
    api_version: str
    description: str
    capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        if not str(self.toolkit_id or "").strip():
            raise ValueError("toolkit_id is required")
        if not str(self.version or "").strip():
            raise ValueError("toolkit version is required")
        if not str(self.api_version or "").strip():
            raise ValueError("toolkit api_version is required")

    @property
    def source(self) -> str:
        return f"toolkit:{self.toolkit_id}"


__all__ = ["ToolkitDescriptor"]
