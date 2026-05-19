from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskExecutionContext,
    FileTaskExecutionBrief,
    FileTaskEvent,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskLedger,
    FileTaskRequest,
    FileTaskToolStreamChunk,
    FileTaskToolStreamResult,
)
from app.core.agent.file_task_intent_planner import FileTaskIntentPlanner
from app.core.agent.file_task_capability import (
    build_request_capability_profiles,
    matched_native_capability_names,
    native_tool_gap_for_request,
)
from app.core.agent.file_task_model import FileTaskModelClient
from app.core.agent.file_task_validation import (
    build_file_task_requirements,
    validate_file_task_plan,
)
from app.core.agent.file_task_tool_catalog import (
    extract_koto_paths,
    extract_sandbox_artifacts,
    file_states_for_changes,
    is_file_task_tool,
    is_write_tool,
    parse_file_change,
    supported_file_workflows,
    tool_result_preview,
    stringify_result,
    write_target_for_tool,
)
from app.core.agent.file_task_tool_gateway import (
    FileTaskToolContext,
    FileTaskToolGateway,
    FileTaskToolProvider,
    ToolExecutor,
)
from app.core.agent.tool_design_protocol import (
    TOOL_DESIGN_PROTOCOL,
    build_next_action_artifact,
    extract_first_json_value,
    extract_tool_gap_from_response,
    merge_tool_gaps,
    tool_design_prompt_text,
)
from app.core.shared.tool_parser import parse_task_tool_calls

logger = logging.getLogger(__name__)

ModelCaller = Callable[..., Dict[str, Any]]


_READ_LIMIT = 12_000
_WRITE_INTENT_WORDS = (
    "修改", "写入", "生成", "创建", "替换", "插入", "更新", "保存", "导出",
    "写回", "加入", "添加", "追加", "附加", "导入", "合并", "填入", "填充", "批注", "标注", "审校", "校对",
    "润色", "改写", "重写",
    "美化", "排版", "套用主题", "应用主题", "设计主题", "设计风格",
    "fill", "write", "create", "insert", "update", "replace", "export",
    "add", "append", "import", "merge", "theme", "layout", "template", "style", "annotate", "comment", "review", "proofread",
    "rewrite", "polish",
)
_WRITE_INTENT_PATTERNS = (
    re.compile(r"放(?:到|进|入).{0,24}(?:页|页里|幻灯片|slide|slides)", re.IGNORECASE),
    re.compile(r"(?:新增|添加|生成|新建).{0,12}(?:页|幻灯片|slide|slides)", re.IGNORECASE),
    re.compile(r"(?:总结|概括).{0,20}(?:放(?:到|进|入)|生成).{0,20}(?:页|幻灯片|slide|slides)", re.IGNORECASE),
    re.compile(r"(?:pptx?|slides?|幻灯片|演示文稿).{0,24}(?:补充|充实|扩写|完善).{0,18}(?:每一页|每页|逐页|各页|内容|文字|文本|页|slide|slides)", re.IGNORECASE),
    re.compile(r"(?:每一页|每页|逐页|各页).{0,24}(?:补充|充实|扩写|完善).{0,18}(?:内容|文字|文本|页|slide|slides)?", re.IGNORECASE),
)
_EXPLICIT_WRITE_INTENT_WORDS = (
    "写入", "写回", "保存", "导出", "插入", "替换", "更新到", "应用到", "应用进", "同步到",
    "填入", "填充", "附加", "追加", "导入", "合并", "创建文件", "新建文件", "批注", "标注", "审校", "校对",
    "write back", "save", "export", "insert", "replace", "append",
)
_SOFT_WRITE_ACTION_WORDS = (
    "修改", "更新", "添加", "生成", "创建", "润色", "改写", "重写", "补充", "充实", "完善", "美化", "排版",
)
_WRITE_TARGET_HINT_WORDS = (
    "文件", "文档", "word", "docx", "ppt", "pptx", "幻灯片", "slide", "slides", "页面", "页",
    "excel", "xlsx", "工作表", "sheet", "表格", "当前", "目标", "译稿", "原文", "文本", "段落",
)
_ANALYSIS_ADVICE_PATTERNS = (
    re.compile(r"(?:看看|看下|分析|评估|审查|review|review一下).{0,32}(?:哪些|哪里|什么地方|哪部分).{0,20}(?:需要|可以)?(?:修改|改进|优化|调整)", re.IGNORECASE),
    re.compile(r"(?:哪些|哪里|什么地方|哪部分).{0,16}(?:需要|可以)?(?:修改|改进|优化|调整)(?:的地方|之处)?", re.IGNORECASE),
    re.compile(r"(?:修改建议|改进建议|优化建议|调整建议)", re.IGNORECASE),
    re.compile(r"(?:从大方向上|整体上|方向上).{0,12}(?:修改|改进|优化)", re.IGNORECASE),
)
_ANALYSIS_CUE_WORDS = (
    "分析", "看看", "看下", "评估", "审查", "review", "指出", "列出", "说明", "找出", "发现",
)
_ADVICE_CUE_WORDS = (
    "修改", "改进", "优化", "调整", "建议", "问题", "风险", "方向",
)
_DIAGNOSTIC_REQUEST_PATTERNS = (
    re.compile(r"^\s*(?:为什么|为啥|为何|怎么会|怎么没有|为什么没有|为什么没|失败原因|原因是什么|怎么回事|哪里出了问题|请解释|解释一下|说明一下|帮我解释|帮我说明)", re.IGNORECASE),
    re.compile(r"^\s*(?:这个任务|这次任务|这个结果|这次结果|上一轮|上次|这轮|这个流程|这次审校).{0,18}(?:为什么|为啥|为何|失败|出错|不对|有问题)", re.IGNORECASE),
    re.compile(r"(?:为什么|为啥|为何).{0,20}(?:任务|结果|审校|修订|写回|批注|修改|删除|失败|报错|权限|permission denied)", re.IGNORECASE),
)
_DIAGNOSTIC_NEW_TASK_PATTERNS = (
    re.compile(r"(?:并|然后|顺便|同时).{0,8}(?:请|帮我|直接)?(?:修改|删除|写入|应用|批注|润色|重写|继续处理|重新执行)", re.IGNORECASE),
    re.compile(r"(?:请|帮我|麻烦).{0,6}(?:直接|顺便)?(?:修改|删除|写入|应用|批注|润色|重写|继续处理|重新执行)", re.IGNORECASE),
)
_IMPERATIVE_WRITE_PATTERNS = (
    re.compile(r"^(?:请|帮我|麻烦)?(?:把|将)?(?:这个|当前|这份|该)?(?:文件|文档|word|ppt|表格|内容|文本|段落|译稿|稿件).{0,12}(?:修改|更新|润色|改写|重写|补充|完善)", re.IGNORECASE),
    re.compile(r"^(?:请|帮我|麻烦)?(?:直接|立刻)?(?:修改|更新|润色|改写|重写|补充|完善).{0,16}(?:文件|文档|word|ppt|表格|内容|文本|段落|译稿|稿件)", re.IGNORECASE),
)
_DOCX_ANNOTATE_INTENT_WORDS = (
    "批注", "标注", "审校", "校对", "润色", "批改", "修改建议", "写得不好的地方", "不通顺", "不自然",
    "comment", "annotate", "proofread", "polish",
)
_MAX_MODEL_ROUNDS = 6
_MAX_VERIFY_REPAIR_ATTEMPTS = 2
_MAX_WRITE_OPS_PER_FILE = 1
_KOTO_CREATED_MARKER = "__koto_created__:"
_KOTO_MODIFIED_MARKER = "__koto_modified__:"


