# ══════════════════════════════════════════════════════════════
# task_agent.py — Generic tool-using task engine for nested skill execution
#
# Replaces hardcoded workflow executors with an LLM-driven
# plan → execute → deliver loop. The model freely composes
# tools from task_tools.py to accomplish tool-using tasks.
#
# Current role:
#   - used by skill_runner.py for nested skill execution
#   - retained for skill/tool workflows outside the whitebox file-task runtime
#   - NOT the active workspace-assistant file-task runtime
#
# Koto task-agent architecture:
#   - LLM IS the planner (no separate planning module)
#   - Skills = prompt injection, not hardcoded logic
#   - Streaming execution with approval gates
#   - Composable tool layer
# ══════════════════════════════════════════════════════════════
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from app.core.llm.model_mode import normalize_model_mode
from app.core.llm.model_selection import get_configured_cloud_model, get_provider_for_model_mode
from app.core.shared.tool_parser import parse_task_tool_calls, stringify_tool_result

logger = logging.getLogger(__name__)

_FILE_CONTEXT_PREVIEW_LIMIT = 8_000
_HISTORY_MESSAGE_CONTEXT_LIMIT = 2_000
_TOOL_RESULT_CONTEXT_LIMIT = 24_000
_FILE_TASK_LLM_CALL_TIMEOUT = float(os.getenv("KOTO_FILE_TASK_LLM_TIMEOUT", "45"))
_REPEATED_TOOL_BATCH_MESSAGE = "检测到模型重复请求同一组工具，已自动停止以避免重复处理。"
_KOTO_CREATED_MARKER = "__koto_created__:"
_KOTO_MODIFIED_MARKER = "__koto_modified__:"


def _extract_koto_paths(result_str: Any, marker: str) -> List[str]:
    text = str(result_str or "")

    try:
        payload = json.loads(text)
    except Exception:
        payload = None

    if isinstance(payload, dict):
        key = "__koto_created__" if marker == _KOTO_CREATED_MARKER else "__koto_modified__"
        values = payload.get(key)
        if not isinstance(values, list):
            fallback_key = "_koto_created" if marker == _KOTO_CREATED_MARKER else "_koto_modified"
            values = payload.get(fallback_key)
        if isinstance(values, list):
            return [str(item) for item in values if str(item or "").strip()]

    idx = text.rfind(marker)
    if idx == -1:
        return []
    try:
        return json.loads(text[idx + len(marker):])
    except Exception:
        return []


def _extract_koto_created_paths(result_str: str) -> List[str]:
    """Parse __koto_created__:[...] marker appended by run_python_in_sandbox."""
    return _extract_koto_paths(result_str, _KOTO_CREATED_MARKER)


def _extract_koto_modified_paths(result_str: str) -> List[str]:
    """Parse __koto_modified__:[...] marker appended by run_python_in_sandbox."""
    return _extract_koto_paths(result_str, _KOTO_MODIFIED_MARKER)


def _sample_context_text(text: Any, limit: int) -> str:
    content = str(text or "")
    if len(content) <= limit:
        return content
    head = max(int(limit * 0.7), 1)
    tail = max(limit - head - 48, 0)
    marker = "\n\n...[中间内容已省略]...\n\n"
    if tail <= 0:
        return content[:limit]
    return content[:head] + marker + content[-tail:]


def _extract_tool_error_text(result_str: Any) -> str:
    text = str(result_str or "").strip()
    if not text:
        return ""

    try:
        payload = json.loads(text)
    except Exception:
        payload = None

    if isinstance(payload, dict):
        error_text = str(payload.get("error") or "").strip()
        if error_text:
            return error_text

    for prefix in ("Error:", "Sandbox error:", "[error]"):
        if text.startswith(prefix):
            return text[len(prefix):].strip() or text

    marker_idx = text.rfind("\n[error]")
    if marker_idx != -1:
        tail = text[marker_idx + 1:].strip()
        return tail[len("[error]"):].strip() or tail

    inline_error_idx = text.find("[error]")
    if inline_error_idx != -1:
        tail = text[inline_error_idx + len("[error]"):].strip()
        if tail:
            return tail

    return ""


def _build_failed_tool_feedback(failures: List[Dict[str, str]]) -> str:
    if not failures:
        return ""

    lines = [
        "上一轮工具调用失败。你必须先理解失败原因，再决定下一步。",
        "不要重复完全相同的工具调用、参数或代码。",
        "如果要重试，必须明确修正点，并改动参数、代码或工具选择。",
        "如果已有专用写入工具适合当前任务，优先改用专用工具，不要继续盲目重复 run_python_code。",
        "",
        "失败详情:",
    ]
    for index, item in enumerate(failures[:3], start=1):
        tool_name = str(item.get("tool_name") or "tool")
        error_text = str(item.get("error") or "未知错误")
        lines.append(f"{index}. {tool_name}: {error_text}")
        args_preview = str(item.get("args_preview") or "").strip()
        if args_preview:
            lines.append(f"   参数摘要: {args_preview}")
    return "\n".join(lines)


def _summarize_failed_tool_batch(failures: List[Dict[str, str]]) -> str:
    if not failures:
        return ""

    parts = []
    for item in failures[:2]:
        tool_name = str(item.get("tool_name") or "tool")
        error_text = str(item.get("error") or "未知错误")
        short_error = error_text if len(error_text) <= 80 else error_text[:80] + "..."
        parts.append(f"{tool_name}: {short_error}")
    return "；".join(parts)

# ── SSE event builders (compatible with workflow_engine format) ────────────

def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def sse_plan(steps: list[dict]) -> str:
    """Emit the execution plan for frontend preview / approval."""
    return _sse({"type": "plan", "steps": steps})


def sse_plan_summary(text: str) -> str:
    """Short natural-language summary of what the agent will do."""
    return _sse({"type": "plan_summary", "text": text})


def sse_step_start(step_id: str, description: str) -> str:
    return _sse({"type": "step_start", "step_id": step_id, "text": description})


def sse_step_progress(step_id: str, detail: str) -> str:
    return _sse({"type": "step_progress", "step_id": step_id, "detail": detail})


def sse_step_done(step_id: str, summary: str) -> str:
    return _sse({"type": "step_done", "step_id": step_id, "text": summary})


def sse_step_error(step_id: str, error: str) -> str:
    return _sse({"type": "step_error", "step_id": step_id, "error": error})


