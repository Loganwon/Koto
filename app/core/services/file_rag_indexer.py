# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
File RAG Indexer — 自动文件索引服务
====================================
监控工作区文件变更，自动将新增/修改的文件建立 RAG 向量索引。

特性：
  - 基于文件哈希去重，避免重复索引
  - 支持：PDF, DOCX, XLSX, PPTX, TXT, MD, CSV, JSON
  - 轮询模式（轻量，无需 OS 文件监听器）
  - 与 RAGService 深度集成

用法：
    from app.core.services.file_rag_indexer import FileRAGIndexer

    indexer = FileRAGIndexer(watch_dir="/path/to/workspace")
    indexer.scan_and_index()          # 一次性全量扫描
    indexer.start_watching(interval=30)  # 启动定期轮询
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ── 支持的文件扩展名 ─────────────────────────────────────────────────────────
SUPPORTED_EXTENSIONS: Set[str] = {
    ".txt",
    ".md",
    ".markdown",
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".pptx",
    ".ppt",
    ".csv",
    ".json",
}

# ── 文件哈希计算 ─────────────────────────────────────────────────────────────


def _file_hash(file_path: str, block_size: int = 65536) -> str:
    """计算文件的 SHA-256 哈希（仅读前 1MB + 文件大小，快速去重）。"""
    file_size = os.path.getsize(file_path)
    hasher = hashlib.sha256()
    hasher.update(str(file_size).encode())
    with open(file_path, "rb") as f:
        chunk = f.read(min(block_size, 1024 * 1024))
        hasher.update(chunk)
    return hasher.hexdigest()


# ── FileRAGIndexer ──────────────────────────────────────────────────────────


