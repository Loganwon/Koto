from __future__ import annotations

import functools
import hashlib
import importlib.util
import json
import logging
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence

from app.core.agent.file_task_contract import FileTaskRequest
from app.core.agent.tool_design_protocol import (
    TOOL_DESIGN_PROTOCOL,
    external_planner_protocol_text,
    extract_first_json_value,
    extract_tool_gap_from_response,
    planner_response_shape,
)
from app.core.shared.tool_parser import parse_task_tool_calls

logger = logging.getLogger(__name__)

PlannerResponse = Dict[str, Any]


_DEFAULT_HERMES_PLANNER_MAX_ITERATIONS = 4
_DEFAULT_HERMES_PLANNER_MODEL = "gemini-3-flash-preview"


@dataclass(frozen=True)
class FileTaskPlannerSupport:
    backend: str
    available: bool
    detected: bool = False
    reason: str = ""
    repo_path: str = ""
    transport: str = ""
    transport_hint: str = ""


class FileTaskPlannerAdapter(Protocol):
    backend_name: str

    def support(self, request: Optional[FileTaskRequest] = None) -> FileTaskPlannerSupport:
        ...

    def call(
        self,
        *,
        request: FileTaskRequest,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Dict[str, Any]],
    ) -> PlannerResponse:
        ...


def _koto_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_repo_path(repo_dir_name: str) -> Path:
    return _koto_root() / ".tmp_external_agents" / repo_dir_name


def _normalize_command_parts(command: Any) -> List[str]:
    if isinstance(command, (list, tuple)):
        return [str(part).strip() for part in command if str(part).strip()]

    text = str(command or "").strip()
    if not text:
        return []
    if os.name == "nt":
        return ["cmd", "/c", text]
    return ["/bin/sh", "-lc", text]


def _planner_option(request: Optional[FileTaskRequest], *keys: str, default: Any = None) -> Any:
    if request is None:
        return default
    for key in keys:
        if key in request.options:
            value = request.options.get(key)
            if value is not None:
                return value
    return default


