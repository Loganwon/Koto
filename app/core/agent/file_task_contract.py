from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional


def _clean_str(value: Any, limit: int = 0) -> str:
    text = str(value or "").strip()
    if limit and len(text) > limit:
        return text[:limit]
    return text


def _clean_str_list(value: Any, *, limit: int = 12, item_limit: int = 240) -> List[str]:
    items = value if isinstance(value, list) else []
    cleaned: List[str] = []
    for item in items[:limit]:
        text = _clean_str(item, item_limit)
        if text:
            cleaned.append(text)
    return cleaned


@dataclass
class FileTaskFile:
    path: str = ""
    name: str = ""
    type: str = ""
    content: str = ""
    target: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "FileTaskFile":
        path = _clean_str(data.get("path") or data.get("source_path") or data.get("ws_source_path"))
        name = _clean_str(data.get("name") or data.get("file_name"))
        if not name and path:
            name = path.replace("\\", "/").rstrip("/").split("/")[-1]
        return cls(
            path=path,
            name=name,
            type=_clean_str(data.get("type") or data.get("file_type")).lower().lstrip("."),
            content=_clean_str(data.get("content"), 24_000),
            target=bool(data.get("target") or data.get("is_target")),
        )

    def public_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "type": self.type,
            "target": self.target,
            "has_content": bool(self.content),
        }


@dataclass
class FileTaskRequest:
    task: str
    run_id: str = ""
    session_id: str = ""
    files: List[FileTaskFile] = field(default_factory=list)
    current_file: Optional[FileTaskFile] = None
    selection: str = ""
    selection_source: str = ""
    target_path: str = ""
    model_mode: str = "cloud"
    model_id: str = ""
    history: List[Dict[str, Any]] = field(default_factory=list)
    options: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "FileTaskRequest":
        options = dict(data.get("options") or {}) if isinstance(data.get("options"), Mapping) else {}
        for key in (
            "planner_backend",
            "planner_policy",
            "planner_allow_native_fallback",
            "planner_command",
            "planner_timeout",
            "hermes_planner_command",
            "openclaw_planner_command",
        ):
            if key in data and key not in options:
                options[key] = data.get(key)
        raw_planner_options = data.get("planner_options")
        if isinstance(raw_planner_options, Mapping):
            merged_planner_options = {}
            if isinstance(options.get("planner_options"), Mapping):
                merged_planner_options.update(dict(options["planner_options"]))
            merged_planner_options.update(dict(raw_planner_options))
            options["planner_options"] = merged_planner_options

        files: List[FileTaskFile] = []
        for item in data.get("files") or []:
            if isinstance(item, Mapping):
                parsed = FileTaskFile.from_mapping(item)
                if parsed.path or parsed.name or parsed.content:
                    files.append(parsed)

        current_file = None
        raw_current = data.get("current_file")
        if isinstance(raw_current, Mapping):
            parsed_current = FileTaskFile.from_mapping(raw_current)
            if parsed_current.path or parsed_current.name or parsed_current.content:
                current_file = parsed_current

        history = data.get("history") or []
        if not isinstance(history, list):
            history = []

        return cls(
            task=_clean_str(data.get("task") or data.get("instruction") or data.get("selection"), 8_000),
            run_id=_clean_str(data.get("run_id")) or uuid.uuid4().hex[:12],
            session_id=_clean_str(data.get("session_id"), 96),
            files=files,
            current_file=current_file,
            selection=_clean_str(data.get("selection"), 12_000),
            selection_source=_clean_str(data.get("selection_source"), 240),
            target_path=_clean_str(data.get("target_path") or data.get("target"), 1_000),
            model_mode=_clean_str(data.get("model_mode") or "cloud", 32) or "cloud",
            model_id=_clean_str(data.get("model_id"), 160),
            history=history[-20:],
            options=options,
        )


