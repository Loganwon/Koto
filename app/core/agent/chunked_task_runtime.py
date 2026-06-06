from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Generator, Iterable, List, Optional

from app.core.agent.task_agent import (
    TaskAgent,
    sse_done,
    sse_error,
    sse_file_change,
    sse_plan,
    sse_result,
    sse_step_done,
    sse_step_error,
    sse_step_progress,
    sse_step_start,
)

logger = logging.getLogger(__name__)

_SUPPORTED_TEXT_TYPES = {"doc", "docx", "md", "markdown", "txt"}
# Non-text formats that must never go through the chunked rewrite path regardless
# of content length (presentations, spreadsheets, PDFs have specialist tools).
_UNSUPPORTED_FILE_TYPES = {"pptx", "ppt", "xlsx", "xls", "csv", "pdf"}
_TRANSFORM_HINTS = (
    "polish",
    "refine",
    "rewrite",
    "translate",
    "improve",
    "edit",
    "optimize",
    "润色",
    "优化",
    "改写",
    "翻译",
    "整理",
    "重写",
    "修订",
)
_MIN_SOURCE_CHARS = 6_000
_TARGET_CHUNK_CHARS = 2_400
_TARGET_LOCAL_CHUNK_CHARS = 1_400
_BOUNDARY_CHARS = 220

_PHASES = [
    {"id": "detect", "label": "识别任务"},
    {"id": "chunk", "label": "切分文档"},
    {"id": "execute", "label": "处理分块"},
    {"id": "merge", "label": "合并结果"},
    {"id": "verify", "label": "校验结果"},
]


def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def sse_phase(current: str, status: str = "running") -> str:
    return _sse(
        {"type": "phase", "phases": _PHASES, "current": current, "status": status}
    )


def sse_progress(current: int, total: int, detail: str = "") -> str:
    return _sse(
        {"type": "progress", "current": current, "total": total, "detail": detail}
    )


@dataclass
class ChunkUnit:
    chunk_id: str
    order: int
    label: str
    text: str
    start_hint: str = ""
    end_hint: str = ""