def _normalize_name_list(value: Any) -> List[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def _tool_name(definition: Dict[str, Any]) -> str:
    function_payload = definition.get("function") if isinstance(definition.get("function"), dict) else {}
    return str(definition.get("name") or function_payload.get("name") or "").strip()


def _tool_parameters(definition: Dict[str, Any]) -> Dict[str, Any]:
    function_payload = definition.get("function") if isinstance(definition.get("function"), dict) else {}
    parameters = definition.get("parameters")
    if isinstance(parameters, dict):
        return dict(parameters)
    parameters = function_payload.get("parameters")
    return dict(parameters) if isinstance(parameters, dict) else {}


def _tool_prompt_payload(definition: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": _tool_name(definition),
        "description": str(definition.get("description") or "").strip(),
        "parameters": _tool_parameters(definition),
        "read_only": bool(definition.get("read_only")),
        "file_types": list(definition.get("file_types") or []),
    }


def _json_preview(value: Any, limit: int = 3_000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False)
    except Exception:
        text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _message_prompt_payload(message: Dict[str, Any]) -> Dict[str, Any]:
    role = str(message.get("role") or "").strip().lower()
    if role == "model":
        role = "assistant"
    elif role == "function":
        role = "tool"

    payload: Dict[str, Any] = {
        "role": role or "unknown",
        "content": str(message.get("content") or message.get("text") or "").strip(),
    }
    if message.get("name"):
        payload["name"] = str(message.get("name"))
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        payload["tool_calls"] = [
            {
                "name": str(item.get("name") or item.get("tool_name") or "").strip(),
                "args": item.get("args") or item.get("arguments") or {},
            }
            for item in tool_calls
            if isinstance(item, dict)
        ]
    return payload


def _request_prompt_payload(request: FileTaskRequest) -> Dict[str, Any]:
    return {
        "task": request.task,
        "run_id": request.run_id,
        "session_id": request.session_id,
        "target_path": request.target_path,
        "selection": request.selection,
        "selection_source": request.selection_source,
        "model_mode": request.model_mode,
        "model_id": request.model_id,
        "current_file": request.current_file.public_dict() if request.current_file else None,
        "files": [file_info.public_dict() for file_info in request.files],
    }


def _coerce_tool_calls(candidate: Any, allowed_tool_names: Sequence[str]) -> List[Dict[str, Any]]:
    allowed = {str(name).strip() for name in allowed_tool_names if str(name).strip()}
    items = candidate if isinstance(candidate, list) else [candidate]
    tool_calls: List[Dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            return []
        function_payload = item.get("function") if isinstance(item.get("function"), dict) else {}
        tool_name = str(
            item.get("name")
            or item.get("tool_name")
            or function_payload.get("name")
            or ""
        ).strip()
        if not tool_name or (allowed and tool_name not in allowed):
            return []

        tool_args = item.get("args")
        if tool_args is None:
            tool_args = item.get("arguments")
        if tool_args is None and function_payload:
            tool_args = function_payload.get("arguments")
        if isinstance(tool_args, str):
            try:
                tool_args = json.loads(tool_args)
            except Exception:
                return []
        if tool_args is None:
            tool_args = {}
        if not isinstance(tool_args, dict):
            return []
        tool_calls.append({"name": tool_name, "args": tool_args})

    return tool_calls


def _normalize_planner_output(raw_output: Any, allowed_tool_names: Sequence[str]) -> PlannerResponse:
    parsed_json = raw_output if isinstance(raw_output, (dict, list)) else extract_first_json_value(str(raw_output or ""))

    if isinstance(parsed_json, dict):
        tool_calls = _coerce_tool_calls(parsed_json.get("tool_calls") or parsed_json.get("actions"), allowed_tool_names)
        tool_gap = extract_tool_gap_from_response(parsed_json, include_empty_contract_fields=True)
        content = str(
            parsed_json.get("content")
            or parsed_json.get("message")
            or parsed_json.get("summary")
            or ""
        ).strip()
        if tool_calls or content or tool_gap:
            response: PlannerResponse = {"content": content, "tool_calls": tool_calls}
            if tool_gap:
                response["tool_gap"] = tool_gap
            return response

    if isinstance(parsed_json, list):
        tool_calls = _coerce_tool_calls(parsed_json, allowed_tool_names)
        if tool_calls:
            return {"content": "", "tool_calls": tool_calls}

    content_text, tool_calls = parse_task_tool_calls(str(raw_output or ""), allowed_tool_names)
    return {"content": content_text.strip(), "tool_calls": tool_calls}


def _planner_request_payload(
    request: FileTaskRequest,
    messages: List[Dict[str, Any]],
    system: str,
    tools: List[Dict[str, Any]],
    backend: str,
) -> Dict[str, Any]:
    return {
        "backend": backend,
        "request": asdict(request),
        "messages": messages,
        "system": system,
        "tools": tools,
    }


class CommandPlannerAdapter:
    backend_name = ""
    env_var_name = ""
    repo_dir_name = ""
    transport_hint = (
        "Configure a wrapper command that reads a JSON payload from stdin and prints a JSON model response to stdout."
    )

    def __init__(self, *, repo_path: str = ""):
        self._repo_path = Path(repo_path) if repo_path else _default_repo_path(self.repo_dir_name)

    def _command_option_keys(self) -> Sequence[str]:
        return (
            f"{self.backend_name}_planner_command",
            "planner_command",
        )

    def _planner_command(self, request: Optional[FileTaskRequest] = None) -> Any:
        if request is not None:
            for key in self._command_option_keys():
                value = request.options.get(key)
                if value:
                    return value
        return os.environ.get(self.env_var_name, "")

    def support(self, request: Optional[FileTaskRequest] = None) -> FileTaskPlannerSupport:
        repo_exists = self._repo_path.exists()
        command = self._planner_command(request)
        available = bool(_normalize_command_parts(command))
        if available:
            reason = ""
        elif repo_exists:
            reason = (
                f"Detected local {self.backend_name} sources but no planner command is configured. "
                f"Set request.options['{self.backend_name}_planner_command'], request.options['planner_command'], "
                f"or environment variable {self.env_var_name}."
            )
        else:
            reason = (
                f"No planner command is configured for {self.backend_name}, and local sources were not found at "
                f"{self._repo_path}."
            )
        return FileTaskPlannerSupport(
            backend=self.backend_name,
            available=available,
            detected=repo_exists,
            reason=reason,
            repo_path=str(self._repo_path),
            transport="command" if available else "",
            transport_hint=self.transport_hint,
        )

    def call(
        self,
        *,
        request: FileTaskRequest,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Dict[str, Any]],
    ) -> PlannerResponse:
        support = self.support(request)
        command = _normalize_command_parts(self._planner_command(request))
        if not support.available or not command:
            raise RuntimeError(support.reason or f"{self.backend_name} planner is not configured")

        payload = _planner_request_payload(
            request=request,
            messages=messages,
            system=system,
            tools=tools,
            backend=self.backend_name,
        )
        timeout = float(request.options.get("planner_timeout") or 60)
        completed = subprocess.run(
            command,
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            cwd=str(self._repo_path) if support.detected else None,
            timeout=max(timeout, 1.0),
            check=False,
        )
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if completed.returncode != 0:
            detail = stderr or stdout or f"exit code {completed.returncode}"
            raise RuntimeError(f"{self.backend_name} planner command failed: {detail}")
        if not stdout:
            raise RuntimeError(f"{self.backend_name} planner command returned no stdout payload")

        try:
            response = json.loads(stdout)
        except Exception as exc:
            raise RuntimeError(
                f"{self.backend_name} planner command did not return valid JSON: {_preview_text(stdout)}"
            ) from exc

        if not isinstance(response, dict):
            raise RuntimeError(f"{self.backend_name} planner response must be a JSON object")
        if "content" not in response and "tool_calls" not in response and "tool_gap" not in response:
            raise RuntimeError(
                f"{self.backend_name} planner response must contain 'content', 'tool_calls', or 'tool_gap'"
            )
        return response


class HermesPlannerAdapter(CommandPlannerAdapter):
    backend_name = "hermes"
    env_var_name = "KOTO_HERMES_PLANNER_COMMAND"
    repo_dir_name = "hermes-agent"
    transport_hint = (
        "Uses the local Hermes AIAgent bridge when .tmp_external_agents/hermes-agent/run_agent.py exists; "
        "falls back to a configured planner command when requested."
    )

    def support(self, request: Optional[FileTaskRequest] = None) -> FileTaskPlannerSupport:
        entrypoint = self._entrypoint_path()
        repo_exists = self._repo_path.exists()
        command = self._planner_command(request)
        available = entrypoint.exists() or bool(_normalize_command_parts(command))
        if available:
            reason = ""
        elif repo_exists:
            reason = (
                "Detected local Hermes sources but run_agent.py is missing and no planner command is configured. "
                f"Expected entrypoint at {entrypoint}."
            )
        else:
            reason = (
                "No Hermes planner bridge detected. Add .tmp_external_agents/hermes-agent or configure "
                f"{self.env_var_name}."
            )
        return FileTaskPlannerSupport(
            backend=self.backend_name,
            available=available,
            detected=repo_exists,
            reason=reason,
            repo_path=str(self._repo_path),
            transport="embedded" if entrypoint.exists() else ("command" if bool(_normalize_command_parts(command)) else ""),
            transport_hint=self.transport_hint,
        )

    def call(
        self,
        *,
        request: FileTaskRequest,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Dict[str, Any]],
    ) -> PlannerResponse:
        transport = str(
            _planner_option(
                request,
                "hermes_planner_transport",
                "planner_transport",
                default="",
            )
            or ""
        ).strip().lower()
        use_command = transport in {"command", "cli", "subprocess"}
        entrypoint = self._entrypoint_path()

        if not use_command and entrypoint.exists():
            try:
                return self._call_embedded(request=request, messages=messages, system=system, tools=tools)
            except Exception:
                if _normalize_command_parts(self._planner_command(request)):
                    logger.warning("[HermesPlannerAdapter] embedded Hermes bridge failed; trying command fallback", exc_info=True)
                else:
                    raise

        return super().call(request=request, messages=messages, system=system, tools=tools)

    def _entrypoint_path(self) -> Path:
        return self._repo_path / "run_agent.py"

    def _call_embedded(
        self,
        *,
        request: FileTaskRequest,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Dict[str, Any]],
    ) -> PlannerResponse:
        agent_class = self._load_agent_class()
        planner_model = str(
            _planner_option(
                request,
                "hermes_planner_model",
                "planner_model",
                default="",
            )
            or self._infer_model(request)
        ).strip()
        planner_base_url = str(
            _planner_option(
                request,
                "hermes_planner_base_url",
                "planner_base_url",
                default=os.environ.get("KOTO_HERMES_BASE_URL", ""),
            )
            or ""
        ).strip()
        planner_api_key = str(
            _planner_option(
                request,
                "hermes_planner_api_key",
                "planner_api_key",
                default=os.environ.get("KOTO_HERMES_API_KEY", ""),
            )
            or ""
        ).strip()
        max_iterations = int(
            _planner_option(
                request,
                "hermes_planner_max_iterations",
                "planner_max_iterations",
                default=_DEFAULT_HERMES_PLANNER_MAX_ITERATIONS,
            )
            or _DEFAULT_HERMES_PLANNER_MAX_ITERATIONS
        )

        agent = agent_class(
            base_url=planner_base_url or None,
            api_key=planner_api_key or None,
            model=planner_model,
            max_iterations=max(1, max_iterations),
            tool_delay=0.0,
            enabled_toolsets=[],
            disabled_toolsets=[],
            quiet_mode=True,
            verbose_logging=False,
            skip_context_files=True,
            skip_memory=True,
            load_soul_identity=False,
            session_id=self._session_id(request),
            platform="koto-file-task",
        )
        result = agent.run_conversation(
            user_message=self._build_user_message(request=request, messages=messages, tools=tools),
            system_message=self._build_system_message(system),
            task_id=request.run_id,
        )
        normalized = _normalize_planner_output(result.get("final_response"), [_tool_name(tool) for tool in tools])
        normalized["_planner"] = {
            "backend": self.backend_name,
            "transport": "embedded",
            "api_calls": result.get("api_calls"),
            "completed": result.get("completed"),
            "turn_exit_reason": result.get("turn_exit_reason"),
            "model": result.get("model") or planner_model,
        }
        return normalized

    def _build_system_message(self, system: str) -> str:
        prefix = (
            "You are Hermes acting as the external planner for Koto file tasks. "
            "Do not execute Hermes tools, browse, call terminals, or invent external capabilities. "
            "Return exactly one JSON object with keys 'content', 'tool_calls', and optionally 'tool_gap'. "
            "Each tool call must be an object {'name': string, 'args': object} using only the provided Koto tool names. "
            "If no tool should run next, return an empty tool_calls array. "
            "Prefer the smallest next tool batch and never guess file names, sheet names, slide indices, or document structure without evidence from the provided context."
        )
        prefix += "\n\n" + external_planner_protocol_text()
        if not system.strip():
            return prefix
        return prefix + "\n\nKoto runtime rules:\n" + system.strip()

    def _build_user_message(
        self,
        *,
        request: FileTaskRequest,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> str:
        payload = {
            "request": _request_prompt_payload(request),
            "messages": [_message_prompt_payload(message) for message in messages],
            "available_koto_tools": [_tool_prompt_payload(tool) for tool in tools if _tool_name(tool)],
            "tool_design_protocol": TOOL_DESIGN_PROTOCOL,
            "required_response_shape": planner_response_shape(),
        }
        return (
            "Plan only the next Koto-native action batch for this file task. "
            "If Koto lacks a matching tool, do not fake a tool call. Return tool_gap instead, and keep the proposal scoped to the smallest next capability Koto should add. "
            "Return JSON only.\n\n"
            + _json_preview(payload, limit=24_000)
        )

    def _infer_model(self, request: FileTaskRequest) -> str:
        requested = str(request.model_id or "").strip()
        if requested and requested.lower() not in {"auto", "cloud", "local", "native", "default"}:
            return requested
        if str(request.model_mode or "").strip().lower() == "local":
            local_model = str(request.options.get("local_model") or "").strip()
            if local_model:
                return local_model
        configured = str(os.environ.get("KOTO_HERMES_PLANNER_MODEL") or "").strip()
        if configured:
            return configured
        try:
            from web.app import MODEL_MAP  # type: ignore

            for task_key in ("FILE_TASK", "CHAT"):
                model_from_app = str(MODEL_MAP.get(task_key) or "").strip()
                if model_from_app:
                    return model_from_app
        except Exception:
            pass
        return _DEFAULT_HERMES_PLANNER_MODEL

    def _session_id(self, request: FileTaskRequest) -> str:
        base = str(request.session_id or request.run_id or "koto-file-task").strip() or "koto-file-task"
        return f"koto_file_task_{base[:72]}"

    def _load_agent_class(self):
        return _load_hermes_agent_class(str(self._repo_path))


class OpenClawPlannerAdapter(CommandPlannerAdapter):
    backend_name = "openclaw"
    env_var_name = "KOTO_OPENCLAW_PLANNER_COMMAND"
    repo_dir_name = "openclaw"


class FileTaskPlannerRegistry:
    def __init__(self, adapters: Optional[List[FileTaskPlannerAdapter]] = None):
        self._adapters: Dict[str, FileTaskPlannerAdapter] = {}
        for adapter in adapters or default_file_task_planner_adapters():
            self.register(adapter)

    def register(self, adapter: FileTaskPlannerAdapter) -> None:
        backend = str(getattr(adapter, "backend_name", "") or "").strip().lower()
        if not backend:
            raise ValueError("planner adapter must declare backend_name")
        self._adapters[backend] = adapter

    def get(self, backend: str) -> Optional[FileTaskPlannerAdapter]:
        return self._adapters.get(str(backend or "").strip().lower())

    def describe(self, request: Optional[FileTaskRequest] = None) -> List[FileTaskPlannerSupport]:
        return [adapter.support(request) for adapter in self._adapters.values()]


def default_file_task_planner_adapters() -> List[FileTaskPlannerAdapter]:
    return [HermesPlannerAdapter(), OpenClawPlannerAdapter()]


def _preview_text(value: Any, limit: int = 220) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _load_hermes_agent_class(repo_path: str):
    return _load_hermes_agent_class_cached(str(Path(repo_path).resolve()))


def _import_module_from_file(module_name: str, file_path: Path, sys_path_entry: Path):
    if str(sys_path_entry) not in sys.path:
        sys.path.insert(0, str(sys_path_entry))
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to create import spec for {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@functools.lru_cache(maxsize=2)
def _load_hermes_agent_class_cached(repo_path: str):
    root = Path(repo_path)
    entrypoint = root / "run_agent.py"
    if not entrypoint.exists():
        raise RuntimeError(f"Hermes run_agent.py not found at {entrypoint}")
    module_name = "koto_hermes_run_agent_" + hashlib.sha1(str(entrypoint).encode("utf-8")).hexdigest()[:12]
    module = _import_module_from_file(module_name, entrypoint, root)
    agent_class = getattr(module, "AIAgent", None)
    if agent_class is None:
        raise RuntimeError(f"Hermes entrypoint {entrypoint} does not expose AIAgent")
    return agent_class