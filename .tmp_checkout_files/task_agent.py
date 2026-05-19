from __future__ import annotations

from app.core.agent._pyc_restore import restore_current_module


restore_current_module(__file__, globals())# ══════════════════════════════════════════════════════════════
# task_agent.py — Dynamic AI Task Engine for Koto File Assistant
#
# Replaces hardcoded workflow executors with an LLM-driven
# plan → execute → deliver loop. The model freely composes
# tools from task_tools.py to accomplish user tasks on files.
#
# Inspired by OpenClaw's architecture:
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
from app.core.shared.tool_parser import stringify_tool_result

logger = logging.getLogger(__name__)

_FILE_CONTEXT_PREVIEW_LIMIT = 8_000
_HISTORY_MESSAGE_CONTEXT_LIMIT = 2_000
_TOOL_RESULT_CONTEXT_LIMIT = 24_000
_FILE_TASK_LLM_CALL_TIMEOUT = float(os.getenv("KOTO_FILE_TASK_LLM_TIMEOUT", "45"))
_REPEATED_TOOL_BATCH_MESSAGE = "检测到模型重复请求同一组工具，已自动停止以避免重复处理。"
_KOTO_CREATED_MARKER = "__koto_created__:"
_KOTO_MODIFIED_MARKER = "__koto_modified__:"
_WRITE_REQUIRED_KEYWORDS = (
    "修改",
    "更新",
    "编辑",
    "改写",
    "润色",
    "修订",
    "补充",
    "插入",
    "写入",
    "加入",
    "计入",
    "填入",
    "合并",
    "替换",
    "删除",
    "追加",
    "同步到",
    "保存到",
    "落盘",
    "modify",
    "update",
    "edit",
    "rewrite",
    "insert",
    "write",
    "append",
    "merge",
    "replace",
)


def _extract_koto_markers(result_str: str) -> Dict[str, List[str]]:
    """Parse __koto_created__ and __koto_modified__ markers appended by _wrap_sandbox_result."""
    def _extract(marker: str) -> List[str]:
        idx = result_str.rfind(marker)
        if idx == -1:
            return []
        after = result_str[idx + len(marker):]
        # Trim at any subsequent marker boundary
        cut = after.find("__koto_")
        if cut != -1:
            after = after[:cut]
        try:
            return json.loads(after)
        except Exception:
            return []

    return {
        "created": _extract(_KOTO_CREATED_MARKER),
        "modified": _extract(_KOTO_MODIFIED_MARKER),
    }


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


def _task_requires_file_change(task: str) -> bool:
    text = str(task or "").strip().lower()
    if not text:
        return False
    return any(keyword in text for keyword in _WRITE_REQUIRED_KEYWORDS)


_CONTEXT_PRUNE_THRESHOLD = 150_000  # chars — prune when conversation exceeds this
_CONTEXT_KEEP_TAIL = 13             # keep first message + this many recent messages


def _prune_messages(messages: List[Dict]) -> List[Dict]:
    """Drop oldest intermediate messages to keep total context under threshold.

    Keeps the first message (task description) and the most recent tail so the
    model always has the original task + latest observations without losing context.
    """
    if len(messages) <= 4:
        return messages
    total = sum(len(str(m.get("content") or "")) for m in messages)
    if total <= _CONTEXT_PRUNE_THRESHOLD:
        return messages
    return [messages[0]] + messages[-_CONTEXT_KEEP_TAIL:]


def _tool_target_name(tool_args: Dict[str, Any]) -> str:
    path = (
        tool_args.get("path")
        or tool_args.get("target_path")
        or tool_args.get("source_path")
        or tool_args.get("file_path")
        or tool_args.get("destination")
        or tool_args.get("name")
        or ""
    )
    text = str(path or "").strip()
    if not text:
        return ""
    return os.path.basename(text.rstrip("/\\")) or text


