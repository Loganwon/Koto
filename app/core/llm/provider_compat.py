"""Small provider-neutral request value objects.

These types keep request construction independent from vendor SDK packages.
Execution belongs to :mod:`app.core.llm.runtime_gateway`; this module
intentionally exposes no client or ``client.models`` compatibility surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any


class _DataObject:
    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class GenerateContentConfig(_DataObject):
    pass


class GenerateImagesConfig(_DataObject):
    pass


class ThinkingConfig(_DataObject):
    pass


class FunctionDeclaration(_DataObject):
    pass


class Tool(_DataObject):
    pass


class GoogleSearch(_DataObject):
    pass


@dataclass
class Part:
    text: str | None = None
    data: bytes | None = None
    mime_type: str | None = None

    @classmethod
    def from_text(cls, *, text: str) -> "Part":
        return cls(text=text)

    @classmethod
    def from_bytes(cls, *, data: bytes, mime_type: str) -> "Part":
        return cls(data=data, mime_type=mime_type)


@dataclass
class Content:
    role: str
    parts: list[Part]


class Candidate(_DataObject):
    pass


class UsageMetadata(_DataObject):
    pass


types = SimpleNamespace(
    GenerateContentConfig=GenerateContentConfig,
    GenerateImagesConfig=GenerateImagesConfig,
    ThinkingConfig=ThinkingConfig,
    FunctionDeclaration=FunctionDeclaration,
    Tool=Tool,
    GoogleSearch=GoogleSearch,
    Part=Part,
    Content=Content,
    Candidate=Candidate,
    UsageMetadata=UsageMetadata,
)
