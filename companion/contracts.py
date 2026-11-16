"""Portable document contracts; native handles never leave their owning thread."""

from dataclasses import dataclass, field
from typing import Protocol


class CompanionError(Exception):
    """An actionable error which is safe to display in the local window."""


class DocumentConflict(CompanionError):
    pass


class OperationCancelled(CompanionError):
    pass


class ResultUncertain(CompanionError):
    """A native action might have completed. Never automatically retry it."""


@dataclass(frozen=True)
class Fragment:
    id: str
    text: str
    label: str = "正文"
    editable: bool = True
    reason: str = ""
    kind: str = "text"
    metadata: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class DocumentTarget:
    id: str
    host: str
    name: str
    scope: str
    fragments: tuple[Fragment, ...]
    path: str = ""
    context: dict = field(default_factory=dict, repr=False, compare=False)


class DocumentPort(Protocol):
    def connect(self, host: str) -> DocumentTarget: ...

    def read(self, target_id: str, fragment_id: str) -> str: ...

    def replace(
        self,
        target_id: str,
        fragment_id: str,
        expected: str,
        replacement: str,
        permitted,
    ) -> str: ...

    def locate(self, target_id: str, fragment_id: str) -> None: ...

    def close(self) -> None: ...


def validate_replacement(text: str) -> None:
    if not isinstance(text, str) or not text.strip():
        raise CompanionError("这一段的修改内容为空，请调整要求后重试。")
    if len(text) > 12000:
        raise CompanionError("单段修改过长，请缩小选区。")
    if any(ord(char) < 32 and char != "\t" for char in text):
        raise CompanionError("本轮仅修改单段文字，不能插入换行或文档控制符。")
