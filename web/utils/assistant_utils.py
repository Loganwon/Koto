#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Assistant utility helpers used by chat and generation flows."""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import subprocess
import sys
import time
from typing import Any

from web.runtime_context import (
    get_client_proxy,
    get_types,
    get_workspace_dir,
    service_registry,
)

logger = logging.getLogger(__name__)


def _client() -> Any:
    return get_client_proxy()


def _settings_manager() -> Any:
    manager = service_registry.settings_manager
    if manager is None:
        raise RuntimeError("runtime settings manager is unavailable")
    return manager


def _types() -> Any:
    types_module = get_types()
    if types_module is not None:
        return types_module
    from app.core.llm.provider_compat import types as genai_types

    return genai_types



class Utils:
    _PACKAGE_ALLOWLIST = {
        "pygame": "pygame",
        "numpy": "numpy",
        "pandas": "pandas",
        "requests": "requests",
        "bs4": "beautifulsoup4",
        "beautifulsoup4": "beautifulsoup4",
        "lxml": "lxml",
        "pillow": "Pillow",
        "PIL": "Pillow",
        "opencv": "opencv-python",
        "cv2": "opencv-python",
        "matplotlib": "matplotlib",
        "scipy": "scipy",
        "sklearn": "scikit-learn",
        "flask": "flask",
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "streamlit": "streamlit",
        "gradio": "gradio",
    }

    @staticmethod
    def sanitize_string(s):
        if isinstance(s, str):
            return s.encode("utf-8", "ignore").decode("utf-8")
        return s

    @staticmethod
    def is_failure_output(text: str) -> bool:
        if not text or not str(text).strip():
            return True
        t = str(text).strip().lower()
        if t.startswith("❌") or "失败" in t or "错误" in t:
            return True
        # 检测模型声称「无法联网/没有实时数据」的拒绝型回答
        _no_internet_phrases = [
            "没有直接联网",
            "无法直接联网",
            "无法联网",
            "没有联网",
            "不能联网",
            "没有实时",
            "无法获取实时",
            "不能获取实时",
            "没有访问互联网",
            "无法访问互联网",
            "i don't have access to the internet",
            "i cannot access the internet",
            "i'm unable to access the internet",
            "no internet access",
            "i don't have real-time",
            "i cannot browse",
            "i can't browse",
        ]
        return any(phrase in t for phrase in _no_internet_phrases)

    @staticmethod
    def build_fix_prompt(
        task_type: str, user_input: str, prev_output: str = "", error_hint: str = ""
    ) -> str:
        base = (
            f"用户需求: {user_input}\n\n"
            f"上次输出/错误:\n{prev_output or error_hint}\n\n"
            "请修正并重新输出最终结果。不要解释过程，只输出最终内容。\n"
        )

        if task_type == "FILE_GEN":
            return base + (
                "要求：输出可执行的 Python 脚本，并使用 BEGIN_FILE/END_FILE 标记。\n"
                "必须生成文档或表格文件（docx/xlsx/pdf）。"
            )
        if task_type == "CODER":
            return base + "要求：输出完整可运行代码，并包含必要说明。"
        if task_type == "RESEARCH":
            return base + "要求：输出结构化报告，包含标题与要点。"
        if task_type == "WEB_SEARCH":
            return base + "要求：基于实时信息回答，给出清晰结论。"
        return base

    @staticmethod
    def adapt_prompt_to_markdown(
        task_type: str, user_input: str, history: list = None
    ) -> str:
        """使用本地模板将原始请求转为结构化 Markdown，便于大模型理解。

        注：已移除 flash-lite 二次润色调用（额外 API 费用 + ~300ms 延迟，收益不明显）。
        PromptAdapter 的本地模板（base_md）已足够主模型理解。
        """
        try:
            try:
                from web.prompt_adapter import PromptAdapter
            except ImportError:
                from prompt_adapter import PromptAdapter

            # model_generate=None：仅使用本地关键词提取 + Markdown 模板，不发起额外 LLM 调用
            return PromptAdapter.adapt(
                user_input=user_input,
                task_type=task_type,
                history=history,
                model_generate=None,
            )
        except Exception as e:
            logger.debug(f"[PROMPT_ADAPTER] Failed: {e}")
            return user_input

    @staticmethod
    def quick_self_check(task_type: str, user_input: str, output_text: str) -> dict:
        """使用快速模型进行自检，返回 {'pass': bool, 'fix_prompt': str}。"""
        try:
            check_prompt = (
                "你是质量检查器。判断输出是否满足用户需求。\n"
                "只输出以下格式之一：\n"
                "PASS\n"
                "或\n"
                "FAIL\nFIX_PROMPT: <用于修正的提示词>\n\n"
                f"任务类型: {task_type}\n"
                f"用户需求: {user_input}\n"
                f"模型输出:\n{output_text}\n"
            )
            response = _client().models.generate_content(
                model="deepseek-chat",
                contents=check_prompt,
                config=_types().GenerateContentConfig(
                    max_output_tokens=300,
                    temperature=0.1,
                ),
            )
            text = (response.text or "").strip()
            if text.startswith("PASS"):
                return {"pass": True, "fix_prompt": ""}
            if text.startswith("FAIL"):
                fix = ""
                for line in text.splitlines():
                    if line.startswith("FIX_PROMPT:"):
                        fix = line.replace("FIX_PROMPT:", "").strip()
                        break
                return {"pass": False, "fix_prompt": fix}
            return {"pass": True, "fix_prompt": ""}
        except Exception as e:
            logger.debug(f"[SELF_CHECK] Failed: {e}")
            return {"pass": True, "fix_prompt": ""}

    @staticmethod
    def detect_required_packages(text: str) -> list:
        """从输出中粗略检测第三方依赖（仅返回白名单内的包）。"""
        if not text:
            return []
        modules = set()
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("import "):
                parts = line.replace("import", "").split(",")
                for p in parts:
                    name = p.strip().split(" ")[0]
                    if name:
                        modules.add(name)
            elif line.startswith("from "):
                parts = line.split()
                if len(parts) >= 2:
                    modules.add(parts[1].strip())

        packages = set()
        for mod in modules:
            if mod in Utils._PACKAGE_ALLOWLIST:
                packages.add(Utils._PACKAGE_ALLOWLIST[mod])
        return sorted(packages)

    @staticmethod
    def auto_install_packages(packages: list) -> dict:
        """安装缺失的依赖包。返回安装结果摘要。"""
        result = {"installed": [], "skipped": [], "failed": []}
        if not packages:
            return result

        for pkg in packages:
            try:
                spec = importlib.util.find_spec(pkg)
                if spec is not None:
                    result["skipped"].append(pkg)
                    continue
                module_aliases = [
                    m for m, p in Utils._PACKAGE_ALLOWLIST.items() if p == pkg
                ]
                if any(importlib.util.find_spec(m) is not None for m in module_aliases):
                    result["skipped"].append(pkg)
                    continue
            except Exception:
                import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)

            try:
                if getattr(sys, "frozen", False):
                    # 打包版无法安装新包，pip 在冻结环境下不可用
                    result["failed"].append(pkg)
                else:
                    cmd = [sys.executable, "-m", "pip", "install", pkg]
                    proc = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=120,
                        creationflags=(
                            subprocess.CREATE_NO_WINDOW
                            if sys.platform == "win32"
                            else 0
                        ),
                    )
                    if proc.returncode == 0:
                        result["installed"].append(pkg)
                    else:
                        result["failed"].append(pkg)
            except Exception:
                result["failed"].append(pkg)

        return result

    @staticmethod
    def auto_save_files(text):
        """自动从响应中提取并保存文件"""
        saved = []

        code_dir = os.path.join(get_workspace_dir(), "code")
        os.makedirs(code_dir, exist_ok=True)

        def _get_save_dir(filename):
            ext = os.path.splitext(filename)[1].lower()
            code_exts = {
                ".py",
                ".js",
                ".ts",
                ".tsx",
                ".jsx",
                ".java",
                ".cs",
                ".cpp",
                ".c",
                ".go",
                ".rs",
                ".rb",
                ".php",
                ".swift",
                ".kt",
                ".m",
                ".scala",
                ".sh",
                ".ps1",
                ".bat",
                ".cmd",
                ".json",
                ".yaml",
                ".yml",
                ".toml",
                ".ini",
                ".cfg",
                ".sql",
                ".md",
                ".html",
                ".css",
            }
            return code_dir if ext in code_exts else get_workspace_dir()

        # 调试：打印前800字符看看格式
        logger.debug(f"[FILE_GEN] Response first 800 chars:\n{text[:800]}\n")

        # 预处理：统一格式 (去掉多余空格)
        normalized_text = text

        # 方法1: 多种 BEGIN_FILE 格式的正则匹配
        patterns = [
            # 格式1: ---BEGIN_FILE: filename.py--- (无空格)
            r"---BEGIN_FILE:\s*([a-zA-Z0-9_.-]+)\s*---\s*(.*?)---\s*END_FILE\s*---",
            # 格式2: ---BEGIN_FILE: filename.py--- ... ---END_FILE--- (带换行)
            r"---BEGIN_FILE:\s*([a-zA-Z0-9_.-]+)\s*---\n(.*?)\n---END_FILE---",
            # 格式3: 更宽松 - 允许各种空白
            r"---\s*BEGIN_FILE[:\s]+([a-zA-Z0-9_.-]+)\s*---\s*(.*?)---\s*END_FILE\s*---",
            # 格式4: 最宽松 - 捕获任意文件名
            r"---BEGIN_FILE[:\s]+([^\n-]+?)---\s*(.*?)---END_FILE---",
        ]

        matches1 = []
        for i, pattern in enumerate(patterns):
            try:
                matches1 = re.findall(
                    pattern, normalized_text, re.DOTALL | re.IGNORECASE
                )
                logger.debug(f"[FILE_GEN] Pattern{i+1} matches: {len(matches1)}")
                if matches1:
                    logger.debug(f"[FILE_GEN] ✓ Using pattern {i+1}")
                    break
            except Exception as e:
                logger.debug(f"[FILE_GEN] Pattern{i+1} error: {e}")

        for filename, content in matches1:
            try:
                filename = filename.strip()
                content = content.strip()
                logger.debug(
                    f"[FILE_GEN] Processing file: '{filename}', content length: {len(content)}"
                )

                # 清除 Markdown 代码块标记
                if content.startswith("```"):
                    lines = content.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    content = "\n".join(lines)
                    logger.debug(
                        f"[FILE_GEN] After stripping markdown: {len(content)} chars"
                    )

                # 确保文件名有效
                if not filename or len(filename) > 100:
                    logger.debug(f"[FILE_GEN] Invalid filename: {filename}")
                    continue

                # 确保文件名有扩展名
                if "." not in filename:
                    filename = filename + ".py"

                base_dir = _get_save_dir(filename)
                path = os.path.join(base_dir, filename)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                saved.append(filename)
                logger.info(f"[FILE_GEN] ✅ Saved: {filename} to {path}")
            except Exception as e:
                logger.error(f"[FILE_GEN] ❌ Save failed: {e}")
                import traceback

                traceback.print_exc()

        # 方法2: 如果方法1没找到，尝试提取 ```python 代码块 + 文件名注释
        if not saved:
            logger.debug(
                f"[FILE_GEN] Method1 empty, trying method2 (```python blocks)..."
            )

            # 先尝试匹配带文件名的代码块
            # 例如: # filename: cat_info.py 或 # cat_info.py
            pattern2a = (
                r"```python\s*\n#\s*(?:filename:\s*)?([a-zA-Z0-9_.-]+\.py)\s*\n(.*?)```"
            )
            matches2a = re.findall(pattern2a, text, re.DOTALL)
            logger.debug(
                f"[FILE_GEN] Pattern2a (with filename comment) matches: {len(matches2a)}"
            )

            if matches2a:
                for filename, code in matches2a:
                    code = code.strip()
                    if not code or len(code) < 20:
                        continue
                    base_dir = _get_save_dir(filename)
                    path = os.path.join(base_dir, filename)
                    try:
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(code)
                        saved.append(filename)
                        logger.info(f"[FILE_GEN] ✅ Method2a saved: {filename}")
                    except Exception as e:
                        logger.error(f"[FILE_GEN] ❌ Method2a save failed: {e}")
            else:
                # 无文件名的代码块，使用时间戳
                pattern2 = r"```python\s*\n(.*?)```"
                matches2 = re.findall(pattern2, text, re.DOTALL)
                logger.debug(
                    f"[FILE_GEN] Pattern2 (generic) matches: {len(matches2)}"
                )

                if matches2:
                    timestamp = int(time.time())
                    for idx, code in enumerate(matches2):
                        code = code.strip()
                        if not code or len(code) < 50:
                            continue

                        # 尝试从代码中提取有意义的文件名
                        filename = None
                        # 查找 doc_path, file_path 等变量
                        path_match = re.search(
                            r'(?:doc_path|file_path|filepath|output_path)\s*=.*?["\']([^"\']+\.(pdf|docx|xlsx))["\']',
                            code,
                        )
                        if path_match:
                            # 使用目标文件名作为脚本名
                            target_file = os.path.basename(path_match.group(1))
                            filename = target_file.rsplit(".", 1)[0] + ".py"

                        if not filename:
                            filename = f"generated_{timestamp}_{idx}.py"

                        base_dir = _get_save_dir(filename)
                        path = os.path.join(base_dir, filename)
                        try:
                            with open(path, "w", encoding="utf-8") as f:
                                f.write(code)
                            saved.append(filename)
                            logger.info(f"[FILE_GEN] ✅ Method2 saved: {filename}")
                        except Exception as e:
                            logger.error(f"[FILE_GEN] ❌ Method2 save failed: {e}")

        logger.debug(f"[FILE_GEN] Final saved files: {saved}")
        return saved

    @staticmethod
    def save_image_part(blob_part):
        try:
            # 使用用户设置的图片目录
            images_dir = _settings_manager().images_dir
            os.makedirs(images_dir, exist_ok=True)

            timestamp = int(time.time())
            filename = f"generated_{timestamp}.png"
            filepath = os.path.join(images_dir, filename)
            with open(filepath, "wb") as f:
                f.write(blob_part.inline_data.data)

            # 返回相对于 workspace 的路径
            # 确保路径始终在 workspace 下，且格式为正斜杠
            try:
                rel_path = os.path.relpath(filepath, get_workspace_dir())
                # 如果包含 .. 说明不在 workspace 下，需要处理
                if ".." in rel_path:
                    # 降级为只返回文件名，放在 workspace/images 下
                    abs_workspace_images = os.path.join(get_workspace_dir(), "images")
                    os.makedirs(abs_workspace_images, exist_ok=True)
                    fallback_path = os.path.join(abs_workspace_images, filename)
                    with open(fallback_path, "wb") as f:
                        f.write(blob_part.inline_data.data)
                    rel_path = os.path.relpath(fallback_path, get_workspace_dir())
                    logger.debug(
                        f"[IMAGE] Falling back to workspace/images: {rel_path}"
                    )

                result = rel_path.replace("\\", "/")
                logger.debug(f"[IMAGE] Saved image: {result}")
                return result
            except Exception as path_err:
                logger.debug(f"[IMAGE] Path calculation error: {path_err}")
                # 最后的保险方案：直接保存到 workspace/images
                abs_workspace_images = os.path.join(get_workspace_dir(), "images")
                os.makedirs(abs_workspace_images, exist_ok=True)
                fallback_path = os.path.join(abs_workspace_images, filename)
                with open(fallback_path, "wb") as f:
                    f.write(blob_part.inline_data.data)
                result = os.path.relpath(fallback_path, get_workspace_dir()).replace(
                    "\\", "/"
                )
                logger.debug(f"[IMAGE] Emergency fallback: {result}")
                return result
        except Exception as e:
            logger.debug(f"[IMAGE] Save failed: {e}")
            import traceback

            traceback.print_exc()
            return None


# ================= Session Manager =================
