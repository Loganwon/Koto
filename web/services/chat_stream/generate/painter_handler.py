# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

from __future__ import annotations

import json
import time


def handle_painter(
    task_type,
    user_input,
    effective_input,
    session_name,
    start_time,
    context_info,
    client,
    session_manager,
    settings_manager,
    Utils,
    WORKSPACE_DIR,
    _app_logger,
    interrupted,
):
    """Close the retired image-provider path without invoking archived clients."""
    if task_type != "PAINTER":
        return

    message = (
        "当前版本尚未配置可用的图片生成服务。"
        "你仍可以让我设计画面方案、编写图片提示词，或生成 SVG/HTML 可视化。"
    )
    _app_logger.info("[PAINTER] image generation provider is unavailable")
    yield f"data: {json.dumps({'type': 'progress', 'message': '图片生成服务暂不可用', 'detail': '未配置受支持的图片提供商', 'progress': 100, 'stage': 'unavailable'}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps({'type': 'token', 'content': message}, ensure_ascii=False)}\n\n"

    session_manager.append_and_save(
        f"{session_name}.json",
        user_input,
        message,
        task="PAINTER",
        model_name="unavailable",
    )
    yield f"data: {json.dumps({'type': 'done', 'images': [], 'saved_files': [], 'total_time': time.time() - start_time}, ensure_ascii=False)}\n\n"
