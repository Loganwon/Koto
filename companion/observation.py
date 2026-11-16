"""Bounded native document observation. Called only on the connector's COM STA."""

from copy import deepcopy
import hashlib
import json
import time


def clean_text(text):
    return text.rstrip("\r\x07").replace("\r", "\n").replace("\x07", "\t")


def read_tables(document, selected=None):
    """Enumerate cells, not Rows (which fails for vertically merged cells)."""
    candidates, seen, tables = [], set(), []
    if selected is not None:
        for i in range(1, min(selected.Tables.Count, 6) + 1):
            candidates.append(selected.Tables.Item(i))
    total = document.Tables.Count
    for i in range(1, min(total, 6) + 1):
        candidates.append(document.Tables.Item(i))
    remaining, cell_budget = 18000, 300
    for native in candidates:
        start = native.Range.Start
        if start in seen:
            continue
        seen.add(start)
        cells, truncated = [], False
        collection = native.Range.Cells
        for index in range(1, min(collection.Count, cell_budget) + 1):
            cell = collection.Item(index)
            value = clean_text(cell.Range.Text)
            limit = min(2000, remaining)
            text = value[:limit]
            truncated |= len(text) < len(value)
            cells.append(
                {"row": cell.RowIndex, "column": cell.ColumnIndex, "text": text}
            )
            remaining -= len(text)
            cell_budget -= 1
            if remaining <= 0 or cell_budget <= 0:
                truncated = True
                break
        truncated |= len(cells) < collection.Count
        tables.append(
            {
                "label": f"表格 {len(tables) + 1}",
                "start": start,
                "cells": cells,
                "cell_count": collection.Count,
                "truncated": truncated,
            }
        )
        if remaining <= 0 or cell_budget <= 0 or len(tables) == 6:
            break
    return tables, total, len(seen) < total or any(t["truncated"] for t in tables)


def capture_document(host, document, selected):
    """Read a bounded context without activating, selecting, or saving anything."""
    start, end = selected.Start, selected.End
    body = document.Content
    # Reading a bounded native Range avoids copying a huge document over COM.
    excerpt = document.Range(body.Start, min(body.End, body.Start + 60000)).Text
    selected_text = selected.Text[:12000]
    current = selected if start != end else selected.Paragraphs.Item(1).Range
    current_text = clean_text(current.Text[:12000])
    tables, table_count, tables_truncated = read_tables(document, selected)
    location = (
        f"第 {document.Range(body.Start, max(body.Start, start)).Paragraphs.Count} 段"
    )
    if selected.Tables.Count and selected.Cells.Count:
        cell = selected.Cells.Item(1)
        location = f"表格 · 第 {cell.RowIndex} 行，第 {cell.ColumnIndex} 列"
    return {
        "connected": True,
        "host": host,
        "name": document.Name,
        "path": document.FullName if document.Path else "",
        "saved": bool(document.Saved),
        "read_only": bool(document.ReadOnly or document.ProtectionType != -1),
        "selection": {
            "start": start,
            "end": end,
            "text": clean_text(selected_text),
            "active": start != end,
        },
        "current_text": current_text,
        "location": location,
        "document_chars": max(0, body.End - body.Start - 1),
        "document_text": clean_text(excerpt[:18000]),
        "context_truncated": len(excerpt) > 18000
        or body.End - body.Start > 60000
        or end - start > 12000,
        "tables": tables,
        "table_count": table_count,
        "tables_truncated": tables_truncated,
        "content_fingerprint": hashlib.sha256(
            (excerpt + current_text + json.dumps(tables, ensure_ascii=False)).encode(
                "utf-8"
            )
        ).hexdigest(),
    }


def capture_selection(host, document, selected):
    """Fast local feedback: never enumerate tables or read the full document."""
    start, end = selected.Start, selected.End
    current = selected if start != end else selected.Paragraphs.Item(1).Range
    part = document.Range(current.Start, min(current.End, current.Start + 12000))
    text = clean_text(part.Text)
    body = document.Content
    excerpt = document.Range(body.Start, min(body.End, body.Start + 4000)).Text
    location = "已选文字" if start != end else "光标所在段落"
    if selected.Tables.Count and selected.Cells.Count:
        cell = selected.Cells.Item(1)
        location = f"表格 · 第 {cell.RowIndex} 行，第 {cell.ColumnIndex} 列"
    return {
        "connected": True,
        "host": host,
        "name": document.Name,
        "path": document.FullName if document.Path else "",
        "saved": bool(document.Saved),
        "selection": {
            "start": start,
            "end": end,
            "text": text if start != end else "",
            "active": start != end,
        },
        "current_text": text,
        "location": location,
        "document_chars": max(0, body.End - body.Start - 1),
        "document_text": clean_text(excerpt),
        "context_truncated": body.End - body.Start > 4000
        or current.End - current.Start > 12000,
        "tables": [],
        "table_count": document.Tables.Count,
        "tables_pending": True,
        "tables_truncated": False,
        "content_fingerprint": hashlib.sha256(
            (excerpt + text).encode("utf-8")
        ).hexdigest(),
    }


