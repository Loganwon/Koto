import json

from app.core.agent.file_task_contract import FileTaskRequest
from app.core.agent.tool_design_protocol import (
    TOOL_DESIGN_PROTOCOL,
    build_next_action_artifact,
    extract_tool_gap_from_response,
    merge_tool_gaps,
)


def test_extract_tool_gap_from_response_parses_textual_protocol_payload():
    response = {
        "content": json.dumps(
            {
                "tool_gap": {
                    "summary": "需要一个 CAD 读取工具。",
                    "missing_capability": "read_cad_file",
                    "why_missing": "现有工具不能解析 DWG/DXF。",
                    "suggested_next_step": "先补齐只读能力。",
                    "proposed_tool": {
                        "name": "read_cad_file",
                        "description": "解析 DWG/DXF 为结构化文本。",
                        "parameters": {"type": "object"},
                        "implementation_notes": ["第一版只读。"],
                    },
                }
            },
            ensure_ascii=False,
        )
    }

    gap = extract_tool_gap_from_response(response)

    assert gap == {
        "summary": "需要一个 CAD 读取工具。",
        "missing_capability": "read_cad_file",
        "why_missing": "现有工具不能解析 DWG/DXF。",
        "suggested_next_step": "先补齐只读能力。",
        "proposed_tool": {
            "name": "read_cad_file",
            "description": "解析 DWG/DXF 为结构化文本。",
            "parameters": {"type": "object"},
            "implementation_notes": ["第一版只读。"],
        },
    }


def test_merge_tool_gaps_preserves_known_contract_and_model_details():
    known_gap = {
        "summary": "当前缺少读取 CAD 文件的 Koto 原生工具。",
        "missing_capability": "read_cad_file",
        "why_missing": "allowlist 中没有可读取 dwg 的工具。",
        "suggested_next_step": "先定义原生只读工具。",
        "proposed_tool": {
            "name": "read_cad_file",
            "description": "解析 DWG/DXF 为结构化文本。",
            "parameters": {"type": "object"},
            "returns": "结构化 CAD 文本摘要。",
            "rationale": "CAD 文件需要格式感知解析。",
        },
    }
    model_gap = {
        "summary": "还需要一版最小 CAD 只读能力。",
        "missing_capability": "read_cad_file",
        "why_missing": "现有工具不能解析 DWG。",
        "suggested_next_step": "先实现只读解析，再评估写回。",
        "proposed_tool": {
            "name": "read_cad_file",
            "implementation_notes": ["第一版只读，不写回 CAD。"],
            "safety_constraints": ["不得修改源文件。"],
        },
    }

    merged = merge_tool_gaps(model_gap, known_gap)

    assert merged == {
        "summary": "还需要一版最小 CAD 只读能力。",
        "missing_capability": "read_cad_file",
        "why_missing": "现有工具不能解析 DWG。",
        "suggested_next_step": "先实现只读解析，再评估写回。",
        "proposed_tool": {
            "name": "read_cad_file",
            "description": "解析 DWG/DXF 为结构化文本。",
            "parameters": {"type": "object"},
            "returns": "结构化 CAD 文本摘要。",
            "rationale": "CAD 文件需要格式感知解析。",
            "implementation_notes": ["第一版只读，不写回 CAD。"],
            "safety_constraints": ["不得修改源文件。"],
        },
    }


def test_build_next_action_artifact_uses_protocol_contract_and_acceptance_tests():
    request = FileTaskRequest(task="分析这个 CAD 文件", target_path="drawing.dwg")
    artifact = build_next_action_artifact(
        request,
        {
            "summary": "当前缺少读取 CAD 文件的 Koto 原生工具。",
            "missing_capability": "read_cad_file",
            "why_missing": "allowlist 中没有可读取 dwg 的工具。",
            "suggested_next_step": "先实现只读 CAD 解析工具，再决定写入方案。",
            "proposed_tool": {
                "name": "read_cad_file",
                "description": "解析 DWG/DXF 为可检索的结构化文本。",
                "parameters": {"type": "object"},
                "acceptance_tests": ["DWG/DXF 示例文件可以返回图层和实体摘要。"],
            },
        },
    )

    assert artifact is not None
    assert artifact["tool_design_protocol"] == TOOL_DESIGN_PROTOCOL
    assert artifact["title"] == "Koto 下一步：read_cad_file"
    assert "DWG/DXF 示例文件可以返回图层和实体摘要。" in artifact["acceptance_criteria"]