def _tool_completion_summary(tool_name: str, tool_args: Dict[str, Any], preview_text: str = "") -> str:
    name = str(tool_name or "").strip()
    target = _tool_target_name(tool_args)
    preview = str(preview_text or "").strip()

    if name == "code_execution":
        code = str(tool_args.get("code") or "").strip()
        for line in code.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") and not stripped.startswith("#!"):
                comment = stripped.lstrip("#").strip()
                if comment and len(comment) <= 60:
                    return comment
        if preview and not preview.startswith("Error:") and len(preview) <= 60:
            return preview
        return "代码执行完成"
    if name in {"open_file_in_editor", "editor_open_file"}:
        return f"已打开 {target or '文件'}"
    if name in {"read", "read_file", "workspace_read_file"}:
        return f"已读取 {target or '文件'}"
    if name in {"workspace_create_file"}:
        return f"已创建 {target or '文件'}"
    if name in {"write", "write_file", "edit", "apply_patch", "workspace_save_file", "editor_apply", "editor_live_update"}:
        return f"已更新 {target or '文件'}"
    if name in {"list_workspace_files", "workspace_list_files"}:
        return "已获取文件列表"
    if name == "run_shell_command":
        return "命令执行完成"
    if name == "run_r_code":
        return "R 代码执行完成"
    if preview and len(preview) <= 48 and not preview.startswith("Error:"):
        return preview
    return f"{name} 完成" if name else "步骤完成"

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


def sse_tool_result(step_id: str, tool_name: str, result_preview: str) -> str:
    return _sse({
        "type": "tool_result", "step_id": step_id,
        "tool_name": tool_name, "result_preview": result_preview[:500],
    })


def sse_file_change(
    path: str,
    file_type: str = "",
    operation: str = "",
    summary: str = "",
    preview: str = "",
    change_type: str = "modify",
    focus: bool = False,
    file_size: int = 0,
) -> str:
    payload: dict = {
        "type": "file_change",
        "path": path,
        "name": os.path.basename(str(path)) if path else "",
        "file_type": file_type,
        "operation": operation,
        "summary": summary,
        "preview": preview[:600],
        "change_type": change_type,
        "focus": focus,
    }
    if file_size > 0:
        payload["file_size"] = file_size
    return _sse(payload)


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


# ── TAOR Helpers ───────────────────────────────────────────────────────────

def _build_observe_note(
    round_num: int,
    tool_calls: List[Dict[str, Any]],
    tool_results: List[Dict[str, Any]],
    file_changes: List[Dict[str, Any]],
    errors: List[str],
) -> str:
    """Build a structured observation message to inject into the conversation.

    Summarises what actually happened in the last Act round so the LLM can
    accurately track state and plan the next step.
    """
    lines = [f"[系统·Observe 轮次 {round_num}]"]

    # Tools called
    tool_names = [tc.get("name", "unknown") for tc in tool_calls if isinstance(tc, dict)]
    if tool_names:
        lines.append(f"调用工具: {', '.join(tool_names)}")

    # Successes
    success_summaries = [
        r.get("preview", "")[:120]
        for r in tool_results
        if isinstance(r, dict) and not r.get("is_error")
    ]
    if success_summaries:
        lines.append("执行结果: " + " | ".join(filter(None, success_summaries))[:300])

    # File changes
    if file_changes:
        change_descs = []
        for fc in file_changes:
            if isinstance(fc, dict):
                ct = fc.get("change_type", "modify")
                name = fc.get("name") or os.path.basename(str(fc.get("path", "")))
                change_descs.append(f"{'创建' if ct == 'create' else '修改'}: {name}")
        if change_descs:
            lines.append("文件变更: " + ", ".join(change_descs[:5]))

    # Errors
    if errors:
        for err in errors[:2]:
            lines.append(f"错误: {err[:120]}")

    return "\n".join(lines)


_REFLECT_PROMPT = """[系统·Reflect] 请评估当前任务进度：

1. 是否已完成用户的核心要求？（是/否/部分）
2. 还剩哪些步骤未完成？（如果有）
3. 是否需要调整执行计划？（是/否，如是请说明）

请用一句话概括当前状态，然后决定下一步行动。若任务已完成，直接回复结果即可。"""


# ── Core system prompt ─────────────────────────────────────────────────────