class DocumentObservation:
    """A cached local snapshot; the UI never runs native calls on its polling thread."""

    def observation(self):
        with self._observation_lock:
            return deepcopy(self._observation)

    def watch(self, host="auto", enabled=True):
        return self._call("watch", host, enabled)

    def _watch(self, host, enabled):
        from .windows import HOSTS
        from .contracts import CompanionError

        if host not in (*HOSTS, "auto"):
            raise CompanionError("请选择自动跟随、Word 或 WPS。")
        self._watch_host, self._watch_enabled = host, bool(enabled)
        self._next_observation = 0
        if not enabled:
            with self._observation_lock:
                self._observation = {
                    **self._observation,
                    "watching": False,
                    "message": "跟随已暂停",
                }

    def context(self, target_id):
        return self._call("context", target_id)

    def read_current(self, host="auto", quick=False):
        return self._call("read_current", host, quick)

    def agent_context(self, target_id):
        return self._call("context", target_id, True)

    def _read_current(self, host, quick=False):
        from .windows import HOSTS
        from .contracts import CompanionError
        import win32com.client

        if host == "auto":
            if not self._watch_enabled and self._last_host:
                host = self._last_host
            else:
                self._next_observation = 0
                self._poll_observation()
                observed = self.observation()
                if not observed.get("connected"):
                    raise CompanionError(observed.get("message", "请先打开文档。"))
                host = observed["host"]
        if host not in HOSTS:
            raise CompanionError("请选择 Word 或 WPS。")
        try:
            application = self._applications.get(host)
            if application is None:
                application = win32com.client.GetActiveObject(HOSTS[host][1])
                self._applications[host] = application
            document, selected = (
                application.ActiveDocument,
                application.Selection.Range.Duplicate,
            )
            if selected.StoryType != 1:
                raise CompanionError("请回到文档正文后再提问。")
            return (capture_selection if quick else capture_document)(
                host, document, selected
            )
        except CompanionError:
            raise
        except Exception:
            raise CompanionError("暂时无法读取当前文档，请检查原生应用。") from None

    def _context(self, target_id, quick=False):
        from .contracts import DocumentConflict

        if target_id != self._target_id:
            raise DocumentConflict("文档绑定已变化。")
        ranges = list(self._ranges.values())
        selected = self._document.Range(ranges[0].Start, ranges[-1].End)
        result = (capture_selection if quick else capture_document)(
            self._target_host, self._document, selected
        )
        if quick:
            # Keep initial model context strictly on the bound selection.
            # Full-document tools remain available when the task needs them.
            result.pop("document_text", None)
        return result

    def _poll_observation(self):
        if not self._watch_enabled or time.monotonic() < self._next_observation:
            return
        self._next_observation = time.monotonic() + 0.12
        from .windows import HOSTS
        import win32com.client
        import win32gui
        import win32process

        available = []
        foreground = win32gui.GetForegroundWindow()
        foreground_pid = (
            win32process.GetWindowThreadProcessId(foreground)[1] if foreground else 0
        )
        for host in HOSTS:
            if self._watch_host not in ("auto", host):
                continue
            try:
                application = self._applications.get(host)
                if application is None:
                    # Never launch an application just to monitor it.
                    application = win32com.client.GetActiveObject(HOSTS[host][1])
                    self._applications[host] = application
                if application.Documents.Count == 0:
                    continue
                try:
                    hwnd = int(application.ActiveWindow.Hwnd)
                    active = (
                        win32process.GetWindowThreadProcessId(hwnd)[1] == foreground_pid
                    )
                except Exception:
                    active = False
                available.append((host, application, active))
            except Exception:
                self._applications.pop(host, None)
        if not available:
            self._publish_observation(
                {"connected": False, "message": "打开 Word / WPS 文档，Koto 会自动跟随"}
            )
            return
        chosen = next((item for item in available if item[2]), None)
        if chosen is None:
            chosen = next(
                (item for item in available if item[0] == self._last_host), available[0]
            )
        host, application, _ = chosen
        try:
            document, selected = (
                application.ActiveDocument,
                application.Selection.Range.Duplicate,
            )
            if selected.StoryType != 1:
                self._publish_observation(
                    {
                        "connected": False,
                        "host": host,
                        "message": "当前位于页眉、批注等区域，请回到正文",
                    }
                )
                return
            observed = capture_selection(host, document, selected)
            self._last_host = host
            self._publish_observation(observed)
        except Exception:
            # A transient busy dialog must not leave stale text presented as live.
            self._publish_observation(
                {
                    "connected": False,
                    "host": host,
                    "message": "文档正在忙，稍后自动恢复跟随",
                }
            )

    def _publish_observation(self, observed):
        with self._observation_lock:
            previous = self._observation
            previous_data = {
                k: v
                for k, v in previous.items()
                if k not in ("revision", "watching", "activity", "updated_at")
            }
            previous_data.pop("checked_at", None)
            if previous_data == observed:
                self._observation["checked_at"] = time.time()
                return
            activity = list(previous.get("activity", []))
            if observed.get("connected"):
                if (
                    observed.get("host"),
                    observed.get("name"),
                    observed.get("path"),
                ) != (previous.get("host"), previous.get("name"), previous.get("path")):
                    label = "已跟随当前文档"
                elif observed.get("content_fingerprint") != previous.get(
                    "content_fingerprint"
                ) and (
                    observed.get("selection") == previous.get("selection")
                    or observed.get("document_text") != previous.get("document_text")
                    or observed.get("tables") != previous.get("tables")
                ):
                    label = "文档内容已更新"
                elif observed.get("saved") and not previous.get("saved"):
                    label = "文档已保存"
                else:
                    label = (
                        "选区已变化"
                        if observed["selection"]["active"]
                        else "光标已移动"
                    )
                activity.append(
                    {
                        "text": label,
                        "location": observed["location"],
                        "time": time.time(),
                    }
                )
            self._observation = {
                **observed,
                "watching": True,
                "revision": previous.get("revision", 0) + 1,
                "updated_at": time.time(),
                "checked_at": time.time(),
                "activity": activity[-5:],
            }
