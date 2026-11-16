"""Evidence-preserving retrieval boundary for future RAG plugins."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Tuple

from .contracts import PluginProtocolError

RETRIEVAL_REQUEST_JSON_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 100},
        "tenant_id": {"type": "string"},
        "principal_id": {"type": "string"},
        "filters": {"type": "object"},
        "correlation_id": {"type": "string"},
    },
    "required": ["query"],
    "additionalProperties": False,
}

RETRIEVAL_BATCH_JSON_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "provider_id": {"type": "string", "minLength": 1},
        "correlation_id": {"type": "string"},
        "truncated": {"type": "boolean"},
        "chunks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string", "minLength": 1},
                    "text": {"type": "string", "minLength": 1},
                    "source_uri": {"type": "string", "minLength": 1},
                    "source_title": {"type": "string", "minLength": 1},
                    "citation": {"type": "string", "minLength": 1},
                    "score": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
                    "metadata": {"type": "object"},
                    "acl_tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "chunk_id",
                    "text",
                    "source_uri",
                    "source_title",
                    "citation",
                    "metadata",
                    "acl_tags",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["provider_id", "correlation_id", "truncated", "chunks"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    top_k: int = 8
    tenant_id: str = ""
    principal_id: str = ""
    filters: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str = ""

    def __post_init__(self) -> None:
        if not str(self.query or "").strip():
            raise PluginProtocolError("retrieval query must not be empty")
        if not 1 <= int(self.top_k) <= 100:
            raise PluginProtocolError("retrieval top_k must be between 1 and 100")
        if not isinstance(self.filters, Mapping):
            raise PluginProtocolError("retrieval filters must be an object")
        object.__setattr__(self, "query", str(self.query).strip())
        object.__setattr__(self, "filters", copy.deepcopy(dict(self.filters)))


@dataclass(frozen=True)
class EvidenceChunk:
    chunk_id: str
    text: str
    source_uri: str
    source_title: str
    citation: str
    score: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    acl_tags: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for label, value in (
            ("chunk_id", self.chunk_id),
            ("text", self.text),
            ("source_uri", self.source_uri),
            ("source_title", self.source_title),
            ("citation", self.citation),
        ):
            if not str(value or "").strip():
                raise PluginProtocolError(f"evidence {label} must not be empty")
        if self.score is not None and not 0 <= float(self.score) <= 1:
            raise PluginProtocolError("evidence score must be in [0, 1]")
        if not isinstance(self.metadata, Mapping):
            raise PluginProtocolError("evidence metadata must be an object")
        object.__setattr__(self, "metadata", copy.deepcopy(dict(self.metadata)))
        object.__setattr__(
            self,
            "acl_tags",
            tuple(
                dict.fromkeys(
                    str(item).strip() for item in self.acl_tags if str(item).strip()
                )
            ),
        )


@dataclass(frozen=True)
class RetrievalBatch:
    provider_id: str
    chunks: Tuple[EvidenceChunk, ...]
    correlation_id: str = ""
    truncated: bool = False

    def __post_init__(self) -> None:
        if not str(self.provider_id or "").strip():
            raise PluginProtocolError("retrieval batch requires provider_id")
        if not all(isinstance(item, EvidenceChunk) for item in self.chunks):
            raise PluginProtocolError(
                "retrieval batch only accepts EvidenceChunk items"
            )


@dataclass(frozen=True)
class RetrieverSpec:
    name: str
    description: str
    handler: Callable[[RetrievalRequest], RetrievalBatch] = field(
        repr=False, compare=False
    )
    source: str = ""
    version: str = "1.0.0"
    capabilities: Tuple[str, ...] = ()
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not str(self.name or "").strip() or not str(self.description or "").strip():
            raise PluginProtocolError("retriever requires name and description")
        if not callable(self.handler):
            raise PluginProtocolError("retriever handler must be callable")
        if float(self.timeout_seconds) <= 0:
            raise PluginProtocolError("retriever timeout_seconds must be positive")


__all__ = [
    "EvidenceChunk",
    "RETRIEVAL_BATCH_JSON_SCHEMA",
    "RETRIEVAL_REQUEST_JSON_SCHEMA",
    "RetrievalBatch",
    "RetrievalRequest",
    "RetrieverSpec",
]