def sse_thought(text: str) -> str:
    """Agent's reasoning / thinking visible to user."""
    return _sse({"type": "thought", "text": text})


def sse_tool_call(step_id: str, tool_name: str, tool_args: dict) -> str:
    return _sse({
        "type": "tool_call", "step_id": step_id,
        "tool_name": tool_name, "tool_args": tool_args,
    })


def sse_tool_result(step_id: str, tool_name: str, result_preview: str, max_len: int = 500) -> str:
    return _sse({
        "type": "tool_result", "step_id": step_id,
        "tool_name": tool_name, "result_preview": result_preview[:max_len],
    })


def sse_file_change(
    path: str,
    file_type: str = "",
    operation: str = "",
    summary: str = "",
    preview: str = "",
    change_type: str = "modify",
    focus: bool = False,
) -> str:
    return _sse({
        "type": "file_change",
        "path": path,
        "file_type": file_type,
        "operation": operation,
        "summary": summary,
        "preview": preview[:500],
        "change_type": change_type,
        "focus": focus,
    })


def sse_result(output_type: str, data: Any, summary: str = "") -> str:
    return _sse({"type": "result", "output_type": output_type, "data": data, "summary": summary})


def sse_error(text: str) -> str:
    return _sse({"type": "error", "text": text})


def sse_done(summary: str) -> str:
    return _sse({"type": "done", "summary": summary})


# ── Skill prompt loader ────────────────────────────────────────────────────

_SKILL_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "config" / "task_skills"


def _load_skill_prompts(task_description: str) -> str:
    """Load relevant skill prompt files from config/task_skills/.

    Simple keyword matching — returns concatenated prompt text.
    """
    if not _SKILL_PROMPTS_DIR.is_dir():
        return ""

    parts = []
    task_lower = task_description.lower()
    try:
        for md_file in _SKILL_PROMPTS_DIR.glob("*.md"):
            # Read first line as trigger keywords
            content = md_file.read_text(encoding="utf-8", errors="replace")
            first_line = content.split("\n", 1)[0].lower()
            # Check if any keyword from first line appears in task
            keywords = [k.strip() for k in first_line.replace("#", "").split(",") if k.strip()]
            if any(kw in task_lower for kw in keywords):
                parts.append(content)
    except Exception as e:
        logger.debug("[TaskAgent] Skill prompt loading error: %s", e)

    return "\n\n---\n\n".join(parts)


# ── Core system prompt ─────────────────────────────────────────────────────

_SYSTEM_PROMPT = """你是 Koto 文件任务助手。用户会描述一个涉及文件操作的任务，你需要理解任务、制定计划、使用工具执行。

## 工作模式

1. **理解**: 分析用户任务和提供的文件上下文
2. **计划**: 制定清晰的分步执行计划
3. **执行**: 逐步调用工具完成任务
4. **交付**: 汇报结果

## 可用工具

你可以调用以下工具来完成任务：

**文件读取:**
- `read_sheet_data(path, sheet_name?, max_rows?)` — 读取 Excel 表格数据（结构化 JSON）
- `read_docx_content(path, max_chars?)` — 读取 Word 文档段落和表格
- `parse_file_to_text(path, max_chars?, start_page?, end_page?)` — 将任意文件解析为纯文本；PDF 可按页窗口读取
- `list_workspace_files(path?, recursive?)` — 列出工作区文件
- `open_file_in_editor(path)` — 在前端编辑器中打开并展示文件（用户想查看/打开文件时使用）

**文件写入:**
- `write_sheet_data(path, sheet_name?, updates)` — 写入 Excel 单元格（自动备份）
- `write_docx_content(path, paragraphs)` — 写入 Word 段落
- `insert_image_into_docx(path, image_path, title?, caption?, width_inches?)` — 将图表/图片作为真实 Word 图片插入 DOCX
- `insert_excel_as_docx_table(source_path, target_path, sheet_name?, table_title?)` — 将 Excel 工作表作为真实 Word 表格插入 DOCX
- `create_file(path, content)` — 创建新文件
- `copy_file(source, destination)` — 复制文件

**AI 处理:**
- `llm_extract(text, fields, instructions?)` — 从文本中提取结构化数据
- `llm_transform(text, instruction)` — 按指令转换文本

**代码执行:**
- `run_python_code(code, timeout?)` — 在沙盒中执行 Python 代码
- 当前任务文件会自动复制到沙盒当前目录，可直接按文件名访问；绝对路径见 `TASK_FILE_PATHS`

## 规则

1. 在执行文件写入操作前，先读取目标文件确认当前状态
2. write_sheet_data 的 updates 参数必须是 JSON 字符串格式
3. 对于复杂数据处理，优先使用 run_python_code 而非多次调用 llm_extract
4. 工具调用失败时，分析错误原因，尝试修复后重试（最多重试 2 次）
5. 每一步都给用户清晰的进展说明
6. 如果任务不明确，先用已有工具探索文件内容，然后再决定具体做法
7. 当任务要求把 Excel 数据写入 Word 新表格时，优先使用 `insert_excel_as_docx_table`
8. 当任务要求把图表或图片加入 Word/DOCX 时，优先使用 `insert_image_into_docx`；如需先制图，先用 `run_python_code` 生成真实图片文件，再插入 DOCX，不要用 `write_docx_content` 以文字代替图片
9. 生成中文图表时，优先配置 matplotlib 中文字体候选（`Microsoft YaHei`、`SimHei`、`Noto Sans CJK SC`、`WenQuanYi Micro Hei`、`DejaVu Sans`），并用 `plt.savefig(..., dpi=220, bbox_inches='tight')` 保存
10. 对结果文件负责：完成写入后，必须确认目标文件已经更新，并在最终答复中明确说明修改的是哪个文件
11. 同一轮里不要对完全相同的工具参数重复调用同一个工具；如果某个写入工具已经成功完成，下一步应校验结果或结束，而不是再次重复写入
12. 所有写入文件的内容必须是基于实际任务数据生成的真实内容；严禁使用任何占位符、示例文本或模板内容（如"内容示例""请替换为实际内容""XX此处填写YY"等）——没有数据时先调用读取工具获取，再写入"""


