from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.core.agent.file_task_contract import FileTaskRequest

TOOL_DESIGN_PROTOCOL = "koto_tool_design_v1"
NEXT_ACTION_ARTIFACT_TYPE = "koto_next_action_v1"
NEXT_ACTION_ARTIFACT_CATEGORY = "missing_native_tool"
DEFAULT_TOOL_GAP_SUMMARY = "当前任务缺少对应的 Koto 原生工具。"
STANDARD_FILE_CHANGE_RETURNS = "Koto 标准 file-change payload，包含 path、operation、summary、preview、change_type。"

_PROPOSED_TOOL_OPTIONAL_FIELDS = (
    "implementation_notes",
    "safety_constraints",
    "acceptance_tests",
    "integration_points",
    "dependencies",
    "file_types",
    "output_contract",
    "read_only",
    "tool_family",
)
_DIRECT_TOOL_GAP_KEYS = (
    "summary",
    "missing_capability",
    "why_missing",
    "suggested_next_step",
    "proposed_tool",
    "tool_proposal",
)
_TOOL_DESIGN_RULES = (
    "先检查现有 allowlist 工具是否已经能完成任务；能完成就直接调用，不要返回 tool_gap。",
    "如果一个工具不够，优先组合多个现有工具，不要为工作流本身设计新工具。",
    "如果只是一次性计算、制图、批量转换或复杂处理，优先使用 run_python_code，不要把临时代码路径升级成平台工具。",
    "只有当现有工具与 run_python_code 都不能稳定完成、且缺的是可复用原生能力时，才返回 tool_gap。",
    "proposed_tool 必须是最小下一能力，不要把多步流程、UI 动作、模型提示词或外部系统打包成一个工具。",
    "proposed_tool 只是工具设计草案，不是可以立即执行的工具调用。",
)


def tool_design_rules() -> List[str]:
    return list(_TOOL_DESIGN_RULES)


def tool_gap_response_shape() -> Dict[str, Any]:
    return {
        "summary": "why Koto is blocked right now",
        "missing_capability": "missing capability or tool family",
        "why_missing": "why the available Koto tools cannot do the next step",
        "suggested_next_step": "best next action for Koto or the user",
        "proposed_tool": {
            "name": "optional_new_tool_name",
            "description": "what the new tool should do",
            "parameters": {"type": "object"},
            "returns": "what the tool should return",
            "rationale": "why this is the next best tool to add",
        },
    }


def planner_response_shape() -> Dict[str, Any]:
    return {
        "content": "brief Chinese status summary",
        "tool_calls": [{"name": "tool_name", "args": {}}],
        "tool_gap": tool_gap_response_shape(),
    }


def external_planner_protocol_text() -> str:
    numbered_rules = "\n".join(
        f"{index}. {rule}" for index, rule in enumerate(_TOOL_DESIGN_RULES, start=1)
    )
    return (
        f"Follow Koto Tool Design Protocol {TOOL_DESIGN_PROTOCOL} when native capability is missing.\n"
        f"{numbered_rules}"
    )


def tool_design_prompt_text() -> str:
    numbered_rules = "\n".join(
        f"   {index}. {rule}" for index, rule in enumerate(_TOOL_DESIGN_RULES, start=1)
    )
    return (
        f"Koto Tool Design Protocol（{TOOL_DESIGN_PROTOCOL}）：\n"
        f"{numbered_rules}\n"
        '   返回格式示例：{"tool_gap":{"summary":"...","missing_capability":"snake_case",'
        '"why_missing":"...","suggested_next_step":"...","proposed_tool":{"name":"snake_case",'
        '"description":"...","parameters":{"type":"object","properties":{}},'
        '"returns":"标准 file-change payload","rationale":"..."}}}\n'
        "   proposed_tool 可选补充 implementation_notes、safety_constraints、acceptance_tests、"
        "integration_points、dependencies、file_types、output_contract、read_only、tool_family。"
    )


def extract_first_json_value(text: Any) -> Any:
    decoder = json.JSONDecoder()
    source = str(text or "")
    for index, char in enumerate(source):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(source[index:])
        except Exception:
            continue
        return value
    return None


def _is_nonempty(value: Any) -> bool:
    return value not in (None, "", [], {})


def normalize_proposed_tool(
    value: Any,
    *,
    include_empty_contract_fields: bool = False,
) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None

    proposed_tool: Dict[str, Any] = {
        "name": str(value.get("name") or "").strip(),
        "description": str(value.get("description") or "").strip(),
        "parameters": (
            dict(value.get("parameters") or {})
            if isinstance(value.get("parameters"), dict)
            else {}
        ),
        "returns": str(value.get("returns") or "").strip(),
        "rationale": str(value.get("rationale") or "").strip(),
    }

    for field in _PROPOSED_TOOL_OPTIONAL_FIELDS:
        if field in value and _is_nonempty(value.get(field)):
            proposed_tool[field] = value.get(field)

    if not any(_is_nonempty(item) for item in proposed_tool.values()):
        return None

    if not include_empty_contract_fields:
        proposed_tool = {
            key: item for key, item in proposed_tool.items() if _is_nonempty(item)
        }

    if not proposed_tool:
        return None
    return proposed_tool


