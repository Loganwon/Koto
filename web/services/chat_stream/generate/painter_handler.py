# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import json
import logging
import os
import queue
import threading
import time

_logger = logging.getLogger(__name__)

from web.sse.sanitizer import safe_sse as _safe_sse


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
    """
    Image generation handler (Gemini 3.1 Flash Image → Imagen 4.0 fallback).
    """
    from google.genai import types

    if task_type != "PAINTER":
        return

    used_model = "Gemini 3.1 Flash Image (Imagen 4.0 fallback)"
    yield f"data: {json.dumps({'type': 'progress', 'message': '🎨 正在理解你的创作请求...', 'detail': '', 'progress': 5, 'stage': 'paint_prepare'})}\n\n"

    if (
        context_info
        and context_info.get("is_continuation")
        and context_info.get("enhanced_input")
    ):
        image_prompt = context_info["enhanced_input"]
        _app_logger.debug(
            f"[PAINTER] 使用上下文增强的prompt: {image_prompt[:100]}..."
        )
    else:
        image_prompt = effective_input

    yield f"data: {json.dumps({'type': 'progress', 'message': '🖌️ Gemini 3.1 Flash Image 正在生成图像...', 'detail': '请耐心等待', 'progress': 20, 'stage': 'paint_generate'})}\n\n"

    max_retries = 2
    use_fallback = False
    images = []

    for attempt in range(max_retries):
        try:
            if interrupted():
                yield f"data: {json.dumps({'type': 'token', 'content': '⏹️ 图像生成已中断'})}\n\n"
                total_time = time.time() - start_time
                yield f"data: {json.dumps({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})}\n\n"
                return

            if attempt > 0:
                yield f"data: {json.dumps({'type': 'progress', 'message': f'🔄 第 {attempt} 次重试...', 'detail': '', 'progress': 25, 'stage': 'paint_retry'})}\n\n"
                time.sleep(2)

            if use_fallback:
                model_name = "Imagen 4.0"
                yield f"data: {json.dumps({'type': 'progress', 'message': '🔄 切换到 Imagen 4.0...', 'detail': '', 'progress': 30, 'stage': 'paint_fallback'})}\n\n"
            else:
                model_name = "Gemini 3.1 Flash Image"

            result_queue = queue.Queue()

            def worker():
                try:
                    if use_fallback:
                        result = client.models.generate_images(
                            model="imagen-4.0-fast-generate-001",
                            prompt=image_prompt,
                            config=types.GenerateImagesConfig(
                                number_of_images=1
                            ),
                        )
                    else:
                        result = client.models.generate_content(
                            model="gemini-3.1-flash-image-preview",
                            contents=image_prompt,
                            config=types.GenerateContentConfig(
                                response_modalities=["TEXT", "IMAGE"]
                            ),
                        )
                    result_queue.put(("success", result))
                except Exception as e:
                    result_queue.put(("error", e))

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()

            timeout_seconds = 120 if not use_fallback else 90
            attempt_start = time.time()
            timed_out = False
            response = None

            while True:
                attempt_elapsed = time.time() - attempt_start

                if attempt_elapsed > timeout_seconds:
                    timed_out = True
                    if not use_fallback:
                        _app_logger.debug(
                            f"[PAINTER] Gemini 3.1 Flash Image 超时 ({int(attempt_elapsed)}s)，切换到 Imagen"
                        )
                        use_fallback = True
                        yield f"data: {json.dumps({'type': 'progress', 'message': '⏱️ 模型响应超时，切换到 Imagen...', 'detail': '', 'progress': 28, 'stage': 'paint_fallback'})}\n\n"
                        break
                    else:
                        elapsed = time.time() - start_time
                        yield f"data: {json.dumps({'type': 'token', 'content': f'⚠️ 图像生成超时 ({int(elapsed)}s)，请稍后重试'})}\n\n"
                        total_time = time.time() - start_time
                        yield f"data: {json.dumps({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})}\n\n"
                        return

                if interrupted():
                    yield f"data: {json.dumps({'type': 'token', 'content': '⏹️ 图像生成已中断'})}\n\n"
                    total_time = time.time() - start_time
                    yield f"data: {json.dumps({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})}\n\n"
                    return

                try:
                    status, data = result_queue.get(timeout=3.0)
                    if status == "success":
                        response = data
                        break
                    else:
                        raise data
                except queue.Empty:
                    progress_guess = min(
                        85,
                        30 + int((attempt_elapsed / timeout_seconds) * 55),
                    )
                    yield f"data: {json.dumps({'type': 'progress', 'message': f'🎨 {model_name} 生成中...', 'detail': f'{int(attempt_elapsed)}s', 'progress': progress_guess, 'stage': 'paint_running'})}\n\n"

            if timed_out:
                continue

            yield f"data: {json.dumps({'type': 'progress', 'message': '💾 正在保存图片...', 'detail': '', 'progress': 90, 'stage': 'paint_save'})}\n\n"

            if use_fallback:
                if response.generated_images:
                    for gen_img in response.generated_images:
                        img_data = gen_img.image.image_bytes
                        images_dir = settings_manager.images_dir
                        os.makedirs(images_dir, exist_ok=True)
                        timestamp = int(time.time())
                        filename = f"generated_{timestamp}.png"
                        filepath = os.path.join(images_dir, filename)
                        with open(filepath, "wb") as f:
                            f.write(img_data)

                        try:
                            rel_path = os.path.relpath(
                                filepath, WORKSPACE_DIR
                            ).replace("\\", "/")
                            if ".." not in rel_path:
                                images.append(rel_path)
                                _app_logger.debug(
                                    f"[PAINTER] Imagen 已保存: {rel_path}"
                                )
                            else:
                                abs_workspace_images = os.path.join(
                                    WORKSPACE_DIR, "images"
                                )
                                os.makedirs(
                                    abs_workspace_images, exist_ok=True
                                )
                                fallback_filepath = os.path.join(
                                    abs_workspace_images, filename
                                )
                                with open(fallback_filepath, "wb") as f:
                                    f.write(img_data)
                                fallback_rel = os.path.relpath(
                                    fallback_filepath, WORKSPACE_DIR
                                ).replace("\\", "/")
                                images.append(fallback_rel)
                                _app_logger.debug(
                                    f"[PAINTER] Imagen 降级保存: {fallback_rel}"
                                )
                        except Exception as path_err:
                            _app_logger.debug(
                                f"[PAINTER] Path error: {path_err}"
                            )
            else:
                if (
                    response.candidates
                    and response.candidates[0].content.parts
                ):
                    for part in response.candidates[0].content.parts:
                        if (
                            hasattr(part, "inline_data")
                            and part.inline_data
                        ):
                            img_filename = Utils.save_image_part(part)
                            if img_filename:
                                images.append(img_filename)
                                _app_logger.debug(
                                    f"[PAINTER] Gemini 3.1 Flash Image 已保存: {img_filename}"
                                )

            if images:
                save_path = settings_manager.images_dir
                msg = f"✨ 图片已生成! (使用 {model_name})\n🖼️ 保存位置: {save_path}"
                yield f"data: {json.dumps({'type': 'token', 'content': msg})}\n\n"

                yield f"data: {json.dumps({'type': 'progress', 'message': '✅ 图像生成完成', 'detail': f'{len(images)} 张', 'progress': 100, 'stage': 'complete'})}\n\n"

                session_manager.append_and_save(
                    f"{session_name}.json",
                    user_input,
                    "图像已生成",
                    images=images,
                    task="PAINTER",
                    model_name=model_name,
                )

                total_time = time.time() - start_time
                _app_logger.debug(
                    f"[PAINTER] 发送图片列表: {images}"
                )
                yield f"data: {json.dumps({'type': 'done', 'images': images, 'saved_files': [], 'total_time': total_time})}\n\n"
                return
            else:
                if not use_fallback:
                    use_fallback = True
                    continue
                else:
                    yield f"data: {json.dumps({'type': 'token', 'content': '❌ 模型未返回图片'})}\n\n"

        except Exception as img_err:
            error_msg = str(img_err)
            model_label = (
                "Imagen" if use_fallback else "Gemini-3.1-Flash-Image"
            )
            _app_logger.debug(
                f"[PAINTER] {model_label} 尝试 {attempt+1} 失败 ({type(img_err).__name__}): {error_msg[:300]}"
            )

            if (
                not use_fallback
                and "safety" not in error_msg.lower()
                and "blocked" not in error_msg.lower()
            ):
                _app_logger.debug(
                    f"[PAINTER] Gemini 3.1 Flash Image 失败，切换到 Imagen: {error_msg[:200]}"
                )
                use_fallback = True
                continue

            if (
                "safety" in error_msg.lower()
                or "blocked" in error_msg.lower()
            ):
                user_msg = "❌ 内容被安全策略过滤，请修改描述"
            elif "location is not supported" in error_msg.lower():
                user_msg = "❌ 地区限制，请配置中转服务"
            else:
                user_msg = f"❌ 图像生成失败: {error_msg[:100]}"

            yield f"data: {json.dumps({'type': 'token', 'content': user_msg})}\n\n"

    session_manager.append_and_save(
        f"{session_name}.json", user_input, "图像生成失败"
    )

    total_time = time.time() - start_time
    yield f"data: {json.dumps({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})}\n\n"
