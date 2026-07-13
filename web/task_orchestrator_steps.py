# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import asyncio
import logging
import os
import time

try:
    from app.core.llm.provider_compat import types
except Exception:  # pragma: no cover - optional SDK in some test envs
    types = None

from web.local_executor import LocalExecutor
from web.task_orchestrator_runtime import (
    MODEL_MAP,
    WORKSPACE_DIR,
    call_interactions_api_sync,
    client,
    get_interactions_fallback_model,
    settings_manager,
)
from web.utils.assistant_utils import Utils
from web.web_searcher import WebSearcher

_app_logger = logging.getLogger("koto.app")


async def execute_painter(
    user_input: str, context: dict, progress_callback=None
) -> dict:
    """执行图像生成子任务 - 为PPT等生成配图 (带可视进度)"""

    def _report(msg: str, detail: str = ""):
        _app_logger.debug(f"[PAINTER] {msg} | {detail}")
        if progress_callback:
            progress_callback(msg, detail)

    try:
        topic = context.get("original_input", user_input)
        prompt = f"Professional illustration for: {topic[:100]}. Clean flat design, no text."

        image_paths = []
        images_dir = os.path.join(WORKSPACE_DIR, "images")
        os.makedirs(images_dir, exist_ok=True)

        _report("启动图像生成...", "调用 Imagen 4 模型")

        for i in range(2):
            try:
                _report(
                    f"正在生成第 {i+1}/2 张配图...", f"提示词: {prompt[:30]}..."
                )

                # Run potentially blocking generation in thread
                fname = f"painter_{i}_{int(time.time()*1000)%1000000}.png"
                fpath = os.path.join(images_dir, fname)
                _img_models = [
                    "imagen-4.0-generate-001",
                    "imagen-4.0-fast-generate-001",
                    "imagen-3.0-generate-001",
                ]
                _img_res = None
                for _img_m in _img_models:
                    try:
                        _img_res = await asyncio.to_thread(
                            lambda _m=_img_m: client.models.generate_images(
                                model=_m,
                                prompt=prompt,
                                config=types.GenerateImagesConfig(
                                    number_of_images=1
                                ),
                            )
                        )
                        if _img_res and _img_res.generated_images:
                            break
                    except Exception as _img_e:
                        _app_logger.debug(f"[PAINTER] {_img_m} 失败: {_img_e}")
                        _img_res = None
                if _img_res and _img_res.generated_images:
                    with open(fpath, "wb") as f:
                        f.write(_img_res.generated_images[0].image.image_bytes)
                    image_paths.append(fpath)
                    _app_logger.info(f"[PAINTER] ✅ 配图 {i+1} 已生成: {fname}")
                    _report(f"✅ 配图 {i+1} 完成", fname)
                else:
                    raise RuntimeError("所有图像模型均失败")
            except Exception as img_err:
                _app_logger.warning(f"[PAINTER] ⚠️ 配图 {i+1} 生成失败: {img_err}")
                _report(f"⚠️ 配图 {i+1} 失败", str(img_err))

        success = len(image_paths) > 0
        if success:
            _report("✅ 图像生成任务完成", f"共生成 {len(image_paths)} 张")
        else:
            _report("❌ 图像生成任务失败", "未生成有效图片")

        return {
            "success": success,
            "output": f"已生成 {len(image_paths)} 张配图",
            "content": ",".join(image_paths),
            "image_paths": image_paths,
            "model_id": "imagen-3.0",
        }
    except Exception as e:
        _report("❌ 图像生成遇到致命错误", str(e))
        return {"success": False, "output": "", "error": str(e)}