class FileRAGIndexer:
    """自动文件索引器。

    通过文件哈希追踪已索引文件，避免重复工作。
    支持一次性扫描和持续轮询两种模式。
    """

    def __init__(
        self,
        watch_dir: Optional[str] = None,
        index_dir: Optional[str] = None,
        state_file: Optional[str] = None,
        on_indexed: Optional[Callable[[str, int], None]] = None,
    ):
        """
        参数:
            watch_dir  : 监控的目录路径（默认：Koto workspace 目录）
            index_dir  : RAG 索引存储目录（默认：config/rag_index）
            state_file : 索引状态持久化文件（默认：watch_dir/.rag_state.json）
            on_indexed : 索引完成回调 (file_path, chunk_count)
        """
        if watch_dir is None:
            from app.core.config.workspace_runtime import get_workspace_root

            watch_dir = get_workspace_root()
        self.watch_dir = Path(watch_dir).expanduser().resolve()
        self.state_file = Path(state_file or (self.watch_dir / ".rag_state.json"))
        self.on_indexed = on_indexed
        self._index_dir = index_dir
        self._rag = None
        self._state: Dict[str, str] = {}  # {file_path: file_hash}
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._load_state()

    @property
    def rag(self):
        if self._rag is None:
            from app.core.services.rag_service import get_rag_service

            self._rag = get_rag_service(index_dir=self._index_dir)
        return self._rag

    # ── 状态持久化 ──────────────────────────────────────────────────────────

    def _load_state(self) -> None:
        """从磁盘加载索引状态。"""
        if self.state_file.exists():
            try:
                self._state = json.loads(self.state_file.read_text(encoding="utf-8"))
                logger.info(
                    "[FileRAGIndexer] 已加载索引状态: %d 个文件", len(self._state)
                )
            except Exception as exc:
                logger.warning("[FileRAGIndexer] 状态文件损坏，重置: %s", exc)
                self._state = {}

    def _save_state(self) -> None:
        """持久化索引状态到磁盘。"""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("[FileRAGIndexer] 保存状态失败: %s", exc)

    # ── 核心索引逻辑 ────────────────────────────────────────────────────────

    def _should_index(self, file_path: str) -> bool:
        """判断文件是否需要索引（新增或已修改）。"""
        path_str = str(Path(file_path).resolve())
        try:
            current_hash = _file_hash(file_path)
        except Exception:
            return False

        if path_str not in self._state:
            return True
        return self._state[path_str] != current_hash

    def index_file(self, file_path: str) -> int:
        """索引单个文件。返回新增 chunk 数量，-1 表示失败。"""
        try:
            logger.info("[FileRAGIndexer] 索引: %s", file_path)
            count = self.rag.index_file(file_path)
            if count >= 0:
                path_str = str(Path(file_path).resolve())
                self._state[path_str] = _file_hash(file_path)
                self._save_state()
                if self.on_indexed:
                    self.on_indexed(file_path, count)
            return count
        except Exception as exc:
            logger.warning("[FileRAGIndexer] 索引失败 %s: %s", file_path, exc)
            return -1

    def scan_and_index(self) -> Dict[str, Any]:
        """扫描监控目录，索引所有新文件和已修改文件。

        返回:
            {
                "scanned": int,      # 扫描的文件总数
                "indexed": int,      # 新索引的文件数
                "skipped": int,      # 跳过的文件数（未修改）
                "failed": int,       # 失败的文件数
                "total_chunks": int, # 新增 chunk 总数
                "details": {...}     # 每个文件的详细结果
            }
        """
        with self._lock:
            scanned = 0
            indexed = 0
            skipped = 0
            failed = 0
            total_chunks = 0
            details: Dict[str, Any] = {}

            for root, _dirs, files in os.walk(self.watch_dir):
                for filename in files:
                    ext = Path(filename).suffix.lower()
                    if ext not in SUPPORTED_EXTENSIONS:
                        continue

                    file_path = os.path.join(root, filename)
                    scanned += 1

                    if not self._should_index(file_path):
                        skipped += 1
                        continue

                    count = self.index_file(file_path)
                    if count >= 0:
                        indexed += 1
                        total_chunks += count
                        details[file_path] = {"status": "indexed", "chunks": count}
                    else:
                        failed += 1
                        details[file_path] = {"status": "failed"}

            result = {
                "scanned": scanned,
                "indexed": indexed,
                "skipped": skipped,
                "failed": failed,
                "total_chunks": total_chunks,
                "details": details,
            }
            logger.info(
                "[FileRAGIndexer] 扫描完成: 扫描=%d 索引=%d 跳过=%d 失败=%d chunks=%d",
                scanned,
                indexed,
                skipped,
                failed,
                total_chunks,
            )
            return result

    def remove_deleted(self) -> int:
        """Remove deleted files from both scan state and the canonical RAG index."""
        with self._lock:
            removed = 0
            for path_str in list(self._state.keys()):
                if os.path.exists(path_str):
                    continue
                try:
                    self.rag.remove_source(path_str)
                except Exception as exc:
                    logger.warning(
                        "[FileRAGIndexer] 清理已删除文件失败 %s: %s", path_str, exc
                    )
                    continue
                del self._state[path_str]
                removed += 1
            if removed:
                self._save_state()
                logger.info(
                    "[FileRAGIndexer] 清理了 %d 个已删除文件的索引条目", removed
                )
            return removed

    # ── 轮询模式 ────────────────────────────────────────────────────────────

    def start_watching(self, interval: int = 30) -> None:
        """启动后台轮询线程。

        参数:
            interval: 轮询间隔（秒），默认 30 秒
        """
        if self._running:
            logger.warning("[FileRAGIndexer] 已在运行中")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._watch_loop,
            args=(interval,),
            daemon=True,
            name="FileRAGIndexer",
        )
        self._thread.start()
        logger.info(
            "[FileRAGIndexer] 已启动文件监控 (间隔=%ds, 目录=%s)",
            interval,
            self.watch_dir,
        )

    def stop_watching(self) -> None:
        """停止后台轮询。"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("[FileRAGIndexer] 已停止文件监控")

    def _watch_loop(self, interval: int) -> None:
        """后台轮询循环。"""
        logger.info("[FileRAGIndexer] 监控循环启动")
        while self._running:
            try:
                self.scan_and_index()
                self.remove_deleted()
            except Exception as exc:
                logger.error("[FileRAGIndexer] 监控循环异常: %s", exc)
            time.sleep(interval)

    # ── 状态查询 ────────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """获取索引器状态。"""
        return {
            "running": self._running,
            "watch_dir": str(self.watch_dir),
            "indexed_files": len(self._state),
            "rag_stats": self.rag.stats(),
            "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
        }

    def get_indexed_files(self) -> List[Dict[str, str]]:
        """获取已索引文件列表。"""
        return [
            {"path": path, "hash": file_hash} for path, file_hash in self._state.items()
        ]

    def reindex_all(self) -> Dict[str, Any]:
        """清空状态并全量重建索引。"""
        with self._lock:
            self._state.clear()
            self._save_state()
            self.rag.clear()
        return self.scan_and_index()


_indexers: Dict[tuple[str, str, str], FileRAGIndexer] = {}
_indexers_lock = threading.RLock()


def _indexer_key(
    watch_dir: Optional[str] = None,
    index_dir: Optional[str] = None,
    state_file: Optional[str] = None,
) -> tuple[str, str, str]:
    if watch_dir is None:
        from app.core.config.workspace_runtime import get_workspace_root

        watch_dir = get_workspace_root()
    normalized_watch = str(Path(watch_dir).expanduser().resolve())
    normalized_index = str(Path(index_dir).expanduser().resolve()) if index_dir else ""
    normalized_state = str(
        Path(state_file or (Path(normalized_watch) / ".rag_state.json"))
        .expanduser()
        .resolve()
    )
    return normalized_watch, normalized_index, normalized_state


def get_file_rag_indexer(
    watch_dir: Optional[str] = None,
    index_dir: Optional[str] = None,
    state_file: Optional[str] = None,
) -> FileRAGIndexer:
    """Return the one indexer for a workspace/index/state configuration."""

    key = _indexer_key(watch_dir, index_dir, state_file)
    cached = _indexers.get(key)
    if cached is not None:
        return cached
    with _indexers_lock:
        cached = _indexers.get(key)
        if cached is None:
            cached = FileRAGIndexer(
                watch_dir=key[0],
                index_dir=key[1] or None,
                state_file=key[2],
            )
            _indexers[key] = cached
        return cached


def reset_file_rag_indexers_for_tests() -> None:
    """Stop and forget cached indexers without deleting indexes or state."""

    with _indexers_lock:
        indexers = tuple(_indexers.values())
        _indexers.clear()
    for indexer in indexers:
        indexer.stop_watching()
