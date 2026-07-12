# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import json
import time
import os

from web.sse.sanitizer import safe_sse as _safe_sse
from web.local_executor import LocalExecutor
from app.core.llm.provider_compat import types


def handle_system(yield_thinking, user_input, session_name, start_time, client, model_id, system_instruction, session_manager, _app_logger):
    from web.chat_runtime_services import get_utils

    Utils = get_utils()

    used_model = "LocalExecutor"
    yield _safe_sse({"type": "progress", "message": "正在分析系统指令...", "detail": ""})
    yield _safe_sse({"type": "progress", "message": "正在执行操作...", "detail": ""})

    exec_result = LocalExecutor.execute(user_input)
    response_text = exec_result["message"]
    if exec_result.get("details"):
        response_text += f"\n\n{exec_result['details']}"

    if Utils.is_failure_output(response_text) and exec_result.get("retryable") is not False:
        t = yield_thinking(
            "系统指令执行失败，使用 AI 修正后重试", "validating"
        )
        if t:
            yield t
        yield _safe_sse({"type": "progress", "message": "⚠️ 初次执行失败，正在修正...", "detail": ""})
        fix_prompt = Utils.build_fix_prompt(
            "SYSTEM", user_input, response_text
        )
        fix_resp = client.models.generate_content(
            model=model_id,
            contents=fix_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.4,
                max_output_tokens=1000,
            ),
        )
        response_text = fix_resp.text or response_text

    yield _safe_sse({"type": "token", "content": response_text})

    session_manager.append_and_save(
        f"{session_name}.json",
        user_input,
        response_text,
        task="SYSTEM",
        model_name=used_model,
    )

    total_time = time.time() - start_time
    yield _safe_sse({"type": "done", "images": [], "saved_files": [], "total_time": total_time})
