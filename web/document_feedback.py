#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
文档智能反馈系统 - 完整闭环
1. 读取文档 → 2. AI分析 → 3. 写回原生修订
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

from app.core.llm.model_capabilities import (
    get_interactions_only_model_set,
    is_interactions_only_model,
    normalize_model_id,
)
from app.core.llm.model_selection import is_archived_cloud_model

logger = logging.getLogger(__name__)


class DocumentFeedbackSystem:
    """文档智能反馈系统"""

    def __init__(
        self, gemini_client=None, default_model_id: str = "deepseek-chat"
    ):
        """
        Args:
            gemini_client: 兼容参数名；传入当前活动模型客户端
            default_model_id: 默认优先模型（必须是支持 generate_content 的模型，不能是 Interactions-only 模型）
        """
        self.client = gemini_client
        self.default_model_id = default_model_id
        from web.document_editor import DocumentEditor
        from web.document_reader import DocumentReader

        self.reader = DocumentReader()
        self.editor = DocumentEditor()

        self._model_cache = None

    @staticmethod
    def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
        try:
            return max(minimum, int(os.getenv(name, str(default))))
        except (TypeError, ValueError):
            return default

    def _local_client_model_id(self) -> str:
        direct_model = str(getattr(self.client, "_model_tag", "") or "").strip()
        if direct_model:
            return direct_model
        model_proxy = getattr(self.client, "models", None)
        proxy_model = str(getattr(model_proxy, "_model_tag", "") or "").strip()
        if proxy_model:
            return proxy_model
        return ""

    def _is_local_client(self) -> bool:
        if not self.client:
            return False
        if self._local_client_model_id():
            return True
        return self.client.__class__.__name__ == "OllamaClientProxy"

    def _resolve_runtime_model_id(self, model_id: Optional[str]) -> str:
        preferred = str(model_id or self.default_model_id or "").strip()
        if not self._is_local_client():
            return preferred

        # A local proxy has already selected the concrete Ollama model. Cloud
        # defaults or stale UI model ids must not override that runtime identity.
        return self._local_client_model_id() or preferred or "local"

    def analyze_and_suggest(
        self,
        file_path: str,
        user_requirement: str = "",
        model_id: str = "deepseek-chat",
    ) -> Dict[str, Any]:
        """
        分析文档并给出AI修改建议

        Args:
            file_path: 文档路径
            user_requirement: 用户需求（例如："请优化标题，让它更专业"）
            model_id: 使用的模型ID

        Returns:
            {
                "success": True,
                "original_content": {...},
                "ai_suggestions": "AI分析文本",
                "modifications": [...],
                "summary": "修改建议摘要"
            }
        """
        # 第1步：读取文档
        logger.info(f"[DocumentFeedback] 📖 读取文档: {os.path.basename(file_path)}")
        doc_data = self.reader.read_document(file_path)

        if not doc_data.get("success"):
            return {"success": False, "error": f"读取文档失败: {doc_data.get('error')}"}

        # 第2步：格式化给AI
        formatted_content = self.reader.format_for_ai(doc_data)

        # 第3步：构建AI提示
        prompt = self._build_analysis_prompt(
            doc_data.get("type"), formatted_content, user_requirement
        )

        # 第4步：调用AI分析
        if not self.client:
            return {"success": False, "error": "Gemini客户端未初始化"}

        selected_model, _ = self._select_best_model(model_id)
        logger.info(f"[DocumentFeedback] 🤖 AI分析中...")

        try:
            from app.core.llm.provider_compat import types

            response = self.client.models.generate_content(
                model=selected_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=32000,
                ),
            )

            ai_response = response.text if response else ""
            if not ai_response and getattr(response, "candidates", None):
                # 尝试从候选中提取文本
                try:
                    parts = response.candidates[0].content.parts
                    ai_response = "".join(
                        [
                            getattr(p, "text", "")
                            for p in parts
                            if getattr(p, "text", "")
                        ]
                    )
                except Exception:
                    ai_response = ""

            if not ai_response:
                return {"success": False, "error": "AI分析失败: 模型未返回内容"}

        except Exception as e:
            return {"success": False, "error": f"AI分析失败: {str(e)}"}

        # 第5步：解析AI建议
        logger.info(f"[DocumentFeedback] 📋 解析AI建议...")
        modifications = self.editor.parse_ai_suggestions(ai_response)

        # 提取摘要（AI响应中的文字说明部分）
        summary = self._extract_summary(ai_response)

        return {
            "success": True,
            "file_path": file_path,
            "doc_type": doc_data.get("type"),
            "original_content": doc_data,
            "ai_suggestions": ai_response,
            "modifications": modifications,
            "modification_count": len(modifications),
            "summary": summary,
        }

    def apply_suggestions(self, file_path: str, modifications: list) -> Dict[str, Any]:
        """
        应用AI建议，生成新文档

        Args:
            file_path: 原文档路径
            modifications: 修改指令列表

        Returns:
            {
                "success": True,
                "new_file_path": "...",
                "applied_count": 5
            }
        """
        logger.info(f"[DocumentFeedback] ✏️ 应用修改...")

        # 根据文件类型调用对应的编辑器
        ext = os.path.splitext(file_path)[1].lower()

        if ext in [".ppt", ".pptx"]:
            result = self.editor.edit_ppt(file_path, modifications)
        elif ext in [".doc", ".docx"]:
            result = self.editor.edit_word(file_path, modifications)
        elif ext in [".xls", ".xlsx"]:
            result = self.editor.edit_excel(file_path, modifications)
        else:
            return {"success": False, "error": f"不支持的文件类型: {ext}"}

        if result.get("success"):
            logger.info(
                f"[DocumentFeedback] ✅ 修改完成: {os.path.basename(result['file_path'])}"
            )

        return result

    def full_feedback_loop(
        self, file_path: str, user_requirement: str = "", auto_apply: bool = True
    ) -> Dict[str, Any]:
        """
        完整反馈闭环（同步兼容包装）：读取 → 分析 → 修改

        Args:
            file_path: 文档路径
            user_requirement: 用户需求
            auto_apply: 是否自动应用修改

        Returns:
            完整的处理结果
        """
        logger.info("=" * 60)
        logger.info("🔄 启动文档智能反馈系统（同步兼容包装）")
        logger.info("=" * 60)

        # 第1步：分析并获取建议
        analysis_result = self.analyze_and_suggest(file_path, user_requirement)

        if not analysis_result.get("success"):
            return analysis_result

        logger.info(f"\n📊 分析结果:")
        logger.info(f"   修改建议数: {analysis_result['modification_count']}")
        logger.info(f"   摘要: {analysis_result['summary'][:100]}...")

        # 第2步：应用修改（如果启用）
        if auto_apply and analysis_result["modification_count"] > 0:
            apply_result = self.apply_suggestions(
                file_path, analysis_result["modifications"]
            )

            return {
                "success": True,
                "analysis": analysis_result,
                "edit_result": apply_result,
                "new_file_path": apply_result.get("file_path"),
                "applied_count": apply_result.get("applied_count", 0),
            }
        else:
            return {
                "success": True,
                "analysis": analysis_result,
                "message": "仅分析，未应用修改",
            }

    def _build_analysis_prompt(
        self, doc_type: str, formatted_content: str, user_requirement: str
    ) -> str:
        """构建AI分析提示"""

        base_prompt = f"""你是Koto文档智能分析助手。请分析以下{doc_type.upper()}文档，并给出改进建议。

## 文档内容
{formatted_content}

## 用户需求
{user_requirement if user_requirement else "请全面审查文档，提供专业的优化建议"}

## ⚠️ 特别注意
**请特别关注以下内容，不要遗漏：**
1. **格式变化部分**：包含 **粗体**、*斜体*、[颜色标记] 等格式的文本（文档中标记为"[此段落有格式变化]"）
2. **图标和特殊字符**：如●、★、✓、→、•等符号
3. **字体大小变化**：标题、小字注释等不同字号的内容
4. **混合内容**：既有文字又有图标的部分，例如"● 要点一"、"→ 步骤二"
5. **中英文混排**：包含英文术语的中文句子
6. **数字和单位**：如"10px"、"100%"、"3.5倍"等

## 任务要求
1. 仔细阅读文档内容（**包括所有格式标记的部分**）
2. 分析每个部分的质量和准确性（**尤其是有格式变化的段落**）
3. 给出具体的修改建议（**确保覆盖所有内容，不遗漏图标和特殊格式部分**）

## 输出格式
请按以下JSON格式输出修改建议：

```json
{{
  "summary": "整体分析和建议摘要",
  "modifications": [
"""

        if doc_type == "ppt":
            base_prompt += """    {
      "slide_index": 0,
      "action": "update_title",
      "target": "title",
      "content": "修改后的标题",
      "reason": "修改原因"
    },
    {
      "slide_index": 1,
      "action": "update_content",
      "target": "content",
      "position": 0,
      "content": "修改后的内容点",
      "reason": "修改原因"
    },
    {
      "slide_index": 2,
      "action": "add_content",
      "target": "content",
      "content": "新增的要点",
      "reason": "添加原因"
    }
  ]
}
```

可用的action类型：
- update_title: 修改标题
- update_content: 修改内容点（需要position）
- add_content: 添加新内容点
- delete_content: 删除内容点（需要position）
"""

        elif doc_type == "word":
            base_prompt += """    {
      "paragraph_index": 2,
      "action": "update",
      "content": "修改后的段落内容",
      "reason": "修改原因"
    },
    {
      "paragraph_index": 5,
      "action": "insert",
      "content": "新插入的段落",
      "reason": "插入原因（在第5段之前插入）"
    },
    {
      "paragraph_index": 8,
      "action": "delete",
      "reason": "删除原因"
    },
    {
      "action": "update_table_cell",
      "table_index": 0,
      "row": 1,
      "col": 2,
      "value": "新单元格内容",
      "reason": "修改第1个表格第2行第3列"
    },
    {
      "action": "insert_table_row",
      "table_index": 0,
      "row": 3,
      "reason": "在第3行之前插入空行"
    },
    {
      "action": "delete_table_row",
      "table_index": 0,
      "row": 4,
      "reason": "删除第4行"
    }
  ]
}
```

可用的 action 类型：
锻段落操作（需 paragraph_index）：
- update: 修改现有段落文本
- insert: 在 paragraph_index 段落之前插入新段落
- delete: 删除 paragraph_index 段落

表格操作（需 table_index，索引从0开始）：
- update_table_cell: 修改单元格，需要 row/col/value（索引从0开始）
- insert_table_row: 在 row 之前插入空行
- delete_table_row: 删除 row 行

注意：文档中的 [📷 图片N] 是嵌入图片，无法通过此接口修改图片内容，只能修改其前后的文字。
"""

        elif doc_type == "excel":
            base_prompt += """    {
      "sheet_name": "Sheet1",
      "row": 0,
      "col": 0,
      "action": "update",
      "value": "新值",
      "reason": "修改原因"
    }
  ]
}
```

可用的action类型：
- update: 修改单元格
- insert_row: 插入行
- delete_row: 删除行
"""

        base_prompt += """

注意：
- 只输出JSON，不要其他解释
- modifications数组中每个修改都要有明确的理由
- 索引从0开始
- 保持专业和准确
"""

        return base_prompt

    def _extract_summary(self, ai_response: str) -> str:
        """从AI响应中提取摘要"""
        import json
        import re

        try:
            # 尝试提取JSON中的summary字段
            json_match = re.search(r"```json\s*(\{.*?\})\s*```", ai_response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
                return data.get("summary", "AI建议已生成")

            # 提取非JSON部分作为摘要
            summary = re.sub(r"```json.*?```", "", ai_response, flags=re.DOTALL).strip()
            return summary[:200] if summary else "AI建议已生成"

        except Exception:
            return "AI建议已生成"

    # 仅支持 Interactions API 的模型：所有 generate_content 调用必须排除这些模型
    # 注意：gemini-3-flash/pro-preview 是普通 generate_content 模型，不应列在此
    _INTERACTIONS_ONLY_MODELS = frozenset(get_interactions_only_model_set())

    def _list_available_models(self) -> List[Dict[str, str]]:
        """列出当前 API 可用模型（仅包含支持 generateContent 的模型，排除 Interactions-only）"""
        if self._model_cache is not None:
            return self._model_cache
        if not self.client:
            self._model_cache = []
            return self._model_cache
        if self._is_local_client():
            local_model = self._resolve_runtime_model_id(None)
            self._model_cache = (
                [{"name": local_model, "display_name": local_model}]
                if local_model
                else []
            )
            return self._model_cache
        try:
            import threading

            result_holder: Dict[str, Any] = {"models": None}

            def _fetch_models():
                try:
                    models = []
                    for m in self.client.models.list():
                        name = getattr(m, "name", "")
                        display_name = getattr(m, "display_name", "")
                        base_name = normalize_model_id(name)
                        if not base_name:
                            continue
                        # 新版 google-genai SDK 中 supported_generation_methods 不再作为属性暴露
                        # 改为：只要 API 返回该模型，默认认为支持 generateContent（排除 Interactions-only 例外）
                        supported = getattr(m, "supported_generation_methods", None)
                        if supported is not None:
                            # 旧式 SDK 仍有此字段时沿用过滤逻辑
                            if "generateContent" not in supported:
                                continue
                        # 跳过 Interactions-only 模型（仅支持 Interactions API，不能用于 generate_content）
                        if not is_interactions_only_model(
                            base_name, self._INTERACTIONS_ONLY_MODELS
                        ) and not is_archived_cloud_model(base_name):
                            models.append(
                                {
                                    "name": base_name,
                                    "display_name": display_name or base_name,
                                }
                            )
                    result_holder["models"] = models
                except Exception:
                    result_holder["models"] = []

            t = threading.Thread(target=_fetch_models, daemon=True)
            t.start()
            t.join(timeout=10)  # models.list() 最多等 10s，防止慢网络卡死分析线程
            models = result_holder["models"]
            if models is None:  # timeout
                logger.warning(
                    "[DocumentFeedback] ⚠️ models.list() 超时（>10s），使用空列表降级"
                )
                models = []
            self._model_cache = models
            return models
        except Exception:
            self._model_cache = []
            return self._model_cache

    def _select_best_model(self, preferred: str) -> (str, List[Dict[str, str]]):
        """根据可用模型选择最高质量模型（优先使用 preferred，排除 Interactions-only 模型）"""
        models = self._list_available_models()
        available = {m["name"] for m in models}

        # 若 preferred 本身是 Interactions-only，直接替换为稳定备选
        safe_preferred = (
            preferred
            if not is_interactions_only_model(preferred, self._INTERACTIONS_ONLY_MODELS)
            and not is_archived_cloud_model(preferred)
            else "deepseek-chat"
        )

        if not models:
            return safe_preferred, models

        priority = [safe_preferred, "deepseek-chat"]

        for name in priority:
            if name in available:
                if name != preferred:
                    logger.info(f"[DocumentFeedback] 🔄 模型降级: {preferred} → {name}")
                return name, models

        # 若列表中没有任何匹配，使用 safe_preferred 硬降级
        logger.warning(
            f"[DocumentFeedback] ⚠️ 无可用匹配模型，强制使用: {safe_preferred}"
        )
        return safe_preferred, models

    def _format_model_table(self, models: List[Dict[str, str]]) -> str:
        """生成可用模型表格（Markdown）"""
        if not models:
            return "（暂时无法获取可用模型列表）"

        rows = ["| 模型ID | 显示名称 |", "| --- | --- |"]
        for m in models:
            rows.append(f"| {m['name']} | {m['display_name']} |")
        return "\n".join(rows)

    def _probe_working_model(self, preferred: str, timeout: int = 12) -> Optional[str]:
        """
        快速探测优先级模型列表中第一个可正常响应的模型。
        - 对 503/UNAVAILABLE/overloaded 错误立即跳过（无需重试），尝试下一个
        - 其他错误（auth/quota等）停止往下探测
        - 所有候选均失败时返回 None
        返回第一个成功响应的模型名，若全部失败返回 None。
        """
        resolved_preferred = self._resolve_runtime_model_id(preferred)
        if not self.client:
            return resolved_preferred
        if self._is_local_client():
            return resolved_preferred
        from app.core.llm.provider_compat import types as _gt

        probe_order = list(dict.fromkeys([resolved_preferred, "deepseek-chat"]))
        probe_order = [
            m
            for m in probe_order
            if not is_interactions_only_model(m, self._INTERACTIONS_ONLY_MODELS)
        ]

        for candidate in probe_order:
            import threading

            _result: Dict[str, Any] = {"ok": False, "err": ""}

            def _try(_m=candidate):
                try:
                    self.client.models.generate_content(
                        model=_m,
                        contents="1",
                        config=_gt.GenerateContentConfig(
                            temperature=0.0, max_output_tokens=5
                        ),
                    )
                    _result["ok"] = True
                except Exception as exc:
                    _result["err"] = str(exc)

            t = threading.Thread(target=_try, daemon=True)
            t.start()
            t.join(timeout)
            if t.is_alive():
                logger.info(f"[DocumentFeedback] ⏱️ 探测 {candidate} 超时，跳过")
                continue
            if _result["ok"]:
                logger.info(f"[DocumentFeedback] ✅ 探测成功: {candidate}")
                return candidate
            err = _result["err"]
            _is_503 = (
                "503" in err
                or "UNAVAILABLE" in err
                or "overloaded" in err.lower()
                or "high demand" in err.lower()
            )
            if _is_503:
                logger.warning(
                    f"[DocumentFeedback] ⚠️ {candidate} 过载(503)，尝试下一个模型"
                )
                continue
            # 非 503 错误（认证失败/配额超限等）—— 不再往下尝试
            logger.error(
                f"[DocumentFeedback] ❌ {candidate} 探测失败(非503): {err[:100]}"
            )
            break

        logger.warning(f"[DocumentFeedback] ⚠️ 所有探测候选模型均不可用")
        return None

    # ==================== 文档自动标注功能 ====================

    def _analyze_chunk_for_annotations(
        self,
        chunk: str,
        doc_type: str,
        user_requirement: str,
        model_id: str,
        chunk_index: int,
        total_chunks: int,
        full_doc_context: str = "",
        reference_context: Any = "",
        max_retries: int = 3,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> Optional[List[Dict[str, str]]]:
        """
        分析单个分段并返回标注列表（严格顺序执行，上一段完成后再处理下一段）
        """
        runtime_model_id = self._resolve_runtime_model_id(model_id)
        is_local_client = self._is_local_client()
        base_context = (
            user_requirement
            + f"\n(注：这是文档的第{chunk_index}部分，共{total_chunks}部分)"
        )

        def _emit_status(detail: str) -> None:
            if not status_callback:
                return
            try:
                status_callback(str(detail or "").strip())
            except Exception as exc:
                logger.debug("[DocumentFeedback] status_callback 调用失败: %s", exc)

        def _call_model(contents: str):
            from app.core.llm.provider_compat import types

            _is_thinking_model = False
            _thinking_cfg = (
                types.ThinkingConfig(thinking_budget=4096)
                if _is_thinking_model
                else None
            )
            _cfg_kwargs = dict(
                temperature=0.2,
                max_output_tokens=(
                    self._env_int("KOTO_DOC_REVIEW_LOCAL_MAX_OUTPUT_TOKENS", 6000, minimum=1024)
                    if is_local_client
                    else 16000
                ),
            )
            if _thinking_cfg is not None:
                _cfg_kwargs["thinking_config"] = _thinking_cfg
            return self.client.models.generate_content(
                model=runtime_model_id,
                contents=contents,
                config=types.GenerateContentConfig(**_cfg_kwargs),
            )

        chunk_timeout_seconds = (
            self._env_int("KOTO_DOC_REVIEW_LOCAL_CHUNK_TIMEOUT", 90, minimum=30)
            if is_local_client
            else 240
        )
        retry_limit = (
            self._env_int("KOTO_DOC_REVIEW_LOCAL_CHUNK_RETRIES", 1, minimum=1)
            if is_local_client
            else max_retries
        )

        def _call_with_timeout(contents: str, timeout_seconds: Optional[int] = None):
            import threading

            effective_timeout = timeout_seconds or chunk_timeout_seconds
            result_holder = {"response": None, "error": None}

            def _runner():
                try:
                    logger.info(
                        f"[DocumentFeedback] 🌐 调用AI API (超时: {effective_timeout}s)..."
                    )
                    result_holder["response"] = _call_model(contents)
                    logger.info(f"[DocumentFeedback] ✅ AI响应成功")
                except Exception as e:
                    logger.error(f"[DocumentFeedback] ❌ AI调用异常: {e}")
                    result_holder["error"] = e

            t = threading.Thread(target=_runner, daemon=True)
            t.start()
            t.join(effective_timeout)
            if t.is_alive():
                logger.info(f"[DocumentFeedback] ⏱️ AI调用超时 ({effective_timeout}s)")
                return None, TimeoutError(f"Chunk timeout after {effective_timeout}s")
            if result_holder["error"]:
                return None, result_holder["error"]
            return result_holder["response"], None

        all_annotations: List[Dict[str, str]] = []
        seen_texts = set()
        # 质量优先：确保多轮审阅，避免“只跑一轮”导致遗漏
        if is_local_client:
            max_rounds = 1 if len(chunk) <= 2600 else 2
        elif len(chunk) <= 1800:
            max_rounds = 2
        else:
            max_rounds = 3

        min_new_per_round = 3

        for round_idx in range(1, max_rounds + 1):
            logger.info(
                f"[DocumentFeedback] 🔁 第{chunk_index}段进入第{round_idx}/{max_rounds}轮审阅"
            )
            _emit_status(
                f"第{chunk_index}/{total_chunks}段，第{round_idx}/{max_rounds}轮：正在整理提示词"
            )
            chunk_reference_context = self._select_reference_context(
                reference_context,
                chunk_index=chunk_index,
                total_chunks=total_chunks,
            )
            # 第一轮注重全面扫描，如果只有一轮，则直接要求全面
            current_focus_prompt = ""
            if round_idx == 1:
                target_count = max(5, len(chunk) // 200)  # 动态计算目标数量，每200字1个
                current_focus_prompt = f"\n\n本轮重点：全面扫描，找出所有明显的语病、翻译腔和拗口表达。目标约{target_count}处修改。"
            else:
                current_focus_prompt = "\n\n本轮重点：查漏补缺，关注上一轮可能忽略的逻辑连接词、标点符号和深层润色。目标约5-10处补充修改。"

            prompt = self._build_annotation_prompt(
                doc_type,
                chunk,
                base_context
                + f"\n\n这是第{round_idx}/{max_rounds}轮审阅。请找出真正需要修改的问题，本轮目标约{target_count if round_idx == 1 else 10}处修改。"
                + current_focus_prompt,
                full_doc_context=full_doc_context,
                reference_context=chunk_reference_context,
            )
            strict_prompt = self._build_annotation_prompt(
                doc_type,
                chunk,
                base_context
                + f"\n\n请务必仅输出JSON数组，本轮最多15条；若确实没有问题再返回空数组。",
                reference_context=chunk_reference_context,
            )

            for retry in range(retry_limit):
                try:
                    # 断线重试：首次立即，后续等待 3s / 6s 再试
                    if retry > 0:
                        _wait = 3 * retry
                        _emit_status(
                            f"第{chunk_index}/{total_chunks}段，第{round_idx}/{max_rounds}轮：第{retry + 1}/{retry_limit}次请求前等待 {_wait}s"
                        )
                        logger.info(
                            f"[DocumentFeedback] ⏳ 等待{_wait}s后重试 (第{retry+1}/{retry_limit}次)..."
                        )
                        import time as _time_mod

                        _time_mod.sleep(_wait)
                    _emit_status(
                        f"第{chunk_index}/{total_chunks}段，第{round_idx}/{max_rounds}轮：等待 AI({runtime_model_id}) 返回（第{retry + 1}/{retry_limit}次请求）"
                    )
                    response, err = _call_with_timeout(prompt)  # 默认180秒超时
                    if err:
                        raise err
                    if response and response.text:
                        annotations = self._parse_annotation_response(response.text)
                        if annotations:
                            # 二次快速检测：仅过滤掉"原文在文档中完全找不到"的幻觉项
                            try:
                                from web.document_validator import DocumentValidator

                                validation = DocumentValidator.validate_modifications(
                                    chunk, annotations
                                )
                                if validation.get("risk_level") == "HIGH":
                                    # 只过滤真正找不到原文的项（幻觉），不过滤其他 warning
                                    rejected_indices = set()
                                    for issue in validation.get("issues", []):
                                        import re

                                        m = re.match(r"#(\d+):\s*原文未找到", issue)
                                        if m:
                                            rejected_indices.add(int(m.group(1)) - 1)

                                    if rejected_indices:
                                        before = len(annotations)
                                        annotations = [
                                            a
                                            for i, a in enumerate(annotations)
                                            if i not in rejected_indices
                                        ]
                                        logger.info(
                                            f"[DocumentFeedback] 🛡️ 二次检测: 过滤 {before - len(annotations)} 条幻觉项，保留 {len(annotations)} 条"
                                        )
                            except Exception as e:
                                logger.warning(
                                    f"[DocumentFeedback] ⚠️ 二次检测跳过: {e}"
                                )

                            new_items = []
                            for item in annotations:
                                text = (item.get("原文片段") or "").strip()
                                if text and text not in seen_texts:
                                    seen_texts.add(text)
                                    new_items.append(item)
                            all_annotations.extend(new_items)
                            if len(new_items) < min_new_per_round:
                                if round_idx < max_rounds:
                                    _emit_status(
                                        f"第{chunk_index}/{total_chunks}段，第{round_idx}/{max_rounds}轮完成：新增{len(new_items)}条，继续查漏"
                                    )
                                    logger.info(
                                        f"[DocumentFeedback] ℹ️ 第{chunk_index}段第{round_idx}轮新增较少({len(new_items)}条)，继续下一轮查漏"
                                    )
                                    break
                                return all_annotations
                            break
                        if retry < retry_limit - 1:
                            _emit_status(
                                f"第{chunk_index}/{total_chunks}段，第{round_idx}/{max_rounds}轮：AI 输出为空或格式不符，改用严格 JSON 提示重试"
                            )
                            prompt = strict_prompt
                            continue
                        return all_annotations
                    if retry < retry_limit - 1:
                        _emit_status(
                            f"第{chunk_index}/{total_chunks}段，第{round_idx}/{max_rounds}轮：AI 未返回可解析内容，改用严格 JSON 提示重试"
                        )
                        prompt = strict_prompt
                        continue
                except Exception as e:
                    error_msg = str(e)[:120]
                    if retry < retry_limit - 1:
                        _emit_status(
                            f"第{chunk_index}/{total_chunks}段，第{round_idx}/{max_rounds}轮：请求失败，准备重试（{error_msg}）"
                        )
                    # 503/UNAVAILABLE：模型过载，立即返回兜底（不重试，外层负责切换模型）
                    _is_503 = (
                        "503" in error_msg
                        or "UNAVAILABLE" in error_msg
                        or "overloaded" in error_msg.lower()
                        or "high demand" in error_msg.lower()
                    )
                    if _is_503:
                        logger.info(
                            f"[DocumentFeedback] ⚡ 第{chunk_index}段 503过载，直接返回兜底: {error_msg[:80]}"
                        )
                        fallback = self._fallback_annotations_from_chunk(chunk)
                        for ann in fallback:
                            ann["_koto_fallback_error"] = error_msg
                            ann["_koto_503"] = True  # 通知外层需要切换模型
                        return fallback
                    # 断线/连接重置：值得重试，不降级到兜底
                    _is_disconnect = (
                        "Server disconnected" in error_msg
                        or "Connection reset" in error_msg
                        or "EOF occurred" in error_msg
                        or "ConnectionError" in error_msg
                        or "RemoteDisconnected" in error_msg
                        or "without sending a response" in error_msg
                    )
                    if _is_disconnect and retry < retry_limit - 1:
                        logger.info(
                            f"[DocumentFeedback] 🔌 第{chunk_index}段连接断开，将重试: {error_msg[:80]}"
                        )
                        continue
                    if retry < retry_limit - 1:
                        logger.warning(
                            f"[DocumentFeedback] ⚠️ 第{chunk_index}段第{round_idx}轮失败，准备重试: {error_msg}"
                        )
                        continue
                    logger.error(
                        f"[DocumentFeedback] ❌ 第{chunk_index}段第{round_idx}轮失败（已重试{retry_limit}次）: {error_msg}"
                    )
                    fallback = self._fallback_annotations_from_chunk(chunk)
                    # 给每条标注打上兜底标记，供调用层感知（内部键，最终不暴露给用户）
                    for ann in fallback:
                        ann["_koto_fallback_error"] = error_msg
                    return fallback

        return all_annotations

    @staticmethod
    def _fallback_annotations_from_chunk(chunk: str) -> List[Dict[str, str]]:
        """AI失败时的本地兜底标注 - 优化版（更具体的建议+均匀分布）"""
        import re

        annotations = []

        # ==================== Helper: 生成具体的修改建议 ====================
        def suggest_remove_bei(match_obj, original_text):
            """去掉被动语态：被X的 → X的"""
            verb = match_obj.group(1) if match_obj.lastindex >= 1 else ""
            # 提取完整片段
            full_match = match_obj.group(0)
            new_text = full_match.replace("被", "", 1)
            return {
                "原文片段": full_match,
                "修改建议": f"去除被动语态",
                "修改后文本": new_text,
                "理由": "去除被动语态，使表意更直接",
            }

        def suggest_remove_jinxing(match_obj, original_text):
            """去掉名词化：对X进行Y → YX"""
            obj = match_obj.group(1) if match_obj.lastindex >= 1 else ""
            action = match_obj.group(2) if match_obj.lastindex >= 2 else "处理"
            new_text = f"{action}{obj}"
            return {
                "原文片段": match_obj.group(0),
                "修改建议": "简化名词化表达",
                "修改后文本": new_text,
                "理由": "避免名词化表达，更符合中文习惯",
            }

        def suggest_simplify_tongguo(match_obj, original_text):
            """简化通过：通过X来Y → 用X或XY"""
            method = match_obj.group(1) if match_obj.lastindex >= 1 else ""
            if method:
                new_text = f"用{method}"
                return {
                    "原文片段": match_obj.group(0),
                    "修改建议": "简化连接词",
                    "修改后文本": new_text,
                    "理由": "删除冗余的连接词，表意更简洁",
                }
            return {
                "原文片段": match_obj.group(0),
                "修改建议": "删除冗余连接词",
                "修改后文本": "直接表达",
                "理由": "删除'通过...来'，直接表达",
            }

        def suggest_remove_suo(match_obj, original_text):
            """去掉所字结构：所X的Y → X的Y"""
            verb = match_obj.group(1) if match_obj.lastindex >= 1 else ""
            full_match = match_obj.group(0)
            new_text = full_match.replace("所", "", 1)
            return {
                "原文片段": full_match,
                "修改建议": "去除冗余的'所'字结构",
                "修改后文本": new_text,
                "理由": "去除冗余的'所'字结构，简化表达",
            }

        # ==================== 优化策略1：被动句问题 ====================
        # 被+动词 → 去掉"被"
        passive_patterns = [
            (r"被(\w{2,6})(?:的|了|着)", suggest_remove_bei),
            (r"被(\w{2,4})呈现", suggest_remove_bei),
            (r"被(\w{2,4})记录", suggest_remove_bei),
            (r"被(\w{2,4})感知", suggest_remove_bei),
            (r"被(用)为", suggest_remove_bei),  # 新增：被用为
            (r"被(称)为", suggest_remove_bei),  # 新增：被称为
            (r"被(视)为", suggest_remove_bei),  # 新增：被视为
            (r"被(认)为", suggest_remove_bei),  # 新增：被认为
        ]
        for pattern, suggest_func in passive_patterns:
            for m in re.finditer(pattern, chunk):
                text = m.group(0)
                if 3 <= len(text) <= 15:
                    anno = suggest_func(m, text)
                    if isinstance(anno, dict):
                        annotations.append(anno)

        # ==================== 优化策略2：名词化问题 ====================
        # 对X进行Y → YX
        nominalization_patterns = [
            (r"对(\w{2,4})进行(\w{2,4})", suggest_remove_jinxing),
            (
                r"进行(\w{2,4})(?:的)",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "简化名词化",
                    "修改后文本": f"{m.group(1)}的",
                    "理由": "避免'进行'的冗余表达",
                },
            ),
            (
                r"进行了(\w{2,4})",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "简化名词化",
                    "修改后文本": m.group(1),
                    "理由": "去掉'进行了'，直接用动词",
                },
            ),
        ]
        for pattern, suggest_func in nominalization_patterns:
            for m in re.finditer(pattern, chunk):
                text = m.group(0)
                if 4 <= len(text) <= 12:
                    anno = suggest_func(m, text)
                    if isinstance(anno, dict):
                        annotations.append(anno)

        # ==================== 优化策略3：冗余转移词 ====================
        # 通过X来Y → 用X或XY
        connector_patterns = [
            (r"通过(\w{2,6})(?:得以|来|以)", suggest_simplify_tongguo),
            (
                r"从而(\w{2,4})(?:得以|使|让)",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "简化逻辑连接",
                    "修改后文本": f"使{m.group(1)}",
                    "理由": "用'使'简化'从而'的表达",
                },
            ),
            (
                r"由于(\w{2,4})(?:，|，)从而",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "简化逻辑表达",
                    "修改后文本": f"由于{m.group(1)}，因此",
                    "理由": "用'因此'或'所以'简化",
                },
            ),
            (
                r"以便(\w{2,4})",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "改用更自然的表达",
                    "修改后文本": f"为了{m.group(1)}",
                    "理由": "'为了'比'以便'更自然",
                },
            ),
        ]
        for pattern, suggest_func in connector_patterns:
            for m in re.finditer(pattern, chunk):
                text = m.group(0)
                if 4 <= len(text) <= 15:
                    anno = suggest_func(m, text)
                    if isinstance(anno, dict):
                        annotations.append(anno)

        # ==================== 优化策略4：学术虚词 ====================
        # 影响/作用等 → 具体动词
        abstract_terms = [
            (
                r"\b影响\b(?!力)",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "替换为具体动词",
                    "修改后文本": "（决定/制约/改变/驱动）",
                    "理由": "避免使用空泛的学术虚词",
                },
            ),
            (
                r"\b作用\b(?!域)",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "替换为具体动词",
                    "修改后文本": "（驱动/促进/抑制/推动）",
                    "理由": "避免使用空泛的学术虚词",
                },
            ),
            (
                r"\b关系\b",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "具体化表达",
                    "修改后文本": "（因果关系/相关性/对应关系）",
                    "理由": "用具体的关系类型替代泛指",
                },
            ),
            (
                r"\b机制\b",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "具体化表达",
                    "修改后文本": "（原理/过程/方法/规律）",
                    "理由": "用具体概念替代空泛的'机制'",
                },
            ),
            (
                r"\b因素\b",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "具体化表达",
                    "修改后文本": "（条件/参数/变量/要素）",
                    "理由": "用具体概念替代空泛的'因素'",
                },
            ),
        ]
        for pattern, suggest_func in abstract_terms:
            for m in re.finditer(pattern, chunk):
                text = m.group(0)
                if 2 <= len(text) <= 6:
                    anno = suggest_func(m, text)
                    if isinstance(anno, dict):
                        annotations.append(anno)

        # ==================== 优化策略5：所字结构 ====================
        # 所+动词+的 → 去掉"所"
        suo_patterns = [
            (r"所(\w{2,4})的", suggest_remove_suo),
            (
                r"所谓(\w{2,4})",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "删除冗余修饰",
                    "修改后文本": m.group(1),
                    "理由": "直接表达，删除'所谓'的冗余修饰",
                },
            ),
        ]
        for pattern, suggest_func in suo_patterns:
            for m in re.finditer(pattern, chunk):
                text = m.group(0)
                if 3 <= len(text) <= 10:
                    anno = suggest_func(m, text)
                    if isinstance(anno, dict):
                        annotations.append(anno)

        # ==================== 优化策略6：模糊限定词 ====================
        # 非常/极其等 → 删除或换更强动词
        hedge_patterns = [
            (
                r"(?:非常|极其|十分|特别)(\w{2,6})",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "删除模糊限定词",
                    "修改后文本": m.group(1),
                    "理由": "直接使用形容词，删除模糊修饰",
                },
            ),
            (
                r"(?:似乎|好像|仿佛)(\w{2,6})",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "改为更确定的表述",
                    "修改后文本": f"可能是{m.group(1)}/表明{m.group(1)}",
                    "理由": "避免模糊的推测表达",
                },
            ),
        ]
        for pattern, suggest_func in hedge_patterns:
            for m in re.finditer(pattern, chunk):
                text = m.group(0)[:12]
                if 3 <= len(text) <= 12:
                    anno = suggest_func(m, text)
                    if isinstance(anno, dict):
                        annotations.append(anno)

        # ==================== 优化策略7：冗长表达 ====================
        # X之间的Y → X的Y
        redundant_patterns = [
            (
                r"(\w{2,6})之间(?:的)?",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "去掉冗余的'之间'",
                    "修改后文本": f"{m.group(1)}的",
                    "理由": "简化冗余的'之间'表达",
                },
            ),
            (
                r"(\w{2,4})(?:形式|方式|过程)的(\w{2,4})",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "去除冗余名词",
                    "修改后文本": f"{m.group(1)}{m.group(2)}",
                    "理由": "删除'形式/方式/过程'等冗余名词",
                },
            ),
        ]
        for pattern, suggest_func in redundant_patterns:
            for m in re.finditer(pattern, chunk):
                text = m.group(0)
                if 4 <= len(text) <= 15:
                    anno = suggest_func(m, text)
                    if isinstance(anno, dict):
                        annotations.append(anno)

        # ==================== 优化策略8：消极表述 ====================
        negative_patterns = [
            (
                r"(?:不|无|没有)(?:能|法|办法)(\w{2,4})",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "改为正面表述",
                    "修改后文本": f"难以{m.group(1)}/尚未{m.group(1)}",
                    "理由": "用正面表述替代否定形式",
                },
            ),
            (
                r"难以(\w{2,4})",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "改为更自然的表述",
                    "修改后文本": f"很难{m.group(1)}",
                    "理由": "'很难X'比'难以X'更自然",
                },
            ),
        ]
        for pattern, suggest_func in negative_patterns:
            for m in re.finditer(pattern, chunk):
                text = m.group(0)[:10]
                if 3 <= len(text) <= 10:
                    anno = suggest_func(m, text)
                    if isinstance(anno, dict):
                        annotations.append(anno)

        # ==================== 优化策略9：高频虚词提取 ====================
        freq_words = [
            (
                "能够",
                {
                    "修改建议": "删除冗余虚词",
                    "修改后文本": "（直接用具体动词）",
                    "理由": "删除虚词，直接表达动作",
                },
            ),
            (
                "可以",
                {
                    "修改建议": "根据语境优化",
                    "修改后文本": "（删除或换具体动词）",
                    "理由": "'可以'往往可以省略或用更具体的动词替代",
                },
            ),
            (
                "进一步",
                {
                    "修改建议": "改用更自然的表达",
                    "修改后文本": "进而/接着/随后",
                    "理由": "'进一步'的替代表达更自然",
                },
            ),
        ]
        for word, anno_template in freq_words:
            for match in re.finditer(re.escape(word), chunk):
                # 提取上下文
                start = max(0, match.start() - 3)
                end = min(len(chunk), match.end() + 5)
                context = chunk[start:end].replace("\n", "").strip()
                if len(context) > len(word) and len(context) <= 20:
                    annotations.append(
                        {
                            "原文片段": context[:15],
                            "修改建议": anno_template["修改建议"],
                            "修改后文本": anno_template["修改后文本"],
                            "理由": anno_template["理由"],
                        }
                    )
                    break  # 每个词最多提取一次上下文

        # ==================== 优化策略10：表达冗余检测 ====================
        redundancy_patterns = [
            (
                r"进行(\w{1,4})(处理|分析|研究|操作|观察|测试|验证)",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "去掉冗余的'进行'",
                    "修改后文本": f"{m.group(2)}{m.group(1)}",
                    "理由": "'进行'与后面的动词构成冗余",
                },
            ),
            (
                r"对(\w{1,4})的(分析|研究|处理|观察|理解|认识)",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "简化冗余结构",
                    "修改后文本": f"{m.group(2)}{m.group(1)}",
                    "理由": "去除'对...的'冗余结构",
                },
            ),
        ]
        for pattern, suggest_func in redundancy_patterns:
            for m in re.finditer(pattern, chunk):
                text = m.group(0)
                if 4 <= len(text) <= 12:
                    anno = suggest_func(m, text)
                    if isinstance(anno, dict):
                        annotations.append(anno)

        # ==================== 优化策略11：学术翻译常见问题 ====================
        academic_patterns = [
            # "呈现出" → "呈现"
            (
                r"呈现出(\w{2,4})",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "去掉冗余的'出'",
                    "修改后文本": f"呈现{m.group(1)}",
                    "理由": "'呈现出'中的'出'是冗余的",
                },
            ),
            # "显示出" → "显示"
            (
                r"显示出(\w{2,4})",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "去掉冗余的'出'",
                    "修改后文本": f"显示{m.group(1)}",
                    "理由": "'显示出'中的'出'是冗余的",
                },
            ),
            # "具有...性" → "有...性" 或直接用形容词
            (
                r"具有(\w{2,4})性",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "简化表达",
                    "修改后文本": f"有{m.group(1)}性",
                    "理由": "'具有'可简化为'有'",
                },
            ),
            # "具有...的特征" → "有...特征"
            (
                r"具有(\w{2,4})的特征",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "简化表达",
                    "修改后文本": f"有{m.group(1)}特征",
                    "理由": "简化冗余表达",
                },
            ),
            # "在...方面" 可能是冗余的
            (
                r"在(\w{2,4})方面",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "考虑删除",
                    "修改后文本": f"在{m.group(1)}上",
                    "理由": "'在...方面'可能冗余，考虑简化",
                },
            ),
            # "获得了...的" → "获得..."
            (
                r"获得了(\w{2,4})的",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "简化表达",
                    "修改后文本": f"获得{m.group(1)}",
                    "理由": "去掉冗余的'了...的'",
                },
            ),
            # "产生了...的" → "产生..."
            (
                r"产生了(\w{2,4})的",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "简化表达",
                    "修改后文本": f"产生{m.group(1)}",
                    "理由": "去掉冗余的'了...的'",
                },
            ),
        ]
        for pattern, suggest_func in academic_patterns:
            for m in re.finditer(pattern, chunk):
                text = m.group(0)
                if 3 <= len(text) <= 15:
                    anno = suggest_func(m, text)
                    if isinstance(anno, dict):
                        annotations.append(anno)

        # ==================== 优化策略12：常见 AI 套话 ====================
        ai_style_patterns = [
            (
                r"值得注意的是[，,]?",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "删除空泛的套话开场",
                    "修改后文本": "",
                    "理由": "这类开场没有新增信息，容易显得像 AI 表达",
                },
            ),
            (
                r"综上所述[，,]?",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "删除总结套话",
                    "修改后文本": "",
                    "理由": "结论性套话信息密度低，容易显得生硬",
                },
            ),
            (
                r"为(\w{2,8})提供了有力支撑",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "改成更实的表达",
                    "修改后文本": f"对{m.group(1)}有参考价值",
                    "理由": "避免空泛的结论套话",
                },
            ),
            (
                r"具有重要意义",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "改成更自然的评价",
                    "修改后文本": "很有价值",
                    "理由": "避免空泛评价，降低 AI 味",
                },
            ),
            (
                r"从(\w{2,6})角度来看",
                lambda m, t: {
                    "原文片段": m.group(0),
                    "修改建议": "简化视角引导语",
                    "修改后文本": f"从{m.group(1)}看",
                    "理由": "减少书面腔和 AI 高频句式",
                },
            ),
        ]
        for pattern, suggest_func in ai_style_patterns:
            for m in re.finditer(pattern, chunk):
                text = m.group(0)
                if 3 <= len(text) <= 20:
                    anno = suggest_func(m, text)
                    if isinstance(anno, dict):
                        annotations.append(anno)

        # ==================== 去重+均匀分布 ====================
        # 注：策略12（图标符号）、策略13（中英文混排空格）、策略14（格式标记）
        # 已移除——这些属于纯排版格式问题，不应通过内容批注处理。
        # 按策略分组统计，确保各类都有代表
        unique_annos = {}  # {原文片段: 完整标注}
        for anno in annotations:
            text = anno.get("原文片段", "").strip()
            # 放宽长度限制：2-25字符（之前是2-20）
            if text and 2 <= len(text) <= 25:
                if text not in unique_annos:
                    unique_annos[text] = anno  # 保留完整的标注对象

        # 转换为列表并按长度分布排序（实现均匀分布）
        unique_list = list(unique_annos.values())
        unique_list.sort(key=lambda x: len(x.get("原文片段", "")))

        # 大幅提升每个chunk的标注数量：50 → 80
        return unique_list[:80]

    @staticmethod
    def _split_into_chunks_by_paragraphs(
        formatted_content: str, max_chars: int
    ) -> List[str]:
        """按段落切分，保证每段不超过max_chars"""
        paragraphs = [p for p in formatted_content.split("\n\n") if p.strip()]
        chunks = []
        current = []
        current_len = 0

        for para in paragraphs:
            para_len = len(para) + 2  # 预留分隔符长度
            if current_len + para_len > max_chars and current:
                chunks.append("\n\n".join(current))
                current = [para]
                current_len = para_len
            else:
                current.append(para)
                current_len += para_len

        if current:
            chunks.append("\n\n".join(current))

        return chunks

    def analyze_for_annotation_chunked(
        self,
        file_path: str,
        user_requirement: str = "",
        model_id: Optional[str] = None,
        chunk_size: int = 5000,  # 增大分块大小，减少API调用次数 (原: 3000)
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        reference_context: Any = "",
        chunk_range: Optional[tuple[int, int]] = None,
    ) -> Dict[str, Any]:
        """
        分段处理大文档标注（适用于超大文档）

        Args:
            file_path: Word文档路径
            user_requirement: 用户需求
            model_id: LLM模型ID
            chunk_size: 每段最大字符数
            progress_callback: 进度回调函数 callback(current, total, message)

        Returns:
            合并后的标注结果
        """
        def _emit_progress(current_value, total_value, message_text, **extra):
            if not progress_callback:
                return
            try:
                progress_callback(current_value, total_value, message_text, **extra)
            except TypeError:
                progress_callback(current_value, total_value, message_text)

        def _build_partial_proposal(item: Dict[str, Any], *, chunk_index: int, global_chunk_index: int) -> Optional[Dict[str, Any]]:
            original_text = str(
                item.get("原文片段")
                or item.get("原文")
                or item.get("original")
                or ""
            ).strip()
            proposed_text = str(
                item.get("修改建议")
                or item.get("改为")
                or item.get("修改后文本")
                or item.get("modified")
                or ""
            ).strip()
            reason = str(
                item.get("修改原因")
                or item.get("原因")
                or item.get("reason")
                or ""
            ).strip()
            if not original_text or not proposed_text:
                return None
            preview = {
                "original_text": original_text,
                "proposed_text": proposed_text,
                "anchor_text": original_text,
                "chunk_index": chunk_index,
                "global_chunk_index": global_chunk_index,
                "source": "doc_review_stream",
                "preview_only": True,
            }
            if reason:
                preview["rationale"] = reason
                preview["reason"] = reason
            return preview

        effective_model_id = self._resolve_runtime_model_id(model_id)
        logger.info(f"[DocumentFeedback] 📖 读取大文档: {os.path.basename(file_path)}")

        # 读取文档
        doc_data = self.reader.read_document(file_path)
        if not doc_data.get("success"):
            return {"success": False, "error": f"读取文档失败: {doc_data.get('error')}"}

        formatted_content = self.reader.format_for_ai(doc_data)
        total_length = len(formatted_content)

        def _invoke_chunk_analyzer(**kwargs):
            import inspect

            analyzer = self._analyze_chunk_for_annotations
            try:
                sig = inspect.signature(analyzer)
            except (TypeError, ValueError):
                return analyzer(**kwargs)

            if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values()):
                return analyzer(**kwargs)

            filtered_kwargs = {
                key: value for key, value in kwargs.items() if key in sig.parameters
            }
            return analyzer(**filtered_kwargs)

        # 剥离文档元数据头（# 文档分析 ... ## 文档内容...）避免头部占据第一个chunk导致AI无法集中标注正文
        _content_marker = "## 文档内容"
        _cpos = formatted_content.find(_content_marker)
        if _cpos != -1:
            _cend = formatted_content.find("\n", _cpos)
            content_for_chunking = formatted_content[_cend + 1 :].lstrip("\n")
        else:
            content_for_chunking = formatted_content

        # 如果文档不大（含头部信息后仍在阈值内），直接单段AI标注（避免多段时连接不稳定导致部分失败）
        if total_length <= chunk_size:
            logger.info(
                f"[DocumentFeedback] 📄 文档较小({total_length}字符)，单段AI标注"
            )
            selected_model, _ = self._select_best_model(effective_model_id)

            def _single_chunk_status(detail: str) -> None:
                if detail:
                    _emit_progress(0.05, 1, detail)

            raw_annotations = _invoke_chunk_analyzer(
                chunk=formatted_content,  # 用完整格式化文本（含元数据头），与老多段路径 chunk1 行为一致
                doc_type=doc_data.get("type"),
                user_requirement=user_requirement,
                model_id=selected_model,
                chunk_index=1,
                total_chunks=1,
                full_doc_context=formatted_content,
                reference_context=reference_context,
                max_retries=2,  # 单段只重试一次（总计2次），配合240s超时保证成功率
                status_callback=_single_chunk_status,
            )
            _all_raw = raw_annotations or []
            _fb_items = [a for a in _all_raw if a.get("_koto_fallback_error")]
            anno_list = [a for a in _all_raw if not a.get("_koto_fallback_error")]
            _single_last_err = (
                _fb_items[0].get("_koto_fallback_error", "") if _fb_items else ""
            )
            if _fb_items:
                logger.warning(
                    f"[DocumentFeedback] ⚠️ 单段AI失败，已用本地兜底（{len(_fb_items)}条），均已过滤"
                )
                logger.error(
                    f"[DocumentFeedback] ❌ 单段API错误: {_single_last_err[:100]}"
                )

            # 安全兜底：AI 成功但返回空列表（文档可能无明显翻译腔但有其他问题），
            # 自动运行本地规则引擎确保用户始终获得建议反馈。
            _local_fallback_triggered = False
            if not anno_list and not _fb_items:
                logger.info("[DocumentFeedback] ℹ️ AI 返回空标注，启用本地规则兜底")
                anno_list = self._fallback_annotations_from_chunk(content_for_chunking)
                _local_fallback_triggered = bool(anno_list)
                logger.info(
                    f"[DocumentFeedback] 🔧 本地规则兜底生成 {len(anno_list)} 条标注"
                )

            return {
                "success": True,
                "file_path": file_path,
                "annotations": anno_list,
                "summary": f"单段AI标注，生成{len(anno_list)}条修改建议",
                "annotation_count": len(anno_list),
                "chunks_processed": 1,
                "fallback_used": len(_fb_items) > 0 and len(anno_list) == 0,
                "partial_fallback": len(_fb_items) > 0 and len(anno_list) > 0,
                "fallback_chunk_count": 1 if _fb_items else 0,
                "ai_chunk_count": (
                    0 if _local_fallback_triggered else (1 if anno_list else 0)
                ),
                "empty_result_fallback_chunk_count": (
                    1 if _local_fallback_triggered else 0
                ),
                "last_api_error": _single_last_err,
            }

        # 分段处理（按段落切分，保证不打断句子）
        logger.info(f"[DocumentFeedback] 📚 文档较大({total_length}字符)，分段处理")
        chunks = self._split_into_chunks_by_paragraphs(content_for_chunking, chunk_size)
        total_chunk_count = len(chunks)
        selected_chunk_start = 1
        selected_chunk_end = total_chunk_count
        if chunk_range:
            try:
                selected_chunk_start = max(1, int(chunk_range[0]))
                selected_chunk_end = min(total_chunk_count, int(chunk_range[1]))
            except (TypeError, ValueError, IndexError):
                selected_chunk_start = 1
                selected_chunk_end = total_chunk_count
        selected_chunk_items = [
            (index, chunks[index - 1])
            for index in range(selected_chunk_start, selected_chunk_end + 1)
            if 1 <= index <= total_chunk_count
        ]
        selected_chunk_count = len(selected_chunk_items)
        selected_content_chars = sum(len(chunk) for _, chunk in selected_chunk_items)
        if total_chunk_count > 0 and selected_chunk_count <= 0:
            return {
                "success": False,
                "error": "未找到可处理的文档分段",
                "file_path": file_path,
            }

        # AI禁用时，对每个chunk应用本地兜底
        if os.getenv("KOTO_DISABLE_AI") == "1":
            logger.warning(
                f"[DocumentFeedback] ⚠️ KOTO_DISABLE_AI=1，使用本地兜底标注（{selected_chunk_count or len(chunks)}段）"
            )

            # 第一轮：收集所有候选标注，同时统计每段的信息密度
            all_candidates = []  # [(原文片段, 修改建议, chunk_index, 优先级)]
            chunk_densities = []  # 记录每段的词汇密度

            logger.info(f"\n[DocumentFeedback] 📋 第一阶段：收集标注候选...\n")
            for i, (_, chunk) in enumerate(selected_chunk_items or list(enumerate(chunks, start=1))):
                chunk_fallback = self._fallback_annotations_from_chunk(chunk)
                density = len(chunk_fallback) / max(
                    1, len(chunk) / 1000
                )  # 每1000字的标注密度
                chunk_densities.append(density)

                for anno in chunk_fallback:
                    all_candidates.append(
                        {
                            "原文片段": anno.get("原文片段", ""),
                            "修改建议": anno.get("修改建议", ""),
                            "修改后文本": anno.get("修改后文本", ""),
                            "理由": anno.get("理由", ""),
                            "chunk_idx": i,
                            "density": density,
                        }
                    )

                progress = ((i + 1) / max(1, selected_chunk_count or len(chunks))) * 100
                bar_filled = int(10 * (i + 1) / max(1, selected_chunk_count or len(chunks)))
                bar = "█" * bar_filled + "░" * (10 - bar_filled)
                logger.info(
                    f"[DocumentFeedback] 🔍 [{bar}] {i+1}/{selected_chunk_count or len(chunks)} | 密度: {density:.1f}/千字"
                )

            # 计算平均密度和目标标注数
            avg_density = (
                sum(chunk_densities) / len(chunk_densities) if chunk_densities else 0
            )
            target_count = max(1, (selected_content_chars or total_length) // 1000 * 10)

            # 第二轮：按密度均衡选择标注
            logger.info(
                f"\n[DocumentFeedback] ⚖️ 第二阶段：均衡分布（目标{target_count}条）...\n"
            )

            # 分chunk选择，确保每段都有适当数量
            target_per_chunk = max(1, target_count // max(1, selected_chunk_count or len(chunks)))
            selected_annotations = []
            seen_texts = set()

            for chunk_idx in range(selected_chunk_count or len(chunks)):
                chunk_candidates = [
                    c for c in all_candidates if c["chunk_idx"] == chunk_idx
                ]

                # 去重（放宽长度限制）
                unique_candidates = {}
                for c in chunk_candidates:
                    text = c["原文片段"].strip()
                    if text and 2 <= len(text) <= 20:  # 放宽上限
                        if text not in unique_candidates:
                            unique_candidates[text] = c

                # 按密度调整该段应取的数量
                if chunk_idx < 2:
                    # 前两段词汇密集，多取
                    take_count = min(len(unique_candidates), target_per_chunk + 12)
                elif chunk_idx == 2:
                    # 第3段相对稀疏
                    take_count = min(len(unique_candidates), target_per_chunk + 8)
                elif chunk_idx == 3:
                    # 第4段密集
                    take_count = min(len(unique_candidates), target_per_chunk + 12)
                else:
                    # 第5段最后的都取
                    take_count = len(unique_candidates)

                # 选择该段的标注
                chunk_selection = list(unique_candidates.values())[:take_count]

                for anno in chunk_selection:
                    text = anno["原文片段"].strip()
                    if text not in seen_texts:
                        seen_texts.add(text)
                        selected_annotations.append(
                            {
                                "原文片段": anno["原文片段"],
                                "修改建议": anno["修改建议"],
                                "修改后文本": anno.get("修改后文本", ""),
                                "理由": anno.get("理由", ""),
                            }
                        )

                progress = ((chunk_idx + 1) / max(1, selected_chunk_count or len(chunks))) * 100
                bar_filled = int(20 * (chunk_idx + 1) / max(1, selected_chunk_count or len(chunks)))
                bar = "█" * bar_filled + "░" * (20 - bar_filled)
                logger.info(
                    f"[DocumentFeedback] 📊 [{bar}] {chunk_idx+1}/{selected_chunk_count or len(chunks)} ({progress:.0f}%) | "
                    + f"本段{len(chunk_selection)}条 | 累计{len(selected_annotations)}条"
                )

            # 如果标注数不足目标，补充
            if len(selected_annotations) < target_count:
                shortage = target_count - len(selected_annotations)
                for c in all_candidates:
                    if shortage <= 0:
                        break
                    text = c["原文片段"].strip()
                    if text not in seen_texts and 2 <= len(text) <= 25:  # 放宽限制
                        seen_texts.add(text)
                        selected_annotations.append(
                            {
                                "原文片段": text,
                                "修改建议": c["修改建议"],
                                "修改后文本": c.get("修改后文本", ""),
                                "理由": c.get("理由", ""),
                            }
                        )
                        shortage -= 1

            return {
                "success": True,
                "file_path": file_path,
                "annotations": selected_annotations[:target_count],
                "summary": f"本地兜底分{selected_chunk_count or len(chunks)}段生成{len(selected_annotations)}条标注（目标：{target_count}条）",
                "annotation_count": len(selected_annotations),
                "chunks_processed": selected_chunk_count or len(chunks),
                "chunk_densities": chunk_densities,
                "total_chunk_count": total_chunk_count or len(chunks),
                "selected_chunk_count": selected_chunk_count or len(chunks),
                "selected_chunk_start": selected_chunk_start,
                "selected_chunk_end": selected_chunk_end,
                # 兜底标记
                "fallback_used": True,
                "partial_fallback": False,
                "fallback_chunk_count": selected_chunk_count or len(chunks),
                "ai_chunk_count": 0,
                "last_api_error": "KOTO_DISABLE_AI=1（手动禁用AI）",
            }

        selected_model, available_models = self._select_best_model(effective_model_id)
        model_note = f"模型: {selected_model}"
        if selected_model != effective_model_id:
            model_note += f"（首选: {effective_model_id}，已自动降级）"
        model_table = self._format_model_table(available_models)

        # ── 开始前快速探测，确保所选模型实际可用（防止503退回兜底）──
        if self.client and os.getenv("KOTO_DISABLE_AI") != "1":
            _probed = self._probe_working_model(selected_model)
            if _probed is None:
                logger.warning(
                    f"[DocumentFeedback] ⚠️ 模型探测：所有候选均不可用，将全局使用本地兜底"
                )
            elif _probed != selected_model:
                logger.info(
                    f"[DocumentFeedback] 🔄 模型探测切换: {selected_model} → {_probed}"
                )
                selected_model = _probed
                model_note = f"模型: {selected_model}（首选 {effective_model_id} 不可用，已自动降级）"

        logger.info(
            f"[DocumentFeedback] 📦 文档较大({total_length}字符)，本次处理 {selected_chunk_count or len(chunks)} 段"
        )
        logger.info(
            f"[DocumentFeedback] 🎯 目标标注数: 约{max(1, (selected_content_chars or total_length)//1000*10)}条（每1000字10条）\n"
        )

        # 处理每一段（严格顺序执行，失败自动拆分重试）
        from collections import deque

        all_annotations = []
        seen_texts = set()
        processed = 0
        min_chunk_size = 800
        start_time = time.time()
        queue = deque(selected_chunk_items or list(enumerate(chunks, start=1)))
        total_chunks_initial = len(queue)
        # ── 兜底追踪 ──────────────────────────────────────────────────
        fallback_chunk_count = 0  # 完全使用本地正则兜底的分段数
        ai_chunk_count = 0  # 成功调用 AI 的分段数
        empty_result_fallback_chunk_count = 0  # AI 正常返回空结果时，本地规则补充的分段数
        last_api_error = ""  # 最近一次 API 失败错误信息
        _model_switched = False  # 是否已因 503 切换过模型（避免反复探测）

        while queue:
            global_chunk_index, chunk = queue.popleft()
            processed += 1
            current_total = processed + len(queue)

            elapsed = time.time() - start_time
            progress_pct = (processed / max(1, current_total)) * 100
            bar_length = 20
            bar_filled = int(bar_length * processed / max(1, current_total))
            progress_bar = "█" * bar_filled + "░" * (bar_length - bar_filled)

            logger.info(
                f"\n[DocumentFeedback] 📊 [{progress_bar}] {processed}/{current_total} ({progress_pct:.0f}%)"
            )
            logger.info(
                f"[DocumentFeedback] ⏱️ 已用时: {elapsed:.1f}s | 累计{len(all_annotations)}条标注 | 剩余{len(queue)}段"
            )

            def _chunk_status(detail: str) -> None:
                if not detail:
                    return
                _emit_progress(
                    max(0.05, processed - 0.95),
                    total_chunks_initial,
                    detail,
                )

            annotations = _invoke_chunk_analyzer(
                chunk=chunk,
                doc_type=doc_data.get("type"),
                user_requirement=user_requirement,
                model_id=selected_model,
                chunk_index=global_chunk_index,
                total_chunks=total_chunk_count or current_total,
                full_doc_context=formatted_content,
                reference_context=reference_context,
                max_retries=2,
                status_callback=_chunk_status,
            )

            if annotations is None:
                if len(chunk) <= min_chunk_size:
                    return {
                        "success": False,
                        "error": f"分段内容过小仍失败（{len(chunk)}字符），请检查网络或API配置后重试",
                        "file_path": file_path,
                    }
                sub_chunks = self._split_into_chunks_by_paragraphs(
                    chunk, max(min_chunk_size, len(chunk) // 2)
                )
                if len(sub_chunks) <= 1:
                    return {
                        "success": False,
                        "error": f"分段拆分失败，无法继续处理（{len(chunk)}字符）",
                        "file_path": file_path,
                    }
                for sc in reversed(sub_chunks):
                    queue.appendleft((global_chunk_index, sc))
                logger.info(
                    f"[DocumentFeedback] 🔁 分段失败，已拆分为{len(sub_chunks)}段重试"
                )
                continue

            empty_result_fallback_applied = False
            if not annotations:
                local_annotations = self._fallback_annotations_from_chunk(chunk)
                if local_annotations:
                    annotations = local_annotations
                    empty_result_fallback_applied = True
                    empty_result_fallback_chunk_count += 1
                    logger.info(
                        f"[DocumentFeedback] ℹ️ 第{processed}段 AI 未给出修改，已补充本地规则 {len(local_annotations)} 条"
                    )

            new_count = 0
            chunk_preview_items = []
            # ── 检测本段是否全部来自兜底（_koto_fallback_error 标记） ──
            fb_items = [a for a in annotations if a.get("_koto_fallback_error")]
            if fb_items:
                api_err = fb_items[0].get("_koto_fallback_error", "")
                if not last_api_error:
                    last_api_error = api_err
                if len(fb_items) == len(annotations):
                    fallback_chunk_count += 1
                    logger.error(
                        f"[DocumentFeedback] ⚠️ 第{processed}段全部使用本地兜底（API错误: {api_err[:60]}）"
                    )
                else:
                    # 部分兜底（理论上不会出现，保留以防万一）
                    fallback_chunk_count += 1

                # ── 503 触发模型切换：探测新可用模型，让后续分段继续用 AI ──
                if not _model_switched and any(a.get("_koto_503") for a in annotations):
                    _probed_switch = self._probe_working_model(selected_model)
                    if _probed_switch and _probed_switch != selected_model:
                        logger.info(
                            f"[DocumentFeedback] 🔄 503触发切换: {selected_model} → {_probed_switch}，将重新处理本段"
                        )
                        selected_model = _probed_switch
                        model_note = (
                            f"模型: {selected_model}（运行中自动从503过载模型切换）"
                        )
                        # 把当前段重新推回队列头，用新模型再跑一次
                        queue.appendleft((global_chunk_index, chunk))
                        processed -= 1  # 抵消本次 processed+=1，保持计数准确
                        fallback_chunk_count -= 1  # 本段还没真正兜底，撤回计数
                        _model_switched = True
                        continue
                    _model_switched = True  # 探测失败或模型未变，不再重试
            else:
                if annotations and not empty_result_fallback_applied:
                    ai_chunk_count += 1
            # 清除内部标记键，兜底标注直接丢弃（避免低质量regex内容污染输出）
            for ann in annotations:
                ann.pop("_koto_503", None)

            for item in annotations:
                if item.pop("_koto_fallback_error", None):
                    continue  # 跳过兜底标注，保持输出质量
                text = (item.get("原文片段") or "").strip()
                if text and text not in seen_texts:
                    seen_texts.add(text)
                    all_annotations.append(item)
                    new_count += 1
                    preview_item = _build_partial_proposal(
                        item,
                        chunk_index=processed,
                        global_chunk_index=global_chunk_index,
                    )
                    if preview_item:
                        chunk_preview_items.append(preview_item)

            if total_chunks_initial != (total_chunk_count or total_chunks_initial):
                msg = (
                    f"已完成本批 {processed}/{total_chunks_initial} 段"
                    f"（全局 {global_chunk_index}/{total_chunk_count}，本段+{new_count}条，累计{len(all_annotations)}条）"
                )
            else:
                msg = f"已完成 {processed}/{current_total} 段 (本段+{new_count}条，累计{len(all_annotations)}条)"
            logger.info(
                f"[DocumentFeedback] ✅ 第 {processed} 段完成（全局 {global_chunk_index}/{total_chunk_count or current_total}）: 新增 {new_count} 条标注"
            )
            _emit_progress(
                processed,
                total_chunks_initial,
                msg,
                chunk_status="completed",
                chunk_index=processed,
                chunk_total=total_chunks_initial,
                global_chunk_index=global_chunk_index,
                global_chunk_total=total_chunk_count or current_total,
                added_count=new_count,
                total_annotations=len(all_annotations),
                partial_proposals=chunk_preview_items[:3],
                target_path=file_path,
            )

        elapsed_total = time.time() - start_time

        logger.info(f"\n[DocumentFeedback] 🎉 分段处理完成")
        logger.info(f"[DocumentFeedback] ⏱️ 总耗时: {elapsed_total:.1f}s")
        logger.info(
            f"[DocumentFeedback] 📊 共生成{len(all_annotations)}条标注（目标: 约{total_length//1000*10}条）\n"
        )

        return {
            "success": True,
            "file_path": file_path,
            "annotations": all_annotations,
            "summary": (
                f"分段顺序处理（本批 {total_chunks_initial} 段，全局 {total_chunk_count or total_chunks_initial} 段），共生成{len(all_annotations)}条标注（耗时{elapsed_total:.1f}s）。"
                f"{' 其中 ' + str(empty_result_fallback_chunk_count) + ' 段在 AI 未给出修改时由本地规则补充。' if empty_result_fallback_chunk_count else ''}"
                f"{model_note}\n\n可用模型：\n{model_table}"
            ),
            "annotation_count": len(all_annotations),
            "chunks_processed": processed,
            "target_count": max(1, (selected_content_chars or total_length) // 1000 * 10),
            "total_chunk_count": total_chunk_count or total_chunks_initial,
            "selected_chunk_count": total_chunks_initial,
            "selected_chunk_start": selected_chunk_start,
            "selected_chunk_end": selected_chunk_end,
            # ── 兜底状态（供上层展示警告） ──────────────────────────
            "fallback_chunk_count": fallback_chunk_count,
            "ai_chunk_count": ai_chunk_count,
            "fallback_used": fallback_chunk_count > 0 and ai_chunk_count == 0,
            "partial_fallback": fallback_chunk_count > 0 and ai_chunk_count > 0,
            "empty_result_fallback_chunk_count": empty_result_fallback_chunk_count,
            "last_api_error": last_api_error,
        }

    def analyze_for_annotation(
        self,
        file_path: str,
        user_requirement: str = "",
        model_id: str = "deepseek-chat",
    ) -> Dict[str, Any]:
        """
        分析文档，生成标注格式的建议
        改进版：逐段标注，确保覆盖全文
        """
        logger.info(f"[DocumentFeedback] 📖 读取文档: {os.path.basename(file_path)}")

        # 第1步：读取文档
        doc_data = self.reader.read_document(file_path)
        if not doc_data.get("success"):
            return {"success": False, "error": f"读取文档失败: {doc_data.get('error')}"}

        # 第2步：格式化内容
        formatted_content = self.reader.format_for_ai(doc_data)

        # 第3步：按段落切分
        paragraphs = [p.strip() for p in formatted_content.split("\n\n") if p.strip()]
        logger.info(
            f"[DocumentFeedback] 📝 文档共 {len(paragraphs)} 段，使用 AI({model_id}) 逐段分析..."
        )
        # 注意：此函数仅处理小文档（由 analyze_for_annotation_chunked 路由而来）
        # 大文档已在 analyze_for_annotation_chunked 中按 chunk_size 分段，不应走此函数

        # 第4步：收集所有标注
        all_annotations: List[Dict[str, str]] = []
        seen_texts = set()

        # 如果没有AI客户端，直接用本地标注
        if not self.client:
            logger.warning(f"[DocumentFeedback] ⚠️ 未配置AI客户端，使用本地兜底标注")
            for idx, para in enumerate(paragraphs):
                if para:
                    annotations = self._fallback_annotations_from_chunk(para)
                    for ann in annotations:
                        text = (ann.get("原文片段") or "").strip()
                        if text and text not in seen_texts:
                            seen_texts.add(text)
                            all_annotations.append(ann)
            return {
                "success": True,
                "annotations": all_annotations[:100],
                "summary": f"未配置AI客户端，使用本地规则生成{len(all_annotations)}条标注建议",
                "fallback_used": True,
                "partial_fallback": False,
                "fallback_chunk_count": len(paragraphs),
                "ai_chunk_count": 0,
                "last_api_error": "未配置 Gemini 客户端（self.client is None）",
            }

        # 第5步：逐段用AI标注
        selected_model, available_models = self._select_best_model(model_id)
        _para_fb_count = 0  # 降级到本地兜底的段落数
        _para_ai_count = 0  # 成功调用AI的段落数
        _para_last_err = ""  # 最近段落API错误

        for para_idx, paragraph in enumerate(paragraphs):
            if not paragraph or len(paragraph) < 20:
                continue  # 跳过太短的段落

            logger.info(
                f"[DocumentFeedback] 🔄 分析第 {para_idx + 1}/{len(paragraphs)} 段..."
            )

            # 为每段构建Prompt
            para_prompt = self._build_annotation_prompt(
                doc_data.get("type"),
                paragraph,
                user_requirement + "\n\n请为这一段输出3-8条改进建议。",
            )

            try:
                from app.core.llm.provider_compat import types

                response = self.client.models.generate_content(
                    model=selected_model,
                    contents=para_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=2000,
                    ),
                )

                # 解析标注
                annotations = self._parse_annotation_response(response.text)
                _para_ai_count += 1
                for ann in annotations:
                    text = (ann.get("原文片段") or "").strip()
                    if text and text not in seen_texts and len(text) <= 30:
                        seen_texts.add(text)
                        all_annotations.append(ann)

                # 如果这段没有标注到问题，用本地兜底
                if not annotations:
                    fallback = self._fallback_annotations_from_chunk(paragraph)
                    for ann in fallback[:3]:  # 每段最多补充3条本地标注
                        text = (ann.get("原文片段") or "").strip()
                        if text and text not in seen_texts:
                            seen_texts.add(text)
                            all_annotations.append(ann)

            except Exception as e:
                _err_s = str(e)[:80]
                if not _para_last_err:
                    _para_last_err = _err_s
                _para_fb_count += 1
                logger.warning(
                    f"[DocumentFeedback] ⚠️ 第 {para_idx + 1} 段分析失败，使用本地标注: {_err_s}"
                )
                fallback = self._fallback_annotations_from_chunk(paragraph)
                for ann in fallback[:5]:  # 本地标注最多加5条
                    text = (ann.get("原文片段") or "").strip()
                    if text and text not in seen_texts:
                        seen_texts.add(text)
                        all_annotations.append(ann)

        # 第6步：返回结果
        summary = f"共标注 {len(all_annotations)} 处需要改进"
        logger.info(f"[DocumentFeedback] ✅ 分析完成，{summary}")

        return {
            "success": True,
            "annotations": all_annotations[:150],  # 限制到150条
            "summary": summary,
            "fallback_used": _para_fb_count > 0 and _para_ai_count == 0,
            "partial_fallback": _para_fb_count > 0 and _para_ai_count > 0,
            "fallback_chunk_count": _para_fb_count,
            "ai_chunk_count": _para_ai_count,
            "last_api_error": _para_last_err,
        }

    def _apply_docx_revisions(
        self,
        file_path: str,
        annotations: List[Dict[str, str]],
        *,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """Write AI review results back as native Word tracked revisions in place."""
        from web.track_changes_editor import TrackChangesEditor

        editor = TrackChangesEditor(author="Koto AI")
        result = editor.apply_tracked_changes(
            file_path,
            annotations,
            progress_callback=progress_callback,
        )
        if isinstance(result, dict):
            result.setdefault("original_file", file_path)
            result.setdefault("revised_file", file_path)
            result.setdefault("updated_in_place", True)
        return result

    def annotate_document(
        self, file_path: str, annotations: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        将审阅建议直接写回原 DOCX，生成原生修订。

        Args:
            file_path: 原Word文档路径
            annotations: 修订列表

        Returns:
            {
                "success": True,
                "original_file": "原文件路径",
                "revised_file": "写回后的文件路径",
                "applied": 成功应用数,
                "failed": 失败数
            }
        """
        logger.info("[DocumentFeedback] ✏️ 应用修订...")

        result = self._apply_docx_revisions(file_path, annotations)

        if result.get("success"):
            logger.info(
                f"[DocumentFeedback] ✅ 修订完成: {os.path.basename(result.get('revised_file', ''))}"
            )

        return result

    def full_annotation_loop_streaming(
        self,
        file_path: str,
        user_requirement: str = "",
        task_id: str = None,
        model_id: Optional[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        skill_prompt: str = "",
        reference_context: Any = "",
        chunk_range: Optional[tuple[int, int]] = None,
        batch_index: int = 0,
        total_batches: int = 0,
    ):
        """
        完整修订闭环（流式版本，支持进度反馈和任务取消）

        Args:
            file_path: Word文档路径
            user_requirement: 用户需求
            task_id: 任务ID（用于检查是否被取消）
            skill_prompt: 匹配到的审校类 Skill 专项要求（如商务审校、翻译质检等）

        Yields:
            {'stage': 'xxx', 'progress': 0-100, 'message': '...'}
        """
        # 如果有 Skill 专项要求，将其前置合并到 user_requirement，确保 AI 遵循专业维度
        if skill_prompt and skill_prompt.strip():
            _skill_block = skill_prompt.strip()
            if user_requirement and user_requirement.strip():
                user_requirement = (
                    _skill_block + f"\n\n## 用户具体需求\n{user_requirement.strip()}"
                )
            else:
                user_requirement = _skill_block
        from web.task_scheduler import check_task_cancelled

        effective_model_id = self._resolve_runtime_model_id(model_id)

        def _is_cancelled() -> bool:
            try:
                if cancel_check and cancel_check():
                    return True
            except Exception as _cc_err:
                logger.debug("[DocAnnotator] cancel_check 调用失败: %s", _cc_err)
            return bool(task_id and check_task_cancelled(task_id))

        logger.info("=" * 60)
        logger.info("🔄 启动文档自动修订系统（完整闭环-流式）")
        logger.info("=" * 60)

        # ===== Stage 1: 读取文档 =====
        if _is_cancelled():
            yield {
                "stage": "cancelled",
                "progress": 0,
                "message": "⏸️ 任务已被取消",
                "detail": "",
            }
            return

        yield {
            "stage": "reading",
            "progress": 5,
            "message": f"📖 正在读取文档: {os.path.basename(file_path)}",
            "detail": "解析Word文件结构",
        }

        try:
            doc_data = self.reader.read_document(file_path)
            if not doc_data.get("success"):
                yield {
                    "stage": "error",
                    "progress": 0,
                    "message": f'❌ 读取失败: {doc_data.get("error")}',
                    "detail": "",
                }
                return

            total_paras = len(doc_data.get("paragraphs", []))
            total_chars = sum(
                len(p.get("text", "")) for p in doc_data.get("paragraphs", [])
            )

            yield {
                "stage": "reading_complete",
                "progress": 10,
                "message": "✅ 文档读取完成",
                "detail": f"{total_paras} 段，{total_chars} 字",
            }
        except Exception as e:
            yield {
                "stage": "error",
                "progress": 0,
                "message": f"❌ 读取错误: {str(e)[:100]}",
                "detail": "",
            }
            return

        # ===== Stage 2: 分析生成修订建议 =====
        if _is_cancelled():
            yield {
                "stage": "cancelled",
                "progress": 0,
                "message": "⏸️ 任务已被取消",
                "detail": "分析前中断",
            }
            return

        yield {
            "stage": "analyzing",
            "progress": 15,
            "message": f"🤖 正在分析文档...",
            "detail": (
                f"使用 AI({effective_model_id}) 检查第 {chunk_range[0]}-{chunk_range[1]} 段（共 {total_paras} 段，第 {batch_index}/{total_batches} 批）"
                if chunk_range and batch_index > 0 and total_batches > 0
                else f"使用 AI({effective_model_id}) 检查 {total_paras} 段文本"
            ),
        }

        if self.client and os.getenv("KOTO_DISABLE_AI") != "1":
            chunk_size = (
                self._env_int("KOTO_DOC_REVIEW_LOCAL_CHUNK_SIZE", 2400, minimum=1200)
                if self._is_local_client()
                else 4000
            )
        else:
            chunk_size = 10000

        # ===== 🔌 AI 连通性预检 —— 在开始分段之前快速验证 API 可用，503时自动切模型 =====
        _preflight_error = ""
        if self.client and os.getenv("KOTO_DISABLE_AI") != "1":
            _probed_model = self._probe_working_model(effective_model_id)
            if _probed_model is None:
                # 所有候选模型均不可用
                _preflight_error = "所有可用模型当前均不可用（503或其他错误）"
                logger.error(
                    f"[DocumentFeedback] ❌ AI 预检：所有模型不可用，将使用本地规则兜底"
                )
                yield {
                    "stage": "warning",
                    "progress": 16,
                    "message": "⚠️ Gemini API 暂时全部不可用，将使用本地规则兜底（质量有限）",
                    "detail": "建议稍后重试",
                }
            elif _probed_model != effective_model_id:
                logger.info(
                    f"[DocumentFeedback] 🔄 预检：{effective_model_id} 过载，切换为 {_probed_model}"
                )
                yield {
                    "stage": "info",
                    "progress": 16,
                    "message": f"🔄 {effective_model_id} 当前负载过高，已自动切换到 {_probed_model}",
                    "detail": "系统自动选择可用模型继续任务",
                }
                effective_model_id = _probed_model
            else:
                logger.info(f"[DocumentFeedback] ✅ AI 预检通过: {effective_model_id}")
        # ───────────────────────────────────────────────────────────────────────

        # ===== 使用线程 + Queue 实现真正实时进度推送 =====
        import queue as queue_module
        import threading

        progress_q = queue_module.Queue()
        result_holder = {"result": None, "error": None}
        last_yield_time = [0.0]

        _SENTINEL = object()  # 线程完成的标记

        def on_analysis_progress(current, total, message, **meta):
            """进度回调 — 在分析线程中调用，通过 Queue 发送到主线程"""
            progress = 15 + int((current / max(1, total)) * 35)
            current_time = time.time()
            force_emit = str(meta.get("chunk_status") or "").strip().lower() == "completed"
            if force_emit or current_time - last_yield_time[0] >= 0.3:
                last_yield_time[0] = current_time
                event = {
                    "stage": "analyzing",
                    "progress": progress,
                    "message": f"🤖 {message}",
                    "detail": message,
                }
                for key in (
                    "chunk_status",
                    "chunk_index",
                    "chunk_total",
                    "global_chunk_index",
                    "global_chunk_total",
                    "added_count",
                    "total_annotations",
                    "target_path",
                ):
                    value = meta.get(key)
                    if value not in (None, "", [], {}):
                        event[key] = value
                partial_proposals = meta.get("partial_proposals")
                if isinstance(partial_proposals, list) and partial_proposals:
                    event["partial_proposals"] = [
                        dict(item) for item in partial_proposals if isinstance(item, dict)
                    ]
                progress_q.put(event)

        def run_analysis():
            """在后台线程中运行分析"""
            try:
                result_holder["result"] = self.analyze_for_annotation_chunked(
                    file_path,
                    user_requirement,
                    model_id=effective_model_id,
                    chunk_size=chunk_size,
                    progress_callback=on_analysis_progress,
                    reference_context=reference_context,
                    chunk_range=chunk_range,
                )
            except Exception as e:
                result_holder["error"] = e
            finally:
                progress_q.put(_SENTINEL)

        analysis_thread = threading.Thread(target=run_analysis, daemon=True)
        analysis_thread.start()

        # 主线程：实时从 Queue 取出进度事件并 yield（SSE 推送给浏览器）
        heartbeat_interval = 3.0  # 每3秒发一次心跳防止 SSE 超时
        last_heartbeat = time.time()
        current_progress = [15]  # 跟踪当前进度，防止心跳数字回退
        current_detail = [
            (
                f"使用 AI({effective_model_id}) 检查第 {chunk_range[0]}-{chunk_range[1]} 段（共 {total_paras} 段，第 {batch_index}/{total_batches} 批）"
                if chunk_range and batch_index > 0 and total_batches > 0
                else f"使用 AI({effective_model_id}) 检查 {total_paras} 段文本"
            )
        ]

        try:
            while True:
                if _is_cancelled():
                    yield {
                        "stage": "cancelled",
                        "progress": 0,
                        "message": "⏸️ 任务已被取消",
                        "detail": "分析过程中中断",
                    }
                    return
                try:
                    evt = progress_q.get(timeout=1.0)
                    if evt is _SENTINEL:
                        break
                    current_progress[0] = max(
                        current_progress[0], evt.get("progress", 15)
                    )
                    evt_detail = str(evt.get("detail") or evt.get("message") or "").strip()
                    if evt_detail:
                        current_detail[0] = evt_detail
                    yield evt
                    last_heartbeat = time.time()
                except queue_module.Empty:
                    if not analysis_thread.is_alive():
                        break
                    # 发送心跳防止浏览器 SSE 超时断连
                    now = time.time()
                    if now - last_heartbeat >= heartbeat_interval:
                        last_heartbeat = now
                        yield {
                            "stage": "analyzing",
                            "progress": current_progress[0],
                            "message": "🤖 正在分析文档...",
                            "detail": f"{current_detail[0]}；等待 AI 响应中..." if current_detail[0] else "等待 AI 响应中...",
                        }

            analysis_thread.join(timeout=10)

            # 检查线程执行结果
            if result_holder["error"]:
                raise result_holder["error"]

            analysis_result = result_holder["result"]

            if not analysis_result or not analysis_result.get("success"):
                error_msg = (analysis_result or {}).get("error", "未知错误")
                yield {
                    "stage": "error",
                    "progress": 0,
                    "message": f"❌ 分析失败: {error_msg}",
                    "detail": "",
                }
                return

            annotations = analysis_result.get("annotations", [])

            # ── 兜底检测：若 AI 全部/部分失败，立即向前端推送明显警告 ──
            _fallback_used = analysis_result.get("fallback_used", False)
            _partial_fallback = analysis_result.get("partial_fallback", False)
            _last_api_error = analysis_result.get("last_api_error", "")
            _fb_chunks = analysis_result.get("fallback_chunk_count", 0)
            _ai_chunks = analysis_result.get("ai_chunk_count", 0)
            _empty_ai_fb_chunks = analysis_result.get("empty_result_fallback_chunk_count", 0)

            if _fallback_used or _partial_fallback:
                _fb_label = (
                    "全部"
                    if _fallback_used
                    else f"{_fb_chunks}/{_fb_chunks+_ai_chunks}"
                )
                _err_hint = (
                    f" `{_last_api_error[:80]}`"
                    if _last_api_error
                    else " 请检查 API Key 与模型配置"
                )
                yield {
                    "stage": "warning",
                    "progress": 52,
                    "message": f"⚠️ AI 分析未成功（{_fb_label}分段使用本地规则兜底）",
                    "detail": f"API 错误:{_err_hint}",
                }
                logger.error(
                    f"[DocumentFeedback] ⚠️ 兜底警告已推送: {_fb_label}分段，最近错误: {_last_api_error[:60]}"
                )

            if _empty_ai_fb_chunks:
                yield {
                    "stage": "info",
                    "progress": 52,
                    "message": f"ℹ️ {_empty_ai_fb_chunks} 个分段未返回修改，已补充规则建议",
                    "detail": "当 AI 未返回可直接写回的修改时，系统会补充固定表达问题的规则建议。",
                }

            yield {
                "stage": "analysis_complete",
                "progress": 50,
                "message": f"✅ 分析完成",
                "detail": f"找到 {len(annotations)} 处修改",
            }

        except Exception as e:
            yield {
                "stage": "error",
                "progress": 0,
                "message": f"❌ 分析错误: {str(e)[:100]}",
                "detail": "",
            }
            return

        if len(annotations) == 0:
            yield {
                "stage": "complete",
                "progress": 100,
                "message": "✅ 分析完成，未找到需要修改的地方",
                "detail": "",
                "result": {
                    "success": True,
                    "message": "未找到修改点",
                    "original_file": file_path,
                    "applied": 0,
                },
            }
            return

        # ===== Stage 3: 应用修订到文档 =====
        if _is_cancelled():
            yield {
                "stage": "cancelled",
                "progress": 0,
                "message": "⏸️ 任务已被取消",
                "detail": "应用修改前中断",
            }
            return

        yield {
            "stage": "applying",
            "progress": 55,
            "message": "📝 正在写回原 DOCX...",
            "detail": f"将直接写回原文，共 {len(annotations)} 处",
        }

        try:
            revised_file = file_path

            # 再次检查取消
            if _is_cancelled():
                yield {
                    "stage": "cancelled",
                    "progress": 0,
                    "message": "⏸️ 任务已被取消",
                    "detail": "应用修改过程中中断",
                }
                return

            yield {
                "stage": "applying",
                "progress": 60,
                "message": "📝 正在将修订写回原文...",
                "detail": f"共 {len(annotations)} 项修订",
            }

            # 文件助手主链路统一写回原生修订，不再混入批注气泡。
            apply_q = queue_module.Queue()
            apply_result_holder = {"result": None, "error": None}

            def on_apply_progress(current, total, status, detail, **meta):
                pct = 60 + int((current / total) * 25) if total > 0 else 60
                status_text = {
                    "start": "准备写入修订",
                    "processing": "正在写入修订",
                    "success": "已完成当前修订",
                    "saved": "已写回原文",
                    "failed": "写回失败",
                }.get(str(status or "").strip().lower(), str(status or "正在写回").strip() or "正在写回")
                event = {
                    "stage": "applying",
                    "progress": pct,
                    "message": f"📝 {status_text}",
                    "detail": detail,
                }
                if meta.get("file_updated"):
                    event.update(
                        {
                            "file_updated": True,
                            "path": str(meta.get("file_path") or revised_file),
                            "file_path": str(meta.get("file_path") or revised_file),
                            "supported": True,
                            "applied": int(meta.get("applied") or current or 0),
                            "updated_in_place": bool(meta.get("updated_in_place", True)),
                        }
                    )
                apply_q.put(event)

            def run_apply():
                try:
                    apply_result_holder["result"] = self._apply_docx_revisions(
                        revised_file,
                        annotations,
                        progress_callback=on_apply_progress,
                    )
                except Exception as e:
                    apply_result_holder["error"] = e
                finally:
                    apply_q.put(_SENTINEL)

            apply_thread = threading.Thread(target=run_apply, daemon=True)
            apply_thread.start()

            while True:
                if _is_cancelled():
                    yield {
                        "stage": "cancelled",
                        "progress": 0,
                        "message": "⏸️ 任务已被取消",
                        "detail": "应用修改过程中中断",
                    }
                    return
                try:
                    evt = apply_q.get(timeout=1.0)
                    if evt is _SENTINEL:
                        break
                    yield evt
                except queue_module.Empty:
                    if not apply_thread.is_alive():
                        break

            apply_thread.join(timeout=10)

            if apply_result_holder["error"]:
                raise apply_result_holder["error"]

            edit_result = apply_result_holder["result"]

            applied = edit_result.get("applied", 0)
            failed = edit_result.get("failed", 0)

            yield {
                "stage": "applying_complete",
                "progress": 85,
                "message": f"✅ 原文写回完成",
                "detail": f"成功: {applied}, 失败: {failed}",
            }

        except Exception as e:
            import traceback

            yield {
                "stage": "error",
                "progress": 0,
                "message": f"❌ 应用错误: {str(e)[:100]}",
                "detail": traceback.format_exc()[:200],
            }
            return

        # ===== Stage 4: 完成 =====

        # 添加到文件网络索引
        try:
            from web.processed_file_network import get_file_network

            file_network = get_file_network()
            file_network.record_processing(
                file_path=file_path,
                operation="annotate",
                changes_count=applied,
                output_file=revised_file,
                status="success" if applied > 0 else "partial",
                details={
                    "requirement": user_requirement,
                    "total_annotations": len(annotations),
                    "applied": applied,
                    "failed": failed,
                },
            )
        except Exception as e:
            logger.info(f"[DocumentFeedback] 文件网络索引记录失败: {e}")

        yield {
            "stage": "complete",
            "progress": 100,
            "message": "✅ 文档修改完成！",
            "detail": f"修改位置: {applied}，定位失败: {failed}",
            "result": {
                "success": edit_result.get("success", False),
                "original_file": file_path,
                "revised_file": revised_file,
                "updated_in_place": True,
                "applied": applied,
                "failed": failed,
                "total": len(annotations),
                "analysis_summary": analysis_result.get("summary"),
                # 兜底状态，供 app.py 展示警告
                "fallback_used": analysis_result.get("fallback_used", False),
                "partial_fallback": analysis_result.get("partial_fallback", False),
                "last_api_error": analysis_result.get("last_api_error", ""),
                "fallback_chunk_count": analysis_result.get("fallback_chunk_count", 0),
                "ai_chunk_count": analysis_result.get("ai_chunk_count", 0),
                "empty_result_fallback_chunk_count": analysis_result.get("empty_result_fallback_chunk_count", 0),
            },
        }

    def full_annotation_loop(
        self,
        file_path: str,
        user_requirement: str = "",
        model_id: Optional[str] = None,
        reference_context: Any = "",
    ) -> Dict[str, Any]:
        """
        完整修订闭环：读取 -> 分析 -> 写回

        Args:
            file_path: Word文档路径
            user_requirement: 用户需求

        Returns:
            {
                "success": True,
                "original_file": "...",
                "revised_file": "...",
                "applied": 5,
                "failed": 1
            }
        """
        logger.info("=" * 60)
        logger.info("🔄 启动文档自动修订系统（同步兼容包装）")
        logger.info("=" * 60)
        final_error = ""
        for progress_event in self.full_annotation_loop_streaming(
            file_path,
            user_requirement,
            model_id=model_id,
            reference_context=reference_context,
        ):
            stage = str(progress_event.get("stage") or "").strip().lower()
            if stage == "complete":
                result = progress_event.get("result")
                if isinstance(result, dict):
                    return result
                return {
                    "success": False,
                    "error": "文档修订完成但未返回结果。",
                    "original_file": file_path,
                }
            if stage == "cancelled":
                return {
                    "success": False,
                    "cancelled": True,
                    "message": str(progress_event.get("message") or progress_event.get("detail") or "文档修订任务已取消").strip() or "文档修订任务已取消",
                    "original_file": file_path,
                }
            if stage == "error":
                final_error = str(progress_event.get("message") or progress_event.get("detail") or "文档修订失败").strip()
                return {
                    "success": False,
                    "error": final_error or "文档修订失败",
                    "original_file": file_path,
                }

        return {
            "success": False,
            "error": final_error or "文档修订失败",
            "original_file": file_path,
        }

    @staticmethod
    def _strip_markdown_for_annotation(text: str) -> str:
        """将 format_for_ai 输出的 Markdown 标记还原为纯文本，确保 AI 输出的 `原文`
        能精确匹配 Word 文档中的实际文字（不含 #/*/- 等 Markdown 标记）。"""
        import re

        lines = []
        for line in text.split("\n"):
            # 去掉标题前缀 #### / ### / ## / #
            line = re.sub(r"^#{1,6}\s+", "", line)
            # 去掉列表符 - 或 * 开头（只去符号，保留文字）
            line = re.sub(r"^[-*]\s+", "", line)
            # 去掉引用符 >
            line = re.sub(r"^>\s*", "", line)
            # 去掉行内加粗/斜体 **text** / *text*
            line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
            line = re.sub(r"\*(.+?)\*", r"\1", line)
            # 去掉"← [此段落有格式变化]"标注
            line = re.sub(r"\s*←\s*\[此段落有格式变化\]", "", line)
            # 去掉颜色标记 [text](颜色:RRGGBB)
            line = re.sub(r"\[(.+?)\]\(颜色:[0-9A-Fa-f]+\)", r"\1", line)
            # 去掉表格/图片占位符行（以 [📊 或 [📷 开头）
            if re.match(r"^\[(?:📊|📷)", line.strip()):
                continue
            lines.append(line)
        return "\n".join(lines)

    def _build_annotation_prompt(
        self,
        doc_type: str,
        formatted_content: str,
        user_requirement: str,
        full_doc_context: str = "",
        reference_context: Any = "",
    ) -> str:
        """构建用于标注的AI Prompt - 精准修改版，生成可直接替换的文本修订"""

        # 将 markdown 格式化内容还原为纯文本，确保 AI 的 `原文` 可精确匹配 Word 实际文字
        plain_content = self._strip_markdown_for_annotation(formatted_content)

        # 统计段落数，用于指导 AI 均匀分布
        paragraphs = [p.strip() for p in plain_content.split("\n\n") if p.strip()]
        para_count = len(paragraphs)

        # 判断文档类型：简历 vs 学术文档
        _req_lower = (user_requirement or "").lower()
        _is_resume = any(
            kw in _req_lower
            for kw in [
                "简历",
                "求职",
                "resume",
                " cv",
                "校招",
                "秋招",
                "春招",
                "应聘",
                "招聘",
                "面试",
            ]
        )

        if _is_resume:
            persona = "你是一名资深HR简历顾问兼职场写作专家"
            task_intro = f"请逐段审阅此简历片段（共{para_count}段），以求职竞争力为核心进行直接修改。"
            default_req = "优化简历表达，使成果描述更量化、动词更有力、语言更精炼，突出候选人竞争优势"
            type_specific_tips = """
### 简历专项要求：
- **量化成果**：能加数字就加（提升XX%、负责XX人、完成XX个）；没有数据则用具体动词描述结果。
- **强动词开头**：每条经历用动词开头（主导/搭建/优化/实现/设计/推进），去掉"负责了解参与"这类弱动词。
- **删冗余**：去掉"主要负责"、"参与了"、"帮助团队"等废话铺垫。
- **保留专业术语**：技术栈名称（Python/MySQL/React等）、公司名、学校名、证书名**禁止修改**。
- **保留原有结构**：不新增板块，不建议调整顺序，只改文字表述。"""
        else:
            persona = "你是一名资深中文编辑和写作顾问"
            task_intro = f"请逐段审阅此{doc_type.upper()}文档片段（共{para_count}段），基于全文背景进行直接修改。"
            default_req = "对文档进行全面编辑润色，包括：纠正翻译腔、消除官话套话、精简冗余表述、提升表达清晰度和逻辑连贯性"
            type_specific_tips = """
### 中文文档专项审查维度（请全面扫描，不局限于翻译问题）：
- **官话套话**：删除"切实""扎实推进""稳步推进""持续深化""大力推进"等空洞套话，用具体动作替代。
- **重复冗余**：找出同义重复（"提升和改善"、"推进和落实"）、无意义的修饰词（"进一步""不断地""积极"）。
- **抽象模糊**：将"高质量发展""新质生产力""创新驱动"等空泛表述换成有具体含义的说法（如果语境允许）。
- **翻译腔/书面腔**：纠正不自然的书面体（"进行了XXX"→"做了XXX"，"对XXX进行XXX"→直接动词）。
- **句式臃肿**：拆分超长句子，删除"的"字长串（"对于XXX的XXX的XXX"）。
- **逻辑断层**：标注句间逻辑不通或推论不当之处。"""

        # 如果提供了全文背景，限制长度以免超限(保留开头结尾和目录大纲信息)
        global_ctx_prompt = ""
        if full_doc_context and len(full_doc_context) > len(plain_content) * 1.5:
            # 只有当背景明显长于当前片段时才包含背景，避免第一段自我重复干扰
            plain_ctx = self._strip_markdown_for_annotation(full_doc_context)
            ctx_len = len(plain_ctx)
            if ctx_len > 30000:
                # 截取开头3000字和结尾2000字作为背景
                global_ctx_prompt = f"""
## 全文背景参考（节选，纯文本）
...（前文忽略）
{plain_ctx[:3000]}
...
{plain_ctx[-2000:]}
"""
            else:
                global_ctx_prompt = f"""
## 全文完整背景（供连贯性分析参考，纯文本）
{plain_ctx}
"""

        reference_prompt = ""
        reference_text = self._select_reference_context(reference_context)
        if reference_text:
            if len(reference_text) > 16000:
                reference_text = reference_text[:15997] + "..."
            reference_prompt = f"""
## 参考原文（按 PDF 页窗口抽取，仅供忠实对照，不要直接改写原文）
{reference_text}
"""

        base_prompt = f"""{persona}。{task_intro}

{global_ctx_prompt}

{reference_prompt}

## 当前待审阅文档片段（共{para_count}段，纯文本，标题/粗体等格式已剥离）
{plain_content}

## 任务要求
{user_requirement if user_requirement else default_req}
{type_specific_tips}

## 🚫 绝对不处理（格式问题，请直接跳过）：
- 中英文之间是否需要加空格（如"Python应用"不需要改成"Python 应用"）
- 字母大小写（除明显错误的专有名词外）
- 列表符号、编号格式（●、•、1.、①等保持原样）
- 粗体、斜体、下划线等排版样式
- 标点符号（除非有严重语义错误）
- 数字与单位的间距格式

## ⚠️ 重要写作指令：
1. **少废话，多干活**：不要给出"建议修改..."的空洞批注，直接提供修改后的文本。
2. **逐段覆盖（关键！）**：必须审阅文档中**每一段**，从第一段到最后一段，不得跳过任何段落，每段至少尝试找出1处问题。
3. **精准定位**：`原文` 字段必须与文档片段中显示的**纯文本**完全一致，逐字复制，不增删任何字符。
4. **最小原文范围（最关键！）**：`原文` 必须是**需要改动的最小文本单元**。规则如下：
   - 只改一个词 → `原文` 只填那个词（2-6字）
   - 只改一个短语 → `原文` 只填那个短语（5-15字）
   - 整句有问题 → `原文` 填那整句（最多30字）
   - **严禁把整段文字都放进 `原文`**（超过40字的 `原文` 几乎都是错误用法）
   - 正常标注中，80%应该是片段级别（≤15字），20%是句子级别（≤35字）
5. **适度修改**：只修改真正有语病、翻译腔、逻辑不通顺或生硬的地方。不要为了修改而修改。
6. **禁止批注式输出**：`改为` 必须是可以直接替换原文的最终文本，不要写“建议：”“批注：”“可改为：”等前缀。

## ⚠️ 去AI味 — 必须严格遵守的语言风格：
你改写后的文本**绝对不能有AI味**。以下是具体禁令：
- **禁用破折号**（——）来做解释或插入语，改用逗号、括号或拆成两句。
- **禁用引号强调**：不要用"XXX"来强调概念，直接写出来。
- **禁用排比堆砌**：不要把三个以上并列短语排在一起，像"提升了效率、优化了流程、增强了体验"这种要砍掉。
- **禁用AI高频套话**：值得注意的是、综上所述、不仅...而且...、从...角度来看、具有重要意义、提供了有力支撑。
- **少用"进行""实现""开展"等万能动词**，换成具体的动作。
- **句子要短**，一句话说一件事。

### 示例（错误 vs 正确）：
- ❌ "该方法在提升效率、优化流程、增强体验等方面具有重要意义"
- ✅ "该方法能有效提升工作效率"
- ❌ "值得注意的是，这一发现为后续研究提供了有力支撑"
- ✅ "这一发现对后续研究有参考价值"

## 修订类型

### 类型A：术语与用词修正（直接替换）
纠正不地道的表达、口语化词汇、翻译腔。
*   原文="被广泛地进行使用" -> 改为="已广泛使用"
*   原文="在这个图像中" -> 改为="该图像"

### 类型B：句子重写与润色（直接替换）
遇到长难句、逻辑不通顺的句子，**直接重写**整句。用短句，少用从句。
*   原文="[选中拗口的整句]" -> 改为="[重写后的简洁句子]"
*   ⚠️ **注意**：选中文本不要超过一段，最好以句为单位。

### 类型C：无法安全直改的问题（直接跳过）
如果某处问题必须依赖大段重组、补充上下文或结构调整，且无法对当前原文做安全替换，请直接跳过。
*   禁止输出 `建议：...`、`批注：...`、`可考虑...` 这类无法直接写回原文的内容。

## 输出格式
只返回JSON数组，禁止其他文字：
[
  {{"原文": "进行使用", "改为": "使用", "原因": "精简"}},
  {{"原文": "在这个图像中", "改为": "该图像", "原因": "翻译腔"}},
  {{"原文": "研究者们主要聚焦于", "改为": "研究主要集中在", "原因": "去冗余"}},
  {{"原文": "这为后续研究提供了有力支撑", "改为": "这对后续研究有参考价值", "原因": "去套话"}}
]

❌ 错误示例（`原文` 过长，超过整段）：
{{"原文": "在当前数字艺术发展的主流实践中，研究者们主要聚焦于三个核心方向：技术驱动的创新探索、社会文化的批判性介入以及跨学科的融合实践。", "改为": "..."}}
✅ 应拆分为多条短标注，每条只针对一个问题词组。
"""
        return base_prompt

    def _select_reference_context(
        self,
        reference_context: Any,
        *,
        chunk_index: int = 1,
        total_chunks: int = 1,
    ) -> str:
        """Select the most relevant PDF reference window(s) for the current DOCX chunk."""
        if not reference_context:
            return ""

        if isinstance(reference_context, str):
            return reference_context.strip()

        if not isinstance(reference_context, list):
            return str(reference_context).strip()

        blocks = [str(item or "").strip() for item in reference_context if str(item or "").strip()]
        if not blocks:
            return ""
        if len(blocks) <= 3:
            return "\n\n".join(blocks)

        normalized_index = max(1, int(chunk_index or 1))
        normalized_total = max(1, int(total_chunks or 1))
        if normalized_total <= 1:
            return "\n\n".join(blocks[:3])

        ratio = (normalized_index - 1) / max(1, normalized_total - 1)
        center = int(round(ratio * max(0, len(blocks) - 1)))
        start = max(0, center - 1)
        end = min(len(blocks), center + 2)
        return "\n\n".join(blocks[start:end])

    def _parse_annotation_response(self, ai_response: str) -> List[Dict[str, str]]:
        """解析AI响应为标注格式"""
        import json
        import re

        def _clean_original(text: str) -> str:
            """清理 `原文` 字段：去除 AI 意外输出的 Markdown 标记，确保可精确匹配原文。"""
            # 去掉行首 Markdown 符号（##, -, *, >）
            text = re.sub(r"^#{1,6}\s+", "", text.strip())
            text = re.sub(r"^[-*]\s+", "", text)
            text = re.sub(r"^>\s*", "", text)
            # 去掉行内加粗/斜体
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
            text = re.sub(r"\*(.+?)\*", r"\1", text)
            # 去掉格式变化标注
            text = re.sub(r"\s*←\s*\[此段落有格式变化\]", "", text)
            # 去掉颜色标记
            text = re.sub(r"\[(.+?)\]\(颜色:[0-9A-Fa-f]+\)", r"\1", text)
            return text.strip()

        try:
            # 尝试提取JSON数组
            json_match = re.search(r"```json\s*(\[.*?\])\s*```", ai_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # 尝试直接找数组
                json_match = re.search(r"\[.*\]", ai_response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = ai_response

            data = json.loads(json_str)

            # 验证格式
            if isinstance(data, list):
                valid_annotations = []
                for item in data:
                    if isinstance(item, dict):
                        # 提取原文
                        original = (
                            item.get("原文片段")
                            or item.get("原文")
                            or item.get("original")
                        )
                        # 提取修改建议
                        modified = (
                            item.get("修改建议")
                            or item.get("改为")
                            or item.get("修改后文本")
                            or item.get("modified")
                        )
                        # 提取原因
                        reason = (
                            item.get("修改原因")
                            or item.get("原因")
                            or item.get("reason")
                        )

                        if original and modified:
                            cleaned_orig = _clean_original(str(original))
                            if not cleaned_orig:
                                continue
                            # 过滤超长 `原文`（超过60字几乎肯定是整段，无法精确锚定）
                            if len(cleaned_orig) > 60:
                                logger.debug(
                                    f"[DocumentFeedback] ⚠️ 过滤超长原文({len(cleaned_orig)}字): {cleaned_orig[:30]}..."
                                )
                                # 超长项：尝试拆分为第一个逗号/句号前的片段
                                _short = re.split(r"[，。；！？,;!?]", cleaned_orig)[0].strip()
                                if 4 <= len(_short) <= 40:
                                    cleaned_orig = _short
                                else:
                                    continue  # 无法拆分，丢弃
                            entry = {
                                "原文片段": cleaned_orig,
                                "修改建议": str(modified).strip(),
                            }
                            if reason:
                                entry["修改原因"] = str(reason).strip()
                            valid_annotations.append(entry)
                return valid_annotations

            # 如果是对象包裹格式，尝试提取 annotations/modifications/suggestions
            if isinstance(data, dict):
                for key in ["annotations", "modifications", "suggestions"]:
                    if key in data and isinstance(data[key], list):
                        valid_annotations = []
                        for item in data[key]:
                            if isinstance(item, dict):
                                # 同样支持多种格式
                                original = (
                                    item.get("原文片段")
                                    or item.get("原文")
                                    or item.get("original")
                                )
                                modified = (
                                    item.get("修改建议")
                                    or item.get("改为")
                                    or item.get("修改后文本")
                                    or item.get("modified")
                                )
                                reason = (
                                    item.get("修改原因")
                                    or item.get("原因")
                                    or item.get("reason")
                                )

                                if original and modified:
                                    cleaned_orig = _clean_original(str(original))
                                    if not cleaned_orig:
                                        continue
                                    if len(cleaned_orig) > 60:
                                        logger.debug(
                                            f"[DocumentFeedback] ⚠️ 过滤超长原文({len(cleaned_orig)}字): {cleaned_orig[:30]}..."
                                        )
                                        _short = re.split(r"[，。；！？,;!?]", cleaned_orig)[0].strip()
                                        if 4 <= len(_short) <= 40:
                                            cleaned_orig = _short
                                        else:
                                            continue
                                    entry = {
                                        "原文片段": cleaned_orig,
                                        "修改建议": str(modified).strip(),
                                    }
                                    if reason:
                                        entry["修改原因"] = str(reason).strip()
                                    valid_annotations.append(entry)
                        if valid_annotations:
                            return valid_annotations

            return []

        except Exception as e:
            logger.info(f"[DocumentFeedback] 解析标注失败: {e}")
            return []


# ---------------------------------------------------------------------------
# Convenience wrappers (moved from document_annotation_compat.py)
# ---------------------------------------------------------------------------


def resolve_document_path(file_path: str, workspace_dir: str) -> str:
    text = str(file_path or "").strip()
    if not text:
        return ""
    if os.path.isabs(text):
        return text
    return os.path.join(workspace_dir, "documents", text)


def collect_annotation_result(
    *,
    file_path: str,
    user_requirement: str,
    gemini_client: Any,
    model_id: str = "deepseek-chat",
    task_id: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    skill_prompt: str = "",
) -> Dict[str, Any]:
    feedback_system = DocumentFeedbackSystem(
        gemini_client=gemini_client, default_model_id=model_id
    )
    last_error = ""

    for progress_event in feedback_system.full_annotation_loop_streaming(
        file_path,
        user_requirement,
        task_id=task_id,
        model_id=model_id,
        cancel_check=cancel_check,
        skill_prompt=skill_prompt,
    ):
        stage = str(progress_event.get("stage") or "").strip().lower()
        if stage == "complete":
            result = progress_event.get("result")
            if isinstance(result, dict):
                return result
            return {"success": False, "error": "兼容标注路径未返回结果"}
        if stage == "cancelled":
            return {
                "success": False,
                "cancelled": True,
                "message": str(
                    progress_event.get("message") or "文档标注任务已取消"
                ).strip()
                or "文档标注任务已取消",
            }
        if stage == "error":
            last_error = str(
                progress_event.get("message")
                or progress_event.get("detail")
                or "文档标注失败"
            ).strip()

    return {"success": False, "error": last_error or "文档标注失败"}


def iter_annotation_progress_events(
    *,
    file_path: str,
    user_requirement: str,
    gemini_client: Any,
    model_id: str = "deepseek-chat",
    task_id: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    skill_prompt: str = "",
) -> Iterable[Dict[str, Any]]:
    feedback_system = DocumentFeedbackSystem(
        gemini_client=gemini_client, default_model_id=model_id
    )
    yield from feedback_system.full_annotation_loop_streaming(
        file_path,
        user_requirement,
        task_id=task_id,
        model_id=model_id,
        cancel_check=cancel_check,
        skill_prompt=skill_prompt,
    )


def stream_annotation_events(
    *,
    file_path: str,
    user_requirement: str,
    gemini_client: Any,
    model_id: str = "deepseek-chat",
    task_id: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    skill_prompt: str = "",
) -> Iterable[str]:
    feedback_system = DocumentFeedbackSystem(
        gemini_client=gemini_client, default_model_id=model_id
    )

    for progress_event in iter_annotation_progress_events(
        file_path=file_path,
        user_requirement=user_requirement,
        gemini_client=gemini_client,
        model_id=model_id,
        task_id=task_id,
        cancel_check=cancel_check,
        skill_prompt=skill_prompt,
    ):
        stage = str(progress_event.get("stage") or "").strip().lower()

        if stage == "complete":
            result = (
                progress_event.get("result")
                if isinstance(progress_event.get("result"), dict)
                else {}
            )
            yield f"event: complete\ndata: {json.dumps({'success': bool(result.get('success')), **result}, ensure_ascii=False)}\n\n"
            return

        if stage in {"error", "cancelled"}:
            payload = {
                "success": False,
                "stage": stage,
                "message": str(
                    progress_event.get("message")
                    or progress_event.get("detail")
                    or "文档标注失败"
                ).strip()
                or "文档标注失败",
            }
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            return

        payload = {
            "stage": stage,
            "progress": progress_event.get("progress", 0),
            "message": progress_event.get("message", ""),
            "detail": progress_event.get("detail", ""),
        }
        yield f"event: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


if __name__ == "__main__":
    logger.info("文档智能反馈系统准备就绪")
