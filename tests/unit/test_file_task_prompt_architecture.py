from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_file_task_prompt_is_built_before_kernel_adapter() -> None:
    phase = _read("app/core/agent/runtime/verify_phase.py")
    adapter = _read("app/core/agent/file_task_kernel_adapter.py")

    assert "build_file_task_runtime_system_prompt(" in phase
    assert "build_file_task_runtime_messages(" in phase
    assert "runtime._build_system_prompt(" in adapter
    assert "runtime._build_messages(" in adapter


def test_prompt_builder_owns_generic_guidance_and_payload() -> None:
    builder = _read("app/core/agent/file_task_system_prompt_builder.py")
    guidance = _read("app/core/agent/file_task_system_prompt_guidance.py")
    payload = _read("app/core/agent/file_task_system_prompt_payload.py")

    assert "build_file_task_system_prompt_guidance(" in builder
    assert "build_file_task_system_prompt_payload(" in builder
    assert "build_docx_prompt_guidance(" not in guidance
    assert "followup_guidance" in guidance
    assert "class FileTaskSystemPromptPayload" in payload


def test_message_payload_owns_file_context_projection() -> None:
    helper = _read("app/core/agent/file_task_message_payload.py")

    assert "def build_file_task_runtime_messages(" in helper
    assert "build_file_task_messages(" in helper
    assert "build_request_capability_profiles(request)" in helper
    assert "followup_context(request)" in helper


def test_prompt_keeps_relative_outputs_in_input_directory() -> None:
    prompt = _read("app/core/agent/file_task_system_prompt.py")

    assert "相对输出路径" in prompt
    assert "明确的输入目录" in prompt
    assert "工作区根目录" in prompt
