# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""KotoBrain - non-streaming chat orchestration (routing -> generation -> fallback).

Extracted from web/app.py to reduce module size and improve testability.

Usage:
    from app.core.brain import KotoBrain
    brain = KotoBrain()
    result = brain.chat(history, user_input)
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_app_logger = logging.getLogger("koto.brain")


_INTERACTIONS_FALLBACK_MODEL = "deepseek-chat"


@dataclass(frozen=True)
class BrainRuntimeServices:
    """Runtime dependencies required by :class:`KotoBrain`.

    Callables intentionally resolve values at request time: the web runtime can
    replace a client or dispatcher in-process without leaving an existing brain
    instance with stale references.
    """

    get_smart_dispatcher: Callable[[], Any]
    get_utils: Callable[[], Any]
    get_local_executor: Callable[[], Any]
    get_client: Callable[[], Any]
    get_workspace_dir: Callable[[], str]
    get_settings_manager: Callable[[], Any]
    get_model_map: Callable[[], dict]


_default_brain_runtime: BrainRuntimeServices | None = None


def configure_default_brain_runtime(runtime: BrainRuntimeServices) -> None:
    """Configure the application-owned default for compatibility construction."""
    global _default_brain_runtime
    _default_brain_runtime = runtime


# ContextAnalyzer - lazy import with fallback
try:
    from web.context_analyzer import ContextAnalyzer as _ContextAnalyzer
except Exception:

    class _ContextAnalyzer:
        @staticmethod
        def filter_history(_query, history):
            return history


# GEMINI ARCHIVED - all Gemini code paths return clear error messages
_GEMINI_ARCHIVED = True


# Chat-system helpers retained behind their compatibility module during migration.
from web.chat_system_instruction import (
    get_chat_system_instruction as _get_chat_system_instruction,
    get_default_chat_system_instruction as _get_DEFAULT_CHAT_SYSTEM_INSTRUCTION,
)


def _get_system_instruction():
    """Build the FILE_GEN system instruction with a current time anchor."""
    from datetime import datetime

    now = datetime.now()
    date_str = now.strftime("%Y年%m月%d日")
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
    base_instruction = f"""你是 Koto 文档生成专家，专注于生成高质量、可用的文档。

## 当前时间上下文
📅 **生成日期**: {date_str} {weekday}

## 时间理解规则
- 以本次系统日期为唯一时间锚点理解“今天、本月、今年”等相对时间。
- 用户只写月份而未写年份时，默认使用当前年份。
- 除非用户明确指定，不要擅自使用过去年份。

## 核心职责
1. **直接输出文档内容** - 输出最终要保存的内容，而不是代码或 JSON 包装。
2. **中文优先** - 默认使用简体中文，保持专业术语准确。
3. **结构清晰** - 使用标题、列表和段落组织内容。

## 输出优先级
1. 直接输出内容 > 代码生成 > JSON 结构。
2. 内容准确、结构清晰 > 形式复杂。
3. 实际可执行性 > 装饰性表达。
"""
    try:
        from app.core.skills.skill_manager import SkillManager

        return SkillManager.inject_into_prompt(
            base_instruction,
            task_type="FILE_GEN",
        )
    except Exception:
        return base_instruction


def _is_interactions_only(model_id: str) -> bool:
    """Return whether a model requires the archived Interactions API."""
    if not model_id:
        return False
    interactions_models = {"o4-mini", "o3", "o3-mini", "o1", "o1-mini", "o1-pro"}
    return model_id in interactions_models


def _call_interactions_api_sync(
    model_id,
    messages,
    system_instruction=None,
    session_name="",
    start_time=0,
    original_input="",
    history=None,
    smart_dispatcher=None,
    target_key="CHAT",
    _interactions_fallback_model="deepseek-chat",
):
    """Compatibility error for the archived Interactions API path."""
    _app_logger.debug(f"[brain] _call_interactions_api_sync: model={model_id}")
    raise RuntimeError(
        f"Interactions API 已归档（model={model_id}）。\n\n"
        "请改用 DeepSeek 或当前已配置的模型。"
    )


def _gemini_archived_error(feature: str = "this feature") -> str:
    return (
        f"\u274c **{feature}** \u6682\u65f6\u4e0d\u53ef\u7528\n\n"
        "Gemini API \u5df2\u5c01\u5b58\uff0c\u8bf7\u4f7f\u7528 DeepSeek \u6216\u5176\u4ed6\u6a21\u578b\u3002"
    )