def normalize_tool_gap(
    candidate: Any,
    *,
    include_empty_contract_fields: bool = False,
) -> Optional[Dict[str, Any]]:
    if not isinstance(candidate, dict):
        return None

    if "proposed_tool" not in candidate and any(
        key in candidate for key in ("name", "description", "parameters")
    ):
        candidate = {
            "summary": candidate.get("summary") or DEFAULT_TOOL_GAP_SUMMARY,
            "missing_capability": candidate.get("missing_capability")
            or candidate.get("name")
            or "",
            "why_missing": candidate.get("why_missing")
            or candidate.get("reason")
            or "",
            "suggested_next_step": candidate.get("suggested_next_step")
            or candidate.get("next_step")
            or "",
            "proposed_tool": candidate,
        }

    summary = str(
        candidate.get("summary")
        or candidate.get("message")
        or candidate.get("title")
        or ""
    ).strip()
    missing_capability = str(
        candidate.get("missing_capability")
        or candidate.get("capability")
        or candidate.get("missing_tool")
        or ""
    ).strip()
    why_missing = str(
        candidate.get("why_missing") or candidate.get("reason") or ""
    ).strip()
    suggested_next_step = str(
        candidate.get("suggested_next_step")
        or candidate.get("next_step")
        or candidate.get("workaround")
        or ""
    ).strip()

    proposed_tool_raw = candidate.get("proposed_tool")
    if not isinstance(proposed_tool_raw, dict):
        proposed_tool_raw = (
            candidate.get("tool_proposal")
            if isinstance(candidate.get("tool_proposal"), dict)
            else None
        )
    proposed_tool = normalize_proposed_tool(
        proposed_tool_raw,
        include_empty_contract_fields=include_empty_contract_fields,
    )

    if not any([missing_capability, why_missing, suggested_next_step, proposed_tool]):
        return None

    payload: Dict[str, Any] = {
        "summary": summary or DEFAULT_TOOL_GAP_SUMMARY,
        "missing_capability": missing_capability,
        "why_missing": why_missing,
        "suggested_next_step": suggested_next_step,
    }
    if proposed_tool:
        payload["proposed_tool"] = proposed_tool
    return payload


def extract_tool_gap_from_response(
    response: Any,
    *,
    include_empty_contract_fields: bool = False,
) -> Optional[Dict[str, Any]]:
    if isinstance(response, dict):
        candidate = response.get("tool_gap")
        if not isinstance(candidate, dict):
            candidate = (
                response.get("capability_gap")
                if isinstance(response.get("capability_gap"), dict)
                else None
            )
        if not isinstance(candidate, dict):
            candidate = (
                response.get("tool_proposal")
                if isinstance(response.get("tool_proposal"), dict)
                else None
            )
        if not isinstance(candidate, dict) and any(
            key in response for key in _DIRECT_TOOL_GAP_KEYS
        ):
            candidate = response
        if isinstance(candidate, dict):
            return normalize_tool_gap(
                candidate,
                include_empty_contract_fields=include_empty_contract_fields,
            )
        parsed = extract_first_json_value(response.get("content"))
        if parsed is not None:
            return extract_tool_gap_from_response(
                parsed,
                include_empty_contract_fields=include_empty_contract_fields,
            )
    elif isinstance(response, str):
        parsed = extract_first_json_value(response)
        if parsed is not None:
            return extract_tool_gap_from_response(
                parsed,
                include_empty_contract_fields=include_empty_contract_fields,
            )
    return None


def build_tool_gap(
    *,
    summary: str = "",
    missing_capability: str = "",
    why_missing: str = "",
    suggested_next_step: str = "",
    proposed_tool: Optional[Dict[str, Any]] = None,
    include_empty_contract_fields: bool = False,
) -> Optional[Dict[str, Any]]:
    candidate: Dict[str, Any] = {
        "summary": summary,
        "missing_capability": missing_capability,
        "why_missing": why_missing,
        "suggested_next_step": suggested_next_step,
    }
    if isinstance(proposed_tool, dict):
        candidate["proposed_tool"] = proposed_tool
    return normalize_tool_gap(
        candidate,
        include_empty_contract_fields=include_empty_contract_fields,
    )