_LIVE_UPDATE_PROMPT = """

## 前端实时更新

当前运行连接了前端编辑器。只要已经产出了可展示的阶段性成果，就不要等到最后一次性给出结果；应尽快把中间结果同步到当前打开的文件预览中，让用户边看边确认。

使用 `editor_live_update` 工具推送实时结果：

- 文本 / Word：
    - `editor_live_update(type="set_html", content="当前完整草稿")` → 用当前完整草稿覆盖预览
    - `editor_live_update(type="insert_text", content="新增段落", position="end")` → 在末尾追加阶段性内容
- Excel：
    - `editor_live_update(type="set_cell", r=0, c=0, value="...")`
    - `editor_live_update(type="set_cells", cells=[{"r":0,"c":0,"value":"..."}])`
- PPTX：
    - `editor_live_update(type="set_pptx_text", slide_index=0, shape_id=123, text="...")`

实时更新不能替代正式文件写入：当结果需要真正保存到文件时，仍然要继续调用对应的写入工具完成落盘。
"""


_LOCAL_SYSTEM_PROMPT = """你是 Koto 文件助手（本地模式）。

用户会描述一个文件操作任务，你必须通过调用工具来完成，而不是只给出文字描述。

## 工具使用规则

1. 优先调用 `parse_file_to_text`、`read_docx_content` 或 `read_sheet_data` 读取文件，再决定如何修改
2. 对文件的所有修改必须通过工具完成并落盘；如需操作 PPTX/PDF 等，使用 `run_python_code` 编写 python-pptx 代码执行
3. **严禁新建文件**：所有修改必须写回原始文件路径，不能另存为新文件（如 _优化版、_updated 等）
4. 每步给用户简洁的进度说明
5. 写入工具执行成功后确认结果，不要重复写入同一文件
6. 如果文件内容不足以完成任务，先调用读取工具获取，再写入；严禁使用占位符或示例内容
7. 当任务是把 Excel/XLSX 数据加入 Word/DOCX 时，默认目标仍是生成真实 Word 表格；优先调用 `insert_excel_as_docx_table` 完成表格落盘。
8. 当任务要求把图表或图片加入 Word/DOCX 时，优先调用 `insert_image_into_docx`；如果需要先生成图表，先用 `run_python_code` 产出真实图片文件，再把图片写回目标文档；不要把图片描述文字写进 Word 代替真实插图
9. 生成中文图表时，优先配置 matplotlib 中文字体候选（`Microsoft YaHei`、`SimHei`、`Noto Sans CJK SC`、`WenQuanYi Micro Hei`、`DejaVu Sans`），并用 `plt.savefig(..., dpi=220, bbox_inches='tight')` 保存
10. 如果用户明确要求“整理、摘要、分析、结论、说明”等文字结果，先用 `write_docx_content` 把基于真实表格数据生成的摘要/结论写入目标文档，再按需调用一次 `insert_excel_as_docx_table` 插入支撑表格；不要只插原表就结束，也不要只写摘要而漏掉需要保留的表格
11. `write_docx_content` 只适合写自由文本段落、结论、说明；只有用户明确要求“摘要、分析、结论、说明”时，才把表格数据改写成文字段落
12. 完成 Excel 到 Word 的写入后，优先再次调用 `read_docx_content` 检查目标文档已经新增了表格或对应内容
13. 同一轮里不要对完全相同的工具参数重复调用同一个工具；如果某个写入工具已经成功完成，下一步应校验结果或结束，而不是再次重复写入"""


# ── TaskAgent ──────────────────────────────────────────────────────────────

# Maximum tool call rounds per task execution
MAX_ROUNDS = 20
# Maximum rounds when running on a local (Ollama) model — saves time
MAX_ROUNDS_LOCAL = 10
# Maximum consecutive errors before aborting
MAX_CONSECUTIVE_ERRORS = 3
_MODIFIER_TOOLS = {
    "write_sheet_data",
    "write_docx_content",
    "insert_image_into_docx",
    "create_file",
    "copy_file",
    "extract_to_file",
    "insert_excel_as_docx_table",
}

# 一次任务中，写入工具对同一个目标文件的最大成功执行次数
# 超过此数字认为是重复写入，跳过并注入警告
_MAX_WRITE_OPS_PER_FILE = 1


