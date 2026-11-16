# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Knowledge Base Config — 知识库配置层
====================================
管理公司内部知识库的目录配置、索引策略和状态。

用法:
    from app.core.services.kb_config import KBConfig

    kb = KBConfig()
    kb.set_root("/path/to/company/docs")
    kb.get_status()  # {root, indexed_files, total_chunks, ...}
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_LEGACY_CONFIG_PATH = _PROJECT_ROOT / "config" / "kb_config.json"


def _default_config_path() -> Path:
    """Return the mutable KB settings path outside the source config tree."""
    explicit = str(os.environ.get("KOTO_KB_CONFIG_PATH") or "").strip()
    return Path(explicit) if explicit else _PROJECT_ROOT / "data" / "kb_config.json"


class KBConfig:
    """知识库配置管理器。

    管理：
      - 知识库根目录
      - 索引策略（自动/手动）
      - 支持的文件类型
      - 索引状态
    """

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path) if path is not None else _default_config_path()
        self._config = self._load()

    def _load(self) -> Dict[str, Any]:
        candidates = [self._path]
        # Older source installations stored personal paths under config/. Read
        # that file once as a compatibility fallback, but all subsequent writes
        # go to data/ (or the explicit override) so source stays immutable.
        if (
            "KOTO_KB_CONFIG_PATH" not in os.environ
            and self._path != _LEGACY_CONFIG_PATH
            and not self._path.exists()
        ):
            candidates.append(_LEGACY_CONFIG_PATH)
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                loaded = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    return loaded
            except Exception:
                pass
        return {
            "root_dir": "",
            "auto_index": True,
            "watch_interval": 30,
            "extensions": [
                ".txt",
                ".md",
                ".pdf",
                ".docx",
                ".doc",
                ".xlsx",
                ".xls",
                ".pptx",
                ".ppt",
                ".csv",
                ".json",
            ],
            "created_at": "",
        }

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── 根目录 ──────────────────────────────────────────────────────────

    @property
    def root_dir(self) -> str:
        return self._config.get("root_dir", "")

    def set_root(self, path: str) -> bool:
        """设置知识库根目录。"""
        p = Path(path).resolve()
        if not p.exists():
            logger.error("[KBConfig] 目录不存在: %s", path)
            return False
        if not p.is_dir():
            logger.error("[KBConfig] 路径不是目录: %s", path)
            return False
        self._config["root_dir"] = str(p)
        import time

        self._config["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._save()
        logger.info("[KBConfig] 知识库根目录已设置: %s", p)
        return True

    @property
    def auto_index(self) -> bool:
        return bool(self._config.get("auto_index", True))

    @auto_index.setter
    def auto_index(self, value: bool) -> None:
        self._config["auto_index"] = bool(value)
        self._save()

    @property
    def watch_interval(self) -> int:
        return int(self._config.get("watch_interval", 30))

    @property
    def extensions(self) -> List[str]:
        return list(self._config.get("extensions", []))

    def get_status(self) -> Dict[str, Any]:
        """获取 KB 综合状态。"""
        status = {
            "configured": bool(self.root_dir),
            "root_dir": self.root_dir,
            "auto_index": self.auto_index,
            "watch_interval": self.watch_interval,
            "extensions": self.extensions,
            "created_at": self._config.get("created_at", ""),
        }

        # 附加 RAG 索引状态
        try:
            from app.core.services.rag_service import get_rag_service

            rag = get_rag_service()
            status["rag"] = rag.stats()
        except Exception:
            status["rag"] = {"initialized": False}

        # 附加索引器状态
        try:
            from app.core.services.file_rag_indexer import get_file_rag_indexer

            indexer = (
                get_file_rag_indexer(watch_dir=self.root_dir) if self.root_dir else None
            )
            if indexer:
                status["indexer"] = indexer.get_status()
        except Exception:
            status["indexer"] = {"running": False}

        # 检查 Ollama 状态
        status["ollama"] = _check_ollama()

        # 附加模型配置信息
        try:
            from app.core.llm.model_config import (
                get_chat_model,
                get_embed_model,
                get_model_mode,
            )

            status["model_config"] = {
                "mode": get_model_mode(),
                "chat_model": get_chat_model(),
                "embed_model": get_embed_model(),
            }
        except Exception:
            status["model_config"] = {"mode": "unknown"}

        return status


def _check_ollama() -> Dict[str, Any]:
    """检查 Ollama 是否就绪 + 已安装的模型列表。"""
    result = {"available": False, "models": [], "recommendation": ""}
    try:
        import socket

        s = socket.socket()
        s.settimeout(0.3)
        if s.connect_ex(("127.0.0.1", 11434)) != 0:
            result["recommendation"] = "请先安装并启动 Ollama: https://ollama.com"
            s.close()
            return result
        s.close()

        import urllib.request

        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            result["available"] = True
            result["models"] = [m["name"] for m in data.get("models", [])]

        # 检查推荐的模型
        has_embed = any(
            "nomic-embed" in m or "bge-m3" in m or "mxbai" in m or "minilm" in m
            for m in result["models"]
        )
        has_chat = len([m for m in result["models"] if "embed" not in m.lower()]) > 0

        missing = []
        if not has_embed:
            missing.append("nomic-embed-text")
        if not has_chat:
            missing.append("qwen2.5:7b")

        if missing:
            result["recommendation"] = (
                f"建议运行: ollama pull {' && ollama pull '.join(missing)}"
            )
        else:
            result["recommendation"] = "✅ Ollama 就绪"

    except Exception as e:
        result["recommendation"] = f"Ollama 连接异常: {e}"

    return result
