"""Immutable, fully addressable text snapshots; model context remains paginated."""

from dataclasses import dataclass
import hashlib

from .contracts import CompanionError


class DeferredSnapshot:
    """Read native full text only when the agent requests it, once per step."""

    def __init__(self, name, loader):
        self.name, self._loader, self._snapshot = name, loader, None

    def manifest(self):
        return (
            self._snapshot.manifest()
            if self._snapshot
            else {
                "name": self.name,
                "loaded": False,
                "access": "可通过 read_current_document / search_current_document 按需读取全文",
            }
        )

    def _get(self):
        if self._snapshot is None:
            self._snapshot = self._loader()
        return self._snapshot

    def read(self, *args, **kwargs):
        return self._get().read(*args, **kwargs)

    def search(self, *args, **kwargs):
        return self._get().search(*args, **kwargs)


@dataclass(frozen=True)
class TextSnapshot:
    name: str
    text: str
    coverage: tuple[str, ...] = ("文本",)
    limitations: tuple[str, ...] = ()

    @property
    def version(self):
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def manifest(self):
        return {
            "name": self.name,
            "characters": len(self.text),
            "version": self.version,
            "coverage": list(self.coverage),
            "limitations": list(self.limitations),
        }

    def read(self, start=0, limit=10000):
        if type(start) is not int or start < 0 or start > len(self.text):
            raise CompanionError("读取位置无效。")
        if type(limit) is not int or not 1 <= limit <= 12000:
            raise CompanionError("每次读取范围应为 1 至 12000 字符。")
        end = min(len(self.text), start + limit)
        return {
            **self.manifest(),
            "start": start,
            "end": end,
            "next": end if end < len(self.text) else None,
            "text": self.text[start:end],
        }

    def search(self, query, limit=8):
        if not isinstance(query, str) or not query.strip() or len(query) > 200:
            raise CompanionError("请提供 1 至 200 字的查找内容。")
        matches, position = [], 0
        lowered = self.text.lower()
        needle = query.lower()
        while len(matches) < limit:
            found = lowered.find(needle, position)
            if found < 0:
                break
            start, end = max(0, found - 350), min(
                len(self.text), found + len(query) + 650
            )
            matches.append(
                {
                    "offset": found,
                    "start": start,
                    "end": end,
                    "text": self.text[start:end],
                }
            )
            position = found + len(query)
        return {
            **self.manifest(),
            "matches": matches,
            "more": lowered.find(needle, position) >= 0,
        }