_SYSTEM_PROMPT = """你是 Koto 文件任务助手。用户会描述一个涉及文件操作的任务，你通过编写代码完成任务。

## 可用工具

**主要执行工具:**
- `code_execution(code, timeout?)` — 在沙盒中执行 Python 代码（**处理所有文件格式的首选工具**）
  - 可用包：pandas、openpyxl、python-docx、python-pptx、pdfplumber、numpy、matplotlib 及标准库
  - 任务文件已自动注入沙盒：用 `TASK_SANDBOX_FILE_PATHS["<文件名>"]` 获取路径，或直接用 `TASK_SANDBOX_FILES` 列表
  - 修改文件后打印：`KOTO_MODIFIED:<绝对路径>`（系统用此追踪文件变更）
  - 创建新文件后打印：`KOTO_CREATED:<绝对路径>`

**文件 I/O（仅限文本文件）:**
- `read(path, start_line?, end_line?)` — 读取文本文件；Excel/Word/PPT/PDF 请用 code_execution
- `write(path, content)` — 写入/创建文本文件
- `edit(path, old_string, new_string)` — 精确替换文件中的字符串（old_string 必须唯一）
- `apply_patch(path, patch)` — 应用 unified diff 格式补丁

**工作区:**
- `list_workspace_files(path?, recursive?)` — 列出工作区文件
- `open_file_in_editor(path)` — 在编辑器中打开文件展示给用户

**技能库（专项任务）:**
- `search_skills(query)` — 搜索适合当前任务的技能，返回技能 ID 和描述列表
- `call_skill(skill_id, task_description)` — 调用特定技能完成专项任务
  - 本地已有 90+ 内置技能（数据分析、文档生成、Excel、PPT、PDF、代码审查等）
  - 当本地找不到时，会自动从社区技能库下载临时使用
  - 如不确定 skill_id，先调用 search_skills 查询

## 规则

1. Excel/Word/PPT/PDF → 必须用 `code_execution`（分别用 openpyxl、python-docx、python-pptx、pdfplumber）
2. 文本文件（.txt/.csv/.json/.md 等）→ 可用 `read`/`write`/`edit`/`apply_patch`
3. 代码执行后打印 `KOTO_MODIFIED:<path>`，否则系统无法追踪文件变更
4. 禁止任何占位符内容；无数据时先读取获取，再写入
5. 直接修改原始文件，除非用户明确要求新文件名
6. 代码出错时分析错误原因，修复后重试（最多 2 次）
7. 对结果负责：完成后确认文件已正确更新"""


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

## 可用工具

- `code_execution(code, timeout?)` — Python 沙盒执行（处理 Excel/Word/PPT/PDF 等所有格式）
  - 可用包：pandas、openpyxl、python-docx、python-pptx、pdfplumber、numpy 及标准库
  - 任务文件路径通过 `TASK_FILE_PATHS["<文件名>"]` 获取
  - 修改文件后打印 `KOTO_MODIFIED:<绝对路径>`；创建新文件后打印 `KOTO_CREATED:<绝对路径>`
- `read(path, start_line?, end_line?)` — 读取文本文件（.txt/.csv/.json 等）
- `write(path, content)` — 写入/创建文本文件
- `edit(path, old_string, new_string)` — 精确替换文件中的字符串
- `list_workspace_files(path?, recursive?)` — 列出工作区文件
- `search_skills(query)` — 搜索适合当前任务的专项技能，返回技能 ID 和描述
- `call_skill(skill_id, task_description)` — 调用专项技能完成复杂任务

## 规则