class ChunkedTaskRuntime:
    """Small first-slice chunk runtime for long text transformation tasks."""

    def __init__(
        self,
        socketio=None,
        model_id: str = "gemini-3.1-pro-preview",
        api_key: Optional[str] = None,
    ):
        self._socketio = socketio
        self._model_id = model_id
        self._api_key = api_key
        self._task_agent: Optional[TaskAgent] = None

    def _get_task_agent(self) -> TaskAgent:
        if self._task_agent is None:
            self._task_agent = TaskAgent(
                socketio=self._socketio,
                model_id=self._model_id,
                api_key=self._api_key,
            )
        return self._task_agent

    def should_handle(
        self,
        task: str,
        files: Optional[List[Dict[str, str]]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self._looks_like_transform_task(task):
            return False

        file_type = self._resolve_file_type(files, options)
        # Explicit exclusion takes priority — presentation/spreadsheet/PDF files
        # are handled by specialist tools, never by the text-chunking path.
        if file_type in _UNSUPPORTED_FILE_TYPES:
            return False
        if file_type not in _SUPPORTED_TEXT_TYPES:
            return False

        source_text = self._resolve_source_text(files, options)
        return len(source_text) >= _MIN_SOURCE_CHARS

    def execute(
        self,
        task: str,
        files: Optional[List[Dict[str, str]]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Generator[str, None, None]:
        options = options or {}
        files = files or []
        source_text = self._resolve_source_text(files, options)
        file_type = self._resolve_file_type(files, options)
        file_path = str(
            options.get("current_file")
            or (files[0].get("path") if files else "")
            or "current_document"
        )

        if not source_text.strip():
            logger.debug(
                "[ChunkedTaskRuntime] Empty source text — delegating to TaskAgent"
            )
            yield from self._get_task_agent().execute(
                task=task, files=files, options=options
            )
            return

        chunks = self._build_chunks(source_text, options)
        if len(chunks) <= 1:
            # Document is too short or has no paragraph breaks for chunking; fall
            # back to the regular TaskAgent so the user gets a useful response
            # instead of a red error.
            logger.debug(
                "[ChunkedTaskRuntime] Only %d chunk(s) — delegating to TaskAgent",
                len(chunks),
            )
            yield from self._get_task_agent().execute(
                task=task, files=files, options=options
            )
            return

        yield sse_phase("detect", "running")
        yield sse_step_progress(
            "detect", f"已识别为长文档分块任务（{len(source_text)} 字）"
        )
        yield sse_phase("detect", "done")

        yield sse_phase("chunk", "running")
        yield sse_plan(
            [{"id": chunk.chunk_id, "description": chunk.label} for chunk in chunks]
        )
        yield sse_progress(0, len(chunks), f"已切分为 {len(chunks)} 个连续分块")
        yield sse_phase("chunk", "done")

        yield sse_phase("execute", "running")
        provider = self._get_task_agent()._get_provider(options)
        if not provider:
            yield sse_error("无法初始化分块任务所需的 LLM 服务")
            yield sse_done("执行失败")
            return

        merged_parts: List[str] = []
        previous_summary = ""
        total = len(chunks)

        for index, chunk in enumerate(chunks, start=1):
            yield sse_step_start(chunk.chunk_id, chunk.label)
            try:
                result = self._process_chunk(
                    provider=provider,
                    task=task,
                    chunk=chunk,
                    previous_summary=previous_summary,
                    file_type=file_type,
                    options=options,
                )
            except Exception as exc:
                logger.warning(
                    "[ChunkedTaskRuntime] chunk failed: %s", exc, exc_info=True
                )
                yield sse_step_error(chunk.chunk_id, str(exc))
                yield sse_error(f"{chunk.label} 处理失败：{exc}")
                yield sse_done("执行失败")
                return

            chunk_output = str(result.get("chunk_output") or "").strip()
            if not chunk_output:
                yield sse_step_error(chunk.chunk_id, f"{chunk.label} 未返回有效内容")
                yield sse_error(f"{chunk.label} 未返回有效内容")
                yield sse_done("执行失败")
                return

            merged_parts.append(chunk_output)
            previous_summary = (
                str(result.get("chunk_summary") or "").strip() or previous_summary
            )

            merged_text = self._merge_outputs(merged_parts)
            yield sse_progress(index, total, f"已完成 {chunk.label}")
            yield sse_file_change(
                path=file_path,
                file_type=file_type,
                operation="chunk_merge",
                summary=f"已合并 {index}/{total} 个分块",
                preview=merged_text,
                change_type="modify",
                focus=index == total,
            )
            yield sse_step_done(chunk.chunk_id, f"{chunk.label} 完成")

        yield sse_phase("execute", "done")
        yield sse_phase("merge", "running")

        merged_text = self._merge_outputs(merged_parts)
        yield sse_step_progress("merge", f"已生成整文结果（{len(merged_text)} 字）")
        yield sse_phase("merge", "done")

        yield sse_phase("verify", "running")
        verified_text = self._verify_output(merged_text)
        yield sse_step_done("verify", "已完成整文结果校验")
        yield sse_phase("verify", "done")

        yield sse_result("markdown", verified_text, "分块处理结果")
        yield sse_done(f"已完成 {len(chunks)} 个分块的顺序处理")

    @staticmethod
    def _looks_like_transform_task(task: str) -> bool:
        task_lower = str(task or "").strip().lower()
        if not task_lower:
            return False
        return any(hint in task_lower for hint in _TRANSFORM_HINTS)

    @staticmethod
    def _resolve_file_type(
        files: Optional[List[Dict[str, str]]],
        options: Optional[Dict[str, Any]],
    ) -> str:
        files = files or []
        options = options or {}
        if files:
            ftype = str(files[0].get("type") or "").strip().lower()
            if ftype:
                return ftype

        current_name = str(options.get("current_file_name") or "").strip().lower()
        if "." in current_name:
            return current_name.rsplit(".", 1)[-1]
        return ""

    @staticmethod
    def _resolve_source_text(
        files: Optional[List[Dict[str, str]]],
        options: Optional[Dict[str, Any]],
    ) -> str:
        files = files or []
        options = options or {}
        source_text = str(options.get("current_file_text") or "")
        if source_text.strip():
            return source_text
        if files:
            return str(files[0].get("content_preview") or "")
        return ""

    def _build_chunks(
        self, source_text: str, options: Dict[str, Any]
    ) -> List[ChunkUnit]:
        from app.core.llm.model_mode import normalize_model_mode

        target_size = (
            _TARGET_LOCAL_CHUNK_CHARS
            if normalize_model_mode(options.get("model_mode")) == "local"
            else _TARGET_CHUNK_CHARS
        )
        paragraphs = self._split_paragraphs(source_text)
        chunks: List[ChunkUnit] = []
        buffer: List[str] = []
        buffer_len = 0

        def _flush() -> None:
            nonlocal buffer, buffer_len
            if not buffer:
                return
            chunk_text = "\n\n".join(buffer).strip()
            if not chunk_text:
                buffer = []
                buffer_len = 0
                return
            chunks.append(ChunkUnit(chunk_id="", order=0, label="", text=chunk_text))
            buffer = []
            buffer_len = 0

        for paragraph in paragraphs:
            paragraph_len = len(paragraph)
            if buffer and buffer_len + paragraph_len > target_size:
                _flush()
            buffer.append(paragraph)
            buffer_len += paragraph_len

        _flush()

        total = len(chunks)
        finalized: List[ChunkUnit] = []
        for index, chunk in enumerate(chunks, start=1):
            finalized.append(
                ChunkUnit(
                    chunk_id=f"chunk_{index}",
                    order=index,
                    label=f"第 {index}/{total} 块",
                    text=chunk.text,
                    start_hint=chunk.text[:_BOUNDARY_CHARS],
                    end_hint=chunk.text[-_BOUNDARY_CHARS:],
                )
            )
        return finalized

    @staticmethod
    def _split_paragraphs(text: str) -> List[str]:
        blocks = [
            block.strip()
            for block in re.split(r"\n\s*\n", str(text or ""))
            if block.strip()
        ]
        if blocks:
            return blocks

        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        if lines:
            return lines

        text = str(text or "").strip()
        return [text] if text else []

    def _process_chunk(
        self,
        provider,
        task: str,
        chunk: ChunkUnit,
        previous_summary: str,
        file_type: str,
        options: Dict[str, Any],
    ) -> Dict[str, str]:
        system = (
            "你是 Koto 长文档分块处理器。你当前只负责处理整篇文档中的一个连续分块。\n"
            "输出必须是 JSON 对象，格式为:\n"
            '{"chunk_output": "处理后的当前分块完整文本", "chunk_summary": "当前分块改动摘要（80字内）"}\n\n'
            "规则:\n"
            "1. 只处理当前分块，不要复述其他分块的内容。\n"
            "2. chunk_output 必须是该分块处理后的完整文本，不要附加解释。\n"
            "3. chunk_summary 用一句话概括本分块的处理结果。\n"
            "4. 不要输出 markdown 代码块。"
        )

        prompt = (
            f"用户任务:\n{task}\n\n"
            f"文件类型: {file_type or 'text'}\n"
            f"前一分块摘要:\n{previous_summary or '（无）'}\n\n"
            f"当前分块: {chunk.label}\n"
            f"当前分块前导提示:\n{chunk.start_hint}\n\n"
            f"当前分块正文:\n{chunk.text}\n\n"
            f"当前分块尾部提示:\n{chunk.end_hint}\n\n"
            "请只返回 JSON。"
        )
        response = self._get_task_agent()._call_llm(
            provider=provider,
            messages=[{"role": "user", "content": prompt}],
            system=system,
            tool_defs=[],
            options=options,
        )
        content = str(response.get("content") or "").strip()
        payload = self._parse_json_payload(content)
        return {
            "chunk_output": str(payload.get("chunk_output") or "").strip(),
            "chunk_summary": str(payload.get("chunk_summary") or "").strip(),
        }

    @staticmethod
    def _parse_json_payload(content: str) -> Dict[str, Any]:
        raw = str(content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        raw = raw.strip()
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        match = re.search(r"(\{[\s\S]*\})", raw)
        if match:
            try:
                parsed = json.loads(match.group(1))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

        return {"chunk_output": raw, "chunk_summary": raw[:80]}

    @staticmethod
    def _merge_outputs(parts: Iterable[str]) -> str:
        merged = "\n\n".join(
            str(part or "").strip() for part in parts if str(part or "").strip()
        )
        return re.sub(r"\n{3,}", "\n\n", merged).strip()

    @staticmethod
    def _verify_output(text: str) -> str:
        return re.sub(r"\n{3,}", "\n\n", str(text or "").strip())