@dataclass
class FileTaskExecutionBrief:
    title: str = "任务分析"
    summary: str = ""
    objective: str = ""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    planned_tools: List[str] = field(default_factory=list)
    read_targets: List[str] = field(default_factory=list)
    write_targets: List[str] = field(default_factory=list)
    verification: str = ""
    delegated_planner: str = ""
    note: str = ""
    estimated: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "FileTaskExecutionBrief":
        raw_steps = data.get("steps") or data.get("plan") or []
        steps: List[Dict[str, Any]] = []
        if isinstance(raw_steps, list):
            for index, item in enumerate(raw_steps[:8], start=1):
                if not isinstance(item, Mapping):
                    continue
                title = _clean_str(item.get("title") or item.get("step") or item.get("tool_name") or item.get("name"), 160)
                description = _clean_str(item.get("description") or item.get("detail"), 400)
                tool_name = _clean_str(item.get("tool_name") or item.get("name"), 120)
                step_payload: Dict[str, Any] = {
                    "id": _clean_str(item.get("id") or f"brief_step_{index}", 64) or f"brief_step_{index}",
                }
                if title:
                    step_payload["title"] = title
                if description:
                    step_payload["description"] = description
                if tool_name:
                    step_payload["tool_name"] = tool_name
                if len(step_payload) > 1:
                    steps.append(step_payload)

        summary = _clean_str(data.get("summary") or data.get("brief") or data.get("status"), 600)
        objective = _clean_str(data.get("objective") or data.get("goal") or data.get("outcome"), 800)
        if not summary and objective:
            summary = objective

        return cls(
            title=_clean_str(data.get("title") or "任务分析", 80) or "任务分析",
            summary=summary,
            objective=objective,
            steps=steps,
            planned_tools=_clean_str_list(data.get("planned_tools") or data.get("tools"), item_limit=120),
            read_targets=_clean_str_list(data.get("read_targets") or data.get("inputs"), item_limit=240),
            write_targets=_clean_str_list(data.get("write_targets") or data.get("targets"), item_limit=240),
            verification=_clean_str(data.get("verification") or data.get("verify") or data.get("success_check"), 400),
            delegated_planner=_clean_str(data.get("delegated_planner") or data.get("planner") or data.get("delegate_to"), 120),
            note=_clean_str(data.get("note") or data.get("notes"), 400),
            estimated=bool(data.get("estimated", True)),
        )

    def public_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "title": self.title or "任务分析",
            "summary": self.summary or self.objective or "AI 已完成任务分析。",
            "estimated": bool(self.estimated),
        }
        if self.steps:
            payload["steps"] = [dict(step) for step in self.steps]
        if self.objective:
            payload["objective"] = self.objective
        if self.planned_tools:
            payload["planned_tools"] = list(self.planned_tools)
        if self.read_targets:
            payload["read_targets"] = list(self.read_targets)
        if self.write_targets:
            payload["write_targets"] = list(self.write_targets)
        if self.verification:
            payload["verification"] = self.verification
        if self.delegated_planner:
            payload["delegated_planner"] = self.delegated_planner
        if self.note:
            payload["note"] = self.note
        return payload


@dataclass
class FileTaskClassification:
    request_kind: str = "new_task"
    task_family: str = "analyze"
    operation_kind: str = "read"
    execution_mode: str = "generic_tool_loop"
    output_mode: str = "answer"
    write_intent: bool = False
    diagnostic_request: bool = False
    docx_annotation_request: bool = False
    planner_policy: str = ""
    planner_reason: str = ""
    planner_backend: str = ""
    target_file_type: str = ""
    known_native_tool_gap: str = ""
    file_types: List[str] = field(default_factory=list)
    matched_capabilities: List[str] = field(default_factory=list)
    reason_codes: List[str] = field(default_factory=list)
    confidence: float = 1.0

    def public_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["file_types"] = [item for item in self.file_types if item]
        data["matched_capabilities"] = [item for item in self.matched_capabilities if item]
        data["reason_codes"] = [item for item in self.reason_codes if item]
        return data