1. Excel/Word/PPT/PDF → 必须用 `code_execution`
2. 文本文件（.txt/.csv/.json 等）→ 可用 `read`/`write`/`edit`
3. 修改文件后在代码中打印 `KOTO_MODIFIED:<绝对路径>`，否则系统无法追踪变更
4. 所有修改必须写回原始文件路径，严禁使用占位符或示例内容
5. 每步给用户简洁进度说明
6. 代码出错时分析原因，修复后重试"""


# ── TaskAgent ──────────────────────────────────────────────────────────────

# Maximum tool call rounds per task execution
MAX_ROUNDS = 20
# Maximum rounds when running on a local (Ollama) model — saves time
MAX_ROUNDS_LOCAL = 10
# Maximum consecutive errors before aborting
MAX_CONSECUTIVE_ERRORS = 3
# TAOR: every this many successful rounds, inject a Reflect prompt
_REFLECT_EVERY_N_ROUNDS = 5
_MODIFIER_TOOLS = {
    "write",
    "edit",
    "apply_patch",
}

# 一次任务中，写入工具对同一个目标文件的最大成功执行次数
# 超过此数字认为是重复写入，跳过并注入警告
# NOTE: code_execution 不按工具计数，通过 KOTO 标记追踪；修改类工具最多写入 3 次。
_MAX_WRITE_OPS_PER_FILE = 3


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
        registry = self._build_registry(files, options)
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

        # Skill-call injection: prepend the calling skill's prompt as extra context
        skill_inject = str(options.get("_skill_system_inject") or "").strip()
        if skill_inject:
            system = skill_inject + "\n\n" + system

        # TAOR Think injection: append the pre-computed plan as a system hint
        plan_inject = str(options.get("_taor_plan_inject") or "").strip()
        if plan_inject:
            system = system + "\n\n## 当前执行计划\n\n" + plan_inject

        # ── Build initial messages ─────────────────────────────────────
        user_message = self._build_user_message(task, file_context)
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
        last_successful_tool_batch_signature: Optional[str] = None
        last_successful_tool_batch_summary = ""
        final_summary = ""
        requires_file_change = _task_requires_file_change(task)
        has_detected_file_change = False
        # Cross-round write dedup: tracks (tool_name, canonical_target_path) → success count
        completed_write_ops: dict[str, int] = {}
        # Track whether any tool call ever produced a hard error across all rounds
        had_any_error = False
        # Local model: whether we've already injected a "write your answer" directive
        _local_final_answer_injected = False
        # TAOR: count of successful (non-error) rounds for Reflect trigger
        _successful_rounds = 0
        # TAOR: whether a Reflect prompt has been injected this cycle
        _reflect_injected_at: int = -99
        while rounds < _max_rounds:
            rounds += 1

            messages = _prune_messages(messages)
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

            # ── Emit model's user-facing response text ─────────────────
            # Only emit when the model produces a short, user-relevant message,
            # not verbose internal reasoning or very long planning text.
            if content_text and not tool_calls and not (requires_file_change and not has_detected_file_change):
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
                    if requires_file_change and not has_detected_file_change:
                        messages.append({
                            "role": "user",
                            "content": (
                                "你已经读取了文件内容，但系统尚未检测到任何实际文件变更。"
                                "不要继续重复读取；请立即调用 code_execution 或写入类工具，"
                                "把结果真实写回目标文件，并打印 KOTO_MODIFIED 或 KOTO_CREATED。"
                                "完成真实文件写入后再总结。"
                            ),
                        })
                    else:
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

            # ── No tool calls → final answer, we're done ───────────────
            if not tool_calls:
                if requires_file_change and not has_detected_file_change:
                    if rounds >= _max_rounds:
                        yield sse_error("任务尚未完成：未检测到任何文件变更，请继续执行真实写入后再结束")
                        final_summary = "任务未完成：未检测到文件变更"
                        break
                    yield sse_thought("尚未检测到文件变更，继续执行写入步骤")
                    messages.append({
                        "role": "user",
                        "content": (
                            "当前任务要求真实修改文件，但系统还没有检测到任何文件变更。"
                            "请继续调用工具完成写入，不要只给结论。"
                            "完成后必须让系统看到 KOTO_MODIFIED/KOTO_CREATED 或文本文件写入结果。"
                        ),
                    })
                    continue
                if content_text:
                    yield sse_result("markdown", content_text, "任务完成")
                final_summary = "任务完成"
                break

            # ── Execute tool calls ─────────────────────────────────────
            batch_had_error = False
            batch_summaries: list[str] = []
            batch_file_changes: list[dict[str, Any]] = []
            batch_seen_tool_signatures: set[str] = set()
            batch_errors: list[str] = []
            batch_tool_results: list[dict[str, Any]] = []
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
                try:
                    result = registry.execute(tool_name, tool_args) if registry else None
                    result_str = stringify_tool_result(result)
                except Exception as e:
                    result_str = f"Error: {e}"
                    batch_had_error = True
                    had_any_error = True
                    logger.warning("[TaskAgent] Tool %s failed: %s", tool_name, e)
                    yield sse_step_error(current_step_id, str(e))
                    batch_errors.append(f"{tool_name}: {e}")

                # Stream result preview
                preview_text = self._tool_result_preview(tool_name, result_str)
                if result_str.startswith("Error:"):
                    batch_had_error = True
                    had_any_error = True
                    if not any(result_str in e for e in batch_errors):
                        batch_errors.append(f"{tool_name}: {result_str[6:120]}")
                    batch_tool_results.append({"name": tool_name, "preview": preview_text, "is_error": True})
                else:
                    if preview_text:
                        batch_summaries.append(preview_text)
                    batch_tool_results.append({"name": tool_name, "preview": preview_text, "is_error": False})
                yield sse_tool_result(current_step_id, tool_name, preview_text)
                file_change = self._extract_file_change(tool_name, tool_args, result_str)
                if file_change:
                    has_detected_file_change = True
                    batch_file_changes.append(file_change)
                    yield sse_file_change(**file_change)

                # code_execution may create/modify workspace files — detect KOTO markers
                _code_exec_had_koto_changes = False
                if tool_name == "code_execution" and not result_str.startswith("Error:"):
                    markers = _extract_koto_markers(result_str)
                    _code_exec_had_koto_changes = bool(markers.get("modified") or markers.get("created"))
                    for created_path in markers.get("created", []):
                        has_detected_file_change = True
                        py_change = {
                            "path": created_path,
                            "file_type": Path(created_path).suffix.lstrip(".").lower(),
                            "operation": "code_execution",
                            "summary": f"Python 代码创建了 {os.path.basename(created_path)}",
                            "preview": "",
                            "change_type": "create",
                            "focus": True,
                        }
                        batch_file_changes.append(py_change)
                        yield sse_file_change(**py_change)
                        write_key = f"code_execution::{os.path.normcase(created_path)}"
                        completed_write_ops[write_key] = completed_write_ops.get(write_key, 0) + 1
                    for modified_path in markers.get("modified", []):
                        has_detected_file_change = True
                        py_change = {
                            "path": modified_path,
                            "file_type": Path(modified_path).suffix.lstrip(".").lower(),
                            "operation": "code_execution",
                            "summary": f"Python 代码修改了 {os.path.basename(modified_path)}",
                            "preview": "",
                            "change_type": "modify",
                            "focus": False,
                        }
                        batch_file_changes.append(py_change)
                        yield sse_file_change(**py_change)
                        write_key = f"code_execution::{os.path.normcase(modified_path)}"
                        completed_write_ops[write_key] = completed_write_ops.get(write_key, 0) + 1

                # Track successful write operations for cross-round dedup
                # Treat both "Error: ..." strings and {"error": ...} JSON as failures.
                _is_success = not result_str.startswith("Error:")
                if _is_success:
                    try:
                        _p = json.loads(result_str)
                        if isinstance(_p, dict) and _p.get("error"):
                            _is_success = False
                    except Exception:
                        pass
                if tool_name in _MODIFIER_TOOLS and _is_success:
                    canonical_target = self._canonical_write_target(tool_name, tool_args)
                    write_key = f"{tool_name}::{canonical_target}"
                    completed_write_ops[write_key] = completed_write_ops.get(write_key, 0) + 1

                _step_done_text = (
                    "代码执行完成"
                    if _code_exec_had_koto_changes
                    else _tool_completion_summary(tool_name, tool_args, preview_text)
                )
                yield sse_step_done(current_step_id, _step_done_text)

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
                _successful_rounds += 1
            elif batch_had_error:
                last_successful_tool_batch_signature = None
                last_successful_tool_batch_summary = ""

            # ── Local early-exit: file written → stop immediately ──────
            # For local mode, once a file change is confirmed this batch there is
            # no benefit letting the model run additional verification rounds.
            # Break now so the Done section emits the correct final SSE event.
            if _is_local and batch_file_changes and has_detected_file_change and not batch_had_error:
                final_summary = "任务完成"
                break

            # ── TAOR: Observe ──────────────────────────────────────────
            # Inject a structured observation note so the LLM knows exactly
            # what happened and can plan the next step accurately.
            if not _is_local and tool_calls:
                observe_note = _build_observe_note(
                    round_num=rounds,
                    tool_calls=tool_calls,
                    tool_results=batch_tool_results,
                    file_changes=batch_file_changes,
                    errors=batch_errors,
                )
                messages.append({"role": "user", "content": observe_note})

            # ── TAOR: Reflect ──────────────────────────────────────────
            # Every _REFLECT_EVERY_N_ROUNDS successful rounds (and not immediately
            # after injecting the previous Reflect), prompt the LLM to recalibrate.
            if (
                not _is_local
                and _successful_rounds > 0
                and _successful_rounds % _REFLECT_EVERY_N_ROUNDS == 0
                and rounds != _reflect_injected_at
            ):
                _reflect_injected_at = rounds
                messages.append({"role": "user", "content": _REFLECT_PROMPT})

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

        parts = ["## ═══ 本次任务文件（以下文件是当前任务的目标，历史对话中的文件与本次任务无关）═══\n"]
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

    def _build_user_message(self, task: str, file_context: str) -> str:
        """Compose the user message with task + file context."""
        parts = [f"## 任务\n\n{task}"]
        if file_context:
            parts.append(file_context)
        return "\n\n".join(parts)

    def _build_conversation_messages(
        self,
        user_message: str,
        history: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        import re as _re
        _file_ctx_pat = _re.compile(
            r"##\s*(?:当前文件上下文|═+\s*本次任务文件[^#]*═+)[^\n]*\n.*",
            _re.DOTALL,
        )
        messages: List[Dict[str, str]] = []
        for item in history:
            role = str(item.get("role") or "").strip().lower()
            if role not in {"user", "model"}:
                continue
            content = item.get("content", "")
            # Strip file context blocks from historical user messages to avoid
            # cross-task file confusion (old files contaminating the current task)
            if role == "user":
                content = _file_ctx_pat.sub("", content).strip()
            content = _sample_context_text(content, _HISTORY_MESSAGE_CONTEXT_LIMIT)
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

    def _build_registry(
        self,
        files: Optional[List[Dict[str, str]]] = None,
        options: Optional[Dict[str, Any]] = None,
    ):
        """Build a ToolRegistry with TaskTools."""
        from app.core.agent.task_tools import TaskToolsPlugin
        from app.core.agent.tool_registry import ToolRegistry

        registry = ToolRegistry()
        registry.register_plugin(TaskToolsPlugin(
            socketio=self._socketio,
            task_files=files,
            model_id=self._model_id,
            api_key=self._api_key,
            options=options or {},
        ))
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
            or "modify"
        )
        summary = payload.get("summary") or f"{Path(str(path)).name} 已更新"
        preview = payload.get("preview") or change.get("modified") or ""
        focus = bool(payload.get("focus"))

        # Try to get actual file size for richer display
        file_size = 0
        try:
            if os.path.isfile(str(path)):
                file_size = os.path.getsize(str(path))
        except Exception:
            pass

        return {
            "path": str(path),
            "file_type": file_type,
            "operation": payload.get("operation") or tool_name,
            "summary": str(summary),
            "preview": str(preview),
            "change_type": change_type,
            "focus": focus,
            "file_size": file_size,
        }

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
            from app.core.llm.gemini import GeminiProvider

            api_key = self._api_key
            if not api_key:
                api_key = (
                    os.environ.get("GEMINI_API_KEY")
                    or os.environ.get("API_KEY")
                    or os.environ.get("GOOGLE_API_KEY")
                )
            if not api_key:
                logger.error("[TaskAgent] No API key available")
                return None
            return GeminiProvider(api_key=api_key)
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
        call_timeout: Optional[float] = None,
    ) -> dict:
        """Call the LLM with messages and tools. Returns response dict."""
        effective_timeout = call_timeout if call_timeout is not None else _FILE_TASK_LLM_CALL_TIMEOUT
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
                call_timeout=effective_timeout,
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
                call_timeout=effective_timeout,
            )
        except ImportError:
            return provider.generate_content(
                prompt=messages,
                model=self._model_id,
                system_instruction=system,
                tools=tool_defs if tool_defs else None,
                stream=False,
                call_timeout=effective_timeout,
            )
