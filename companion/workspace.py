"""User-selected local tree and versioned, read-only reference tools."""

import os
from pathlib import Path
import threading

from .contracts import CompanionError, DocumentConflict
from .file_readers import SUPPORTED, parse_file


class LocalWorkspace:
    def __init__(self, excluded=()):
        self._root = None
        self._lock = threading.RLock()
        self._excluded = {Path(p).resolve() for p in excluded}
        self._statuses = {}
        self._generation = 0

    def open(self, directory):
        path = Path(directory).resolve()
        if not path.is_dir():
            raise CompanionError("请选择一个本地文件夹。")
        with self._lock:
            self._root = path
            self._statuses.clear()
            self._generation += 1
        return self.tree()

    def _path(self, file_id):
        with self._lock:
            root = self._root
        if not root or not isinstance(file_id, str) or not file_id:
            raise CompanionError("请先打开本地工作文件夹。")
        path = (root / file_id).resolve()
        if (
            not path.is_relative_to(root)
            or path in self._excluded
            or any(p.startswith(".") for p in path.relative_to(root).parts)
        ):
            raise CompanionError("这个文件不在已选择的工作区内，或属于受保护配置。")
        if not path.is_file():
            raise CompanionError("文件已移动或不存在，请刷新文件列表。")
        return path

    def tree(self, include_unsupported=False):
        with self._lock:
            root, statuses, generation = (
                self._root,
                dict(self._statuses),
                self._generation,
            )
        if root is None:
            return {
                "root": None,
                "name": "未打开文件夹",
                "entries": [],
                "generation": generation,
                "truncated": False,
            }
        entries, truncated = [], False
        for directory, folders, files in os.walk(root, followlinks=False):
            folders[:] = sorted(
                f
                for f in folders
                if not f.startswith(".")
                and f not in {"node_modules", "__pycache__", "dist"}
                and not (Path(directory) / f).is_symlink()
            )
            for name in sorted(files):
                path = Path(directory) / name
                readable = path.suffix.lower() in SUPPORTED
                if name.startswith((".", "~$")) or (not readable and not include_unsupported):
                    continue
                try:
                    file_id = path.relative_to(root).as_posix()
                    self._path(file_id)
                except (CompanionError, OSError):
                    continue
                entries.append(
                    {
                        "id": file_id,
                        "name": name,
                        "folder": path.parent.relative_to(root).as_posix(),
                        "status": statuses.get(file_id, "unread") if readable else "unsupported_format",
                        "readable": readable,
                    }
                )
                if len(entries) >= 1500:
                    truncated = True
                    break
            if truncated:
                break
        return {
            "root": str(root),
            "name": root.name,
            "entries": entries,
            "generation": generation,
            "truncated": truncated,
        }

    def session(self, live_reader=None):
        with self._lock:
            return ReferenceReads(self, self._generation, live_reader)

    def mark(self, file_id, status):
        with self._lock:
            self._statuses[file_id] = status


class ReferenceReads:
    """Each agent step pins source versions and verifies them before a native write."""

    def __init__(self, workspace, generation, live_reader):
        self.workspace, self.generation, self.live_reader = (
            workspace,
            generation,
            live_reader,
        )
        self._reads = {}

    def ensure_current(self):
        with self.workspace._lock:
            if self.workspace._generation != self.generation:
                raise DocumentConflict("工作文件夹已切换，请使用新工作区重新发起任务。")

    def list(self, start=0, limit=100, query=""):
        self.ensure_current()
        tree = self.workspace.tree(include_unsupported=True)
        if tree["generation"] != self.generation:
            raise DocumentConflict("工作文件夹已切换，请使用新工作区重新发起任务。")
        if (
            type(start) is not int
            or start < 0
            or type(limit) is not int
            or not 1 <= limit <= 200
            or not isinstance(query, str)
        ):
            raise CompanionError("文件列表读取范围无效。")
        files = [
            entry for entry in tree["entries"] if query.lower() in entry["id"].lower()
        ]
        end = min(start + limit, len(files))
        return {
            "name": tree["name"],
            "files": files[start:end],
            "next": end if end < len(files) else None,
            "count": len(files),
            "truncated": tree["truncated"],
            "listing_scope": "workspace_files_including_unreadable_formats",
        }

    def _load(self, file_id):
        self.ensure_current()
        path = self.workspace._path(file_id)
        self.workspace.mark(file_id, "reading")
        try:
            snapshot = self.live_reader(str(path)) if self.live_reader else None
            live = snapshot is not None
            if snapshot is None and path.suffix.lower() not in SUPPORTED:
                raise CompanionError(f"文件 {file_id} 存在，但暂不支持读取 {path.suffix} 格式；没有读取其内容，请提供可读版本。")
            snapshot = snapshot or parse_file(path)
            self.workspace.mark(
                file_id,
                "text_ready" if not snapshot.limitations else "text_with_limits",
            )
            return path, snapshot, live
        except Exception:
            self.workspace.mark(file_id, "error")
            raise

    def snapshot(self, file_id):
        self.ensure_current()
        if file_id not in self._reads:
            if len(self._reads) >= 8:
                raise CompanionError("本轮最多读取 8 个参考文件，请缩小范围。")
            self._reads[file_id] = self._load(file_id)
        return self._reads[file_id][1]

    def read(self, file_id, start=0, limit=10000):
        return {"file_id": file_id, **self.snapshot(file_id).read(start, limit)}

    def search(self, file_id, query):
        return {"file_id": file_id, **self.snapshot(file_id).search(query)}

    def verify(self):
        self.ensure_current()
        for file_id, (_, original, _) in self._reads.items():
            _, latest, _ = self._load(file_id)
            if original.version != latest.version:
                raise DocumentConflict(
                    f"参考文件 {file_id} 在等待期间已变化，旧修改未写入，请按最新资料重做。"
                )

    def evidence(self):
        return [
            {"file_id": file_id, **snapshot.manifest()}
            for file_id, (_, snapshot, _) in self._reads.items()
        ]
