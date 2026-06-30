# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""File-chat request handlers split out from ``web.app``.

The current ``web.app`` imports this module during startup. Keep this layer
thin: it saves uploaded files, extracts readable context with FileProcessor,
and delegates response generation back to the app module's existing ``brain``.
"""

from __future__ import annotations

import os
from typing import Any

from flask import jsonify

from web.file_processor import FileProcessor
from web.runtime_context import get_brain, get_model_map, get_session_manager, get_workspace_dir
from web.utils.filenames import secure_filename as _secure_filename


def _module_attr(app_module: Any, name: str, default: Any = None) -> Any:
    if app_module is not None:
        return getattr(app_module, name, default)
    return default


def _secure_name(app_module: Any, filename: str) -> str:
    sanitizer = _module_attr(app_module, "_secure_filename")
    if callable(sanitizer):
        return sanitizer(filename)
    return _secure_filename(filename)


def _uploads_dir(app_module: Any) -> str:
    workspace = get_workspace_dir() or _module_attr(app_module, "WORKSPACE_DIR") or os.getcwd()
    upload_dir = os.path.join(workspace, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def _save_upload(app_module: Any, file_obj: Any) -> str:
    filename = _secure_name(app_module, getattr(file_obj, "filename", "") or "")
    if not filename:
        raise ValueError("Empty filename")
    target = os.path.join(_uploads_dir(app_module), filename)
    file_obj.save(target)
    return target


def _format_context(path: str, user_input: str) -> tuple[str, dict[str, Any]]:
    processor = FileProcessor()
    raw = processor.process_file(path)
    formatted, file_data = processor.format_result_for_chat(raw, user_input)
    return formatted, file_data or {}


def _chat(app_module: Any, session_name: str, user_input: str, prompt: str, file_data: dict[str, Any], locked_model: str):
    try:
        brain = get_brain()
    except RuntimeError:
        brain = _module_attr(app_module, "brain")
    if brain is None:
        return jsonify({"error": "Chat brain is not initialized"}), 500

    try:
        session_manager = get_session_manager()
    except RuntimeError:
        session_manager = _module_attr(app_module, "session_manager")
    history = []
    if session_manager is not None:
        try:
            history = session_manager.load_session(f"{session_name}.json")
        except Exception:
            history = []

    model = None
    model_map = get_model_map() or _module_attr(app_module, "MODEL_MAP", {}) or {}
    if locked_model and locked_model != "auto":
        model = locked_model
    else:
        model = model_map.get("CHAT")

    result = brain.chat(
        history=history,
        user_input=prompt,
        file_data=file_data or None,
        model=model,
        auto_model=(locked_model == "auto"),
    )
    if not isinstance(result, dict):
        result = {"response": str(result or "")}

    response_text = result.get("response") or result.get("text") or ""
    if session_manager is not None:
        try:
            session_manager.append_and_save(f"{session_name}.json", user_input, response_text)
        except Exception:
            pass

    return jsonify(
        {
            "success": True,
            "response": response_text,
            "model": result.get("model"),
            "images": result.get("images", []),
            "saved_files": result.get("saved_files", []),
        }
    )


def handle_single_file_chat_request(
    *,
    app_module: Any,
    session_name: str,
    user_input: str,
    file: Any,
    locked_task: str | None = None,
    locked_model: str = "auto",
):
    """Handle ``POST /api/chat/file`` with one uploaded file."""
    try:
        path = _save_upload(app_module, file)
        prompt, file_data = _format_context(path, user_input)
        return _chat(app_module, session_name, user_input, prompt, file_data, locked_model)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def handle_multi_file_chat_request(
    *,
    app_module: Any,
    session_name: str,
    user_input: str,
    files: list[Any],
    locked_task: str | None = None,
    locked_model: str = "auto",
    stream_mode: bool = False,
):
    """Handle ``POST /api/chat/file`` with several uploaded files."""
    try:
        contexts: list[str] = []
        merged_file_data: dict[str, Any] = {}
        for file_obj in files:
            path = _save_upload(app_module, file_obj)
            context, file_data = _format_context(path, user_input)
            contexts.append(context)
            if file_data and not merged_file_data:
                merged_file_data = file_data

        prompt = (
            f"{user_input}\n\n"
            "以下是用户上传的多个文件内容，请综合这些文件回答：\n\n"
            + "\n\n---\n\n".join(contexts)
        )
        return _chat(app_module, session_name, user_input, prompt, merged_file_data, locked_model)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
