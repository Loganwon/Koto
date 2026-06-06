from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol

from app.core.agent.file_task_tool_catalog import file_task_tool_specs, is_file_task_tool

ToolExecutor = Callable[[str, Dict[str, Any]], Any]


@dataclass(frozen=True)
class FileTaskToolContext:
    """Per-run context passed to file-task tool providers."""

    task_files: List[Dict[str, Any]] = field(default_factory=list)
    workspace_root: str = ""
    gemini_client: Any = None
    request_context: Dict[str, Any] = field(default_factory=dict)


class FileTaskToolProvider(Protocol):
    """Stable provider interface for Koto file-task tools."""

    def definitions(self) -> List[Dict[str, Any]]:
        ...

    def allowed_names(self) -> set[str]:
        ...

    def execute(self, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        ...


def _minimal_definition(tool_name: str) -> Dict[str, Any]:
    spec = next((item for item in file_task_tool_specs() if item.name == tool_name), None)
    return {
        "name": tool_name,
        "description": f"Koto file-task tool ({spec.family if spec else 'custom'}).",
        "parameters": {"type": "object", "properties": {}},
        "read_only": bool(spec.read_only) if spec else False,
        "file_types": list(spec.file_types) if spec else [],
    }


class CallableFileTaskToolProvider:
    """Adapter used by tests and narrow integrations that only supply execute()."""

    def __init__(self, executor: ToolExecutor, *, definitions: Optional[List[Dict[str, Any]]] = None):
        self._executor = executor
        self._definitions = definitions or [_minimal_definition(spec.name) for spec in file_task_tool_specs()]

    def definitions(self) -> List[Dict[str, Any]]:
        return [dict(definition) for definition in self._definitions if is_file_task_tool(str(definition.get("name") or ""))]

    def allowed_names(self) -> set[str]:
        return {str(definition.get("name") or "") for definition in self.definitions()}

    def execute(self, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        return self._executor(tool_name, dict(tool_args or {}))


class RegistryBackedFileTaskToolProvider:
    """Current built-in adapter around Koto's existing TaskToolsPlugin registry."""

    def __init__(self, *, context: Optional[FileTaskToolContext] = None):
        from app.core.agent.task_tools import TaskToolsPlugin
        from app.core.agent.tool_registry import ToolRegistry

        self._context = context or FileTaskToolContext()
        self._registry = ToolRegistry()
        self._registry.register_plugin(
            TaskToolsPlugin(
                task_files=self._context.task_files or [],
                gemini_client=self._context.gemini_client,
                workspace_root=self._context.workspace_root,
                request_context=self._context.request_context or {},
            )
        )
        self._definitions = [
            definition
            for definition in self._registry.get_definitions()
            if is_file_task_tool(str(definition.get("name") or ""))
        ]

    def definitions(self) -> List[Dict[str, Any]]:
        return [dict(definition) for definition in self._definitions]

    def allowed_names(self) -> set[str]:
        return {str(definition.get("name") or "") for definition in self._definitions}

    def execute(self, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        return self._registry.execute(tool_name, dict(tool_args or {}))


class FileTaskToolGateway:
    """Single execution entry for current and future file-task tool adapters.

    The runtime depends on this gateway instead of concrete Office/PDF/OCR tool
    implementations. New providers can be added here without changing the agent
    loop, while the Koto allowlist remains the final boundary exposed to models.
    """

    def __init__(
        self,
        *,
        context: Optional[FileTaskToolContext] = None,
        providers: Optional[Iterable[FileTaskToolProvider]] = None,
        tool_executor: Optional[ToolExecutor] = None,
    ):
        self._context = context or FileTaskToolContext()
        self._task_file_types = {
            str(item.get("type") or item.get("file_type") or "").strip().lower().lstrip(".")
            for item in (self._context.task_files or [])
            if isinstance(item, dict)
        }
        self._task_file_types.discard("")
        self._task_file_types.update(self._request_context_file_types())
        provider_list = list(providers or [])
        if tool_executor is not None:
            provider_list.append(CallableFileTaskToolProvider(tool_executor))
        if not provider_list:
            provider_list.append(RegistryBackedFileTaskToolProvider(context=self._context))

        self._providers = provider_list
        self._provider_by_tool: Dict[str, FileTaskToolProvider] = {}
        self._definitions = self._merge_definitions(provider_list)

    def definitions(self) -> List[Dict[str, Any]]:
        return [dict(definition) for definition in self._definitions]

    def allowed_names(self) -> set[str]:
        return set(self._provider_by_tool)

    def execute(self, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        name = str(tool_name or "").strip()
        if not is_file_task_tool(name):
            raise ValueError(f"Tool '{name}' is not allowlisted for Koto file tasks")
        provider = self._provider_by_tool.get(name)
        if provider is None:
            raise ValueError(f"Tool '{name}' has no registered Koto file-task provider")
        return provider.execute(name, dict(tool_args or {}))

    def _merge_definitions(self, providers: List[FileTaskToolProvider]) -> List[Dict[str, Any]]:
        definitions_by_name: Dict[str, Dict[str, Any]] = {}
        for provider in providers:
            provider_names = {
                str(name or "").strip()
                for name in provider.allowed_names()
                if self._tool_matches_context(str(name or "").strip())
            }
            for name in provider_names:
                if is_file_task_tool(name) and name not in self._provider_by_tool:
                    self._provider_by_tool[name] = provider

            for definition in provider.definitions():
                name = str(definition.get("name") or "").strip()
                if is_file_task_tool(name) and self._tool_matches_context(name) and name not in definitions_by_name:
                    definitions_by_name[name] = dict(definition)

        for name in self._provider_by_tool:
            definitions_by_name.setdefault(name, _minimal_definition(name))

        spec_order = [spec.name for spec in file_task_tool_specs()]
        return [definitions_by_name[name] for name in spec_order if name in definitions_by_name]

    def _tool_matches_context(self, tool_name: str) -> bool:
        if not self._task_file_types:
            return True

        spec = next((item for item in file_task_tool_specs() if item.name == tool_name), None)
        if spec is None or not spec.file_types:
            return True
        return bool(self._task_file_types.intersection(spec.file_types))

    def _request_context_file_types(self) -> set[str]:
        request_context = self._context.request_context if isinstance(self._context.request_context, dict) else {}
        inferred: set[str] = set()
        target_path = str(request_context.get("target_path") or "").strip()
        target_suffix = Path(target_path).suffix.lstrip(".").lower()
        if target_suffix:
            inferred.add(target_suffix)
        options = request_context.get("options") if isinstance(request_context.get("options"), dict) else {}
        option_type = str(options.get("inferred_target_file_type") or options.get("target_file_type") or "").strip().lower().lstrip(".")
        if option_type:
            inferred.add(option_type)
        task_text = str(request_context.get("task") or "").strip().lower()
        if re.search(r"(?:创建|新建|生成|输出|写入|加入|插入|整理成|create|generate|output|record|write).{0,24}(?:docx|word|文档)", task_text, re.IGNORECASE):
            inferred.add("docx")
        if re.search(r"(?:创建|新建|生成|输出|写入|加入|插入|整理成).{0,24}(?:pptx|ppt|幻灯片|演示文稿|slides?)", task_text, re.IGNORECASE):
            inferred.add("pptx")
        if re.search(r"(?:创建|新建|生成|输出|写入|加入|插入|整理成).{0,24}(?:xlsx|excel|工作簿|表格)", task_text, re.IGNORECASE):
            inferred.add("xlsx")
        return {item for item in inferred if item}
