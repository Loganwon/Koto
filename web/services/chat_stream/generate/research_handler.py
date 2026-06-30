# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import json
import logging
import time

_logger = logging.getLogger(__name__)

from web.sse.sanitizer import safe_sse as _safe_sse


def handle_research(
    yield_thinking,
    task_type,
    user_input,
    effective_input,
    session_name,
    start_time,
    model_id,
    system_instruction,
    context_info,
    _rag_context_block,
    client,
    session_manager,
    MODEL_MAP,
    WebSearcher,
    _app_logger,
    stream_with_keepalive,
    interrupted,
):
    """
    Deep research mode with streaming response.
    Handles fallback to flash model on 503 errors.
    """
    from google.genai import types

    if task_type != "RESEARCH":
        return

    research_model = model_id or MODEL_MAP.get("RESEARCH", "gemini-2.5-pro")
    used_model = research_model
    t = yield_thinking(
        f"进入深度研究模式，使用 {research_model} 进行专业级分析",
        "analyzing",
    )
    if t:
        yield t
    newline = "\n"
    _detail = (
        "使用 Interactions API 深度研究"
        if research_model.startswith("deep-research-pro-preview")
        else f"使用 {research_model} 进行流式分析"
    )
    yield f"data: {json.dumps({'type': 'progress', 'message': '🔬 启动深度研究模式...', 'detail': _detail})}{newline}{newline}"

    research_instruction = """你是一位专业的研究助手，擅长深度分析复杂技术话题。请按照以下结构提供全面深入的研究报告：

1. **技术概述**：清晰定义和解释核心概念
2. **技术原理**：详细说明工作机制和底层原理
3. **优势分析**：列举主要优点和应用场景
4. **问题与挑战**：分析存在的问题和技术瓶颈
5. **对比分析**：与其他同类技术进行横向对比
6. **发展趋势**：讨论未来发展方向和应用前景
7. **参考资料**：提供相关技术文档和学术资料的引用

📌 **特殊查询类型增强规则**：

**价格/费用/票务查询**（如高铁票、机票、酒店、门票等）：
- ✅ **首先输出一个清晰的表格**，包含关键信息（车次、发车时间、到达时间、座位、价格、时长等）
- ✅ 必须提供**具体价格**（例如：二等座 ¥524.5）
- ❌ 禁止使用价格区间（如"500-600元"）
- ✅ 按座位/房型等级**分别列出**每个选项的确切价格
- ✅ 列出**具体班次/车次号**（如 G12、航班 MU5137）
- ✅ 列出**发车时间和到达时间**，方便用户对比选择
- ❌ 禁止输出重复内容或多个相同的段落

**强制使用表格格式**：
```
🚄 上海虹桥 → 北京南（2026年2月12日）

| 车次   | 发车  | 到达  | 座位类型 | 价格     | 时长  |
|--------|-------|-------|----------|----------|-------|
| G12次  | 09:00 | 13:24 | 商务座   | ¥1,748   | 4h24m |
| G12次  | 09:00 | 13:24 | 一等座   | ¥933     | 4h24m |
| G12次  | 09:00 | 13:24 | 二等座   | ¥524.5   | 4h24m |
| G8次   | 10:00 | 14:31 | 商务座   | ¥1,748   | 4h31m |
| G8次   | 10:00 | 14:31 | 一等座   | ¥933     | 4h31m |
| G8次   | 10:00 | 14:31 | 二等座   | ¥524.5   | 4h31m |

💡 购票方式：访问 12306.cn 搜索对应车次购买。
```

要求：
- 提供具体的技术细节和数据支持
- 使用专业术语但确保可理解性
- 保持客观中立的分析态度
- 内容全面且有深度
- 适当使用图表和示例说明"""

    _research_skill = (context_info or {}).get("skill_prompt")
    if _research_skill:
        research_instruction += (
            f"\n\n[用户期望的输出重点] {_research_skill}"
        )
    if _rag_context_block:
        research_instruction += (
            f"\n\n[📚 知识库参考资料]\n{_rag_context_block}"
        )

    collected_text = []

    try:
        newline = "\n"
        if research_model.startswith("deep-research-pro-preview"):
            yield f"data: {json.dumps({'type': 'progress', 'message': '📊 正在进行深度分析...', 'detail': 'Deep Research 正在检索与综合，可能需要较长时间'})}{newline}{newline}"
            deep_text = WebSearcher.deep_research_for_ppt(
                effective_input, ""
            )
            if not deep_text:
                raise RuntimeError("Deep Research 未返回有效内容")
            collected_text.append(deep_text)
            yield f"data: {json.dumps({'type': 'token', 'content': deep_text})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'progress', 'message': '📊 正在进行深度分析...', 'detail': f'{research_model} 正在思考，可能需要30-90秒'})}{newline}{newline}"

            response_stream = client.models.generate_content_stream(
                model=research_model,
                contents=effective_input,
                config=types.GenerateContentConfig(
                    system_instruction=research_instruction,
                    temperature=0.7,
                    max_output_tokens=8000,
                    top_p=0.95,
                ),
            )

        if not research_model.startswith("deep-research-pro-preview"):
            chunk_count = 0
            heartbeat_interval = 5
            first_chunk_received = False

            for item_type, item_data in stream_with_keepalive(
                response_stream,
                start_time,
                keepalive_interval=heartbeat_interval,
                max_wait_first_token=90,
            ):
                if interrupted():
                    _app_logger.debug(f"[RESEARCH] 用户中断研究")
                    newline = "\n"
                    interrupt_msg = f"{newline}{newline}⏹️ 研究已被用户中断"
                    yield f"data: {json.dumps({'type': 'token', 'content': interrupt_msg})}{newline}{newline}"
                    break

                if item_type == "heartbeat":
                    elapsed = item_data
                    if first_chunk_received:
                        char_count = len("".join(collected_text))
                        yield f"data: {json.dumps({'type': 'progress', 'message': '📝 正在生成中...', 'detail': f'已生成 {char_count} 字符，耗时 {elapsed}s'})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'progress', 'message': '🧠 模型正在深度思考...', 'detail': f'已等待 {elapsed}s，请耐心等待'})}\n\n"

                elif item_type == "timeout":
                    yield f"data: {json.dumps({'type': 'token', 'content': f'⚠️ {item_data}，模型响应时间过长，请稍后重试'})}\n\n"
                    break

                elif item_type == "chunk":
                    chunk = item_data
                    if chunk.text:
                        if not first_chunk_received:
                            first_chunk_received = True
                            _app_logger.debug(
                                f"[RESEARCH] 收到第一个响应块，耗时 {time.time() - start_time:.1f}s"
                            )

                        collected_text.append(chunk.text)
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk.text})}\n\n"
                        chunk_count += 1

                        if chunk_count % 50 == 0:
                            _app_logger.debug(
                                f"[RESEARCH] 已生成 {chunk_count} 个chunk, {len(''.join(collected_text))} 字符"
                            )

        final_text = "".join(collected_text)
        _app_logger.info(
            f"[RESEARCH] ✅ 研究完成，共 {len(final_text)} 字符"
        )

        session_manager.append_and_save(
            f"{session_name}.json",
            user_input,
            final_text[:4000],
            task="RESEARCH",
            model_name=used_model,
        )

    except Exception as research_err:
        error_msg = str(research_err)
        _app_logger.debug(f"[RESEARCH] 错误: {error_msg}")

        if "503" in error_msg or "UNAVAILABLE" in error_msg:
            try:
                newline = "\n"
                yield f"data: {json.dumps({'type': 'progress', 'message': '⚠️ 服务繁忙，切换到 Gemini 2.5 Flash...', 'detail': ''})}{newline}{newline}"

                response_stream = client.models.generate_content_stream(
                    model="gemini-2.5-flash",
                    contents=effective_input,
                    config=types.GenerateContentConfig(
                        system_instruction=research_instruction,
                        temperature=0.7,
                        max_output_tokens=8000,
                    ),
                )

                last_heartbeat_flash = time.time()
                for chunk in response_stream:
                    if interrupted():
                        break
                    if chunk.text:
                        collected_text.append(chunk.text)
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk.text})}\n\n"

                        current_time = time.time()
                        if current_time - last_heartbeat_flash > 3:
                            elapsed = int(current_time - start_time)
                            yield f"data: {json.dumps({'type': 'progress', 'message': f'⚡ 快速模式生成中...', 'detail': f'{elapsed}s'})}\n\n"
                            last_heartbeat_flash = current_time

                final_text = "".join(collected_text)
                session_manager.append_and_save(
                    f"{session_name}.json",
                    user_input,
                    final_text[:4000],
                    task="RESEARCH",
                    model_name="gemini-2.5-flash",
                )

            except Exception as fallback_err:
                error_text = f"❌ 研究服务暂时不可用\n\n错误信息: {str(fallback_err)[:200]}\n\n💡 建议：\n1. 稍后重试\n2. 简化问题\n3. 使用普通对话模式"
                yield f"data: {json.dumps({'type': 'token', 'content': error_text})}\n\n"
                session_manager.append_and_save(
                    f"{session_name}.json",
                    user_input,
                    error_text[:1000],
                    task="RESEARCH",
                    model_name="gemini-2.5-flash",
                )

        elif (
            "timeout" in error_msg.lower()
            or "disconnect" in error_msg.lower()
        ):
            error_text = f"⚠️ 连接超时或中断\n\n可能原因：\n1. 网络不稳定\n2. 服务器繁忙\n3. 代理配置问题\n\n建议：请稍后重试，或检查网络连接"
            yield f"data: {json.dumps({'type': 'token', 'content': error_text})}\n\n"
            session_manager.append_and_save(
                f"{session_name}.json",
                user_input,
                error_text[:1000],
                task="RESEARCH",
                model_name=used_model,
            )

        else:
            error_text = f"❌ 研究过程中出现错误\n\n{error_msg[:300]}\n\n请尝试：\n1. 重新提问\n2. 简化问题描述\n3. 稍后重试"
            yield f"data: {json.dumps({'type': 'token', 'content': error_text})}\n\n"
            session_manager.append_and_save(
                f"{session_name}.json",
                user_input,
                error_text[:1000],
                task="RESEARCH",
                model_name=used_model,
            )

    total_time = time.time() - start_time
    newline = "\n"
    yield f"data: {json.dumps({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})}{newline}{newline}"