class TaskAgent:
    """
    Dynamic AI Task Engine — LLM-driven plan & execute loop.

    Unlike hardcoded WorkflowExecutors, the TaskAgent:
    - Receives a natural language task + file context
    - Lets the LLM plan and choose which tools to call
    - Streams progress to the frontend via SSE
    - Adapts to errors and re-plans dynamically
    """

    def __init__(
        self,
        socketio=None,
        model_id: str = "gemini-3.1-pro-preview",
        api_key: Optional[str] = None,
    ):
        self._socketio = socketio
        self._model_id = model_id
        self._api_key = api_key

    def execute(
        self,
        task: str,
        files: Optional[List[Dict[str, str]]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Generator[str, None, None]:
        """
        Main entry point. Yields SSE event strings.

        Args:
            task:    Natural language task description
            files:   List of file context dicts: [{path, name, type, content_preview}]
            options: Optional settings (model_mode, auto_approve, etc.)
        """
        start_time = time.time()
        files = files or []
        options = options or {}
        task_id = uuid.uuid4().hex[:8]
        _is_local = normalize_model_mode(options.get("model_mode")) == "local"

        yield sse_plan_summary("正在分析任务...")

        # ── Build context ──────────────────────────────────────────────
        file_context = self._build_file_context(files)

        # ── Build tool registry ────────────────────────────────────────
        registry = self._build_registry(files)
        tool_defs = registry.get_definitions()

        # ── Build system prompt ────────────────────────────────────────
        if _is_local:
            system = _LOCAL_SYSTEM_PROMPT
        else:
            system = _SYSTEM_PROMPT
            if self._socketio:
                system += _LIVE_UPDATE_PROMPT
            skill_prompt = _load_skill_prompts(task)
            if skill_prompt:
                system += f"\n\n## 参考知识\n\n{skill_prompt}"

        # ── Build initial messages ─────────────────────────────────────
        user_message = self._build_user_message(task, file_context, options)
        history = self._normalize_history_messages(options.get("history") if options else [])
        messages = self._build_conversation_messages(user_message, history)

        # ── Get LLM provider ──────────────────────────────────────────
        provider = self._get_provider(options)
        if not provider:
            yield sse_error("无法初始化 LLM 服务（请检查 API Key 配置）")
            yield sse_done("执行失败")
            return

        # ── Main execution loop ────────────────────────────────────────
        rounds = 0
        consecutive_errors = 0
        _max_rounds = MAX_ROUNDS_LOCAL if normalize_model_mode((options or {}).get("model_mode")) == "local" else MAX_ROUNDS
        current_step_id = "init"
        has_live_update_tool = any(d.get("name") == "editor_live_update" for d in tool_defs)
        has_stage_verification_tool = any(d.get("name") == "verify_task_completion" for d in tool_defs)
        last_successful_tool_batch_signature: Optional[str] = None
        last_successful_tool_batch_summary = ""
        last_failed_tool_batch_signature: Optional[str] = None
        last_failed_tool_batch_summary = ""
        final_summary = ""
        file_states: list[dict[str, Any]] = []
        # Cross-round write dedup: tracks (tool_name, canonical_target_path) → success count
        completed_write_ops: dict[str, int] = {}
        # Track whether any tool call ever produced a hard error across all rounds
        had_any_error = False
        # Local model: whether we've already injected a "write your answer" directive
        _local_final_answer_injected = False

        while rounds < _max_rounds:
            rounds += 1

            try:
                response = self._call_llm(
                    provider, messages, system, tool_defs, options,
                )
            except Exception as e:
                logger.error("[TaskAgent] LLM call failed: %s", e, exc_info=True)
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    # All cloud attempts exhausted — try local Ollama as last resort
                    local_resp = self._try_local_fallback(messages, system, tool_defs, options)
                    if local_resp is not None:
                        consecutive_errors = 0
                        yield sse_step_start("fallback", "切换到本地 AI 继续执行")
                        response = local_resp
                        yield sse_step_done("fallback", "已切换到本地 Ollama")
                    else:
                        yield sse_error(f"LLM 连续调用失败 ({consecutive_errors} 次): {e}")
                        break
                else:
                    continue  # retry silently

            consecutive_errors = 0  # reset on success

            content_text = response.get("content", "")
            tool_calls = response.get("tool_calls", [])
            parsed_text_tool_calls = False
            if not tool_calls and content_text:
                allowed_tool_names = {
                    str(defn.get("name") or "").strip()
                    for defn in tool_defs
                    if str(defn.get("name") or "").strip()
                }
                content_text, tool_calls = parse_task_tool_calls(content_text, allowed_tool_names)
                parsed_text_tool_calls = bool(tool_calls)

            # ── Emit model's user-facing response text ─────────────────
            # Only emit when the model produces a short, user-relevant message,
            # not verbose internal reasoning or very long planning text.
            if content_text and not tool_calls:
                # Final answer (no more tool calls) — always emit
                yield sse_thought(content_text)
            elif content_text and len(content_text) <= 200:
                # Brief intermediate remark — show as status update
                yield sse_thought(content_text)

            # Append model turn (include tool_calls + raw_parts for Gemini multi-turn)
            model_msg: Dict[str, Any] = {"role": "model", "content": content_text or ""}
            if tool_calls:
                # Ensure every tool call has an id for proper multi-turn tracking
                for _tc in tool_calls:
                    if not _tc.get("id"):
                        _tc["id"] = uuid.uuid4().hex[:8]
                model_msg["tool_calls"] = tool_calls
            raw_parts = response.get("_raw_parts")
            if parsed_text_tool_calls and isinstance(raw_parts, list):
                raw_parts = [
                    part for part in raw_parts
                    if isinstance(part, dict) and (part.get("thought") or part.get("thought_signature"))
                ]
            if raw_parts:
                model_msg["parts"] = raw_parts
            messages.append(model_msg)

            tool_batch_signature = self._tool_batch_signature(tool_calls)
            if tool_batch_signature and tool_batch_signature == last_successful_tool_batch_signature:
                # Local models sometimes loop on read-only tool calls after getting file content.
                # Inject a final-answer directive once before giving up.
                _is_local = normalize_model_mode((options or {}).get("model_mode")) == "local"
                if _is_local and not _local_final_answer_injected:
                    _local_final_answer_injected = True
                    messages.append({
                        "role": "user",
                        "content": (
                            "你已经读取了文件内容，请不要再调用任何工具。"
                            "直接用文字写出你的分析、总结或回答。"
                        ),
                    })
                    # Don't break — allow one more round to generate a text answer
                else:
                    repeat_notice = "检测到模型重复请求同一组工具，已自动停止后续执行"
                    if last_successful_tool_batch_summary:
                        repeat_notice = f"{repeat_notice}：{last_successful_tool_batch_summary}"
                    yield sse_thought(repeat_notice)
                    final_summary = "检测到重复步骤，已自动停止"
                    break

            if tool_batch_signature and tool_batch_signature == last_failed_tool_batch_signature:
                repeat_notice = "检测到模型重复提交上一轮失败的工具调用，已自动停止"
                if last_failed_tool_batch_summary:
                    repeat_notice = f"{repeat_notice}：{last_failed_tool_batch_summary}"
                yield sse_thought(repeat_notice)
                final_summary = "检测到重复失败步骤，已自动停止"
                break

            # ── No tool calls → final answer, we're done ───────────────
            if not tool_calls:
                # Detect tasks that should have written files but didn't.
                # has_stage_verification_tool is True only for file-modification tasks.
                no_writes = has_stage_verification_tool and not completed_write_ops
                status_label = "请检查结果" if no_writes else "任务完成"
                if content_text:
                    yield sse_result("markdown", content_text, status_label)
                final_summary = status_label
                break

            # ── Execute tool calls ─────────────────────────────────────
            batch_had_error = False
            batch_failures: list[dict[str, str]] = []
            batch_summaries: list[str] = []
            batch_file_changes: list[dict[str, Any]] = []
            batch_seen_tool_signatures: set[str] = set()
            for tool_index, tc in enumerate(tool_calls, start=1):
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                tool_call_id = tc.get("id", uuid.uuid4().hex[:8])
                tool_call_signature = self._tool_call_signature(tool_name, tool_args)

                # Generate step ID from tool name
                current_step_id = f"{tool_name}_{rounds}_{tool_index}"

                if tool_call_signature and tool_call_signature in batch_seen_tool_signatures:
                    skip_summary = f"检测到重复工具调用，已跳过 {tool_name}"
                    yield sse_thought(skip_summary)
                    yield sse_tool_result(current_step_id, tool_name, "已跳过重复工具调用")
                    messages.append({
                        "role": "function",
                        "name": tool_name,
                        "tool_call_id": tool_call_id,
                        "content": "已跳过重复工具调用",
                    })
                    continue

                if tool_call_signature:
                    batch_seen_tool_signatures.add(tool_call_signature)

                # Cross-round write dedup: prevent repeated writes to the same file
                if tool_name in _MODIFIER_TOOLS:
                    canonical_target = self._canonical_write_target(tool_name, tool_args)
                    write_key = f"{tool_name}::{canonical_target}"
                    prior_count = completed_write_ops.get(write_key, 0)
                    if prior_count >= _MAX_WRITE_OPS_PER_FILE:
                        skip_msg = (
                            f"[系统提示] `{tool_name}` 已成功对该文件执行 {prior_count} 次写入，"
                            "文件数据已是最新状态，本次调用已自动跳过（保护数据完整性）。"
                            "请直接汇报已完成的结果，无需再次写入。"
                        )
                        # Silently skip with feedback to model, no user-facing noise
                        messages.append({
                            "role": "function",
                            "name": tool_name,
                            "tool_call_id": tool_call_id,
                            "content": skip_msg,
                        })
                        continue

                yield sse_step_start(current_step_id, f"调用 {tool_name}")
                yield sse_tool_call(current_step_id, tool_name, tool_args)

                # Execute the tool
                caught_error_text = ""
                try:
                    result = registry.execute(tool_name, tool_args) if registry else None
                    result_str = stringify_tool_result(result)
                except Exception as e:
                    caught_error_text = str(e).strip()
                    result_str = f"Error: {e}"
                    batch_had_error = True
                    had_any_error = True
                    logger.warning("[TaskAgent] Tool %s failed: %s", tool_name, e)
                    yield sse_step_error(current_step_id, caught_error_text or str(e))

                error_text = caught_error_text or _extract_tool_error_text(result_str)
                if error_text:
                    batch_had_error = True
                    had_any_error = True
                    batch_failures.append({
                        "tool_name": tool_name,
                        "error": error_text,
                        "args_preview": _sample_context_text(
                            json.dumps(tool_args or {}, ensure_ascii=False, sort_keys=True, default=str),
                            320,
                        ),
                    })
                    if not caught_error_text:
                        logger.warning("[TaskAgent] Tool %s reported error: %s", tool_name, error_text)
                        yield sse_step_error(current_step_id, error_text)

                # Stream result preview
                preview_text = self._tool_result_preview(tool_name, result_str)
                if not error_text and preview_text:
                    batch_summaries.append(preview_text)
                _result_max_len = 2000 if tool_name == "run_python_code" else 500
                yield sse_tool_result(current_step_id, tool_name, preview_text, max_len=_result_max_len)
                # Emit code_block event so the frontend can render code + output together
                if tool_name == "run_python_code":
                    yield _sse({
                        "type": "code_block",
                        "step_id": current_step_id,
                        "code": tool_args.get("code", ""),
                        "output": result_str[:2000],
                        "error": bool(error_text),
                    })
                if not error_text and has_live_update_tool:
                    self._emit_auto_live_update(registry, tool_name, tool_args, files, options)
                file_change = self._extract_file_change(tool_name, tool_args, result_str)
                if file_change:
                    batch_file_changes.append(file_change)
                    yield sse_file_change(**file_change)

                # run_python_code may create workspace files — detect KOTO_CREATED markers
                if tool_name == "run_python_code" and not error_text:
                    for created_path in _extract_koto_created_paths(result_str):
                        py_change = {
                            "path": created_path,
                            "file_type": Path(created_path).suffix.lstrip(".").lower(),
                            "operation": "run_python_code",
                            "summary": f"Python 代码创建了 {os.path.basename(created_path)}",
                            "preview": "",
                            "change_type": "create",
                            "focus": True,
                        }
                        batch_file_changes.append(py_change)
                        yield sse_file_change(**py_change)
                        # Track as a write op to prevent the model from writing the same file again
                        write_key = f"run_python_code::{os.path.normcase(created_path)}"
                        completed_write_ops[write_key] = completed_write_ops.get(write_key, 0) + 1
                    for modified_path in _extract_koto_modified_paths(result_str):
                        py_change = {
                            "path": modified_path,
                            "file_type": Path(modified_path).suffix.lstrip(".").lower(),
                            "operation": "run_python_code",
                            "summary": f"Python 代码修改了 {os.path.basename(modified_path)}",
                            "preview": "",
                            "change_type": "modify",
                            "focus": False,
                        }
                        batch_file_changes.append(py_change)
                        yield sse_file_change(**py_change)
                        write_key = f"run_python_code::{os.path.normcase(modified_path)}"
                        completed_write_ops[write_key] = completed_write_ops.get(write_key, 0) + 1

                # Track successful write operations for cross-round dedup
                # Treat both "Error: ..." strings and {"error": ...} JSON as failures.
                _is_success = not error_text
                if tool_name in _MODIFIER_TOOLS and _is_success:
                    canonical_target = self._canonical_write_target(tool_name, tool_args)
                    write_key = f"{tool_name}::{canonical_target}"
                    completed_write_ops[write_key] = completed_write_ops.get(write_key, 0) + 1

                if not error_text:
                    yield sse_step_done(current_step_id, f"{tool_name} 完成")

                # Append to conversation as function response
                messages.append({
                    "role": "function",
                    "name": tool_name,
                    "tool_call_id": tool_call_id,
                    "content": _sample_context_text(result_str, _TOOL_RESULT_CONTEXT_LIMIT),
                })

            if tool_batch_signature and not batch_had_error:
                last_successful_tool_batch_signature = tool_batch_signature
                last_successful_tool_batch_summary = "；".join(batch_summaries[:3])[:240]
                last_failed_tool_batch_signature = None
                last_failed_tool_batch_summary = ""
            elif batch_had_error:
                last_successful_tool_batch_signature = None
                last_successful_tool_batch_summary = ""
                last_failed_tool_batch_signature = tool_batch_signature or None
                last_failed_tool_batch_summary = _summarize_failed_tool_batch(batch_failures)
                corrective_feedback = _build_failed_tool_feedback(batch_failures)
                if corrective_feedback:
                    messages.append({
                        "role": "user",
                        "content": _sample_context_text(corrective_feedback, 4_000),
                    })
            else:
                last_failed_tool_batch_signature = None
                last_failed_tool_batch_summary = ""

            if has_stage_verification_tool and batch_file_changes:
                # Run verification whenever any files were written in this batch,
                # even if other tools in the same batch errored — partial progress
                # is still worth verifying so the model knows what's done.
                file_states = self._merge_file_states(file_states, batch_file_changes)
                verify_step_id = f"verify_{rounds}"
                yield sse_step_start(verify_step_id, "阶段检测")
                yield sse_step_progress(verify_step_id, "正在检查当前结果是否符合任务要求")
                verification = self._run_stage_verification(registry, task, file_states, options)
                verification_summary = self._format_stage_verification_summary(verification)

                if verification.get("error"):
                    yield sse_step_error(verify_step_id, str(verification.get("error")))
                else:
                    yield sse_step_done(verify_step_id, verification_summary or "阶段检测完成")

                    # Build verification feedback with explicit write-dedup warning
                    already_written_tools = [
                        k.split("::")[0]
                        for k, cnt in completed_write_ops.items()
                        if cnt >= 1
                    ]
                    verify_content = json.dumps(verification, ensure_ascii=False)
                    if not verification.get("completed") and already_written_tools:
                        unique_written = list(dict.fromkeys(already_written_tools))
                        dedup_warning = (
                            f"\n\n⚠️ 注意：以下写入工具已成功执行，请勿再次调用它们：{', '.join(unique_written)}。"
                            "如需修复格式或数据问题，请使用 run_python_code 进行后处理，"
                            "或使用其他工具读取并分析当前文件状态，而不是覆盖重写。"
                        )
                        verify_content = verify_content.rstrip("}")
                        verify_content += f', "_dedup_warning": {json.dumps(dedup_warning, ensure_ascii=False)}}}'

                    messages.append({
                        "role": "function",
                        "name": "verify_task_completion",
                        "content": _sample_context_text(verify_content, 4_000),
                    })
                    if verification.get("completed") is True:
                        final_summary = verification_summary or "阶段检测通过，任务完成"
                        break

        # ── Done ───────────────────────────────────────────────────────
        elapsed = round(time.time() - start_time, 1)
        if final_summary:
            yield sse_done(f"{final_summary}，耗时 {elapsed}s（共 {rounds} 轮）")
        elif had_any_error:
            yield sse_done(f"执行遇到错误，耗时 {elapsed}s（共 {rounds} 轮）")
        else:
            yield sse_done(f"任务完成，耗时 {elapsed}s（共 {rounds} 轮）")

    # ── Internal helpers ───────────────────────────────────────────────

    def _build_file_context(self, files: List[Dict[str, str]]) -> str:
        """Build a file context description for the LLM."""
        if not files:
            return ""

        parts = ["## 当前文件上下文\n"]
        for f in files:
            path = f.get("path", "")
            name = f.get("name", os.path.basename(path))
            ftype = f.get("type", Path(path).suffix if path else "unknown")
            preview = f.get("content_preview", "")

            parts.append(f"### 文件: {name}")
            parts.append(f"- 路径: {path}")
            parts.append(f"- 类型: {ftype}")
            if preview:
                parts.append(
                    f"- 内容预览:\n```\n{_sample_context_text(preview, _FILE_CONTEXT_PREVIEW_LIMIT)}\n```"
                )
            parts.append("")

        return "\n".join(parts)

    def _build_selection_context_block(self, options: Dict[str, Any]) -> str:
        selection_context = options.get("selection_context") if isinstance(options, dict) else {}
        if not isinstance(selection_context, dict):
            return ""

        text = str(selection_context.get("text") or "").strip()
        if not text:
            return ""

        source_path = str(selection_context.get("source_path") or "").strip()
        source_name = str(selection_context.get("source_name") or "").strip() or (os.path.basename(source_path) if source_path else "")
        source_type = str(selection_context.get("source_type") or "").strip().lower()

        parts = ["## 参考文本上下文"]
        if source_name:
            parts.append(f"- 来源文件: {source_name}")
        if source_path:
            parts.append(f"- 来源路径: {source_path}")
        if source_type:
            parts.append(f"- 来源类型: {source_type}")
        parts.append(f"- 文本内容:\n```\n{_sample_context_text(text, _FILE_CONTEXT_PREVIEW_LIMIT)}\n```")
        parts.append("- 说明: 这段文本是显式提供的参考上下文，不应默认视为待修改文件。")
        return "\n".join(parts)

    def _build_user_message(self, task: str, file_context: str, options: Dict[str, Any]) -> str:
        """Compose the user message with task + file context."""
        parts = [f"## 任务\n\n{task}"]
        selection_context = self._build_selection_context_block(options or {})
        if selection_context:
            parts.append(selection_context)
        if file_context:
            parts.append(file_context)
        return "\n\n".join(parts)

    def _build_conversation_messages(
        self,
        user_message: str,
        history: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        for item in history:
            role = str(item.get("role") or "").strip().lower()
            if role not in {"user", "model"}:
                continue
            content = _sample_context_text(item.get("content", ""), _HISTORY_MESSAGE_CONTEXT_LIMIT)
            if not content:
                continue
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})
        return messages

    @staticmethod
    def _normalize_history_messages(history: Any) -> List[Dict[str, str]]:
        normalized: List[Dict[str, str]] = []
        for item in history or []:
            if not isinstance(item, dict):
                continue

            role = str(item.get("role") or "").strip().lower()
            if role == "assistant":
                role = "model"
            if role not in {"user", "model"}:
                continue

            content = item.get("content")
            if content is None:
                parts = item.get("parts")
                if isinstance(parts, list) and parts:
                    content = parts[0]
            text = str(content or "").strip()
            if not text:
                continue
            normalized.append({"role": role, "content": text})
        return normalized[-20:]

    def _build_registry(self, files: Optional[List[Dict[str, str]]] = None):
        """Build a ToolRegistry with TaskTools."""
        from app.core.agent.task_tools import TaskToolsPlugin
        from app.core.agent.tool_registry import ToolRegistry

        registry = ToolRegistry()
        registry.register_plugin(TaskToolsPlugin(socketio=self._socketio, task_files=files))
        return registry

    def _tool_result_preview(self, tool_name: str, result_str: str) -> str:
        """Extract a short user-facing preview from a tool result."""
        try:
            payload = json.loads(result_str)
        except Exception:
            return result_str

        if not isinstance(payload, dict):
            return result_str
        if payload.get("error"):
            return f"Error: {payload['error']}"
        if payload.get("summary"):
            return str(payload["summary"])
        if tool_name == "read_sheet_data":
            return f"已读取 {payload.get('row_count', 0)} 行表格数据"
        if tool_name == "read_docx_content":
            return (
                f"已读取 {payload.get('total_paragraphs', 0)} 段文本，"
                f"{payload.get('total_tables', 0)} 个表格"
            )
        return result_str

    def _extract_file_change(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result_str: str,
    ) -> Optional[Dict[str, Any]]:
        """Detect file modifications from structured tool responses."""
        if tool_name not in _MODIFIER_TOOLS:
            return None

        try:
            payload = json.loads(result_str)
        except Exception:
            return None

        if not isinstance(payload, dict) or payload.get("error"):
            return None

        change = payload.get("change") if isinstance(payload.get("change"), dict) else {}
        path = (
            payload.get("path")
            or payload.get("file_path")
            or change.get("file_path")
            or tool_args.get("path")
            or tool_args.get("target_path")
            or tool_args.get("destination")
        )
        if not path:
            return None

        file_type = payload.get("file_type") or Path(str(path)).suffix.lstrip(".").lower()
        change_type = (
            payload.get("change_type")
            or change.get("change_type")
            or ("create" if tool_name in {"create_file", "copy_file"} else "modify")
        )
        summary = payload.get("summary") or f"{Path(str(path)).name} 已更新"
        preview = payload.get("preview") or change.get("modified") or ""
        focus = bool(payload.get("focus"))

        return {
            "path": str(path),
            "file_type": file_type,
            "operation": payload.get("operation") or tool_name,
            "summary": str(summary),
            "preview": str(preview),
            "change_type": change_type,
            "focus": focus,
        }

    def _emit_auto_live_update(
        self,
        registry,
        tool_name: str,
        tool_args: Dict[str, Any],
        files: List[Dict[str, str]],
        options: Dict[str, Any],
    ) -> None:
        payload = self._build_live_update_payload(tool_name, tool_args, files, options)
        if not payload:
            return

        try:
            registry.execute("editor_live_update", payload)
        except Exception as exc:
            logger.debug("[TaskAgent] live update emit skipped: %s", exc)

    def _build_live_update_payload(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        files: List[Dict[str, str]],
        options: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if tool_name == "write_docx_content":
            target_path = str(tool_args.get("path") or "")
            if not self._matches_current_file(target_path, files, options):
                return None

            paragraphs = self._json_arg(tool_args.get("paragraphs"), [])
            if not isinstance(paragraphs, list):
                return None

            text_parts = [str(item.get("text", "")) for item in paragraphs if isinstance(item, dict)]
            content = "\n\n".join(part for part in text_parts if part.strip()).strip()
            if not content:
                return None
            return {"type": "set_html", "content": content}

        if tool_name == "write_sheet_data":
            target_path = str(tool_args.get("path") or "")
            if not self._matches_current_file(target_path, files, options):
                return None

            raw_updates = self._json_arg(tool_args.get("updates"), [])
            if not isinstance(raw_updates, list) or not raw_updates:
                return None

            cells = []
            for item in raw_updates:
                if not isinstance(item, dict):
                    continue

                value = item.get("value", "")
                if "r" in item or "c" in item:
                    row = int(item.get("r", 0))
                    col = int(item.get("c", 0))
                else:
                    row = max(int(item.get("row", 1)) - 1, 0)
                    col = max(int(item.get("col", 1)) - 1, 0)

                cells.append({"r": row, "c": col, "value": value})

            if not cells:
                return None
            if len(cells) == 1:
                cell = cells[0]
                return {"type": "set_cell", **cell}
            return {"type": "set_cells", "cells": cells}

        return None

    def _matches_current_file(
        self,
        candidate_path: str,
        files: List[Dict[str, str]],
        options: Dict[str, Any],
    ) -> bool:
        candidate_path = str(candidate_path or "").strip()
        if not candidate_path:
            return False

        candidate_abs = os.path.normcase(os.path.abspath(candidate_path))
        current_file = str(options.get("current_file") or "").strip()
        current_name = str(options.get("current_file_name") or "").strip()

        if current_file:
            current_abs = os.path.normcase(os.path.abspath(current_file))
            return candidate_abs == current_abs or os.path.basename(candidate_path) == os.path.basename(current_file)

        if current_name:
            return os.path.basename(candidate_path) == os.path.basename(current_name)

        if len(files) == 1:
            only_file = files[0]
            only_path = str(only_file.get("path") or "").strip()
            only_name = str(only_file.get("name") or "").strip()
            if only_path and candidate_abs == os.path.normcase(os.path.abspath(only_path)):
                return True
            if only_name and os.path.basename(candidate_path) == os.path.basename(only_name):
                return True

        return False

    @staticmethod
    def _json_arg(raw_value: Any, default: Any) -> Any:
        if isinstance(raw_value, str):
            try:
                return json.loads(raw_value)
            except Exception:
                return default
        return raw_value if raw_value is not None else default

    @staticmethod
    def _canonical_write_target(tool_name: str, tool_args: Dict[str, Any]) -> str:
        """Return a canonical string key for the write target of a modifier tool.

        Used to detect cross-round duplicate writes to the same file.
        For insert_excel_as_docx_table we intentionally do NOT include sheet_name
        so that all sheet insertions to the same DOCX count against the same cap.
        """
        path = (
            tool_args.get("path")
            or tool_args.get("target_path")
            or tool_args.get("destination")
            or ""
        )
        path = os.path.normcase(os.path.abspath(str(path))) if path else "__unknown__"
        return path

    @staticmethod
    def _tool_batch_signature(tool_calls: List[Dict[str, Any]]) -> str:
        if not tool_calls:
            return ""

        normalized_calls = []
        for item in tool_calls:
            if not isinstance(item, dict):
                continue
            normalized_calls.append({
                "name": str(item.get("name", "")),
                "args": item.get("args", {}),
            })

        if not normalized_calls:
            return ""

        payload = json.dumps(normalized_calls, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _tool_call_signature(tool_name: str, tool_args: Dict[str, Any]) -> str:
        if not tool_name:
            return ""
        payload = json.dumps(
            {"name": str(tool_name), "args": tool_args or {}},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _merge_file_states(
        file_states: List[Dict[str, Any]],
        file_changes: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        state_by_path: Dict[str, Dict[str, Any]] = {}
        for item in file_states:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            if path:
                state_by_path[path] = dict(item)

        for change in file_changes:
            if not isinstance(change, dict):
                continue
            path = str(change.get("path") or "").strip()
            if not path:
                continue
            state = state_by_path.get(path, {"path": path})
            state.update({
                "path": path,
                "exists": True,
                "modified": change.get("change_type") != "none",
                "preview": str(change.get("preview") or ""),
                "summary": str(change.get("summary") or state.get("summary") or ""),
                "file_type": str(change.get("file_type") or state.get("file_type") or ""),
            })
            state_by_path[path] = state

        return list(state_by_path.values())

    def _run_stage_verification(
        self,
        registry,
        task: str,
        file_states: List[Dict[str, Any]],
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        verify_args = {
            "task_description": task,
            "file_states": json.dumps(file_states, ensure_ascii=False),
            "model_mode": str((options or {}).get("model_mode") or "auto").strip().lower() or "auto",
        }
        try:
            result = registry.execute("verify_task_completion", verify_args)
        except Exception as exc:
            return {"error": str(exc), "completed": False}

        if isinstance(result, dict):
            return result
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
            except Exception:
                return {"completed": False, "summary": str(result)}
            if isinstance(parsed, dict):
                return parsed
        return {"completed": False, "summary": str(result)}

    @staticmethod
    def _format_stage_verification_summary(verification: Dict[str, Any]) -> str:
        if not isinstance(verification, dict):
            return ""
        if verification.get("error"):
            return str(verification.get("error"))

        summary = str(verification.get("summary") or "").strip()
        remaining_steps = verification.get("remaining_steps") or []
        if verification.get("completed") is True:
            return summary or "当前结果已符合任务要求"
        if summary and remaining_steps:
            return f"{summary}；待完成：{'；'.join(str(item) for item in remaining_steps[:3])}"
        if remaining_steps:
            return f"待完成：{'；'.join(str(item) for item in remaining_steps[:3])}"
        return summary or "当前结果尚未完全符合任务要求"

    def _try_local_fallback(
        self,
        messages: list,
        system: str,
        tool_defs: list,
        options: Optional[Dict[str, Any]] = None,
    ) -> Optional[dict]:
        """Attempt to call local Ollama when cloud models are unavailable.

        Returns response dict on success, or None if Ollama is not available.
        """
        try:
            from app.core.routing.local_model_router import LocalModelRouter

            if not LocalModelRouter.is_ollama_available():
                return None

            # Flatten messages for Ollama (no native tool-calling support)
            flat_msgs = [{"role": "system", "content": system}] if system else []
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("function", "tool"):
                    role = "user"
                    fn_name = msg.get("name", "tool")
                    content = f"[Tool result from {fn_name}]: {content}"
                if content:
                    flat_msgs.append({"role": role if role != "model" else "assistant", "content": str(content)})

            text, err = LocalModelRouter.call_ollama_chat(messages=flat_msgs, timeout=60.0)
            if err or not text:
                return None
            return {"content": text, "tool_calls": [], "model": "local/ollama"}
        except Exception as exc:
            logger.warning("[TaskAgent] Local fallback failed: %s", exc)
            return None

    def _get_provider(self, options: Optional[Dict[str, Any]] = None):
        """Get LLM provider instance."""
        model_mode = normalize_model_mode((options or {}).get("model_mode"))
        if model_mode == "local":
            try:
                from app.core.llm.ollama_llm_provider import OllamaLLMProvider

                local_model = str((options or {}).get("local_model") or "").strip()
                # Discard cloud-only model IDs that Ollama cannot serve
                if local_model.lower().startswith("gemini") or local_model.lower() in {"auto", "cloud"}:
                    local_model = ""
                return OllamaLLMProvider(model=local_model or None)
            except Exception as e:
                logger.error("[TaskAgent] Failed to init local LLM provider: %s", e)
                return None

        try:
            from app.core.llm.provider_factory import get_llm_provider

            provider_name = get_provider_for_model_mode(model_mode)
            self._model_id = get_configured_cloud_model(
                task_type="FILE_TASK",
                fallback_model=self._model_id,
                provider=provider_name,
            ) or self._model_id
            return get_llm_provider(
                provider=provider_name,
                model=self._model_id,
                allow_local_fallback=False,
            )
        except Exception as e:
            logger.error("[TaskAgent] Failed to init LLM provider: %s", e)
            return None

    def _call_llm(
        self,
        provider,
        messages: list,
        system: str,
        tool_defs: list,
        options: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """Call the LLM with messages and tools. Returns response dict."""
        model_mode = normalize_model_mode((options or {}).get("model_mode"))
        if model_mode == "local":
            # Pass tools through — OllamaLLMProvider supports native tool calling
            # for compatible models (qwen3, llama3.1, mistral-nemo, etc.)
            _local_m = str((options or {}).get("local_model") or "").strip()
            if _local_m.lower().startswith("gemini") or _local_m.lower() in {"auto", "cloud"}:
                _local_m = ""
            return provider.generate_content(
                prompt=messages,
                model=_local_m or None,
                system_instruction=system,
                tools=tool_defs if tool_defs else None,
                stream=False,
                call_timeout=_FILE_TASK_LLM_CALL_TIMEOUT,
            )

        try:
            from app.core.llm.model_fallback import get_fallback_executor
            executor = get_fallback_executor()
            return executor.generate_with_fallback(
                provider=provider,
                prompt=messages,
                preferred_model=self._model_id,
                task_type="FILE_TASK",
                system_instruction=system,
                tools=tool_defs if tool_defs else None,
                stream=False,
                call_timeout=_FILE_TASK_LLM_CALL_TIMEOUT,
            )
        except ImportError:
            return provider.generate_content(
                prompt=messages,
                model=self._model_id,
                system_instruction=system,
                tools=tool_defs if tool_defs else None,
                stream=False,
                call_timeout=_FILE_TASK_LLM_CALL_TIMEOUT,
            )