def merge_tool_gaps(
    tool_gap: Optional[Dict[str, Any]],
    known_tool_gap: Optional[Dict[str, Any]],
    *,
    include_empty_contract_fields: bool = False,
) -> Optional[Dict[str, Any]]:
    if not isinstance(tool_gap, dict):
        return normalize_tool_gap(
            known_tool_gap,
            include_empty_contract_fields=include_empty_contract_fields,
        )
    if not isinstance(known_tool_gap, dict):
        return normalize_tool_gap(
            tool_gap,
            include_empty_contract_fields=include_empty_contract_fields,
        )

    merged = dict(known_tool_gap)
    merged.update(
        {key: value for key, value in tool_gap.items() if _is_nonempty(value)}
    )

    known_proposed = (
        known_tool_gap.get("proposed_tool")
        if isinstance(known_tool_gap.get("proposed_tool"), dict)
        else {}
    )
    model_proposed = (
        tool_gap.get("proposed_tool")
        if isinstance(tool_gap.get("proposed_tool"), dict)
        else {}
    )
    if known_proposed or model_proposed:
        proposed_tool = dict(known_proposed)
        proposed_tool.update(
            {key: value for key, value in model_proposed.items() if _is_nonempty(value)}
        )
        normalized = normalize_proposed_tool(
            proposed_tool,
            include_empty_contract_fields=include_empty_contract_fields,
        )
        if normalized:
            merged["proposed_tool"] = normalized

    return normalize_tool_gap(
        merged,
        include_empty_contract_fields=include_empty_contract_fields,
    )


def build_next_action_artifact(
    request: FileTaskRequest,
    tool_gap: Optional[Dict[str, Any]],
    *,
    generated_by: str = "koto_file_task_runtime",
    external_planner_required: bool = False,
) -> Optional[Dict[str, Any]]:
    normalized_gap = normalize_tool_gap(
        tool_gap,
        include_empty_contract_fields=True,
    )
    if not isinstance(normalized_gap, dict):
        return None

    proposed_tool = normalize_proposed_tool(
        (
            normalized_gap.get("proposed_tool")
            if isinstance(normalized_gap.get("proposed_tool"), dict)
            else None
        ),
        include_empty_contract_fields=True,
    )
    summary = str(normalized_gap.get("summary") or DEFAULT_TOOL_GAP_SUMMARY).strip()
    missing_capability = str(
        normalized_gap.get("missing_capability")
        or (proposed_tool or {}).get("name")
        or ""
    ).strip()
    why_missing = str(normalized_gap.get("why_missing") or "").strip()
    suggested_next_step = str(normalized_gap.get("suggested_next_step") or "").strip()
    title_subject = str(
        (proposed_tool or {}).get("name") or missing_capability or "补齐缺失能力"
    ).strip()

    acceptance_criteria: List[str] = []
    if missing_capability:
        acceptance_criteria.append(
            f"为 {missing_capability} 提供稳定的 Koto 原生工具入口"
        )
    else:
        acceptance_criteria.append("为当前缺失能力提供稳定的 Koto 原生工具入口")
    acceptance_criteria.append("工具返回结构需要可被 file-task 规划器直接消费")
    acceptance_criteria.append("补齐能力后可重新执行当前任务而无需改写用户意图")
    if isinstance(proposed_tool, dict):
        for item in proposed_tool.get("acceptance_tests") or []:
            text = str(item or "").strip()
            if text and text not in acceptance_criteria:
                acceptance_criteria.append(text)

    artifact: Dict[str, Any] = {
        "artifact_type": NEXT_ACTION_ARTIFACT_TYPE,
        "category": NEXT_ACTION_ARTIFACT_CATEGORY,
        "tool_design_protocol": TOOL_DESIGN_PROTOCOL,
        "tool_design_status": "draft",
        "generated_by": generated_by,
        "external_planner_required": bool(external_planner_required),
        "title": f"Koto 下一步：{title_subject}",
        "summary": summary,
        "source_task": request.task,
        "target_path": request.target_path or "",
        "missing_capability": missing_capability,
        "why_missing": why_missing,
        "suggested_next_step": suggested_next_step,
        "implementation_scope": "smallest_next_capability",
        "acceptance_criteria": acceptance_criteria,
    }
    if proposed_tool:
        artifact["proposed_tool"] = proposed_tool
    return artifact


__all__ = [
    "DEFAULT_TOOL_GAP_SUMMARY",
    "NEXT_ACTION_ARTIFACT_CATEGORY",
    "NEXT_ACTION_ARTIFACT_TYPE",
    "STANDARD_FILE_CHANGE_RETURNS",
    "TOOL_DESIGN_PROTOCOL",
    "build_next_action_artifact",
    "build_tool_gap",
    "external_planner_protocol_text",
    "extract_first_json_value",
    "extract_tool_gap_from_response",
    "merge_tool_gaps",
    "normalize_proposed_tool",
    "normalize_tool_gap",
    "planner_response_shape",
    "tool_gap_response_shape",
    "tool_design_prompt_text",
    "tool_design_rules",
]