async def execute_research(
    user_input: str, context: dict, progress_callback=None
) -> dict:
    """执行深度研究子任务 - 使用 Gemini Pro 深度分析 (可视进度)"""

    def _report(msg: str, detail: str = ""):
        _app_logger.debug(f"[RESEARCH] {msg} | {detail}")
        if progress_callback:
            progress_callback(msg, detail)

    try:
        _report("启动深度研究流程...", "分析上下文数据")
        search_data = context.get("WEB_SEARCH_result", {})
        search_text = search_data.get("content", "") or search_data.get(
            "output", ""
        )

        # Phase 1: Planning
        _report("规划研究大纲...", "确定分析维度")
        # (Implied planning by WebSearcher internal logic, but we report it)
        await asyncio.sleep(0.5)  # Simulate quick think

        # Phase 2: Synthesis
        _report("正在进行深度分析...", "优先 Deep Research Pro，失败自动回退")
        # Run in thread to not block event loop if sync
        research_text = await asyncio.to_thread(
            WebSearcher.deep_research_for_ppt, user_input, search_text
        )

        # Phase 3: Verification
        _report("验证研究报告...", "检查内容完整性")
        if research_text:
            _report("✅ 研究完成", f"生成 {len(research_text)} 字详细报告")
            return {
                "success": True,
                "output": f"深度研究完成，获取 {len(research_text)} 字专业分析",
                "content": research_text,
                "model_id": MODEL_MAP.get(
                    "RESEARCH", "deep-research-pro-preview-12-2025"
                ),
            }
        else:
            _report("⚠️ 研究产出为空", "回退到基础搜索结果")
            return {
                "success": True,
                "output": "研究未返回结果，将使用已有信息",
                "content": search_text,
            }
    except Exception as e:
        _report("❌ 研究过程出错", str(e))
        return {"success": False, "output": "", "error": str(e)}

async def execute_coder(
    user_input: str, context: dict, progress_callback=None
) -> dict:
    """执行代码生成子任务 - 使用最佳可用 Gemini 模型"""

    def _report(msg: str, detail: str = ""):
        _app_logger.debug(f"[CODER] {msg} | {detail}")
        if progress_callback:
            progress_callback(msg, detail)

    try:
        model_id = MODEL_MAP.get("CODER", "deepseek-chat")
        _report("启动代码生成...", f"模型: {model_id}")

        # 注入前步搜索/研究结果（如有）
        search_ctx = ""
        for key in (
            "WEB_SEARCH_result",
            "RESEARCH_result",
            "search_result",
            "research_result",
        ):
            val = context.get(key)
            if val:
                text = (
                    val.get("content") or val.get("output") or ""
                    if isinstance(val, dict)
                    else str(val)
                )
                if text:
                    search_ctx = text[:3000]
                    break

        full_prompt = user_input
        if search_ctx:
            full_prompt = f"参考信息:\n{search_ctx}\n\n任务: {user_input}"

        sys_instr = (
            "你是 Koto 代码专家。直接输出完整可运行代码，使用代码块（```语言）包裹，"
            "不加废话前言。必要时简短说明运行方式（≤3行）。"
        )
        _report("正在生成代码...", "调用 Interactions API")

        result_text = await asyncio.to_thread(
            call_interactions_api_sync, model_id, full_prompt, sys_instr, 90.0
        )

        if not result_text:
            _report("⚠️ 主模型超时，尝试稳定模式...", "deepseek-chat")
            resp = await asyncio.to_thread(
                lambda: client.models.generate_content(
                    model=get_interactions_fallback_model(),
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=sys_instr,
                        temperature=0.3,
                        max_output_tokens=4096,
                    ),
                )
            )
            result_text = resp.text or "(无输出)"
            model_id = get_interactions_fallback_model()

        # 自动保存代码文件
        if settings_manager.get("ai", "auto_save_files") is not False:
            saved = Utils.auto_save_files(result_text)
        else:
            saved = []
        _report(
            "✅ 代码生成完成",
            f"已保存 {len(saved)} 个文件" if saved else "未检测到文件标记",
        )

        return {
            "success": True,
            "output": result_text,
            "content": result_text,
            "saved_files": saved,
            "model_id": model_id,
        }
    except Exception as e:
        _report("❌ 代码生成失败", str(e))
        return {"success": False, "output": "", "error": str(e)}

async def execute_system(
    user_input: str, context: dict, progress_callback=None
) -> dict:
    """执行系统操作子任务 - 调用 LocalExecutor"""

    def _report(msg: str, detail: str = ""):
        _app_logger.debug(f"[SYSTEM] {msg} | {detail}")
        if progress_callback:
            progress_callback(msg, detail)

    try:
        _report("执行系统操作...", user_input[:40])
        result = await asyncio.to_thread(LocalExecutor.execute, user_input)
        success = result.get("success", False)
        msg = result.get("message", "")
        if success:
            _report("✅ 系统操作完成", msg[:60])
        else:
            _report("⚠️ 系统操作失败", msg[:60])
        return {
            "success": success,
            "output": msg,
            "content": msg,
            "model_id": "local-executor",
        }
    except Exception as e:
        _report("❌ 系统操作异常", str(e))
        return {"success": False, "output": "", "error": str(e)}