def _preview(value: Any, limit: int = 700) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _compact_line(value: Any, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _json_payload(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_error_result(value: Any) -> bool:
    payload = _json_payload(value)
    if payload.get("error"):
        return True
    text = str(value or "").strip()
    return text.startswith(("Error:", "Sandbox error:", "[error]")) or "\n[error]" in text


def _sanitize_followup_file_changes(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return []
    if not isinstance(value, list):
        return []

    cleaned: List[Dict[str, Any]] = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        entry: Dict[str, Any] = {}
        for key in (
            "path",
            "file_type",
            "operation",
            "summary",
            "source_path",
            "sheet",
            "requested_sheet",
            "table_title",
            "change_type",
            "original_target_path",
        ):
            text = str(item.get(key) or "").strip()
            if text:
                entry[key] = _preview(text, 400)
        for key in ("rows_written", "columns_written"):
            raw_value = item.get(key)
            if raw_value in (None, ""):
                continue
            try:
                entry[key] = int(raw_value)
            except Exception:
                continue
        if bool(item.get("fallback_copy")):
            entry["fallback_copy"] = True
        if entry:
            cleaned.append(entry)
    return cleaned


def _followup_has_prior_excel_docx_insert(followup_context: Dict[str, Any]) -> bool:
    for change in _sanitize_followup_file_changes(followup_context.get("previous_task_file_changes")):
        if str(change.get("operation") or "").strip() == "insert_excel_as_docx_table":
            return True
    return False


class FileTaskRuntime:
    """First Koto-native whitebox runtime for file-assistant complex tasks.

    Typed file-task runtime with an allowlisted model -> tool -> checker loop.

    The model can plan and call tools freely, but only through the Koto-native
    tool catalog. The runtime owns event logging, duplicate-write guards, file
    change detection, and final verification.
    """

    def __init__(
        self,
        *,
        tool_executor: Optional[ToolExecutor] = None,
        tool_provider: Optional[FileTaskToolProvider] = None,
        tool_gateway: Optional[FileTaskToolGateway] = None,
        model_client: Optional[FileTaskModelClient | ModelCaller] = None,
        intent_planner: Optional[FileTaskIntentPlanner] = None,
        gemini_client: Any = None,
        workspace_root: str = "",
        max_rounds: int = _MAX_MODEL_ROUNDS,
    ):
        self._tool_executor = tool_executor
        self._tool_provider = tool_provider
        self._tool_gateway = tool_gateway
        self._model_client = model_client or FileTaskModelClient()
        self._intent_planner = intent_planner or FileTaskIntentPlanner()
        self._gemini_client = gemini_client
        self._workspace_root = workspace_root
        self._max_rounds = max(1, int(max_rounds or _MAX_MODEL_ROUNDS))

    def run(self, request: FileTaskRequest) -> Iterable[FileTaskEvent]:
        from app.core.agent import file_task_doc_annotate_bridge

        ledger = FileTaskLedger(request.run_id)

        if file_task_doc_annotate_bridge.should_route_request(request):
            yield ledger.event(
                "plan.checked",
                {
                    "passed": True,
                    "status": "pass",
                    "summary": "文档批注路由检查通过。",
                    "routing": "doc_annotate_bridge",
                    "requirements": {},
                    "violations": [],
                },
                step_id="plan",
            )
            terminal_event: Optional[FileTaskEvent] = None
            terminal_status = "needs_attention"
            terminal_summary = ""

            for event in file_task_doc_annotate_bridge.stream_request(
                request,
                workspace_root=self._workspace_root,
                gemini_client=self._gemini_client,
            ):
                if event.type == "run.finished":
                    terminal_event = event
                    terminal_payload = event.payload if isinstance(event.payload, dict) else {}
                    terminal_summary = str(terminal_payload.get("summary") or "").strip()
                    runtime_payload = terminal_payload.get("runtime") if isinstance(terminal_payload.get("runtime"), dict) else {}
                    terminal_status = str(runtime_payload.get("terminal_status") or "").strip().lower() or (
                        "verified" if terminal_payload.get("completed_task") else "needs_attention"
                    )
                    if bool(terminal_payload.get("completed_task")):
                        yield event
                        return
                    continue
                if event.type == "run.error":
                    terminal_event = event
                    terminal_payload = event.payload if isinstance(event.payload, dict) else {}
                    terminal_summary = str(terminal_payload.get("text") or "").strip()
                    terminal_status = "failed"
                    continue
                yield event

            if terminal_event is None:
                return
            yield terminal_event
            return

        context_files = self._context_files(request)
        execution_context = self._build_execution_context(
            request,
            context_files,
            quick_action_mode=self._quick_action_mode(request),
        )
        known_tool_gap = execution_context.known_tool_gap
        classification = execution_context.classification
        intent_plan = execution_context.intent_plan
        requirements = execution_context.requirements
        plan_check = execution_context.plan_check
        quick_action_mode = execution_context.quick_action_mode
        simple_quick_action = execution_context.simple_quick_action
        write_intent = execution_context.write_intent
        gateway = self._build_tool_gateway(request, context_files)
        tool_defs = gateway.definitions()
        executor = gateway.execute

        classification_payload = classification.public_dict()
        intent_plan_payload = intent_plan.public_dict()
        requirements_payload = requirements.public_dict()
        plan_check_payload = plan_check.public_dict()
        plan_runtime = self._build_runtime_metadata(
            terminal_status="plan_checked",
            readonly_fallback_used=False,
            model_failed=False,
            planner_payload={
                "backend": execution_context.effective_planner_backend or "native",
                "source": "native",
                "policy": execution_context.effective_planner_policy or "native_only",
                "transport": "native",
                "reason": execution_context.effective_planner_reason or "file_task_native_only",
                "round": 1,
            },
            planner_fallback_payload={},
        )

        yield ledger.event("run.started", {
            "task": request.task,
            "mode": "whitebox_v1",
            "file_count": len(context_files),
            "target_path": request.target_path,
            "model_mode": request.model_mode,
            "model_id": request.model_id,
            "quick_action_mode": quick_action_mode,
            **classification_payload,
            "intent_plan": intent_plan_payload,
        })

        if not simple_quick_action:
            yield ledger.event(
                "task.classified",
                execution_context.public_dict(),
                step_id="plan",
            )
        yield ledger.event(
            "plan.checked",
            {
                **plan_check_payload,
                "requirements": requirements_payload,
                **({
                    "quick_action_bypass": True,
                } if simple_quick_action else {}),
            },
            step_id="plan",
        )

        if not plan_check.passed:
            yield ledger.event("step.result", self._build_step_result_payload(
                title="规划检查",
                summary=plan_check.summary,
                status="failed",
                runtime=plan_runtime,
                passed=False,
            ), step_id="plan")
            yield ledger.event("run.finished", {
                "task": request.task,
                "mode": "whitebox_v1",
                "summary": plan_check.summary,
                "completed_task": False,
                "context": [],
                "file_changes": [],
                "runtime": plan_runtime,
                "quick_action_mode": quick_action_mode,
                "intent_plan": intent_plan_payload,
                "requirements": requirements_payload,
                "plan_check": plan_check_payload,
                **classification_payload,
            })
            return

        plan_steps = intent_plan.dynamic_steps or self._build_plan(
            request,
            context_files,
            write_intent,
            classification.output_mode,
            known_tool_gap,
        )
        if not simple_quick_action:
            yield ledger.event("plan.created", {
                "summary": self._plan_summary(request, context_files, write_intent),
                "steps": plan_steps,
                "success_criteria": self._success_criteria(request, write_intent, classification.output_mode),
                "tool_families": supported_file_workflows(),
                "intent_plan": intent_plan_payload,
            })

        context_step_id = "context"
        yield ledger.event("step.started", {
            "title": "读取显式上下文",
            "detail": "只使用用户附加、选中或明确指向的文件。",
        }, step_id=context_step_id)

        snippets: List[Dict[str, Any]] = []
        if request.selection:
            snippets.append({
                "source": request.selection_source or "selection",
                "preview": _preview(request.selection, 500),
                "chars": len(request.selection),
            })
            yield ledger.event("tool.finished", {
                "tool_name": "selection_context",
                "success": True,
                "result_preview": _preview(request.selection, 500),
            }, step_id=context_step_id)

        for file_info in context_files:
            if file_info.content:
                snippets.append({
                    "source": file_info.name or file_info.path,
                    "path": file_info.path,
                    "preview": _preview(file_info.content, 500),
                    "chars": len(file_info.content),
                })
                yield ledger.event("tool.finished", {
                    "tool_name": "provided_file_context",
                    "success": True,
                    "path": file_info.path,
                    "result_preview": _preview(file_info.content, 500),
                }, step_id=context_step_id)
                continue

            if not file_info.path:
                continue
            args = {"path": file_info.path, "max_chars": _READ_LIMIT}
            yield ledger.event("tool.started", {
                "tool_name": "parse_file_to_text",
                "tool_args": args,
            }, step_id=context_step_id)
            try:
                result = executor("parse_file_to_text", args)
                success = not _is_error_result(result)
            except Exception as exc:
                result = str(exc)
                success = False
                logger.warning("[FileTaskRuntime] parse_file_to_text failed: %s", exc)
            yield ledger.event("tool.finished", {
                "tool_name": "parse_file_to_text",
                "success": success,
                "result_preview": _preview(result),
            }, step_id=context_step_id)
            if success:
                snippets.append({
                    "source": file_info.name or file_info.path,
                    "path": file_info.path,
                    "preview": _preview(result, 500),
                    "chars": len(str(result or "")),
                })

        context_summary = f"已整理 {len(snippets)} 份上下文片段。" if snippets else "没有显式文件或选区可读取。"
        yield ledger.event("step.finished", {
            "summary": context_summary,
        }, step_id=context_step_id)
        yield ledger.event("step.result", self._build_step_result_payload(
            title="读取显式上下文",
            summary=context_summary,
            status="completed" if snippets else "needs_attention",
            snippet_count=len(snippets),
            snippets=snippets,
        ), step_id=context_step_id)

        execute_step_id = "execute"
        yield ledger.event("step.started", {
            "title": "模型规划并调用工具",
            "detail": "模型只能调用 Koto 文件工具目录中的 allowlist 工具。",
            "max_rounds": self._max_rounds,
        }, step_id=execute_step_id)

        messages = self._build_messages(
            request,
            snippets,
            context_files,
            known_tool_gap,
            classification,
            intent_plan,
            execution_context=execution_context,
        )
        system = self._build_system_prompt(
            request,
            context_files,
            known_tool_gap,
            classification,
            intent_plan,
            execution_context=execution_context,
        )
        model_request = self._initial_model_request(request)
        completed_write_ops: Dict[str, int] = {}
        file_changes: List[Dict[str, Any]] = []
        final_summary = ""
        completed_task = False
        model_failed = False
        readonly_fallback_used = False
        last_tool_batch_signature = ""
        planner_runtime_payload: Dict[str, Any] = {}
        planner_fallback_runtime_payload: Dict[str, Any] = {}
        last_tool_gap_signature = ""
        plan_confirmed_emitted = False
        last_execution_brief_signature = ""
        write_guard_injected = False
        repair_attempts = 0
        last_check_payload: Optional[Dict[str, Any]] = None
        tool_gap: Optional[Dict[str, Any]] = None
        next_action_artifact: Optional[Dict[str, Any]] = None
        tool_runtime_outcome: Optional[Dict[str, Any]] = None

        for round_index in range(1, self._max_rounds + 1):
            planner_fallback_runtime_payload = {}
            try:
                response = self._call_model(request=model_request, messages=messages, system=system, tools=tool_defs)
            except Exception as exc:
                logger.warning("[FileTaskRuntime] model call failed: %s", exc)
                fallback_summary = "" if write_intent else self._fallback_readonly_summary(
                    request,
                    snippets,
                    context_files,
                    exc,
                )
                if fallback_summary:
                    readonly_fallback_used = True
                    completed_task = True
                    final_summary = fallback_summary
                    yield ledger.event("tool.finished", {
                        "tool_name": "model_message",
                        "success": True,
                        "fallback": True,
                        "model_unavailable": True,
                        "result_preview": fallback_summary,
                    }, step_id=execute_step_id)
                    yield ledger.event("step.result", self._build_step_result_payload(
                        title="模型规划并调用工具",
                        summary=fallback_summary,
                        status="completed",
                        round_index=round_index,
                    ), step_id=execute_step_id)
                else:
                    model_failed = True
                    error_text = f"模型调用失败：{exc}"
                    yield ledger.event("run.error", {
                        "text": error_text,
                        "recoverable": not write_intent,
                    }, step_id=execute_step_id)
                    yield ledger.event("step.result", self._build_step_result_payload(
                        title="模型规划并调用工具",
                        summary=error_text,
                        status="failed",
                        round_index=round_index,
                    ), step_id=execute_step_id)
                break

            planner_runtime_payload = {
                "backend": execution_context.effective_planner_backend or "native",
                "source": "native",
                "policy": execution_context.effective_planner_policy or "native_only",
                "transport": "native",
                "reason": execution_context.effective_planner_reason or "file_task_native_only",
                "round": round_index,
            }
            planner_meta = dict(planner_runtime_payload)

            tool_gap = extract_tool_gap_from_response(response)
            if tool_gap and known_tool_gap:
                tool_gap = merge_tool_gaps(tool_gap, known_tool_gap)
            content_text, tool_calls = self._normalize_model_response(response, tool_defs)
            execution_brief, content_text = self._extract_execution_brief(response, content_text)
            external_planner_request = False
            if (
                not tool_gap
                and known_tool_gap
                and not tool_calls
                and not external_planner_request
                and not bool((model_request.options or {}).get("planner_runtime_fallback_attempted"))
            ):
                tool_gap = known_tool_gap

            if execution_brief:
                brief_payload = execution_brief.public_dict()
                brief_signature = json.dumps(brief_payload, ensure_ascii=False, sort_keys=True, default=str)
                if brief_signature != last_execution_brief_signature:
                    last_execution_brief_signature = brief_signature
                    yield ledger.event("plan.briefed", brief_payload, step_id=execute_step_id)

            if tool_gap:
                gap_runtime = self._build_runtime_metadata(
                    terminal_status="tool_gap",
                    readonly_fallback_used=readonly_fallback_used,
                    model_failed=model_failed,
                    planner_payload=planner_runtime_payload,
                    planner_fallback_payload=planner_fallback_runtime_payload,
                )
                next_action_artifact = self._with_runtime_context(
                    build_next_action_artifact(request, tool_gap),
                    gap_runtime,
                )
                gap_payload = {
                    "summary": str(tool_gap.get("summary") or ""),
                    "missing_capability": str(tool_gap.get("missing_capability") or ""),
                    "why_missing": str(tool_gap.get("why_missing") or ""),
                    "suggested_next_step": str(tool_gap.get("suggested_next_step") or ""),
                    "proposed_tool": tool_gap.get("proposed_tool") if isinstance(tool_gap.get("proposed_tool"), dict) else None,
                    "next_action_artifact": next_action_artifact,
                    "runtime": gap_runtime,
                    "round": round_index,
                }
                gap_signature = json.dumps(gap_payload, ensure_ascii=False, sort_keys=True, default=str)
                if gap_signature != last_tool_gap_signature:
                    last_tool_gap_signature = gap_signature
                    yield ledger.event("tool.missing", gap_payload, step_id=execute_step_id)

            if tool_calls and not plan_confirmed_emitted:
                plan_confirmed_emitted = True
                yield ledger.event(
                    "plan.confirmed",
                    self._build_confirmed_plan(
                        request,
                        context_files,
                        tool_calls,
                        write_intent,
                        content_text,
                    ),
                    step_id=execute_step_id,
                )

            if content_text and (not tool_calls or len(content_text) <= 220):
                yield ledger.event("tool.finished", {
                    "tool_name": "model_message",
                    "success": True,
                    "result_preview": _preview(content_text, 600),
                }, step_id=execute_step_id)

            model_turn: Dict[str, Any] = {"role": "model", "content": content_text or ""}
            if tool_calls:
                for tool_call in tool_calls:
                    tool_call.setdefault("id", uuid.uuid4().hex[:8])
                model_turn["tool_calls"] = tool_calls
            raw_parts = response.get("_raw_parts") if isinstance(response, dict) else None
            if raw_parts:
                model_turn["parts"] = raw_parts
            if tool_gap:
                model_turn["tool_gap"] = tool_gap
            messages.append(model_turn)

            if not tool_calls:
                if tool_gap:
                    final_summary = content_text or str(tool_gap.get("summary") or "当前任务缺少对应的 Koto 原生工具。")
                    completed_task = False
                    yield ledger.event("step.result", self._build_step_result_payload(
                        title="模型规划并调用工具",
                        summary=final_summary,
                        status="failed",
                        round_index=round_index,
                        file_changes=file_changes,
                        next_action_artifact=next_action_artifact,
                    ), step_id=execute_step_id)
                    break
                if execution_brief and round_index < self._max_rounds:
                    model_request = self._request_after_execution_brief(request, model_request, execution_brief)
                    reminder = self._execution_brief_continue_message(request, execution_brief)
                    final_summary = execution_brief.summary or content_text or "已完成任务分析，准备继续执行。"
                    yield ledger.event("step.result", self._build_step_result_payload(
                        title="模型规划并调用工具",
                        summary=final_summary,
                        status="pending",
                        round_index=round_index,
                        file_changes=file_changes,
                    ), step_id=execute_step_id)
                    messages.append({"role": "user", "content": reminder})
                    continue
                runtime_status = self._tool_runtime_status(tool_runtime_outcome)
                awaiting_confirmation = runtime_status == "awaiting_confirmation"
                terminal_write_blocked = runtime_status in {"blocked", "write_blocked"}
                if write_intent and not file_changes and not awaiting_confirmation and not terminal_write_blocked and not write_guard_injected and round_index < self._max_rounds:
                    write_guard_injected = True
                    reminder = self._write_retry_message(request, context_files)
                    yield ledger.event("tool.finished", {
                        "tool_name": "write_guard",
                        "success": False,
                        "result_preview": reminder,
                    }, step_id=execute_step_id)
                    messages.append({"role": "user", "content": reminder})
                    final_summary = content_text or "模型未再请求工具调用。"
                    yield ledger.event("step.result", self._build_step_result_payload(
                        title="模型规划并调用工具",
                        summary=reminder,
                        status="needs_attention",
                        round_index=round_index,
                    ), step_id=execute_step_id)
                    continue
                if write_intent:
                    last_check_payload = self._verify_task(
                        request,
                        executor,
                        file_changes,
                        write_intent,
                        classification.output_mode,
                        model_failed,
                        readonly_fallback_used=readonly_fallback_used,
                        tool_runtime_outcome=tool_runtime_outcome,
                        tool_gap=tool_gap,
                        next_action_artifact=next_action_artifact,
                    )
                    if self._should_attempt_repair(
                        last_check_payload,
                        round_index=round_index,
                        repair_attempts=repair_attempts,
                    ):
                        repair_attempts += 1
                        repair_runtime = self._build_runtime_metadata(
                            terminal_status=str(last_check_payload.get("status") or "").strip(),
                            readonly_fallback_used=readonly_fallback_used,
                            model_failed=model_failed,
                            planner_payload=planner_runtime_payload,
                            planner_fallback_payload=planner_fallback_runtime_payload,
                        )
                        repair_check_payload = dict(last_check_payload)
                        repair_check_payload["runtime"] = repair_runtime
                        repair_check_payload["repair_attempt"] = repair_attempts
                        yield ledger.event("check.started", {
                            "title": "检查执行状态",
                            "criteria": self._success_criteria(request, write_intent, classification.output_mode),
                            "repair_attempt": repair_attempts,
                        }, step_id="check")
                        yield ledger.event("check.finished", repair_check_payload, step_id="check")
                        yield ledger.event("step.result", self._build_step_result_payload(
                            title="检查执行状态",
                            summary=str(repair_check_payload.get("summary") or "检查未通过。"),
                            status="completed" if repair_check_payload.get("passed") else "needs_attention",
                            runtime=repair_runtime,
                            passed=repair_check_payload.get("passed"),
                            file_changes=file_changes,
                            next_action_artifact=repair_check_payload.get("next_action_artifact"),
                        ), step_id="check")
                        repair_message = self._repair_retry_message(request, last_check_payload, file_changes)
                        yield ledger.event("tool.finished", {
                            "tool_name": "repair_guard",
                            "success": False,
                            "result_preview": repair_message,
                        }, step_id=execute_step_id)
                        messages.append({"role": "user", "content": repair_message})
                        completed_write_ops.clear()
                        last_check_payload = None
                        final_summary = repair_check_payload.get("summary") or content_text or "核验未通过，准备修复。"
                        continue
                    check_status = str(last_check_payload.get("status") or "").strip().lower()
                    final_summary = content_text or str(last_check_payload.get("summary") or "模型未再请求工具调用。")
                    completed_task = bool(last_check_payload.get("passed"))
                    yield ledger.event("step.result", self._build_step_result_payload(
                        title="模型规划并调用工具",
                        summary=self._execute_step_summary(
                            round_index=round_index,
                            final_summary=final_summary,
                            model_failed=model_failed,
                            tool_gap=tool_gap,
                            file_changes=file_changes,
                            tool_runtime_outcome=tool_runtime_outcome,
                        ),
                        status=self._execute_step_result_status(
                            completed=completed_task,
                            tool_gap=tool_gap,
                            tool_runtime_outcome=tool_runtime_outcome,
                            model_failed=model_failed,
                        ),
                        round_index=round_index,
                        file_changes=file_changes,
                        next_action_artifact=next_action_artifact,
                    ), step_id=execute_step_id)
                    break
                final_summary = content_text or "模型未再请求工具调用。"
                completed_task = not write_intent or bool(file_changes)
                yield ledger.event("step.result", self._build_step_result_payload(
                    title="模型规划并调用工具",
                    summary=self._execute_step_summary(
                        round_index=round_index,
                        final_summary=final_summary,
                        model_failed=model_failed,
                        tool_gap=tool_gap,
                        file_changes=file_changes,
                        tool_runtime_outcome=tool_runtime_outcome,
                    ),
                    status=self._execute_step_result_status(
                        completed=completed_task,
                        tool_gap=tool_gap,
                        tool_runtime_outcome=tool_runtime_outcome,
                        model_failed=model_failed,
                    ),
                    round_index=round_index,
                    file_changes=file_changes,
                    next_action_artifact=next_action_artifact,
                ), step_id=execute_step_id)
                break

            batch_signature = self._tool_batch_signature(tool_calls)
            if batch_signature and batch_signature == last_tool_batch_signature:
                final_summary = "检测到重复工具调用，已自动停止以避免重复写入。"
                yield ledger.event("tool.finished", {
                    "tool_name": "duplicate_guard",
                    "success": True,
                    "skipped": True,
                    "result_preview": final_summary,
                }, step_id=execute_step_id)
                yield ledger.event("step.result", self._build_step_result_payload(
                    title="模型规划并调用工具",
                    summary=final_summary,
                    status="needs_attention",
                    round_index=round_index,
                    file_changes=file_changes,
                ), step_id=execute_step_id)
                break
            last_tool_batch_signature = batch_signature

            for tool_index, tool_call in enumerate(tool_calls, start=1):
                tool_name = str(tool_call.get("name") or "").strip()
                tool_args = dict(tool_call.get("args") or {})
                tool_call_id = str(tool_call.get("id") or uuid.uuid4().hex[:8])
                current_step_id = f"tool_{round_index}_{tool_index}"

                if not is_file_task_tool(tool_name):
                    error_text = f"工具 {tool_name or '<empty>'} 不在 Koto 文件任务 allowlist 中。"
                    yield ledger.event("tool.finished", {
                        "tool_name": tool_name,
                        "success": False,
                        "result_preview": error_text,
                    }, step_id=current_step_id)
                    messages.append({
                        "role": "function",
                        "name": tool_name or "invalid_tool",
                        "tool_call_id": tool_call_id,
                        "content": self._tool_feedback_for_model(
                            tool_name or "invalid_tool",
                            tool_args,
                            {"error": error_text},
                            success=False,
                            invalid=True,
                        ),
                    })
                    continue

                if is_write_tool(tool_name) and tool_name != "run_python_code":
                    target = write_target_for_tool(tool_name, tool_args)
                    write_key = f"{tool_name}::{target}"
                    if completed_write_ops.get(write_key, 0) >= _MAX_WRITE_OPS_PER_FILE:
                        skip_text = f"{tool_name} 已成功写入过 {target or '同一目标'}，本次跳过以避免重复覆盖。"
                        yield ledger.event("tool.finished", {
                            "tool_name": tool_name,
                            "success": True,
                            "skipped": True,
                            "result_preview": skip_text,
                        }, step_id=current_step_id)
                        messages.append({
                            "role": "function",
                            "name": tool_name,
                            "tool_call_id": tool_call_id,
                            "content": self._tool_feedback_for_model(
                                tool_name,
                                tool_args,
                                {"summary": skip_text},
                                success=True,
                                skipped=True,
                            ),
                        })
                        continue

                yield ledger.event("tool.started", {
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "round": round_index,
                }, step_id=current_step_id)

                blocked_message = self._blocked_run_python_message(tool_name, tool_args, request, context_files)
                if blocked_message:
                    yield ledger.event("tool.finished", {
                        "tool_name": tool_name,
                        "success": False,
                        "blocked": True,
                        "result_preview": blocked_message,
                    }, step_id=current_step_id)
                    messages.append({
                        "role": "function",
                        "name": tool_name,
                        "tool_call_id": tool_call_id,
                        "content": self._tool_feedback_for_model(
                            tool_name,
                            tool_args,
                            {"error": blocked_message},
                            success=False,
                            blocked=True,
                        ),
                    })
                    continue

                if tool_name == "run_python_code":
                    yield ledger.event("code.started", {
                        "code": str(tool_args.get("code") or ""),
                    }, step_id=current_step_id)

                try:
                    result = executor(tool_name, tool_args)
                    if isinstance(result, FileTaskToolStreamResult):
                        result = yield from self._consume_streaming_tool_result(
                            ledger,
                            step_id=current_step_id,
                            stream_result=result,
                        )
                    success = not _is_error_result(result)
                except Exception as exc:
                    result = f"Error: {exc}"
                    success = False
                    logger.warning("[FileTaskRuntime] tool %s failed: %s", tool_name, exc)

                model_result = self._tool_result_for_model(tool_name, result)
                current_tool_runtime_outcome = self._extract_tool_runtime_outcome(result)
                if current_tool_runtime_outcome:
                    tool_runtime_outcome = current_tool_runtime_outcome
                    artifact = current_tool_runtime_outcome.get("next_action_artifact")
                    if isinstance(artifact, dict):
                        next_action_artifact = artifact
                runtime_status = self._tool_runtime_status(current_tool_runtime_outcome)
                runtime_blocked = runtime_status in {"blocked", "write_blocked"}
                result_text = stringify_result(model_result)
                artifacts = self._tool_artifacts(tool_name, result)
                if tool_name == "run_python_code":
                    yield ledger.event("code.output", {
                        "text": self._code_output_preview(tool_name, result, result_text),
                        "stream": "stdout" if success else "stderr",
                    }, step_id=current_step_id)
                    yield ledger.event("code.finished", {
                        "success": success,
                    }, step_id=current_step_id)

                tool_finished_payload = {
                    "tool_name": tool_name,
                    "success": success,
                    "result_preview": tool_result_preview(tool_name, model_result, 1200),
                }
                if runtime_blocked:
                    tool_finished_payload["blocked"] = True
                if artifacts:
                    tool_finished_payload["artifacts"] = artifacts
                yield ledger.event("tool.finished", tool_finished_payload, step_id=current_step_id)

                messages.append({
                    "role": "function",
                    "name": tool_name,
                    "tool_call_id": tool_call_id,
                    "content": self._tool_feedback_for_model(
                        tool_name,
                        tool_args,
                        model_result,
                        success=success,
                        blocked=runtime_blocked,
                    ),
                })

                extracted_changes = self._extract_file_changes(tool_name, tool_args, result)
                if success and is_write_tool(tool_name) and tool_name != "run_python_code":
                    target = write_target_for_tool(tool_name, tool_args)
                    write_key = f"{tool_name}::{target}"
                    completed_write_ops[write_key] = completed_write_ops.get(write_key, 0) + 1

                for change in extracted_changes:
                    file_changes.append(change)
                    yield ledger.event("file.changed", change, step_id=current_step_id)

            execute_round_summary = self._execute_step_summary(
                round_index=round_index,
                final_summary=final_summary,
                model_failed=model_failed,
                tool_gap=tool_gap,
                file_changes=file_changes,
                tool_runtime_outcome=tool_runtime_outcome,
            )
            yield ledger.event("step.finished", {
                "title": "模型工具执行完成",
                "summary": execute_round_summary,
            }, step_id=execute_step_id)
            yield ledger.event("step.result", self._build_step_result_payload(
                title="模型工具执行完成",
                summary=execute_round_summary,
                status=self._execute_step_result_status(
                    completed=not model_failed and not tool_gap,
                    tool_gap=tool_gap,
                    tool_runtime_outcome=tool_runtime_outcome,
                    model_failed=model_failed,
                ),
                round_index=round_index,
                file_changes=file_changes,
                next_action_artifact=next_action_artifact,
            ), step_id=execute_step_id)
            if self._tool_runtime_status(tool_runtime_outcome) in {"blocked", "write_blocked"}:
                final_summary = execute_round_summary
                completed_task = False
                break

        check_step_id = "check"
        yield ledger.event("check.started", {
            "title": "检查执行状态",
            "criteria": self._success_criteria(request, write_intent, classification.output_mode),
        }, step_id=check_step_id)

        check_payload = dict(last_check_payload) if isinstance(last_check_payload, dict) else self._verify_task(
            request,
            executor,
            file_changes,
            write_intent,
            classification.output_mode,
            model_failed,
            readonly_fallback_used,
            tool_runtime_outcome,
            tool_gap,
            next_action_artifact,
        )
        terminal_runtime = self._build_runtime_metadata(
            terminal_status=str(check_payload.get("status") or "").strip(),
            readonly_fallback_used=readonly_fallback_used,
            model_failed=model_failed,
            planner_payload=planner_runtime_payload,
            planner_fallback_payload=planner_fallback_runtime_payload,
        )
        check_payload["runtime"] = terminal_runtime

        yield ledger.event("check.finished", check_payload, step_id=check_step_id)
        yield ledger.event("step.result", self._build_step_result_payload(
            title="检查执行状态",
            summary=str(check_payload.get("summary") or "检查完成。"),
            status=self._check_step_result_status(check_payload),
            runtime=terminal_runtime,
            passed=check_payload.get("passed"),
            file_changes=file_changes,
            next_action_artifact=check_payload.get("next_action_artifact") or next_action_artifact,
        ), step_id=check_step_id)
        run_summary = check_payload.get("summary") or final_summary or "任务执行结束。"
        if not write_intent and final_summary and not tool_gap:
            run_summary = final_summary
        run_payload = {
            "task": request.task,
            "mode": "whitebox_v1",
            "summary": run_summary,
            "completed_task": bool(check_payload.get("passed")) and (completed_task or not write_intent or bool(file_changes)),
            "context": snippets[:8],
            "file_changes": file_changes,
            "runtime": terminal_runtime,
            "quick_action_mode": quick_action_mode,
            **classification_payload,
        }
        if tool_gap:
            run_payload["tool_gap"] = tool_gap
        if next_action_artifact:
            run_payload["next_action_artifact"] = next_action_artifact
        yield ledger.event("run.finished", run_payload)

    def _build_runtime_metadata(
        self,
        *,
        terminal_status: str,
        readonly_fallback_used: bool,
        model_failed: bool,
        planner_payload: Optional[Dict[str, Any]] = None,
        planner_fallback_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        planner_payload = planner_payload if isinstance(planner_payload, dict) else {}
        planner_fallback_payload = planner_fallback_payload if isinstance(planner_fallback_payload, dict) else {}

        backend = str(planner_payload.get("backend") or "")
        source = str(planner_payload.get("source") or "")
        policy = str(planner_payload.get("policy") or "")
        transport = str(planner_payload.get("transport") or "")
        reason = str(planner_payload.get("reason") or "")
        fallback_from = str(planner_fallback_payload.get("from") or "")

        execution_path = "native"
        if readonly_fallback_used:
            execution_path = "readonly_fallback"
        elif fallback_from:
            execution_path = "planner_fallback"
        elif backend and backend != "native":
            execution_path = "planner"
        elif source and source != "native":
            execution_path = "planner"

        planner_runtime = {
            "backend": backend,
            "source": source,
            "policy": policy,
            "transport": transport,
            "reason": reason,
        }
        round_index = planner_payload.get("round")
        if round_index:
            planner_runtime["round"] = round_index
        if fallback_from:
            planner_runtime["fallback_from"] = fallback_from

        return {
            "execution_path": execution_path,
            "terminal_status": str(terminal_status or ""),
            "model_unavailable": bool(model_failed or readonly_fallback_used),
            "readonly_fallback_used": bool(readonly_fallback_used),
            "planner": planner_runtime,
        }

    def _with_runtime_context(
        self,
        artifact: Optional[Dict[str, Any]],
        runtime_metadata: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(artifact, dict) or not artifact:
            return artifact
        enriched = dict(artifact)
        enriched["runtime_context"] = dict(runtime_metadata)
        return enriched

    def _step_result_file_changes(self, file_changes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for change in file_changes[:8]:
            if not isinstance(change, dict):
                continue
            item: Dict[str, Any] = {}
            for key in (
                "path",
                "file_path",
                "file_type",
                "operation",
                "summary",
                "warning",
                "annotations_added",
                "rows_written",
                "columns_written",
                "requested_sheet",
                "sheet",
                "source_path",
                "slides_designed",
                "theme_name",
                "table_title",
            ):
                value = change.get(key)
                if value in (None, "", [], {}):
                    continue
                item[key] = value
            if item:
                items.append(item)
        return items

    def _build_step_result_payload(
        self,
        *,
        title: str,
        summary: str,
        status: str = "completed",
        round_index: int = 0,
        snippet_count: int = 0,
        snippets: Optional[List[Dict[str, Any]]] = None,
        file_changes: Optional[List[Dict[str, Any]]] = None,
        runtime: Optional[Dict[str, Any]] = None,
        passed: Optional[bool] = None,
        next_action_artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "title": str(title or "").strip() or "步骤结果",
            "summary": str(summary or "").strip() or str(title or "步骤结果").strip() or "步骤结果",
            "status": str(status or "completed").strip().lower() or "completed",
        }
        if round_index > 0:
            payload["round"] = int(round_index)
        if snippet_count > 0:
            payload["snippet_count"] = int(snippet_count)
        if snippets:
            payload["snippets"] = [dict(item) for item in snippets[:4] if isinstance(item, dict)]
        safe_changes = self._step_result_file_changes(file_changes or [])
        if safe_changes:
            payload["file_change_count"] = len(file_changes or [])
            payload["file_changes"] = safe_changes
        if isinstance(runtime, dict) and runtime:
            payload["runtime"] = dict(runtime)
        if passed is not None:
            payload["passed"] = bool(passed)
        if isinstance(next_action_artifact, dict) and next_action_artifact:
            payload["next_action_artifact"] = next_action_artifact
        return payload

    def _execute_step_summary(
        self,
        *,
        round_index: int,
        final_summary: str,
        model_failed: bool,
        tool_gap: Optional[Dict[str, Any]],
        file_changes: List[Dict[str, Any]],
        tool_runtime_outcome: Optional[Dict[str, Any]],
    ) -> str:
        summary = str(final_summary or "").strip()
        if summary:
            return summary
        runtime_status = self._tool_runtime_status(tool_runtime_outcome)
        if runtime_status == "awaiting_confirmation":
            return "已生成下一步执行方案，等待用户确认继续。"
        if runtime_status in {"blocked", "write_blocked"}:
            return str((tool_runtime_outcome or {}).get("summary") or "目标文件当前不可写，已停止继续重试。")
        if model_failed:
            return "模型调用失败，已停止工具执行。"
        if isinstance(tool_gap, dict) and tool_gap:
            return str(tool_gap.get("summary") or "当前任务缺少对应的 Koto 原生工具。")
        if file_changes:
            return f"已完成第 {round_index} 轮工具执行，累计记录 {len(file_changes)} 次文件变更。"
        if round_index > 0:
            return f"已完成第 {round_index} 轮工具执行。"
        return "模型未再请求工具调用。"

    def _execute_step_result_status(
        self,
        *,
        completed: bool,
        tool_gap: Optional[Dict[str, Any]],
        tool_runtime_outcome: Optional[Dict[str, Any]],
        model_failed: bool,
    ) -> str:
        runtime_status = self._tool_runtime_status(tool_runtime_outcome)
        if runtime_status == "awaiting_confirmation":
            return "needs_attention"
        if runtime_status in {"blocked", "write_blocked"}:
            return "failed"
        if model_failed or (isinstance(tool_gap, dict) and tool_gap):
            return "failed"
        return "completed" if completed else "needs_attention"

    def _check_step_result_status(self, check_payload: Dict[str, Any]) -> str:
        status = str(check_payload.get("status") or "").strip().lower()
        if status == "awaiting_confirmation":
            return "needs_attention"
        return "completed" if check_payload.get("passed") else "failed"

    def _context_files(self, request: FileTaskRequest) -> List[FileTaskFile]:
        seen: set[str] = set()
        result: List[FileTaskFile] = []
        for file_info in [*request.files, request.current_file]:
            if not file_info:
                continue
            key = (file_info.path or file_info.name or file_info.content[:80]).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(file_info)
        return result

    def _build_tool_gateway(self, request: FileTaskRequest, context_files: List[FileTaskFile]) -> FileTaskToolGateway:
        if self._tool_gateway is not None:
            return self._tool_gateway
        providers = [self._tool_provider] if self._tool_provider is not None else None
        return FileTaskToolGateway(
            context=FileTaskToolContext(
                task_files=[file_info.public_dict() for file_info in context_files],
                workspace_root=self._workspace_root,
                gemini_client=self._gemini_client,
                request_context={
                    "task": request.task,
                    "target_path": request.target_path,
                    "options": dict(request.options) if isinstance(request.options, dict) else {},
                    "model_mode": request.model_mode,
                    "model_id": request.model_id,
                },
            ),
            providers=providers,
            tool_executor=self._tool_executor,
        )

    def _request_has_file_type(self, request: FileTaskRequest, file_type: str) -> bool:
        normalized = str(file_type or "").strip().lower().lstrip(".")
        if not normalized:
            return False

        candidates = list(request.files or [])
        if request.current_file is not None:
            candidates.append(request.current_file)
        for file_info in candidates:
            detected = (file_info.type or Path(file_info.path or file_info.name).suffix.lstrip(".")).lower()
            if detected == normalized:
                return True

        target_suffix = Path(str(request.target_path or "")).suffix.lstrip(".").lower()
        return target_suffix == normalized

    def _is_docx_annotation_request(self, request: FileTaskRequest) -> bool:
        if not self._request_has_file_type(request, "docx"):
            return False
        options = request.options if isinstance(request.options, dict) else {}
        if bool(options.get("skip_doc_annotate_bridge")):
            return False
        from app.core.agent import file_task_doc_annotate_bridge

        if file_task_doc_annotate_bridge.looks_like_docx_review_clear_request(request.task):
            return False
        if file_task_doc_annotate_bridge.should_route_request(request):
            return True
        task_lower = str(request.task or "").strip().lower()
        if not task_lower:
            return False
        return any(marker in task_lower for marker in _DOCX_ANNOTATE_INTENT_WORDS)

    def _is_docx_clear_review_request(self, request: FileTaskRequest) -> bool:
        if not self._request_has_file_type(request, "docx"):
            return False
        from app.core.agent import file_task_doc_annotate_bridge

        return file_task_doc_annotate_bridge.looks_like_docx_review_clear_request(request.task)

    def _consume_streaming_tool_result(
        self,
        ledger: FileTaskLedger,
        *,
        step_id: str,
        stream_result: FileTaskToolStreamResult,
    ) -> Iterable[FileTaskEvent | Any]:
        final_result: Any = None
        for chunk in stream_result.chunks:
            if not isinstance(chunk, FileTaskToolStreamChunk):
                continue
            if str(chunk.kind or "").strip().lower() == "event":
                event_type = str(chunk.event_type or "").strip()
                if not event_type:
                    continue
                payload = dict(chunk.payload) if isinstance(chunk.payload, dict) else {}
                yield ledger.event(event_type, payload, step_id=step_id)
                continue
            if str(chunk.kind or "").strip().lower() == "result":
                final_result = chunk.payload
        return final_result

    def _has_write_intent(self, task: str) -> bool:
        if self._is_diagnostic_request(task):
            return False
        if self._is_advisory_analysis_request(task):
            return False
        return self._has_explicit_write_intent(task)

    def _has_explicit_write_intent(self, task: str) -> bool:
        lowered = (task or "").lower()
        task_text = task or ""
        if any(word in lowered for word in _EXPLICIT_WRITE_INTENT_WORDS):
            return True
        if any(pattern.search(task_text) for pattern in _WRITE_INTENT_PATTERNS):
            return True
        if any(pattern.search(task_text) for pattern in _IMPERATIVE_WRITE_PATTERNS):
            return True
        has_soft_action = any(word in lowered for word in _SOFT_WRITE_ACTION_WORDS)
        has_target_hint = any(word in lowered for word in _WRITE_TARGET_HINT_WORDS)
        if has_soft_action and has_target_hint:
            return True
        return any(word in lowered for word in _WRITE_INTENT_WORDS)

    def _is_advisory_analysis_request(self, task: str) -> bool:
        task_text = str(task or "").strip()
        if not task_text:
            return False
        lowered = task_text.lower()
        if any(pattern.search(task_text) for pattern in _ANALYSIS_ADVICE_PATTERNS):
            return True
        has_analysis_cue = any(word in lowered for word in _ANALYSIS_CUE_WORDS)
        has_advice_cue = any(word in lowered for word in _ADVICE_CUE_WORDS)
        return has_analysis_cue and has_advice_cue and not self._has_explicit_write_intent(task_text)

    def _is_diagnostic_request(self, task: str) -> bool:
        task_text = str(task or "").strip()
        if not task_text:
            return False
        if any(pattern.search(task_text) for pattern in _DIAGNOSTIC_NEW_TASK_PATTERNS):
            return False
        return any(pattern.search(task_text) for pattern in _DIAGNOSTIC_REQUEST_PATTERNS)

    def _explicit_output_mode(self, request: FileTaskRequest) -> str:
        options = request.options if isinstance(request.options, dict) else {}
        normalized = str(options.get("output_mode") or "").strip().lower()
        if normalized in {"answer", "write", "hybrid"}:
            return normalized
        return ""

    def _has_target_context(self, request: FileTaskRequest, files: List[FileTaskFile]) -> bool:
        if str(request.target_path or "").strip():
            return True
        if request.current_file is not None:
            return True
        return any(bool(file_info and file_info.target) for file_info in files)

    def _infer_output_mode(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        *,
        write_intent: bool,
        diagnostic_request: bool,
        docx_annotation_request: bool,
        advisory_analysis_request: bool,
    ) -> str:
        explicit_mode = self._explicit_output_mode(request)
        if explicit_mode:
            return explicit_mode
        if diagnostic_request:
            return "answer"
        if write_intent or docx_annotation_request:
            return "write"
        if advisory_analysis_request and self._has_target_context(request, files):
            return "hybrid"
        return "answer"

    def _quick_action_mode(self, request: FileTaskRequest) -> str:
        options = request.options if isinstance(request.options, dict) else {}
        return str(options.get("quick_action_mode") or "").strip().lower()

    def _classify_request(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        known_tool_gap: Optional[Dict[str, Any]] = None,
    ) -> FileTaskClassification:
        options = request.options if isinstance(request.options, dict) else {}
        followup_context = self._followup_context(request)
        matched_capabilities = matched_native_capability_names(request)
        advisory_analysis_request = self._is_advisory_analysis_request(request.task)
        raw_write_intent = self._has_explicit_write_intent(request.task)
        write_intent = self._has_write_intent(request.task)
        raw_docx_annotation_request = self._is_docx_annotation_request(request)
        docx_annotation_request = raw_docx_annotation_request
        clear_docx_review_request = self._is_docx_clear_review_request(request)
        if clear_docx_review_request and "annotate_file" in matched_capabilities:
            matched_capabilities = [name for name in matched_capabilities if name != "annotate_file"]
        planner_policy, planner_reason, planner_backend = self._planner_classification(request)
        batch_control = options.get("batch_control") if isinstance(options.get("batch_control"), dict) else {}
        batch_adapter = str(batch_control.get("adapter") or "").strip().lower()
        diagnostic_request = self._is_diagnostic_request(request.task)

        request_kind = "new_task"
        execution_mode = "generic_tool_loop"
        reason_codes: List[str] = []
        followup_action = str(followup_context.get("followup_action") or "").strip().lower()
        previous_task_family = str(followup_context.get("previous_task_family") or "").strip().lower()
        previous_task_execution_mode = str(followup_context.get("previous_task_execution_mode") or "").strip().lower()
        previous_task_output_mode = str(followup_context.get("previous_task_output_mode") or "").strip().lower()
        previous_task_intent_can_apply = str(followup_context.get("previous_task_intent_can_apply") or "").strip().lower()
        if batch_control:
            request_kind = "resume"
            execution_mode = "awaiting_confirmation_resume"
            reason_codes.append("batch_control_resume")
            if batch_adapter:
                reason_codes.append(f"batch_adapter:{batch_adapter}")
        elif followup_context:
            request_kind = "followup"
            execution_mode = "followup_contextual"
            if followup_action:
                reason_codes.append(f"followup_action:{followup_action}")
            else:
                reason_codes.append("followup_context")

        if request_kind == "followup" and followup_action == "question":
            diagnostic_request = True
            reason_codes.append("followup_question")

        if clear_docx_review_request:
            reason_codes.append("docx_clear_review_request")
            if not write_intent:
                write_intent = True
                reason_codes.append("docx_clear_review_forced_write_intent")

        if diagnostic_request:
            reason_codes.append("diagnostic_request")
            if write_intent or raw_write_intent:
                write_intent = False
                reason_codes.append("diagnostic_overrode_write_intent")
            if docx_annotation_request or raw_docx_annotation_request:
                docx_annotation_request = False
                reason_codes.append("diagnostic_overrode_docx_annotation")

        if batch_adapter == "doc_annotate_bridge":
            docx_annotation_request = True
        if request_kind == "followup" and followup_action == "improve":
            if previous_task_family == "annotate":
                reason_codes.append("followup_previous_task_family:annotate")
                if self._request_has_file_type(request, "docx"):
                    docx_annotation_request = True
            if previous_task_execution_mode in {"annotate_tool_loop", "awaiting_confirmation_resume"}:
                reason_codes.append(f"followup_previous_execution_mode:{previous_task_execution_mode}")
                if self._request_has_file_type(request, "docx"):
                    docx_annotation_request = True
        if request_kind == "followup" and followup_action == "apply":
            if previous_task_output_mode in {"hybrid", "write"} or previous_task_intent_can_apply == "true":
                write_intent = True
                reason_codes.append("followup_apply_write_intent")

        if docx_annotation_request:
            if request_kind == "new_task":
                execution_mode = "annotate_tool_loop"
            reason_codes.append("docx_annotation_request")

        if write_intent:
            reason_codes.append("write_intent")

        if planner_policy:
            reason_codes.append(f"planner_policy:{planner_policy}")
        elif planner_reason == "deferred_to_execution_brief":
            reason_codes.append("planner_deferred:model_first")
        if planner_backend:
            reason_codes.append(f"planner_backend:{planner_backend}")

        known_gap_name = ""
        if isinstance(known_tool_gap, dict):
            known_gap_name = str(known_tool_gap.get("missing_capability") or "").strip()
            if known_gap_name:
                reason_codes.append(f"native_tool_gap:{known_gap_name}")

        reason_codes.extend(f"capability:{name}" for name in matched_capabilities[:4])

        task_family = "analyze"
        operation_kind = "read"
        if diagnostic_request:
            task_family = "analyze"
            operation_kind = "read"
        elif docx_annotation_request or "annotate_file" in matched_capabilities:
            task_family = "annotate"
            operation_kind = "annotate"
        elif "compare_files" in matched_capabilities:
            task_family = "compare"
            operation_kind = "compare"
        elif "run_python_code" in matched_capabilities:
            task_family = "automation"
            operation_kind = "compute"
        elif write_intent:
            task_family = "transform"
            operation_kind = "write"

        file_types = sorted({
            str(profile.get("format") or "").strip().lower()
            for profile in build_request_capability_profiles(request)
            if str(profile.get("format") or "").strip()
        })
        target_file_type = Path(str(request.target_path or "")).suffix.lstrip(".").lower()
        if not target_file_type:
            for file_info in files:
                if not file_info.target:
                    continue
                target_file_type = (file_info.type or Path(file_info.path or file_info.name).suffix.lstrip(".")).lower()
                if target_file_type:
                    break

        output_mode = self._infer_output_mode(
            request,
            files,
            write_intent=write_intent,
            diagnostic_request=diagnostic_request,
            docx_annotation_request=docx_annotation_request,
            advisory_analysis_request=advisory_analysis_request,
        )

        confidence = 1.0
        if diagnostic_request:
            confidence = 0.7 if (raw_write_intent or raw_docx_annotation_request) else 0.9

        return FileTaskClassification(
            request_kind=request_kind,
            task_family=task_family,
            operation_kind=operation_kind,
            execution_mode=execution_mode,
            output_mode=output_mode,
            write_intent=write_intent,
            diagnostic_request=diagnostic_request,
            docx_annotation_request=docx_annotation_request,
            planner_policy=planner_policy,
            planner_reason=planner_reason,
            planner_backend=planner_backend,
            target_file_type=target_file_type,
            known_native_tool_gap=known_gap_name,
            file_types=file_types,
            matched_capabilities=matched_capabilities,
            reason_codes=reason_codes,
            confidence=confidence,
        )

    def _effective_planner_classification(self, request: FileTaskRequest) -> tuple[str, str, str]:
        return self._planner_classification(request)

    def _build_execution_context(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        *,
        known_tool_gap: Optional[Dict[str, Any]] = None,
        classification: Optional[FileTaskClassification] = None,
        intent_plan: Optional[FileTaskIntentPlan] = None,
        quick_action_mode: str = "",
    ) -> FileTaskExecutionContext:
        resolved_known_tool_gap = known_tool_gap if isinstance(known_tool_gap, dict) else native_tool_gap_for_request(request)
        resolved_classification = classification or self._classify_request(request, files, resolved_known_tool_gap)
        resolved_intent_plan = self._resolve_intent_plan(
            request,
            files,
            known_tool_gap=resolved_known_tool_gap,
            classification=resolved_classification,
            intent_plan=intent_plan,
        )
        requirements = build_file_task_requirements(request, resolved_classification)
        plan_check = validate_file_task_plan(requirements, resolved_classification, resolved_intent_plan)
        effective_planner_policy, effective_planner_reason, effective_planner_backend = self._effective_planner_classification(request)
        resolved_quick_action_mode = str(quick_action_mode or self._quick_action_mode(request)).strip().lower()
        return FileTaskExecutionContext(
            classification=resolved_classification,
            intent_plan=resolved_intent_plan,
            requirements=requirements,
            plan_check=plan_check,
            known_tool_gap=resolved_known_tool_gap,
            effective_planner_policy=effective_planner_policy,
            effective_planner_reason=effective_planner_reason,
            effective_planner_backend=effective_planner_backend,
            quick_action_mode=resolved_quick_action_mode,
            simple_quick_action=resolved_quick_action_mode == "simple",
        )

    def _planner_classification(self, request: FileTaskRequest) -> tuple[str, str, str]:
        return "native_only", "file_task_native_only", "native"

    def _has_explicit_planner_override(self, request: FileTaskRequest) -> bool:
        return False

    def _sanitize_planner_options(self, options: Dict[str, Any]) -> Dict[str, Any]:
        planner_option_keys = {
            "planner_backend",
            "planner_policy",
            "planner_allow_native_fallback",
            "planner_command",
            "planner_timeout",
            "planner_options",
            "planner_runtime_reason",
            "planner_runtime_fallback_attempted",
            "hermes_planner_command",
            "openclaw_planner_command",
            "hermes_planner_model",
            "hermes_planner_base_url",
            "hermes_planner_api_key",
            "openclaw_planner_model",
            "openclaw_planner_base_url",
            "openclaw_planner_api_key",
        }
        return {
            str(key): value
            for key, value in dict(options or {}).items()
            if str(key) not in planner_option_keys
        }

    def _clone_request_with_options(self, request: FileTaskRequest, options: Dict[str, Any]) -> FileTaskRequest:
        return FileTaskRequest(
            task=request.task,
            run_id=request.run_id,
            session_id=request.session_id,
            files=list(request.files),
            current_file=request.current_file,
            selection=request.selection,
            selection_source=request.selection_source,
            target_path=request.target_path,
            model_mode=request.model_mode,
            model_id=request.model_id,
            history=list(request.history),
            options=dict(options),
        )

    def _initial_model_request(self, request: FileTaskRequest) -> FileTaskRequest:
        options = self._sanitize_planner_options(dict(request.options or {}))
        options["planner_policy"] = "native_only"
        options["planner_runtime_reason"] = "file_task_native_only"
        return self._clone_request_with_options(request, options)

    def _request_after_execution_brief(
        self,
        original_request: FileTaskRequest,
        current_request: FileTaskRequest,
        brief: FileTaskExecutionBrief,
    ) -> FileTaskRequest:
        options = self._sanitize_planner_options(dict(current_request.options or {}))
        options["planner_policy"] = "native_only"
        options["planner_runtime_reason"] = "file_task_native_only"
        return self._clone_request_with_options(original_request, options)

    def _request_after_runtime_external_fallback(
        self,
        original_request: FileTaskRequest,
        current_request: FileTaskRequest,
        *,
        reason: str,
    ) -> Optional[FileTaskRequest]:
        return None

    def _fallback_planner_backend_for_request(self, request: FileTaskRequest) -> str:
        return ""

    def _external_fallback_continue_message(
        self,
        request: FileTaskRequest,
        *,
        backend: str,
        failure_summary: str,
    ) -> str:
        lines = [
            "当前 Koto 原生路径未能完成任务，下一轮改由外部 planner 继续同一任务。",
        ]
        if request.target_path:
            lines.append(f"目标文件：{request.target_path}")
        if backend:
            lines.append(f"兜底后端：{backend}")
        if failure_summary:
            lines.append(f"失败线索：{failure_summary}")
        lines.append("保留已读取上下文、工具反馈和已有文件变更，只补足当前未完成部分，不要重新开始首轮分析。")
        return "\n".join(lines)

    def _build_plan(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        write_intent: bool,
        output_mode: str,
        known_tool_gap: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        context_parts = []
        if files:
            context_parts.append(f"{len(files)} 个文件")
        if request.selection:
            context_parts.append("1 段选区")
        context_detail = "和".join(context_parts)
        steps = [
            {
                "id": "context",
                "title": "读取显式上下文",
                "description": f"读取 {context_detail}，并保留来源引用。" if context_detail else "检查是否有选区、附件或明确当前文件。",
            },
            {
                "id": "execute",
                "title": "执行任务",
                "description": self._execute_plan_description(write_intent, output_mode, known_tool_gap),
            },
            {
                "id": "check",
                "title": "核验结果",
                "description": "输出检查结论和剩余动作，避免静默失败。",
            },
        ]
        return steps

    def _resolve_intent_plan(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        *,
        known_tool_gap: Optional[Dict[str, Any]] = None,
        classification: Optional[FileTaskClassification] = None,
        intent_plan: Optional[FileTaskIntentPlan] = None,
    ) -> FileTaskIntentPlan:
        resolved_classification = classification or self._classify_request(request, files, known_tool_gap)
        if isinstance(intent_plan, FileTaskIntentPlan):
            planned = intent_plan
        else:
            try:
                planned = self._intent_planner.plan(
                    request,
                    files,
                    resolved_classification,
                    known_tool_gap=known_tool_gap,
                )
            except Exception as exc:
                logger.warning("[FileTaskRuntime] intent planner failed: %s", exc)
                planned = self._fallback_intent_plan(request, files, resolved_classification, known_tool_gap)
            if not isinstance(planned, FileTaskIntentPlan):
                planned = self._fallback_intent_plan(request, files, resolved_classification, known_tool_gap)

        planned.intent_type = str(planned.intent_type or resolved_classification.task_family or "analyze").strip() or "analyze"
        planned.output_mode = str(resolved_classification.output_mode or planned.output_mode or "answer").strip().lower() or "answer"
        planned.confidence = float(resolved_classification.confidence if resolved_classification.confidence is not None else planned.confidence or 0.0)
        planned.write_intent = bool(resolved_classification.write_intent)
        if not str(planned.goal_statement or "").strip():
            planned.goal_statement = self._fallback_intent_goal_statement(request, resolved_classification, known_tool_gap)
        if not planned.dynamic_steps:
            planned.dynamic_steps = self._build_plan(
                request,
                files,
                resolved_classification.write_intent,
                planned.output_mode,
                known_tool_gap,
            )
        if not planned.reason_codes:
            planned.reason_codes = [item for item in resolved_classification.reason_codes if item]
        return planned

    def _fallback_intent_plan(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
        known_tool_gap: Optional[Dict[str, Any]] = None,
    ) -> FileTaskIntentPlan:
        output_mode = str(classification.output_mode or "answer").strip().lower() or "answer"
        recommended_strategy = self._fallback_intent_strategy(classification, output_mode, known_tool_gap)
        can_apply = output_mode in {"write", "hybrid"} and self._fallback_intent_has_apply_target(request, files)
        requires_confirmation = output_mode == "hybrid"
        reason_codes = [item for item in classification.reason_codes if item]
        reason_codes.extend(
            [
                "intent_plan:fallback",
                f"intent_type:{classification.task_family or 'analyze'}",
                f"strategy:{recommended_strategy}",
            ]
        )
        if can_apply:
            reason_codes.append("can_apply")
        if requires_confirmation:
            reason_codes.append("requires_confirmation")
        return FileTaskIntentPlan(
            intent_type=classification.task_family or "analyze",
            goal_statement=self._fallback_intent_goal_statement(request, classification, known_tool_gap),
            output_mode=output_mode,
            confidence=float(classification.confidence or 0.0),
            write_intent=bool(classification.write_intent),
            can_apply=can_apply,
            requires_confirmation=requires_confirmation,
            recommended_strategy=recommended_strategy,
            dynamic_steps=self._build_plan(request, files, classification.write_intent, output_mode, known_tool_gap),
            reason_codes=reason_codes,
        )

    def _fallback_intent_goal_statement(
        self,
        request: FileTaskRequest,
        classification: FileTaskClassification,
        known_tool_gap: Optional[Dict[str, Any]] = None,
    ) -> str:
        task_text = _preview(request.task, 180) or "当前文件任务"
        output_mode = str(classification.output_mode or "answer").strip().lower() or "answer"
        if known_tool_gap:
            return f"识别缺失原生能力并输出可落地工具设计：{task_text}"
        if classification.request_kind == "resume":
            return f"延续上一轮待确认的文件任务：{task_text}"
        if output_mode == "write":
            return f"完成真实文件修改并交付结果：{task_text}"
        if output_mode == "hybrid":
            return f"先分析并整理可应用建议，再等待确认：{task_text}"
        return f"基于显式上下文给出结论或答复：{task_text}"

    def _fallback_intent_strategy(
        self,
        classification: FileTaskClassification,
        output_mode: str,
        known_tool_gap: Optional[Dict[str, Any]] = None,
    ) -> str:
        if known_tool_gap:
            return "design_new_tool"
        if classification.request_kind == "resume":
            return "resume_previous_plan"
        if output_mode == "write":
            return "write_through"
        if output_mode == "hybrid":
            return "analyze_then_confirm"
        return "answer_only"

    def _fallback_intent_has_apply_target(self, request: FileTaskRequest, files: List[FileTaskFile]) -> bool:
        if str(request.target_path or "").strip():
            return True
        if request.selection:
            return True
        return any(file_info.target or file_info.path or file_info.name for file_info in files)

    def _execute_plan_description(self, write_intent: bool, output_mode: str, known_tool_gap: Optional[Dict[str, Any]]) -> str:
        if known_tool_gap:
            capability = str(known_tool_gap.get("missing_capability") or "缺失能力").strip()
            return f"当前任务触发 Koto 原生能力缺口：{capability}；模型需要产出 {TOOL_DESIGN_PROTOCOL} 工具规格，不调用未注册工具。"
        if write_intent:
            return "模型在 Koto allowlist 工具目录内规划并执行，写入后产生 file.changed 事件。"
        if output_mode == "hybrid":
            return "模型先读取文件并给出可应用的分析建议；当前轮不默认直接写入原文件。"
        return "模型可读取文件、调用分析工具并生成可审计答复。"

    def _output_mode_label(self, output_mode: str) -> str:
        normalized = str(output_mode or "").strip().lower()
        if normalized == "write":
            return "写入文件"
        if normalized == "hybrid":
            return "先分析后决定"
        return "只给答案"

    def _output_mode_guidance(self, classification: FileTaskClassification) -> str:
        output_mode = str(classification.output_mode or "answer").strip().lower()
        label = self._output_mode_label(output_mode)
        if output_mode == "write":
            return (
                f"当前任务反馈模式：{label}。\n"
                "本轮目标是完成真实文件修改；除非进入等待确认状态，否则不要只给建议或总结就结束。\n"
                "如果没有产生真实 file.changed，就不能把任务说成已完成。\n"
            )
        if output_mode == "hybrid":
            return (
                f"当前任务反馈模式：{label}。\n"
                "本轮先基于显式上下文给出分析、问题清单、修改方向或可应用方案。\n"
                "除非用户这轮已经明确要求直接应用到文件，否则不要直接调用写入工具，也不要声称文件已经更新。\n"
                "如果需要后续落盘，应先把建议说清楚，再等待用户继续要求应用。\n"
            )
        return (
            f"当前任务反馈模式：{label}。\n"
            "本轮默认只返回分析、总结、解释或结论。\n"
            "不要调用写入工具，不要伪造 file.changed，也不要把结果描述成已经写入文件。\n"
            "只有当用户明确要求把结果写入文件时，才改走写回路径。\n"
        )

    def _intent_plan_guidance(self, intent_plan: FileTaskIntentPlan) -> str:
        lines = ["高阶意图规划："]
        goal_statement = str(intent_plan.goal_statement or "").strip()
        if goal_statement:
            lines.append(f"- 目标：{goal_statement}")
        lines.append(f"- 策略：{str(intent_plan.recommended_strategy or 'answer_only').strip() or 'answer_only'}")
        lines.append(f"- 可应用：{'是' if intent_plan.can_apply else '否'}")
        lines.append(f"- 写回前需要确认：{'是' if intent_plan.requires_confirmation else '否'}")
        return "\n".join(lines) + "\n"

    def _execution_brief_schema(self) -> Dict[str, Any]:
        return {
            "execution_brief": {
                "summary": "一句中文概述当前准备怎么处理",
                "objective": "本轮要完成的目标",
                "steps": [{"title": "步骤标题", "description": "准备做什么"}],
                "planned_tools": ["tool_name"],
                "read_targets": ["会读取的文件或对象"],
                "write_targets": ["会写入的文件或对象"],
                "verification": "准备如何验证结果",
                "delegated_planner": "可选，hermes 或 openclaw",
            }
        }

    def _normalize_execution_brief(self, value: Any) -> Optional[FileTaskExecutionBrief]:
        candidate = value
        if isinstance(candidate, dict) and isinstance(candidate.get("execution_brief"), dict):
            candidate = candidate.get("execution_brief")
        if not isinstance(candidate, dict):
            return None
        brief = FileTaskExecutionBrief.from_mapping(candidate)
        if not any((
            brief.summary,
            brief.objective,
            brief.steps,
            brief.planned_tools,
            brief.read_targets,
            brief.write_targets,
            brief.verification,
            brief.delegated_planner,
        )):
            return None
        return brief

    def _looks_like_brief_only_content(self, content_text: str) -> bool:
        text = str(content_text or "").strip()
        if not text:
            return False
        if text.startswith(("{", "[")):
            return True
        if text.startswith("```") and extract_first_json_value(text) is not None:
            return True
        return False

    def _extract_execution_brief(
        self,
        response: Any,
        content_text: str,
    ) -> tuple[Optional[FileTaskExecutionBrief], str]:
        candidate: Any = None
        if isinstance(response, dict):
            if isinstance(response.get("execution_brief"), dict):
                candidate = response.get("execution_brief")
            elif content_text:
                candidate = extract_first_json_value(content_text)
        elif content_text:
            candidate = extract_first_json_value(content_text)

        brief = self._normalize_execution_brief(candidate)
        if not brief:
            return None, content_text

        cleaned_content = content_text.strip()
        if self._looks_like_brief_only_content(cleaned_content):
            cleaned_content = brief.summary or brief.objective or ""
        return brief, cleaned_content

    def _execution_brief_continue_message(
        self,
        request: FileTaskRequest,
        brief: FileTaskExecutionBrief,
    ) -> str:
        summary = brief.summary or brief.objective or "已完成任务分析。"
        lines = [
            f"已收到 execution_brief：{summary}",
            "下一轮请直接调用需要的 Koto 工具继续执行，不要重复输出同一份 brief。",
        ]
        if brief.delegated_planner:
            lines.append(f"如果仍然需要委托 external planner，请按 delegated_planner={brief.delegated_planner} 继续执行，并给出可落地结果。")
        if request.target_path:
            lines.append(f"当前目标文件是：{request.target_path}。")
        return " ".join(lines)

    def _build_confirmed_plan(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        tool_calls: List[Dict[str, Any]],
        write_intent: bool,
        content_text: str,
    ) -> Dict[str, Any]:
        steps: List[Dict[str, Any]] = []
        seen: set[str] = set()
        has_write_step = False

        for idx, tool_call in enumerate(tool_calls, start=1):
            tool_name = str(tool_call.get("name") or "").strip()
            tool_args = dict(tool_call.get("args") or {})
            if not tool_name:
                continue
            signature = json.dumps({"name": tool_name, "args": tool_args}, ensure_ascii=False, sort_keys=True, default=str)
            if signature in seen:
                continue
            seen.add(signature)
            has_write_step = has_write_step or (is_write_tool(tool_name) and tool_name != "run_python_code")
            steps.append({
                "id": f"model_step_{idx}",
                "tool_name": tool_name,
                "title": self._tool_plan_title(tool_name),
                "description": self._tool_plan_description(tool_name, tool_args, files, request),
            })

        if write_intent and not has_write_step:
            steps.append(self._inferred_write_plan_step(request, files))

        steps.append({
            "id": "verify",
            "title": "核验结果",
            "description": "检查目标文件是否真的更新，并给出最终结论。",
        })

        clean_summary = _preview(content_text, 180) if content_text else "AI 已确认执行方案。"
        return {
            "summary": clean_summary,
            "steps": steps,
            "estimated": True,
            "note": "实际步骤会根据读取结果和工具返回自动微调。",
        }

    def _tool_plan_title(self, tool_name: str) -> str:
        labels = {
            "read_sheet_data": "读取 Excel 表格",
            "inspect_workbook_structure": "检查 Excel 结构",
            "audit_financial_workbook": "审计财务模型",
            "read_docx_content": "读取 Word 内容",
            "parse_file_to_text": "解析文件文本",
            "clear_docx_review_marks": "清除 Word 审阅标记",
            "insert_image_into_docx": "插入 Word 图片",
            "insert_excel_as_docx_table": "写入 Word 表格",
            "write_docx_content": "写入 Word 内容",
            "write_sheet_data": "写入 Excel 单元格",
            "design_pptx_theme_layout": "设计 PPT 主题版式",
            "write_pptx_slides": "更新 PPT 页面",
            "add_pptx_slides": "新增 PPT 页面",
            "create_file": "创建文件",
            "copy_file": "复制文件",
            "read_file_range": "读取文本片段",
            "compare_files": "对比文件",
            "extract_to_file": "提取到文件",
            "annotate_file": "添加批注",
            "run_python_code": "运行代码处理",
        }
        return labels.get(tool_name, f"调用工具 {tool_name}")

    def _tool_plan_description(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        files: List[FileTaskFile],
        request: FileTaskRequest,
    ) -> str:
        if tool_name == "read_sheet_data":
            source = self._display_path(tool_args.get("path")) or self._first_file_name(files, {"xlsx", "xlsm", "csv"}) or "表格文件"
            sheet = str(tool_args.get("sheet_name") or "").strip()
            rows = str(tool_args.get("max_rows") or "").strip()
            suffix = f"，工作表：{sheet}" if sheet else ""
            rows_text = f"，最多 {rows} 行" if rows else ""
            return f"读取 {source} 的表格数据{suffix}{rows_text}。"
        if tool_name == "inspect_workbook_structure":
            source = self._display_path(tool_args.get("path")) or self._first_file_name(files, {"xlsx", "xlsm"}) or "Excel 文件"
            return f"检查 {source} 的工作表结构、公式分布和外部链接依赖。"
        if tool_name == "audit_financial_workbook":
            source = self._display_path(tool_args.get("path")) or self._first_file_name(files, {"xlsx", "xlsm"}) or "财务模型"
            return f"审计 {source} 的三表完整性、外部依赖和关键年份序列红旗。"
        if tool_name == "insert_excel_as_docx_table":
            source = self._display_path(tool_args.get("source_path")) or self._first_file_name(files, {"xlsx", "xlsm", "csv"}) or "表格文件"
            target = self._display_path(tool_args.get("target_path")) or request.target_path or self._first_file_name(files, {"docx"}, target=True) or "Word 文档"
            table_title = str(tool_args.get("table_title") or "").strip()
            title_text = f"，表题：{table_title}" if table_title else ""
            return f"把 {source} 的数据作为真实 Word 表格插入 {self._display_path(target) or target}{title_text}。"
        if tool_name == "insert_image_into_docx":
            target = self._display_path(tool_args.get("path")) or request.target_path or self._first_file_name(files, {"docx"}, target=True) or "Word 文档"
            image_path = self._display_path(tool_args.get("image_path")) or str(tool_args.get("image_path") or "图片文件").strip() or "图片文件"
            title = str(tool_args.get("title") or "").strip()
            title_text = f"，图题：{title}" if title else ""
            return f"把 {image_path} 作为真实图片插入 {self._display_path(target) or target}{title_text}。"
        if tool_name == "write_docx_content":
            target = self._display_path(tool_args.get("path")) or request.target_path or self._first_file_name(files, {"docx"}, target=True) or "Word 文档"
            return f"把生成后的段落写入 {self._display_path(target) or target}。"
        if tool_name == "clear_docx_review_marks":
            target = self._display_path(tool_args.get("path")) or request.target_path or self._first_file_name(files, {"docx"}, target=True) or "Word 文档"
            scope = str(tool_args.get("scope") or "comments").strip().lower() or "comments"
            if scope == "all":
                return f"清除 {self._display_path(target) or target} 中的批注并接受修订。"
            if scope == "revisions":
                return f"接受并清除 {self._display_path(target) or target} 中的修订标记。"
            return f"清除 {self._display_path(target) or target} 中的全部批注。"
        if tool_name == "write_sheet_data":
            target = self._display_path(tool_args.get("path")) or request.target_path or self._first_file_name(files, {"xlsx", "xlsm"}, target=True) or "Excel 文件"
            sheet = str(tool_args.get("sheet_name") or "").strip()
            sheet_text = f"，工作表：{sheet}" if sheet else ""
            return f"把结构化更新写入 {self._display_path(target) or target}{sheet_text}。"
        if tool_name == "annotate_file":
            target = self._display_path(tool_args.get("path")) or request.target_path or self._first_file_name(files, {"docx", "pdf", "txt", "md"}, target=True) or "目标文件"
            requirement = str(tool_args.get("requirement") or "").strip()
            if requirement:
                return f"按要求为 {self._display_path(target) or target} 生成并写回批注：{_compact_line(requirement, 90)}。"
            return f"把结构化批注写入 {self._display_path(target) or target}。"
        if tool_name in {"design_pptx_theme_layout", "write_pptx_slides", "add_pptx_slides"}:
            target = self._display_path(tool_args.get("path")) or request.target_path or self._first_file_name(files, {"pptx"}, target=True) or "PPT 文件"
            if tool_name == "design_pptx_theme_layout":
                style_brief = str(tool_args.get("style_brief") or "").strip()
                style_text = f"，风格要求：{style_brief}" if style_brief else ""
                return f"为 {self._display_path(target) or target} 套用统一主题、字体、配色和安全版式{style_text}。"
            action = "新增" if tool_name == "add_pptx_slides" else "更新"
            return f"在 {self._display_path(target) or target} 中{action}幻灯片内容。"
        if tool_name == "parse_file_to_text":
            source = self._display_path(tool_args.get("path")) or self._first_file_name(files, set()) or "文件"
            return f"解析 {source} 的文本内容，供后续分析使用。"
        if tool_name == "read_file_range":
            source = self._display_path(tool_args.get("path")) or self._first_file_name(files, {"txt", "md", "csv", "json", "py", "js", "html", "css"}) or "文本文件"
            start = str(tool_args.get("start_line") or "1").strip()
            end = str(tool_args.get("end_line") or "").strip()
            window = f"第 {start} 到 {end} 行" if end else f"从第 {start} 行开始"
            return f"读取 {source} 的{window}，供后续分析使用。"
        if tool_name == "compare_files":
            raw_paths = str(tool_args.get("file_paths") or "").strip()
            aspect = str(tool_args.get("aspect") or "content").strip()
            return f"对比文件{f'：{raw_paths}' if raw_paths else ''}，比较维度：{aspect}。"
        if tool_name == "run_python_code":
            return "在沙盒中运行代码处理数据，必要时生成图表或中间文件。"
        target = self._display_path(tool_args.get("path") or tool_args.get("target_path") or tool_args.get("destination"))
        return f"执行 {tool_name}{f'，目标：{target}' if target else ''}。"

    def _inferred_write_plan_step(self, request: FileTaskRequest, files: List[FileTaskFile]) -> Dict[str, Any]:
        source = self._first_file_name(files, {"xlsx", "xlsm", "csv"})
        docx_target = self._display_path(request.target_path) or self._first_file_name(files, {"docx"}, target=True) or self._first_file_name(files, {"docx"})
        pptx_target = self._display_path(request.target_path) or self._first_file_name(files, {"pptx"}, target=True) or self._first_file_name(files, {"pptx"})
        task_lower = (request.task or "").lower()
        if source and docx_target:
            return {
                "id": "inferred_write",
                "title": "写入 Word 表格",
                "description": f"读取完成后，把 {source} 的表格数据写入 {docx_target}。",
            }
        if pptx_target or "ppt" in task_lower or "幻灯片" in task_lower:
            if any(word in task_lower for word in ("风格", "主题", "版式", "美化", "排版", "配色", "视觉", "theme", "layout", "design")):
                return {
                    "id": "inferred_write",
                    "title": "设计 PPT 主题版式",
                    "description": f"读取完成后，为 {pptx_target or '目标 PPT'} 套用统一主题、字体、配色和安全版式。",
                }
            return {
                "id": "inferred_write",
                "title": "写入 PPT 内容",
                "description": f"读取完成后，把整理结果写入 {pptx_target or '目标 PPT'}。",
            }
        target = self._display_path(request.target_path) or next((self._display_path(file_info.path) for file_info in files if file_info.target and file_info.path), "目标文件")
        return {
            "id": "inferred_write",
            "title": "写入目标文件",
            "description": f"读取完成后，把处理结果写入 {target}。",
        }

    def _first_file_name(self, files: List[FileTaskFile], types: set[str], *, target: bool = False) -> str:
        for file_info in files:
            file_type = (file_info.type or Path(file_info.path or file_info.name).suffix.lstrip(".")).lower()
            if target and not file_info.target:
                continue
            if types and file_type not in types:
                continue
            return file_info.name or self._display_path(file_info.path)
        return ""

    def _display_path(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return re.split(r"[\\/]+", text)[-1] or text

    def _plan_summary(self, request: FileTaskRequest, files: List[FileTaskFile], write_intent: bool) -> str:
        target = request.target_path or next((f.path for f in files if f.target), "")
        has_selection = bool(request.selection)
        if write_intent and target:
            suffix = "，并引用 1 段选区" if has_selection else ""
            return f"准备更新 {Path(target).name}{suffix}。"
        if files and has_selection:
            return f"准备处理 {len(files)} 个文件和 1 段选区。"
        if files:
            return f"准备处理 {len(files)} 个文件。"
        if has_selection:
            return "准备处理 1 段选区。"
        return "准备处理当前任务。"

    def _fallback_readonly_summary(
        self,
        request: FileTaskRequest,
        snippets: List[Dict[str, Any]],
        files: List[FileTaskFile],
        exc: Exception,
    ) -> str:
        if not snippets:
            return ""

        lines = [
            "模型暂不可用，Koto 已先基于显式上下文整理可见内容（非模型推理）：",
        ]
        used_sources: set[str] = set()
        for index, snippet in enumerate(snippets[:5], start=1):
            source = str(snippet.get("source") or snippet.get("path") or f"上下文 {index}").strip()
            if not source and index <= len(files):
                source = files[index - 1].name or files[index - 1].path
            source_label = self._display_path(source) or f"上下文 {index}"
            preview = _compact_line(snippet.get("preview"), 320)
            if not preview:
                continue
            dedupe_key = f"{source_label}:{preview}"
            if dedupe_key in used_sources:
                continue
            used_sources.add(dedupe_key)
            lines.append(f"{index}. {source_label}：{preview}")

        if len(lines) == 1:
            return ""

        lines.append("恢复模型后可以继续生成更完整的总结、改写或写入文件。")
        lines.append(f"模型错误：{_compact_line(exc, 160)}")
        return "\n".join(lines)

    def _success_criteria(self, request: FileTaskRequest, write_intent: bool, output_mode: str) -> List[str]:
        criteria = ["每个步骤都产生 typed event，可被前端时间线渲染", "所有上下文来源都来自显式输入"]
        if write_intent:
            criteria.extend(["写入工具必须产生 file.changed 事件", "最终 checker 必须确认目标文件已更新"])
        elif output_mode == "hybrid":
            criteria.append("最终摘要必须给出明确建议，且当前轮不默认直接写入原文件")
        else:
            criteria.append("最终摘要说明已使用的上下文和未完成项")
        return criteria

    def _file_types(self, files: List[FileTaskFile]) -> set[str]:
        file_types: set[str] = set()
        for file_info in files:
            file_type = str(file_info.type or Path(file_info.path or file_info.name).suffix.lstrip(".")).lower().strip()
            if file_type:
                file_types.add(file_type)
        return file_types

    def _looks_like_pdf_python_text_read(self, code: Any) -> bool:
        text = str(code or "").lower()
        if not text.strip():
            return False

        pdf_markers = (
            "pypdf2",
            "from pypdf import",
            "pdfreader",
            "pdfplumber",
            "pymupdf",
            "fitz",
            ".pdf",
            "pdf_path",
        )
        read_markers = (
            "extract_text(",
            "get_text(",
            "reader.pages",
            "page.get_text",
            "page.extract_text",
            "pdf.pages",
        )
        return any(marker in text for marker in pdf_markers) and any(marker in text for marker in read_markers)

    def _blocked_run_python_message(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        request: FileTaskRequest,
        files: List[FileTaskFile],
    ) -> str:
        if tool_name != "run_python_code":
            return ""

        file_types = self._file_types(files)
        code = tool_args.get("code")
        if "pdf" not in file_types and ".pdf" not in str(code or "").lower():
            return ""
        if not self._looks_like_pdf_python_text_read(code):
            return ""

        message = (
            "不要用 run_python_code 直接读取 PDF 文本。"
            "请改用 parse_file_to_text(path, max_chars, start_page, end_page)；"
            "长文或原文对照任务必须按页窗口分段读取。"
        )
        if "docx" in file_types:
            message += " 读取完 PDF 分段后，再用 read_docx_content 读取 DOCX 译稿。"
        if request.target_path:
            message += f" 当前目标文件是：{request.target_path}。"
        return message

    def _write_retry_message(self, request: FileTaskRequest, files: List[FileTaskFile]) -> str:
        target = request.target_path or next((file_info.path for file_info in files if file_info.target and file_info.path), "")
        file_types = self._file_types(files)
        task_text = str(request.task or "")
        hint = "你还没有完成真实文件写入。不要只总结或结束，下一轮必须调用会修改文件的工具。"
        if "xlsx" in file_types and "docx" in file_types:
            hint += " 对于把 Excel 加入 Word，优先调用 insert_excel_as_docx_table；如果已经读到真实工作表名，就用真实 sheet 写入目标 docx。"
        if "docx" in file_types and re.search(r"(?:图表|可视化|绘图|画图|画.{0,4}图|图片|chart|plot|graph|image)", task_text, re.IGNORECASE):
            hint += " 如果用户要求把图表或图片加入 DOCX，先用 run_python_code 生成真实 PNG/JPG 文件，再调用 insert_image_into_docx；不要用 write_docx_content 把图片描述文字写进文档代替真实插图。"
        if {"txt", "md", "csv", "json", "py", "js", "html", "css"}.intersection(file_types):
            hint += " 对于 TXT/MD/CSV/JSON 或代码文本文件，先用 read_file_range 或 parse_file_to_text 读取必要内容，再用 run_python_code 直接覆写目标文件，并在结果里保留 KOTO_MODIFIED 标记；如果只是批注/审校可用 annotate_file。不要只输出润色后的文本而不落盘。"
        if "pdf" in file_types:
            hint += " 读取 PDF 原文必须调用 parse_file_to_text；长文必须用 start_page/end_page 分段读取，不要用 run_python_code、PyPDF2、pdfplumber 或 fitz 直接解析 PDF。"
        if "pdf" in file_types and "docx" in file_types:
            hint += " 对于 PDF 原文和 DOCX 译稿对照任务，先分页读取 PDF，再读取 DOCX；不要试图一次性抽取整本 PDF。"
        if "pptx" in file_types:
            hint += " 对于 PPT，读取内容优先用 parse_file_to_text；如果要整体风格、主题、版式、美化或配色，调用 design_pptx_theme_layout；如果要新增总结页，调用 add_pptx_slides；如果是改现有页文本，用 write_pptx_slides。不要对 PPTX 调用 read_docx_content。"
        if target:
            hint += f" 当前目标文件是：{target}。"
        return hint

    def _build_system_prompt(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        known_tool_gap: Optional[Dict[str, Any]] = None,
        classification: Optional[FileTaskClassification] = None,
        intent_plan: Optional[FileTaskIntentPlan] = None,
        execution_context: Optional[FileTaskExecutionContext] = None,
    ) -> str:
        resolved_context = execution_context or self._build_execution_context(
            request,
            files,
            known_tool_gap=known_tool_gap,
            classification=classification,
            intent_plan=intent_plan,
        )
        resolved_classification = resolved_context.classification
        resolved_intent_plan = resolved_context.intent_plan
        resolved_known_tool_gap = resolved_context.known_tool_gap
        workflows = json.dumps(supported_file_workflows(), ensure_ascii=False, indent=2)
        file_list = ", ".join((file_info.path or file_info.name) for file_info in files if file_info.path or file_info.name) or "none"
        capability_profiles = build_request_capability_profiles(request)
        known_gap_text = ""
        if resolved_known_tool_gap:
            known_gap_text = "\n已知原生工具缺口：\n" + json.dumps(resolved_known_tool_gap, ensure_ascii=False, indent=2) + "\n"
        capability_text = ""
        if capability_profiles:
            capability_text = "文件能力概览：" + json.dumps(capability_profiles, ensure_ascii=False) + "\n"
        followup_context = self._followup_context(request)
        followup_guidance = ""
        clear_docx_review_guidance = ""
        single_docx_annotate_guidance = ""
        if str(followup_context.get("kind") or "").strip() == "review_last_task":
            followup_action = str(followup_context.get("followup_action") or "").strip().lower()
            if followup_action == "apply":
                followup_guidance = (
                    "当前输入是用户要求把上一轮文件任务中的建议直接应用到文件。这不是一个无关的新任务，而是同一任务的写回续跑。\n"
                    "优先沿用上一轮的目标文件、分析建议、文件变更和约束；必要时只补充最少量上下文后直接执行写入。\n"
                    "如果上一轮已经给出可应用建议，这一轮应进入真实写回路径并产生 file.changed；不要只重复建议文本。\n"
                )
            elif followup_action == "improve":
                followup_guidance = (
                    "当前输入是用户要求围绕上一轮文件任务结果继续优化。这不是一个无关的新任务，而是同一任务的后续回合。\n"
                    "先解释上一轮结果的不足和这次准备如何改进；如果确实需要，可以继续调用工具修正目标文件。"
                    "优先沿用上一轮的目标、目标文件、失败点和约束，不要把上下文重置成新的独立任务。\n"
                )
                if _followup_has_prior_excel_docx_insert(followup_context):
                    followup_guidance += (
                        "如果上一轮已经通过 insert_excel_as_docx_table 把 Excel 表格写入目标 DOCX，"
                        "这轮继续优化时不要再次插入同一张表。"
                        "优先补写摘要、说明、结论或修正已有文字；"
                        "只有用户明确要求重插、替换或追加另一张表时，才再次插表。\n"
                    )
            else:
                followup_guidance = (
                    "当前输入是用户对上一轮文件任务结果的反馈或质问，不要默认把它当作全新的执行任务。\n"
                    "先解释上一轮结果、指出可能的问题，并回答用户的追问。"
                    "只有当用户明确要求重新修改文件、继续执行或调用工具时，才进入新的工具执行。"
                    "如果当前只是反馈上一轮结果，不要调用写入工具，也不要伪造新的完成状态。\n"
                )
        if resolved_classification.docx_annotation_request:
            target_docx = self._display_path(request.target_path) or self._first_file_name(files, {"docx"}, target=True) or self._first_file_name(files, {"docx"}) or "当前 DOCX"
            single_docx_annotate_guidance = (
                "DOCX 审校/批注任务规则：\n"
                f"- 目标 DOCX：{target_docx}\n"
                "- 直接调用 annotate_file。对于 AI 生成批注的场景，传 path=<目标 DOCX>、requirement=<用户要求>，annotations 保持空数组即可。\n"
                "- 如果当前任务还附带 PDF 原文、分批继续执行信息或上一轮审校 follow-up，上述 annotate_file 会自动复用这些上下文；不要再绕开白盒工具循环。\n"
                "- 不要自己编造 annotations 的 range_start/range_end 去模拟 Word 定位；annotate_file 会负责分析、定位并把批注写回原文。\n"
                "- 如果目标是把意见直接写回 DOCX，不能只输出批注清单文本后结束。\n"
            )
        elif self._is_docx_clear_review_request(request):
            target_docx = self._display_path(request.target_path) or self._first_file_name(files, {"docx"}, target=True) or self._first_file_name(files, {"docx"}) or "当前 DOCX"
            clear_docx_review_guidance = (
                "DOCX 批注/修订清理任务规则：\n"
                f"- 目标 DOCX：{target_docx}\n"
                "- 调用 clear_docx_review_marks。若用户只要求删除批注，scope 用 comments；若明确要求去掉修订或全部审阅标记，scope 用 revisions 或 all。\n"
                "- 不要调用 annotate_file 去重新生成批注，也不要走 doc_annotate_bridge。\n"
                "- 这是一个真实写回任务，完成后必须产生 file.changed。\n"
            )
        return (
            "你是 Koto 文件助手的后端执行 agent。你可以自主规划并调用工具，"
            "但只能调用系统提供的 Koto 文件工具。不要编造工具、文件路径或已经完成的写入。\n\n"
            f"{self._output_mode_guidance(resolved_classification)}"
            f"{self._intent_plan_guidance(resolved_intent_plan)}"
            f"{followup_guidance}"
            f"{clear_docx_review_guidance}"
            f"{single_docx_annotate_guidance}"
            "首轮协议：你可以直接调用工具；如果任务较复杂、需要先拆解执行方案，或需要先决定是否委托 external planner，"
            "也可以先返回 execution_brief。"
            f"execution_brief 格式：{json.dumps(self._execution_brief_schema(), ensure_ascii=False)}\n"
            "如果想把后续执行委托给 hermes 或 openclaw，请在 execution_brief.delegated_planner 中明确写出后端名。\n"
            "返回 execution_brief 后，下一轮必须继续调用工具或明确委托，不要重复同一份 brief。\n"
            "执行原则：\n"
            "1. 优先使用显式提供的当前文件、附件、选区和目标路径。\n"
            "2. Office 文件必须使用格式感知工具；DOCX/XLSX/PPTX 优先用专用工具，PDF 默认只读提取。\n"
            "3. 读取 PDF 文本时只能使用 parse_file_to_text；长文必须使用 start_page/end_page 按页窗口分段读取。不要用 run_python_code 调用 PyPDF2/pypdf/pdfplumber/fitz/PyMuPDF 读取 PDF。\n"
            "4. PDF 原文 + DOCX 译稿/润色/审校任务，先分段读取 PDF，再读取 DOCX；不要一次性抽取整本 PDF，也不要用 Python 临时脚本拼接全文。\n"
            "5. Excel 工作表名未知时不要猜 Sheet1；省略 sheet_name，或先读取表格让工具返回真实 sheet 名。若请求的工作表不存在，继续根据 available_sheets 和已读取结果完成分析，并明确说明缺失的报表。\n"
            "6. 遇到财务模型、预算、预测、报表审阅类任务时，先调用 inspect_workbook_structure 或 audit_financial_workbook，先确认工作表完整性、外部链接、年份列和公式缺口，再用 read_sheet_data 深入关键工作表。区分“结构性缺陷/可复算性问题”和“经营假设偏激进”，不要混为一谈。\n"
            "7. 读取 PPTX 内容优先用 parse_file_to_text；read_docx_content 只用于 DOCX。\n"
            "8. 需要整体设计 PPTX 的风格、主题、版式、美化或配色时调用 design_pptx_theme_layout；需要新增 PPT 总结页时优先用 add_pptx_slides；修改现有页内容时用 write_pptx_slides。\n"
            "9. 对于 TXT/MD/CSV/JSON/代码等文本文件的直接改写，先用 read_file_range 或 parse_file_to_text 读取必要片段，再用 run_python_code 直接覆写目标文件，并在结果里保留 KOTO_MODIFIED 标记；如果只是审校批注可用 annotate_file。不要只返回改写后的文本。\n"
            "10. 需要计算、制图、批量转换或复杂文件处理时使用 run_python_code，并在输出中保留 KOTO_CREATED/KOTO_MODIFIED 标记；但 PDF 文本读取不属于这一类。\n"
            "11. 如果任务要求把图表/图片加入 DOCX，先用 run_python_code 生成真实图片文件，再调用 insert_image_into_docx 把图片写回目标 DOCX；不要把图片描述文字写进文档代替真实插图。\n"
            "12. 生成中文图表时，优先配置 matplotlib 中文字体候选（Microsoft YaHei、SimHei、Noto Sans CJK SC、WenQuanYi Micro Hei、DejaVu Sans）并设置 axes.unicode_minus=False；保存图表时使用 dpi>=220 和 bbox_inches='tight'。\n"
            "13. Excel -> DOCX 任务默认要保留真实表格；优先用 insert_excel_as_docx_table 落盘。但如果用户明确要求整理、总结、分析、说明、结论或要点，先用 write_docx_content 把真实摘要写入目标 DOCX，再按需插入一次支撑表格；不要只插原表就结束。\n"
            "14. 完成写入后直接给出简短结果，不要重复写入同一目标文件。\n"
            "15. 如果任务要求的编辑能力当前工具不支持，必须遵循下面的工具设计协议；不要只说做不了，也不要把任务判定为已完成。\n"
            f"{tool_design_prompt_text()}\n\n"
            f"显式文件：{file_list}\n"
            f"目标路径：{request.target_path or 'none'}\n"
            f"{capability_text}"
            f"工具设计协议：{TOOL_DESIGN_PROTOCOL}\n"
            f"{known_gap_text}"
            f"支持的主流办公文件工作流：\n{workflows}\n\n"
            "如果 provider 原生 tool calling 不可用，也可以在文本中输出 JSON 工具调用，格式为 "
            "{\"name\": \"tool_name\", \"args\": {...}} 或由这些对象组成的数组。"
        )

    def _build_messages(
        self,
        request: FileTaskRequest,
        snippets: List[Dict[str, Any]],
        files: List[FileTaskFile],
        known_tool_gap: Optional[Dict[str, Any]] = None,
        classification: Optional[FileTaskClassification] = None,
        intent_plan: Optional[FileTaskIntentPlan] = None,
        execution_context: Optional[FileTaskExecutionContext] = None,
    ) -> List[Dict[str, Any]]:
        resolved_context = execution_context or self._build_execution_context(
            request,
            files,
            known_tool_gap=known_tool_gap,
            classification=classification,
            intent_plan=intent_plan,
        )
        resolved_classification = resolved_context.classification
        resolved_intent_plan = resolved_context.intent_plan
        resolved_known_tool_gap = resolved_context.known_tool_gap
        capability_profiles = build_request_capability_profiles(request)
        followup_context = self._followup_context(request)
        context = {
            "task": request.task,
            "target_path": request.target_path,
            "selection_source": request.selection_source,
            "task_feedback_mode": {
                "output_mode": resolved_classification.output_mode,
                "label": self._output_mode_label(resolved_classification.output_mode),
                "write_intent": bool(resolved_classification.write_intent),
                "should_write_this_round": str(resolved_classification.output_mode or "").strip().lower() == "write",
            },
            "intent_plan": resolved_intent_plan.public_dict(),
            "files": [file_info.public_dict() for file_info in files],
            "file_capability_profiles": capability_profiles,
            "context_snippets": snippets[:10],
            "execution_brief_schema": self._execution_brief_schema(),
            "tool_design_protocol": TOOL_DESIGN_PROTOCOL,
        }
        if isinstance(request.options, dict):
            memory_context = str(request.options.get("memory_context") or "").strip()
            if memory_context:
                context["memory_context"] = _preview(memory_context, 6000)
        if resolved_known_tool_gap:
            context["known_native_tool_gap"] = resolved_known_tool_gap
        if followup_context:
            context["followup_context"] = followup_context
        messages: List[Dict[str, Any]] = []
        for item in request.history[-6:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "user").strip().lower()
            content = str(item.get("content") or item.get("text") or "").strip()
            if content and role in {"user", "assistant", "model"}:
                messages.append({"role": "model" if role == "assistant" else role, "content": _preview(content, 1500)})
        prompt_prefix = "请完成这个文件任务。"
        if str(followup_context.get("kind") or "").strip() == "review_last_task":
            constFollowupAction = str(followup_context.get("followup_action") or "").strip().lower()
            if constFollowupAction == "apply":
                prompt_prefix = (
                    "用户要求把上一轮文件任务中已经给出的建议直接应用到目标文件。"
                    "请把它视为同一任务的写回续跑，优先沿用上一轮建议、目标文件和已知约束，不要重新从头分析。"
                )
            elif constFollowupAction == "improve":
                prompt_prefix = (
                    "用户要求在上一轮文件任务结果基础上继续优化。"
                    "请把它视为同一任务的后续处理回合，先说明你准备如何改进，再继续处理。"
                )
                if _followup_has_prior_excel_docx_insert(followup_context):
                    prompt_prefix += " 上一轮已经有实际 file.changed 记录表明目标 DOCX 插入过 Excel 表格；请先基于这些已写入结果判断缺口，不要重复同一插表。"
            else:
                prompt_prefix = (
                    "用户正在对上一轮文件任务结果提出反馈。"
                    "请先回答上一轮结果为什么会这样、哪里可能有问题，以及是否需要重做。"
                    "除非用户已经明确提出新的文件修改要求，否则不要把这条消息当成新的文件执行任务。"
                )
        messages.append({
            "role": "user",
            "content": prompt_prefix + "上下文如下：\n" + json.dumps(context, ensure_ascii=False, indent=2),
        })
        return messages

    def _followup_context(self, request: FileTaskRequest) -> Dict[str, Any]:
        if not isinstance(request.options, dict):
            return {}
        value = request.options.get("followup_context")
        if not isinstance(value, dict):
            return {}

        cleaned: Dict[str, Any] = {}
        for key in (
            "kind",
            "source",
            "followup_action",
            "user_feedback",
            "previous_run_id",
            "previous_task_summary",
            "previous_task_status",
            "previous_task_timestamp",
            "previous_user_request",
            "previous_task_request",
            "previous_task_mode",
            "previous_task_request_kind",
            "previous_task_family",
            "previous_task_operation_kind",
            "previous_task_execution_mode",
            "previous_task_output_mode",
            "previous_task_intent_strategy",
            "previous_task_intent_can_apply",
            "previous_task_intent_requires_confirmation",
            "previous_task_target_file_type",
            "previous_completed_task",
        ):
            text = str(value.get(key) or "").strip()
            if text:
                cleaned[key] = _preview(text, 2000)
        previous_task_file_changes = _sanitize_followup_file_changes(value.get("previous_task_file_changes"))
        if previous_task_file_changes:
            cleaned["previous_task_file_changes"] = previous_task_file_changes
        return cleaned

    def _call_model(
        self,
        *,
        request: FileTaskRequest,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if hasattr(self._model_client, "call"):
            return self._model_client.call(request=request, messages=messages, system=system, tools=tools)  # type: ignore[union-attr]
        return self._model_client(request=request, messages=messages, system=system, tools=tools)  # type: ignore[misc]

    def _normalize_model_response(
        self,
        response: Dict[str, Any],
        tool_defs: List[Dict[str, Any]],
    ) -> tuple[str, List[Dict[str, Any]]]:
        if not isinstance(response, dict):
            return str(response or ""), []
        content_text = str(response.get("content") or "")
        tool_calls = response.get("tool_calls") or []
        normalized = self._coerce_tool_calls(tool_calls)
        if not normalized and content_text:
            allowed = {str(definition.get("name") or "") for definition in tool_defs}
            content_text, normalized = parse_task_tool_calls(content_text, allowed)
        return content_text.strip(), normalized

    def _coerce_tool_calls(self, raw_tool_calls: Any) -> List[Dict[str, Any]]:
        items = raw_tool_calls if isinstance(raw_tool_calls, list) else [raw_tool_calls]
        normalized: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            function_payload = item.get("function") if isinstance(item.get("function"), dict) else {}
            tool_name = str(item.get("name") or item.get("tool_name") or function_payload.get("name") or "").strip()
            if not tool_name:
                continue
            tool_args = item.get("args")
            if tool_args is None:
                tool_args = item.get("arguments")
            if tool_args is None and function_payload:
                tool_args = function_payload.get("arguments")
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except Exception:
                    tool_args = {}
            if not isinstance(tool_args, dict):
                tool_args = {}
            normalized.append({
                "id": str(item.get("id") or uuid.uuid4().hex[:8]),
                "name": tool_name,
                "args": tool_args,
            })
        return normalized

    def _tool_batch_signature(self, tool_calls: List[Dict[str, Any]]) -> str:
        if not tool_calls:
            return ""
        safe_calls = [
            {"name": item.get("name"), "args": item.get("args") or {}}
            for item in tool_calls
        ]
        try:
            return json.dumps(safe_calls, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            return str(safe_calls)

    def _extract_file_changes(self, tool_name: str, tool_args: Dict[str, Any], result: Any) -> List[Dict[str, Any]]:
        changes: List[Dict[str, Any]] = []
        structured = parse_file_change(tool_name, tool_args, result)
        if structured:
            changes.append(structured)
        if tool_name == "run_python_code":
            for path in extract_koto_paths(result, _KOTO_CREATED_MARKER):
                changes.append({
                    "path": path,
                    "file_type": Path(path).suffix.lstrip(".").lower(),
                    "operation": "run_python_code",
                    "summary": f"Python 代码创建了 {Path(path).name}",
                    "preview": "",
                    "change_type": "create",
                    "focus": True,
                })
            for path in extract_koto_paths(result, _KOTO_MODIFIED_MARKER):
                changes.append({
                    "path": path,
                    "file_type": Path(path).suffix.lstrip(".").lower(),
                    "operation": "run_python_code",
                    "summary": f"Python 代码更新了 {Path(path).name}",
                    "preview": "",
                    "change_type": "modify",
                    "focus": True,
                })
        return changes

    def _tool_result_for_model(self, tool_name: str, result: Any) -> Any:
        if tool_name != "run_python_code" or not isinstance(result, dict):
            return result

        sanitized: Dict[str, Any] = {}
        summary = str(result.get("summary") or "").strip()
        stdout = str(result.get("stdout") or "").strip()
        stderr = str(result.get("stderr") or "").strip()
        error = str(result.get("error") or "").strip()
        if summary:
            sanitized["summary"] = summary
        if stdout:
            sanitized["stdout"] = stdout
        if stderr:
            sanitized["stderr"] = stderr
        if error:
            sanitized["error"] = error

        created = extract_koto_paths(result, _KOTO_CREATED_MARKER)
        modified = extract_koto_paths(result, _KOTO_MODIFIED_MARKER)
        if created:
            sanitized["created_paths"] = created
        if modified:
            sanitized["modified_paths"] = modified

        artifacts = extract_sandbox_artifacts(result)
        if artifacts:
            sanitized["generated_files"] = [artifact.get("name") for artifact in artifacts]
            sanitized["generated_file_count"] = len(artifacts)
        return sanitized or {"summary": "(no output)"}

    def _tool_feedback_for_model(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        model_result: Any,
        *,
        success: bool,
        blocked: bool = False,
        skipped: bool = False,
        invalid: bool = False,
    ) -> str:
        if success and not blocked and not skipped and not invalid:
            return _preview(stringify_result(model_result), 6000)

        if invalid:
            failure_reason = "invalid_tool"
            next_action = (
                "这个工具当前不在 Koto 文件任务 allowlist 中。"
                "请改用现有 allowlist 工具，或在确实缺原生能力时返回 tool_gap；"
                "不要重复调用同一个无效工具。"
            )
        elif blocked:
            failure_reason = "blocked"
            next_action = (
                "这次调用被运行时拦截。请根据 error 或 summary 改用允许的原生工具或修改方案；"
                "不要重复完全相同的调用。"
            )
        elif skipped:
            failure_reason = "skipped"
            next_action = (
                "这次调用被运行时跳过。请先理解跳过原因，再修改目标或方案；"
                "不要原样重复同一个调用。"
            )
        else:
            failure_reason = "execution_failed"
            next_action = (
                "上一个工具调用执行失败。请先根据 error、stderr、stdout 和 summary 判断错在哪；"
                "只有在参数、代码或方案已经改变时才允许再次调用，不要重复完全相同的调用。"
            )

        payload = {
            "tool_name": tool_name,
            "tool_args": self._truncate_tool_feedback_value(tool_args),
            "success": bool(success),
            "blocked": bool(blocked),
            "skipped": bool(skipped),
            "invalid_tool": bool(invalid),
            "failure_reason": failure_reason,
            "retry_same_call_allowed": False,
            "result": self._truncate_tool_feedback_value(model_result),
            "next_action": next_action,
        }
        return json.dumps(payload, ensure_ascii=False, default=str)

    def _extract_tool_runtime_outcome(self, result: Any) -> Optional[Dict[str, Any]]:
        payload = result if isinstance(result, dict) else _json_payload(result)
        if not isinstance(payload, dict):
            return None

        raw_status = str(payload.get("status") or "").strip().lower()
        awaiting_confirmation = bool(payload.get("awaiting_confirmation")) or raw_status == "awaiting_confirmation"
        artifact = payload.get("next_action_artifact") if isinstance(payload.get("next_action_artifact"), dict) else None
        summary = str(payload.get("summary") or payload.get("error") or "").strip()
        suggested_next_step = str(payload.get("suggested_next_step") or "").strip()
        status = "awaiting_confirmation" if awaiting_confirmation else raw_status
        if not status and artifact is None:
            return None

        outcome: Dict[str, Any] = {
            "status": status or "needs_attention",
            "summary": summary,
        }
        if suggested_next_step:
            outcome["suggested_next_step"] = suggested_next_step
        if artifact is not None:
            outcome["next_action_artifact"] = artifact
        return outcome

    def _tool_runtime_status(self, tool_runtime_outcome: Optional[Dict[str, Any]]) -> str:
        if not isinstance(tool_runtime_outcome, dict):
            return ""
        return str(tool_runtime_outcome.get("status") or "").strip().lower()

    def _truncate_tool_feedback_value(self, value: Any, *, depth: int = 0) -> Any:
        if isinstance(value, str):
            return _preview(value, 2400 if depth == 0 else 1600)
        if value is None or isinstance(value, (int, float, bool)):
            return value
        if depth >= 2:
            try:
                return _preview(json.dumps(value, ensure_ascii=False, default=str), 1600)
            except Exception:
                return _preview(str(value), 1600)
        if isinstance(value, dict):
            trimmed: Dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 20:
                    trimmed["__truncated__"] = True
                    break
                trimmed[str(key)] = self._truncate_tool_feedback_value(item, depth=depth + 1)
            return trimmed
        if isinstance(value, (list, tuple)):
            items = [
                self._truncate_tool_feedback_value(item, depth=depth + 1)
                for item in list(value)[:20]
            ]
            if len(value) > 20:
                items.append("__truncated__")
            return items
        return _preview(str(value), 1600)

    def _tool_artifacts(self, tool_name: str, result: Any) -> List[Dict[str, Any]]:
        if tool_name != "run_python_code":
            return []
        return extract_sandbox_artifacts(result)

    def _should_attempt_repair(
        self,
        check_payload: Optional[Dict[str, Any]],
        *,
        round_index: int,
        repair_attempts: int,
    ) -> bool:
        if not isinstance(check_payload, dict):
            return False
        if repair_attempts >= _MAX_VERIFY_REPAIR_ATTEMPTS:
            return False
        if round_index >= self._max_rounds:
            return False
        if bool(check_payload.get("passed")):
            return False
        status = str(check_payload.get("status") or "").strip().lower()
        return status in {"needs_attention", "no_file_change"}

    def _repair_retry_message(
        self,
        request: FileTaskRequest,
        check_payload: Dict[str, Any],
        file_changes: List[Dict[str, Any]],
    ) -> str:
        lines = [
            "核验未通过，当前任务还不能结束。下一轮必须修复目标文件，而不是重复上一轮完全相同的调用。",
        ]
        status = str(check_payload.get("status") or "").strip()
        summary = str(check_payload.get("summary") or "").strip()
        if status:
            lines.append(f"当前核验状态：{status}")
        if summary:
            lines.append(f"核验摘要：{summary}")
        if request.target_path:
            lines.append(f"目标文件：{request.target_path}")

        remaining = check_payload.get("remaining") if isinstance(check_payload.get("remaining"), list) else []
        if remaining:
            lines.append("仍需满足：")
            for index, item in enumerate(remaining[:5], start=1):
                text = str(item or "").strip()
                if text:
                    lines.append(f"{index}. {text}")

        if file_changes:
            lines.append("已观察到的文件变更：")
            for change in file_changes[-3:]:
                if not isinstance(change, dict):
                    continue
                change_summary = str(change.get("summary") or "").strip()
                path_text = str(change.get("path") or change.get("file_path") or "").strip()
                if change_summary and path_text:
                    lines.append(f"- {path_text}: {change_summary}")
                elif change_summary:
                    lines.append(f"- {change_summary}")
                elif path_text:
                    lines.append(f"- {path_text}")

        lines.append(
            "要求：先理解核验失败原因；只有当参数、代码、工具选择或写入位置已经改变时，才允许再次调用工具；修复后再结束。"
        )
        return "\n".join(lines)

    def _code_output_preview(self, tool_name: str, result: Any, result_text: str) -> str:
        if tool_name != "run_python_code" or not isinstance(result, dict):
            return _preview(result_text, 2000)

        parts: List[str] = []
        stdout = str(result.get("stdout") or "").strip()
        stderr = str(result.get("stderr") or "").strip()
        summary = str(result.get("summary") or "").strip()
        if stdout:
            parts.append(stdout)
        if stderr:
            parts.append(f"[stderr] {stderr}")
        if not parts and summary:
            parts.append(summary)
        return _preview("\n".join(parts) if parts else result_text, 2000)

    def _verify_task(
        self,
        request: FileTaskRequest,
        executor: ToolExecutor,
        file_changes: List[Dict[str, Any]],
        write_intent: bool,
        output_mode: str,
        model_failed: bool,
        readonly_fallback_used: bool = False,
        tool_runtime_outcome: Optional[Dict[str, Any]] = None,
        tool_gap: Optional[Dict[str, Any]] = None,
        next_action_artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if tool_gap:
            remaining = []
            if tool_gap.get("suggested_next_step"):
                remaining.append(str(tool_gap.get("suggested_next_step")))
            if isinstance(tool_gap.get("proposed_tool"), dict) and tool_gap["proposed_tool"].get("name"):
                remaining.append(f"按 {TOOL_DESIGN_PROTOCOL} 评估并实现新工具：{tool_gap['proposed_tool']['name']}")
            if not remaining:
                remaining = ["根据缺口说明补充 Koto 原生工具或调整任务范围"]
            return {
                "passed": False,
                "status": "tool_gap",
                "remaining": remaining,
                "tool_gap": tool_gap,
                "next_action_artifact": next_action_artifact,
            }
        runtime_status = self._tool_runtime_status(tool_runtime_outcome)
        if runtime_status == "awaiting_confirmation":
            artifact = tool_runtime_outcome.get("next_action_artifact") if isinstance(tool_runtime_outcome.get("next_action_artifact"), dict) else next_action_artifact
            remaining: List[str] = []
            if isinstance(artifact, dict):
                suggested = str(artifact.get("suggested_next_step") or artifact.get("summary") or "").strip()
                if suggested:
                    remaining.append(suggested)
            if not remaining:
                remaining = ["等待用户确认后继续下一步。"]
            return {
                "passed": False,
                "status": "awaiting_confirmation",
                "summary": str(tool_runtime_outcome.get("summary") or "任务已暂停，等待用户确认继续。"),
                "remaining": remaining,
                "next_action_artifact": artifact,
            }
        if runtime_status in {"blocked", "write_blocked"}:
            suggested = str((tool_runtime_outcome or {}).get("suggested_next_step") or "").strip()
            remaining = [suggested] if suggested else ["关闭占用目标文件的程序或页签后重试。"]
            return {
                "passed": False,
                "status": runtime_status,
                "summary": str((tool_runtime_outcome or {}).get("summary") or "目标文件当前不可写。"),
                "remaining": remaining,
                "next_action_artifact": next_action_artifact,
            }
        if write_intent and not file_changes:
            return {
                "status": "no_file_change",
                "summary": "任务包含写入意图，但没有任何工具报告文件变更。",
                "passed": False,
                "remaining": ["调用真实写入工具并确保产出 file.changed 事件"],
                "criteria_results": [
                    {
                        "criterion": "file_change_emitted",
                        "passed": False,
                        "detail": "任务包含写入意图，但没有任何工具报告文件变更。",
                        "priority": "critical",
                    }
                ],
            }
        if not write_intent and model_failed:
            return {
                "passed": False,
                "status": "model_unavailable",
                "summary": "模型不可用，已完成显式上下文读取但未生成 AI 分析。",
                "remaining": ["检查云端 API Key 或启动本地 Ollama 后重试"],
            }
        if not write_intent and readonly_fallback_used:
            return {
                "passed": True,
                "status": "context_summary_fallback",
                "summary": "模型不可用，已基于显式上下文生成可见内容摘要。",
                "remaining": ["恢复模型后可生成更完整的 AI 分析"],
            }

        if file_changes:
            verify_args = {
                "task_description": request.task,
                "file_states": json.dumps(file_states_for_changes(file_changes), ensure_ascii=False),
                "file_changes": json.dumps(file_changes, ensure_ascii=False),
                "target_path": request.target_path,
                "model_mode": request.model_mode,
            }
            try:
                result = executor("verify_task_completion", verify_args)
                payload = _json_payload(result)
            except Exception as exc:
                logger.warning("[FileTaskRuntime] verify_task_completion failed: %s", exc)
                payload = {"completed": False, "summary": f"文件已变更，但 AI 核验工具不可用：{exc}"}

            if payload.get("error"):
                return {
                    "passed": False,
                    "status": "verify_error",
                    "summary": f"文件已变更，但核验工具返回错误：{payload.get('error')}",
                    "remaining": ["修复模型/核验工具配置后重新核验"],
                    "criteria_results": [
                        {
                            "criterion": "verification_tool_available",
                            "passed": False,
                            "detail": f"核验工具返回错误：{payload.get('error')}",
                            "priority": "critical",
                        }
                    ],
                }

            completed = payload.get("completed")
            passed = bool(completed) if completed is not None else True
            return {
                "passed": passed,
                "status": "verified" if passed else "needs_attention",
                "summary": str(payload.get("summary") or ("文件变更已记录。" if passed else "核验未通过。")),
                "confidence": payload.get("confidence"),
                "remaining": payload.get("remaining_steps") or ([] if passed else ["根据核验结果继续修复"]),
                "criteria_results": payload.get("criteria_results") or [],
            }

        return {
            "passed": True,
            "status": "completed" if not model_failed else "context_only",
            "summary": "已完成分析建议，当前未直接写入文件。" if output_mode == "hybrid" else "已完成只读任务，没有产生文件写入。",
            "remaining": [],
        }