@dataclass
class FileTaskIntentPlan:
    intent_type: str = "analyze"
    goal_statement: str = ""
    output_mode: str = "answer"
    confidence: float = 1.0
    write_intent: bool = False
    can_apply: bool = False
    requires_confirmation: bool = False
    recommended_strategy: str = "answer_only"
    dynamic_steps: List[Dict[str, Any]] = field(default_factory=list)
    reason_codes: List[str] = field(default_factory=list)

    def public_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["dynamic_steps"] = [dict(step) for step in self.dynamic_steps if isinstance(step, dict)]
        data["reason_codes"] = [item for item in self.reason_codes if item]
        return data


@dataclass
class FileTaskRequirementSet:
    requested_operation: str = "read"
    target_path: str = ""
    target_file_type: str = ""
    write_required: bool = False
    required_capabilities: List[str] = field(default_factory=list)
    forbidden_capabilities: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    reason_codes: List[str] = field(default_factory=list)

    def public_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["required_capabilities"] = [item for item in self.required_capabilities if item]
        data["forbidden_capabilities"] = [item for item in self.forbidden_capabilities if item]
        data["acceptance_criteria"] = [item for item in self.acceptance_criteria if item]
        data["reason_codes"] = [item for item in self.reason_codes if item]
        return data


@dataclass
class FileTaskPlanCheck:
    passed: bool = True
    status: str = "pass"
    summary: str = "计划与任务要求一致。"
    violations: List[str] = field(default_factory=list)

    def public_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["violations"] = [item for item in self.violations if item]
        return data


@dataclass
class FileTaskExecutionContext:
    classification: FileTaskClassification = field(default_factory=FileTaskClassification)
    intent_plan: FileTaskIntentPlan = field(default_factory=FileTaskIntentPlan)
    requirements: FileTaskRequirementSet = field(default_factory=FileTaskRequirementSet)
    plan_check: FileTaskPlanCheck = field(default_factory=FileTaskPlanCheck)
    known_tool_gap: Optional[Dict[str, Any]] = None
    effective_planner_policy: str = ""
    effective_planner_reason: str = ""
    effective_planner_backend: str = ""
    quick_action_mode: str = ""
    simple_quick_action: bool = False

    @property
    def write_intent(self) -> bool:
        return bool(self.classification.write_intent)

    def public_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "classification": self.classification.public_dict(),
            "intent_plan": self.intent_plan.public_dict(),
            "requirements": self.requirements.public_dict(),
            "plan_check": self.plan_check.public_dict(),
            "quick_action_mode": self.quick_action_mode,
            "simple_quick_action": bool(self.simple_quick_action),
            "write_intent": bool(self.write_intent),
        }
        if isinstance(self.known_tool_gap, dict) and self.known_tool_gap:
            data["known_tool_gap"] = dict(self.known_tool_gap)
        if any((self.effective_planner_policy, self.effective_planner_reason, self.effective_planner_backend)):
            data["effective_planner"] = {
                "policy": self.effective_planner_policy,
                "reason": self.effective_planner_reason,
                "backend": self.effective_planner_backend,
            }
        return data


@dataclass
class FileTaskEvent:
    type: str
    run_id: str
    seq: int
    payload: Dict[str, Any] = field(default_factory=dict)
    step_id: str = ""
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["ts"] = round(self.ts, 3)
        return data


@dataclass
class FileTaskToolStreamChunk:
    kind: str
    payload: Any = None
    event_type: str = ""


@dataclass
class FileTaskToolStreamResult:
    chunks: Iterable[FileTaskToolStreamChunk]


class FileTaskLedger:
    def __init__(self, run_id: Optional[str] = None):
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self._seq = 0

    def event(self, event_type: str, payload: Optional[Dict[str, Any]] = None, *, step_id: str = "") -> FileTaskEvent:
        self._seq += 1
        return FileTaskEvent(
            type=event_type,
            run_id=self.run_id,
            seq=self._seq,
            step_id=step_id,
            payload=payload or {},
        )


def event_to_sse(event: FileTaskEvent | Mapping[str, Any]) -> str:
    payload = event.to_dict() if isinstance(event, FileTaskEvent) else dict(event)
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def events_to_sse(events: Iterable[FileTaskEvent]) -> Iterable[str]:
    for event in events:
        yield event_to_sse(event)