class KotoBrain:
    # 图像编辑关键词
    IMAGE_EDIT_KEYWORDS = [
        "修改",
        "换",
        "改成",
        "变成",
        "底色",
        "背景",
        "颜色",
        "抠图",
        "去背景",
        "P图",
        "美化",
        "滤镜",
        "调色",
        "编辑",
        "change",
        "modify",
        "edit",
        "background",
        "color",
    ]

    def __init__(self, runtime: BrainRuntimeServices | None = None) -> None:
        self._runtime = runtime or _default_brain_runtime
        self._smart_dispatcher: Any = None
        self._utils: Any = None
        self._local_executor: Any = None
        self._client: Any = None
        self._workspace_dir = ""
        self._settings_manager: Any = None
        self._model_map: dict = {}

    def _ensure_runtime(self) -> None:
        if self._runtime is None:
            raise RuntimeError(
                "Koto runtime services are not configured; "
                "construct KotoBrain with BrainRuntimeServices."
            )

        self._smart_dispatcher = self._runtime.get_smart_dispatcher()
        self._utils = self._runtime.get_utils()
        self._local_executor = self._runtime.get_local_executor()
        self._client = self._runtime.get_client()
        self._workspace_dir = str(self._runtime.get_workspace_dir() or "")
        self._settings_manager = self._runtime.get_settings_manager()
        self._model_map = self._runtime.get_model_map() or {}

    def chat(
        self,
        history,
        user_input,
        file_data=None,
        model=None,
        auto_model=True,
        task_type: str = None,
    ):
        self._ensure_runtime()
        start_time = time.time()
        original_input = user_input
        # 支持模型选择和自动选择
        _model_id_locked = (
            False  # 如果已在路由中强制设置 model_id，跳过后续 SmartDispatcher 覆盖
        )
        if model and not auto_model:
            model_id = model
            route_method = "Manual select"
            # 优先使用调用方传入的 task_type，避免重复路由
            target_key = task_type or "CHAT"
        else:
            target_key = "CHAT"
            route_method = "Auto"
            model_id = None  # 先置空，下面按路由决定

            if file_data:
                _fd_mime = (
                    file_data.get("mime_type") or "application/octet-stream"
                ).lower()
                _is_image_file = _fd_mime.startswith("image/")
                if _is_image_file:
                    # 图片文件：判断编辑 vs 分析
                    user_lower = user_input.lower()
                    is_edit = any(kw in user_lower for kw in self.IMAGE_EDIT_KEYWORDS)
                    if is_edit:
                        target_key = "PAINTER"
                        route_method = "Image Edit"
                    else:
                        target_key = "VISION"
                        route_method = "Image Analysis"
                else:
                    # 非图片二进制文件（PDF/Word等）：路由为 CHAT，使用降级模型直接读取
                    target_key = "CHAT"
                    route_method = "📄 Binary-Doc-Read"
                    # 强制使用支持 generate_content + 文件字节的降级模型（Interactions API 不支持文件附件）
                    model_id = _INTERACTIONS_FALLBACK_MODEL
                    _model_id_locked = True
            else:
                # 使用智能路由器
                target_key, route_method, _ = self._smart_dispatcher.analyze(user_input)

            if not _model_id_locked:
                model_id = self._smart_dispatcher.get_model_for_task(
                    target_key, has_image=bool(file_data)
                )
                try:
                    from app.core.llm.model_selection import get_configured_cloud_model

                    model_id = (
                        get_configured_cloud_model(
                            task_type=target_key,
                            fallback_model=model_id,
                        )
                        or model_id
                    )
                except Exception as model_select_err:
                    _app_logger.debug(
                        "[ModelSelect] configured cloud model lookup skipped: %s",
                        model_select_err,
                    )

        # 使用小模型将请求转换为结构化 Markdown（仅在大模型处理时启用）
        # ⚠️ 跳过条件：有文件附件时（file_data）、或输入很大（含嵌入文件内容）
        _has_embedded_file_content = (
            "=== 文件内容 ===" in user_input or len(user_input) > 3000
        )
        model_input = user_input
        if (
            auto_model
            and not file_data
            and not _has_embedded_file_content
            and target_key not in ["SYSTEM", "FILE_OP", "PAINTER", "VISION"]
        ):
            # 仅使用本地模板重整（不传 model_generate，避免额外的 flash-lite API 调用）
            model_input = self._utils.adapt_prompt_to_markdown(
                target_key, user_input, history=history
            )
            if model_input != user_input:
                _app_logger.debug("[PROMPT_ADAPTER] Applied local Markdown template")
        result = {
            "task": target_key,
            "model": model_id,
            "route_method": route_method,  # 路由方法信息
            "response": "",
            "images": [],
            "saved_files": [],
            "latency": 0,
            "total_time": 0,
        }

        try:
            # === SYSTEM Mode (本地执行) ===
            if target_key == "SYSTEM":
                exec_result = self._local_executor.execute(user_input)
                result["response"] = exec_result["message"]
                if exec_result.get("details"):
                    result["response"] += f"\n\n{exec_result['details']}"
                result["total_time"] = time.time() - start_time
                return result

            # === PAINTER Mode (图像生成/编辑) ===
            if target_key == "PAINTER":
                # 如果有输入图片（图像编辑模式）- 使用代码方式处理
                if file_data:
                    # 保存上传的图片到 workspace
                    import subprocess
                    import tempfile

                    temp_img_path = os.path.join(
                        self._workspace_dir, "images", f"input_{int(time.time())}.jpg"
                    )
                    os.makedirs(os.path.dirname(temp_img_path), exist_ok=True)
                    with open(temp_img_path, "wb") as f:
                        f.write(file_data["data"])

                    # 构建图像编辑的系统指令
                    edit_instruction = f"""你是一个图像处理专家。用户上传了一张图片，需要你生成 Python 代码来处理它。

图片路径: {temp_img_path}
用户请求: {user_input}

请生成完整的 Python 代码来完成用户的图像编辑请求。

要求:
1. 使用 OpenCV (cv2) 或 PIL 处理图片
2. 处理后的图片保存到: {self._settings_manager.images_dir}
3. 文件名格式: edited_{{timestamp}}.jpg 或 .png
4. 代码必须完整可执行
5. 对于换背景色，使用颜色阈值或边缘检测来识别背景区域

常用的背景色处理方法:
- 证件照换底色: 检测接近原背景色的像素，替换为目标颜色
- 蓝色背景 RGB: (67, 142, 219) 或 (0, 191, 255)
- 红色背景 RGB: (255, 0, 0) 或 (220, 0, 0)
- 白色背景 RGB: (255, 255, 255)

代码格式（必须使用这个格式）:
---BEGIN_FILE: image_edit.py---
# 你的代码
---END_FILE---"""

                    # 调用 Gemini 生成代码（带回退）
                    edit_models = [
                        "deepseek-chat",
                        "deepseek-chat",
                        "deepseek-chat",
                    ]
                    code_response = None
                    last_error = None

                    def _process_code_response(code_response_text: str):
                        # 提取代码 - 支持多种格式
                        import re

                        patterns = [
                            r"---BEGIN_FILE:\s*([a-zA-Z0-9_.-]+)\s*---\s*(.*?)---\s*END_FILE\s*---",
                            r"```python\s*(.*?)```",  # 标准 markdown 代码块
                            r"```\s*(.*?)```",  # 无语言标记的代码块
                        ]

                        code_content = None
                        for pattern in patterns:
                            matches = re.findall(
                                pattern, code_response_text, re.DOTALL | re.IGNORECASE
                            )
                            if matches:
                                if isinstance(matches[0], tuple):
                                    code_content = matches[0][1].strip()
                                else:
                                    code_content = matches[0].strip()
                                _app_logger.debug(
                                    f"[IMAGE_EDIT] Extracted code, length: {len(code_content)}"
                                )
                                break

                        if not code_content:
                            return {
                                "images": [],
                                "response": f"❌ 无法从模型响应中提取代码\n\n模型返回内容:\n```\n{code_response_text[:500]}\n```",
                                "error": "no_code",
                            }

                        # 保存并执行代码
                        temp_script = os.path.join(
                            tempfile.gettempdir(), f"koto_edit_{int(time.time())}.py"
                        )
                        with open(temp_script, "w", encoding="utf-8") as f:
                            f.write(code_content)

                        _app_logger.debug(
                            f"[IMAGE_EDIT] Executing script: {temp_script}"
                        )
                        if getattr(sys, "frozen", False):
                            # 打包模式：sys.executable 是 Koto.exe，不能用来运行脚本，改为进程内 exec()
                            import contextlib as _ctx
                            import io as _io

                            _out, _err, _rc = _io.StringIO(), _io.StringIO(), 0
                            try:
                                _prev = os.getcwd()
                                os.chdir(self._workspace_dir)
                                with _ctx.redirect_stdout(_out), _ctx.redirect_stderr(
                                    _err
                                ):
                                    exec(
                                        open(temp_script, "r", encoding="utf-8").read(),
                                        {"__file__": temp_script},
                                    )
                                os.chdir(_prev)
                            except Exception as _ex:
                                _err.write(str(_ex))
                                _rc = 1

                            class _ImgR:
                                returncode = _rc
                                stdout = _out.getvalue()
                                stderr = _err.getvalue()

                            exec_result = _ImgR()
                        else:
                            exec_result = subprocess.run(
                                [sys.executable, temp_script],
                                capture_output=True,
                                text=True,
                                timeout=60,
                                cwd=self._workspace_dir,
                            )

                        _app_logger.debug(
                            f"[IMAGE_EDIT] Script result: returncode={exec_result.returncode}"
                        )
                        if exec_result.stdout:
                            _app_logger.debug(
                                f"[IMAGE_EDIT] stdout: {exec_result.stdout[:200]}"
                            )
                        if exec_result.stderr:
                            _app_logger.debug(
                                f"[IMAGE_EDIT] stderr: {exec_result.stderr[:200]}"
                            )

                        # 清理临时脚本
                        try:
                            os.remove(temp_script)
                        except OSError:
                            pass

                        if exec_result.returncode == 0:
                            images = []
                            images_dir = self._settings_manager.images_dir
                            for f in os.listdir(images_dir):
                                if f.startswith("edited_") and f.endswith(
                                    (".jpg", ".png", ".jpeg")
                                ):
                                    full_path = os.path.join(images_dir, f)
                                    age = time.time() - os.path.getmtime(full_path)
                                    if age < 60:
                                        rel_path = os.path.relpath(
                                            full_path, self._workspace_dir
                                        ).replace("\\", "/")
                                        images.append(rel_path)

                            if images:
                                return {
                                    "images": images,
                                    "response": f"✅ 图片编辑完成!\n🖼️ 保存位置: `{images_dir}`",
                                    "error": "",
                                }
                            return {
                                "images": [],
                                "response": f"⚠️ 脚本执行成功但未检测到新图片\n\n{exec_result.stdout[:500]}",
                                "error": "no_output",
                            }

                        return {
                            "images": [],
                            "response": f"❌ 图片处理失败\n```\n{exec_result.stderr[:500]}\n```",
                            "error": "exec_failed",
                        }

                    for edit_model in edit_models:
                        try:
                            _app_logger.debug(
                                f"[IMAGE_EDIT] Trying model: {edit_model}"
                            )
                            _app_logger.debug(f"[IMAGE_EDIT] Sending request to API...")
                            raise RuntimeError(
                                _gemini_archived_error()
                            )  # was: response = _client.models.generate_content(
                            #                                 model=edit_model,
                            #                                 contents=edit_instruction,
                            #                                 config=types.GenerateContentConfig(
                            #                                     max_output_tokens=4096, temperature=0.5
                            #                                 ),
                            #                             )
                            #                             _app_logger.debug(f"[IMAGE_EDIT] Got API response")

                            if (
                                response.candidates
                                and response.candidates[0].content.parts
                            ):
                                code_response = (
                                    response.candidates[0].content.parts[0].text
                                )
                                _app_logger.debug(
                                    f"[IMAGE_EDIT] Got response from {edit_model}, length: {len(code_response)}"
                                )
                                break
                        except Exception as model_err:
                            last_error = str(model_err)
                            _app_logger.debug(
                                f"[IMAGE_EDIT] Model {edit_model} failed: {last_error[:100]}"
                            )
                            continue

                    if code_response:
                        run_result = _process_code_response(code_response)
                        result["images"] = run_result["images"]
                        result["response"] = run_result["response"]
                    else:
                        result["response"] = (
                            f"❌ 所有模型都不可用: {last_error[:200] if last_error else '未知错误'}"
                        )

                    # 失败后自动修正并重试一次（避免无编辑结果）
                    if not result["images"] and self._utils.is_failure_output(
                        result["response"]
                    ):
                        fix_prompt = (
                            "上次生成失败，请修正并只输出完整可执行的 Python 代码。\n"
                            "必须使用 BEGIN_FILE/END_FILE 格式。\n"
                            f"图片路径: {temp_img_path}\n"
                            f"输出目录: {self._settings_manager.images_dir}\n"
                            f"用户请求: {user_input}\n\n"
                            f"失败信息/输出: {result['response']}\n"
                        )
                    retry_models = ["deepseek-chat", "deepseek-chat"]
                    for retry_model in retry_models:
                        try:
                            _app_logger.debug(
                                f"[IMAGE_EDIT] Retry with model: {retry_model}"
                            )
                            raise RuntimeError(
                                _gemini_archived_error()
                            )  # was: retry_resp = _client.models.generate_content(
                            #                                     model=retry_model,
                            #                                     contents=fix_prompt,
                            #                                     config=types.GenerateContentConfig(
                            #                                         max_output_tokens=4096
                            #                                     ),
                            #                                 )
                            if (
                                retry_resp.candidates
                                and retry_resp.candidates[0].content.parts
                            ):
                                retry_code = (
                                    retry_resp.candidates[0].content.parts[0].text
                                )
                                retry_run = _process_code_response(retry_code)
                                if retry_run["images"]:
                                    result["images"] = retry_run["images"]
                                    result["response"] = retry_run["response"]
                                    break
                                result["response"] = retry_run["response"]
                        except Exception as retry_err:
                            _app_logger.debug(f"[IMAGE_EDIT] Retry failed: {retry_err}")

                    result["total_time"] = time.time() - start_time
                    return result
                else:
                    # 纯图像生成使用 gemini-3.1-flash-image-preview
                    try:
                        _app_logger.info(f"[图像生成] 开始生成: {user_input[:50]}...")
                        raise RuntimeError(
                            _gemini_archived_error()
                        )  # was: response = _client.models.generate_content(
                        #                             model="gemini-3.1-flash-image-preview",
                        #                             contents=user_input,
                        #                             config=types.GenerateContentConfig(
                        #                                 response_modalities=["TEXT", "IMAGE"]
                        #                             ),
                        #                         )
                        #                         _app_logger.info(
                        #                             f"[图像生成] 响应成功，候选数: {len(response.candidates) if response.candidates else 0}"
                        #                         )

                        # 保存生成的图片
                        #                         if response.candidates and response.candidates[0].content.parts:
                        #                             for part in response.candidates[0].content.parts:
                        #                                 if hasattr(part, "inline_data") and part.inline_data:
                        #                                     img_filename = _Utils.save_image_part(part)
                        #                                     if img_filename:
                        #                                         result["images"].append(img_filename)
                        #                                         _app_logger.info(
                        #                                             f"[图像生成] 已保存: {img_filename}"
                        #                                         )

                        if result["images"]:
                            save_path = self._settings_manager.images_dir
                            result["response"] = (
                                f"✨ 图片已生成!\n🖼️ 保存位置: `{save_path}`"
                            )
                        else:
                            result["response"] = (
                                "❌ 图像生成失败: 无输出内容，请检查提示词"
                            )
                        result["total_time"] = time.time() - start_time
                        return result
                    except Exception as img_err:
                        error_msg = str(img_err)
                        _app_logger.info(f"[图像生成] 错误: {error_msg[:200]}")

                        # 提供更详细的错误信息
                        if (
                            "disconnected" in error_msg.lower()
                            or "timeout" in error_msg.lower()
                        ):
                            result["response"] = (
                                f"❌ 连接超时或中断: {error_msg[:100]}\n\n💡 建议: 请稍后重试，或检查网络连接"
                            )
                        elif "safety" in error_msg.lower():
                            result["response"] = "❌ 内容因安全政策被过滤，请修改提示词"
                        elif (
                            "quota" in error_msg.lower() or "rate" in error_msg.lower()
                        ):
                            result["response"] = "❌ API 配额已达限制，请稍后重试"
                        else:
                            result["response"] = f"❌ 图像生成失败: {error_msg[:100]}"

                        result["total_time"] = time.time() - start_time
                        return result

                if not response.candidates:
                    result["response"] = "Generation failed (safety filter or busy)."
                    result["total_time"] = time.time() - start_time
                    return result

                text_response = ""
                if response.candidates and response.candidates[0].content.parts:
                    for part in response.candidates[0].content.parts:
                        if hasattr(part, "text") and part.text:
                            text_response += part.text
                        if hasattr(part, "inline_data") and part.inline_data:
                            img_filename = self._utils.save_image_part(part)
                            if img_filename:
                                result["images"].append(img_filename)

                # 添加图片保存位置提示
                if result["images"]:
                    save_path = self._settings_manager.images_dir
                    text_response += f"\n\n🖼️ 图片已保存到: `{save_path}`"

                result["response"] = (
                    text_response if text_response else "Image generated successfully!"
                )
                result["total_time"] = time.time() - start_time
                return result

            # === RAG: Retrieve Relevant Context (Auto) ===
            try:
                # 获取知识库实例
                kb_inst = get_knowledge_base()

                # 仅在非特定模式且输入有效时检索
                if target_key not in ["PAINTER", "SYSTEM"] and len(original_input) > 3:
                    # 避免对极短的问候语进行检索
                    skip_keywords = ["你好", "hello", "hi", "test", "测试"]
                    if not any(original_input.lower() == k for k in skip_keywords):
                        _app_logger.debug(
                            f"[RAG]正在检索知识库: {original_input[:50]}..."
                        )
                        rag_results = kb_inst.search(original_input, top_k=3)

                        if rag_results:
                            _app_logger.debug(
                                f"[RAG] 检索到 {len(rag_results)} 个相关片段"
                            )
                            context_str = "\n".join(
                                [
                                    f"--- 来源: {r['file_name']} (相似度: {r['similarity']:.2f}) ---\n{r['text']}"
                                    for r in rag_results
                                ]
                            )

                            # 将上下文注入 prompt
                            rag_context = f"\n\n【参考资料】\n以下是从本地知识库检索到的相关内容，供回答参考：\n{context_str}\n\n"

                            # Log retrieval
                            _app_logger.debug(
                                f"[RAG] Injected context length: {len(rag_context)}"
                            )

                            # Update model input
                            # 如果有 file_data，model_input 可能是 None 或不被直接使用，需谨慎
                            if not file_data:
                                model_input = rag_context + model_input
                            else:
                                # 对于有文件的请求，我们将上下文拼接到 original_input (user prompt)
                                # 注意：下面 generate_content 用的是 original_input + image_part
                                original_input = rag_context + original_input

            except Exception as rag_err:
                _app_logger.debug(f"[RAG] Retrieval warning: {rag_err}")

            # === Regular Mode ===
            # 构建历史记录格式（过滤无关历史）
            history_for_model = _ContextAnalyzer.filter_history(original_input, history)
            formatted_history = []
            for turn in history_for_model:
                formatted_history.append(
                    types.Content(
                        role=turn["role"],
                        parts=[types.Part.from_text(text=p) for p in turn["parts"]],
                    )
                )

            # 根据任务类型选择系统提示：FILE_GEN 走文档生成提示，其余走通用助手提示
            if target_key == "FILE_GEN":
                _brain_sys_instruction = _get_system_instruction()
            else:
                _brain_sys_instruction = _get_chat_system_instruction(original_input)

            try:
                from app.core.llm.model_selection import is_deepseek_model
            except Exception:

                def is_deepseek_model(_model_id):
                    return False

            if file_data and is_deepseek_model(model_id):
                _doc_model = _INTERACTIONS_FALLBACK_MODEL
                _app_logger.info(
                    "[brain.chat] DeepSeek selected with binary file; using Gemini file-capable fallback %s",
                    _doc_model,
                )
                model_id = _doc_model
                result["model"] = model_id

            if file_data:
                # 构建 Part 格式（适用于图片和 PDF/文档）
                doc_part = types.Part.from_bytes(
                    data=file_data["data"], mime_type=file_data["mime_type"]
                )
                _fd_mime2 = (file_data.get("mime_type") or "").lower()
                _is_image = _fd_mime2.startswith("image/")

                if not _is_image:
                    # PDF / 文档二进制：Interactions API 不支持文件附件
                    # → 直接使用 gemini-2.5-flash（原生支持 generate_content + PDF bytes）
                    _doc_model = _INTERACTIONS_FALLBACK_MODEL
                    if model_id != _doc_model:
                        _app_logger.info(
                            f"[brain.chat] 非图片文件 ({_fd_mime2}): 降级模型 {model_id} → {_doc_model}"
                        )
                        model_id = _doc_model
                        result["model"] = model_id
                    raise RuntimeError(
                        _gemini_archived_error()
                    )  # was: response = _client.models.generate_content(
                #                         model=model_id,
                #                         contents=[original_input, doc_part],
                #                         config=types.GenerateContentConfig(
                #                             system_instruction=_brain_sys_instruction
                #                         ),
                #                     )
                #                     accumulated_text = response.text if response.text else ""
                elif _is_interactions_only(model_id):
                    # 图片文件 + gemini-3-preview 模型：走 Interactions API
                    try:
                        accumulated_text = _call_interactions_api_sync(
                            model_id,
                            original_input,
                            sys_instruction=_brain_sys_instruction,
                        )
                        if not accumulated_text:
                            raise ValueError("Interactions API 返回空响应")
                    except Exception as _ia_err:
                        _app_logger.info(
                            f"[brain.chat] {model_id} Interactions API 失败: {_ia_err} → 降级到 {_INTERACTIONS_FALLBACK_MODEL}"
                        )
                        model_id = _INTERACTIONS_FALLBACK_MODEL
                        result["model"] = model_id
                        raise RuntimeError(
                            _gemini_archived_error()
                        )  # was: _fb_resp = _client.models.generate_content(
                        #                             model=model_id,
                        #                             contents=[original_input, doc_part],
                        #                             config=types.GenerateContentConfig(
                        #                                 system_instruction=_brain_sys_instruction
                        #                             ),
                        #                         )
                        accumulated_text = _fb_resp.text if _fb_resp.text else ""
                else:
                    # 图片文件 + 普通 generate_content 模型
                    raise RuntimeError(
                        _gemini_archived_error()
                    )  # was: response = _client.models.generate_content(
            #                         model=model_id,
            #                         contents=[original_input, doc_part],
            #                         config=types.GenerateContentConfig(
            #                             system_instruction=_brain_sys_instruction
            #                         ),
            #                     )
            #                     accumulated_text = response.text if response.text else ""
            else:
                if is_deepseek_model(model_id):
                    from app.core.llm.provider_factory import get_llm_provider

                    provider = get_llm_provider(
                        provider="deepseek",
                        model=model_id,
                        allow_local_fallback=False,
                    )
                    messages = []
                    for turn in history_for_model[-6:]:
                        role = (
                            "assistant"
                            if turn.get("role") == "model"
                            else turn.get("role", "user")
                        )
                        content = "\n".join(
                            str(p)
                            for p in turn.get("parts", [])
                            if str(p or "").strip()
                        )
                        if content:
                            messages.append({"role": role, "content": content})
                    messages.append({"role": "user", "content": model_input})
                    response = provider.generate_content(
                        prompt=messages,
                        model=model_id,
                        system_instruction=_brain_sys_instruction,
                        stream=False,
                    )
                    accumulated_text = (
                        response.get("content", "")
                        if isinstance(response, dict)
                        else str(response)
                    )
                else:
                    # gemini-3-preview 只支持 Interactions API，不支持 generate_content
                    if _is_interactions_only(model_id):
                        try:
                            # 将历史记录折叠进 prompt（Interactions API 不支持多轮历史）
                            history_prefix = ""
                            if formatted_history:
                                history_lines = []
                                for turn in formatted_history[-6:]:  # 最近 3 轮
                                    role_label = (
                                        "用户" if turn.role == "user" else "助手"
                                    )
                                    turn_text = " ".join(
                                        p.text
                                        for p in turn.parts
                                        if hasattr(p, "text") and p.text
                                    )
                                    if turn_text:
                                        history_lines.append(
                                            f"{role_label}: {turn_text}"
                                        )
                                if history_lines:
                                    history_prefix = (
                                        "[对话历史]\n"
                                        + "\n".join(history_lines)
                                        + "\n\n"
                                    )
                            full_prompt = history_prefix + model_input
                            accumulated_text = _call_interactions_api_sync(
                                model_id,
                                full_prompt,
                                sys_instruction=_brain_sys_instruction,
                            )
                            if not accumulated_text:
                                raise ValueError("Interactions API 返回空响应")
                        except Exception as _ia_err:
                            _app_logger.info(
                                f"[brain.chat] {model_id} Interactions API 失败: {_ia_err} → 降级到 {_INTERACTIONS_FALLBACK_MODEL}"
                            )
                            model_id = _INTERACTIONS_FALLBACK_MODEL
                            result["model"] = model_id
                            raise RuntimeError(
                                _gemini_archived_error()
                            )  # was: _fb_resp = _client.models.generate_content(
                            #                                 model=model_id,
                            #                                 contents=formatted_history
                            #                                 + [
                            #                                     types.Content(
                            #                                         role="user",
                            #                                         parts=[types.Part.from_text(text=model_input)],
                            #                                     )
                            #                                 ],
                            #                                 config=types.GenerateContentConfig(
                            #                                     system_instruction=_brain_sys_instruction
                            #                                 ),
                            #                             )
                            accumulated_text = _fb_resp.text if _fb_resp.text else ""
                    else:
                        raise RuntimeError(
                            _gemini_archived_error()
                        )  # was: response = _client.models.generate_content(
            #                             model=model_id,
            #                             contents=formatted_history
            #                             + [
            #                                 types.Content(
            #                                     role="user",
            #                                     parts=[types.Part.from_text(text=model_input)],
            #                                 )
            #                             ],
            #                             config=types.GenerateContentConfig(
            #                                 system_instruction=_brain_sys_instruction
            #                             ),
            #                         )
            #                         accumulated_text = response.text if response.text else ""

            first_token_latency = (time.time() - start_time) * 1000
            result["latency"] = first_token_latency

            # Auto-save files
            if self._settings_manager.get("ai", "auto_save_files") is not False:
                saved_files = self._utils.auto_save_files(accumulated_text)
            else:
                saved_files = []
            result["saved_files"] = saved_files

            # 添加文件保存提示
            if saved_files:
                files_list = ", ".join(saved_files)
                accumulated_text += f"\n\n📁 文件已保存: **{files_list}**\n📂 位置: `{self._workspace_dir}`"

            result["response"] = accumulated_text
            result["total_time"] = time.time() - start_time
            return result
        except Exception as e:
            err_str = str(e)
            # 自动降级：如果模型返回"只支持 Interactions API"错误，用 2.0-flash 重试一次
            if (
                "Interactions API" in err_str
                and not _is_interactions_only(model_id)
                and model_id != _INTERACTIONS_FALLBACK_MODEL
            ):
                _app_logger.info(
                    f"[brain.chat] Interactions API 错误，自动降级 {model_id} → {_INTERACTIONS_FALLBACK_MODEL}"
                )
                try:
                    model_id = _INTERACTIONS_FALLBACK_MODEL
                    raise RuntimeError(
                        _gemini_archived_error()
                    )  # was: _fb = _client.models.generate_content(
                    #                         model=model_id,
                    #                         contents=(
                    #                             formatted_history
                    #                             + [
                    #                                 types.Content(
                    #                                     role="user",
                    #                                     parts=[types.Part.from_text(text=model_input)],
                    #                                 )
                    #                             ]
                    #                         ),
                    #                         config=types.GenerateContentConfig(
                    #                             system_instruction=_brain_sys_instruction
                    #                         ),
                    #                     )
                    #                     result["response"] = _fb.text if _fb.text else ""
                    result["model"] = model_id
                    result["total_time"] = time.time() - start_time
                    return result
                except Exception as _fb_err:
                    result["response"] = f"❌ 分析失败: {_fb_err}"
            elif (
                "API key not valid" in err_str
                or "INVALID_ARGUMENT" in err_str
                and "api key" in err_str.lower()
            ):
                result["response"] = (
                    "❌ **API 密钥无效**\n\n"
                    "请检查您的 云端 API 密钥：\n"
                    "1. 前往 [aistudio.google.com/apikey](https://aistudio.google.com/apikey) 获取有效密钥\n"
                    "2. 在 Koto 设置页面更新 API 密钥\n"
                    "3. 确保密钥所在项目已启用 Generative Language API\n\n"
                    f"原始错误: `{err_str[:200]}`"
                )
            else:
                # ── 模型本身不可用（404 / not-found / Interactions-only 等）──────────
                # 尝试从 ModelFallbackExecutor 获取备选模型并静默重试一次。
                _retried = False
                try:
                    from app.core.llm.model_fallback import (
                        _is_model_unavailable_error as _mue_chk,
                    )
                    from app.core.llm.model_fallback import (
                        get_fallback_executor,
                    )

                    if _mue_chk(e) and model_id not in (
                        None,
                        _INTERACTIONS_FALLBACK_MODEL,
                    ):
                        _fbe = get_fallback_executor()
                        _fbe.mark_unavailable(model_id)
                        _fb_model = _fbe.get_best_available(task_type=target_key)
                        if (
                            _fb_model
                            and _fb_model != model_id
                            and not _is_interactions_only(_fb_model)
                        ):
                            _app_logger.info(
                                f"[brain.chat] 模型不可用 {model_id} → 自动降级 {_fb_model} (task={target_key})"
                            )
                            _fh = locals().get("formatted_history") or []
                            _mi = locals().get("model_input") or original_input
                            _si = locals().get("_brain_sys_instruction") or ""
                            raise RuntimeError(
                                _gemini_archived_error()
                            )  # was: _fb_r = _client.models.generate_content(
                            #                                 model=_fb_model,
                            #                                 contents=_fh
                            #                                 + [
                            #                                     types.Content(
                            #                                         role="user",
                            #                                         parts=[types.Part.from_text(text=_mi)],
                            #                                     )
                            #                                 ],
                            #                                 config=types.GenerateContentConfig(
                            #                                     system_instruction=_si
                            #                                 ),
                            #                             )
                            #                             result["response"] = _fb_r.text if _fb_r.text else ""
                            result["model"] = _fb_model
                            _retried = True
                except Exception as _r_err:
                    _app_logger.info(f"[brain.chat] 降级重试失败: {_r_err}")
                if not _retried:
                    result["response"] = f"❌ 发生错误: {err_str}"
            result["total_time"] = time.time() - start_time
            return result
