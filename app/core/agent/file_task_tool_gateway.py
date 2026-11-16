from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol

from app.core.agent.file_mutation_transaction import FileMutationTransaction
from app.core.agent.file_task_contract import (
    FileTaskToolStreamChunk,
    FileTaskToolStreamResult,
)
from app.core.agent.file_task_document_metrics import (
    assert_transaction_structure_preserved,
    structure_before,
    with_verified_structure,
)
from app.core.agent.kernel import ToolCall, ToolCatalog, ToolExecutionPolicy
from app.core.agent.kernel import ToolExecutor as KernelToolExecutor
from app.core.agent.kernel import ToolSpec
from app.core.agent.toolkits.foundation import (
    FOUNDATION_TOOL_SOURCE,
    FOUNDATION_TOOLKIT_VERSION,
)
from app.core.agent.toolkits.foundation.catalog import (
    file_task_tool_specs,
    is_file_task_tool,
    write_target_for_tool,
)
from app.core.file_assistant.docx_preservation import DocxStructureLossError

LegacyToolExecutor = Callable[[str, Dict[str, Any]], Any]
# Compatibility type alias used by FileTaskRuntime constructor annotations.
ToolExecutor = LegacyToolExecutor


@dataclass(frozen=True)
class FileTaskToolContext:
    """Per-run context passed to file-task tool providers."""

    task_files: List[Dict[str, Any]] = field(default_factory=list)
    workspace_root: str = ""
    request_context: Dict[str, Any] = field(default_factory=dict)


class FileTaskToolProvider(Protocol):
    """Stable provider interface for Koto file-task tools."""

    toolkit_source: str
    toolkit_version: str

    def definitions(self) -> List[Dict[str, Any]]: ...

    def allowed_names(self) -> set[str]: ...

    def execute(self, tool_name: str, tool_args: Dict[str, Any]) -> Any: ...


def _minimal_definition(tool_name: str) -> Dict[str, Any]:
    spec = next(
        (item for item in file_task_tool_specs() if item.name == tool_name), None
    )
    return {
        "name": tool_name,
        "description": f"Koto file-task tool ({spec.family if spec else 'custom'}).",
        "parameters": {"type": "object", "properties": {}},
        "read_only": bool(spec.read_only) if spec else False,
        "file_types": list(spec.file_types) if spec else [],
    }


class CallableFileTaskToolProvider:
    """Adapter used by tests and narrow integrations that only supply execute()."""

    toolkit_source = FOUNDATION_TOOL_SOURCE
    toolkit_version = FOUNDATION_TOOLKIT_VERSION

    def __init__(
        self,
        executor: ToolExecutor,
        *,
        definitions: Optional[List[Dict[str, Any]]] = None,
    ):
        self._executor = executor
        self._definitions = definitions or [
            _minimal_definition(spec.name) for spec in file_task_tool_specs()
        ]

    def definitions(self) -> List[Dict[str, Any]]:
        return [
            dict(definition)
            for definition in self._definitions
            if is_file_task_tool(str(definition.get("name") or ""))
        ]

    def allowed_names(self) -> set[str]:
        return {str(definition.get("name") or "") for definition in self.definitions()}

    def execute(self, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        return self._executor(tool_name, dict(tool_args or {}))


class RegistryBackedFileTaskToolProvider:
    """Current built-in adapter around Koto's existing TaskToolsPlugin registry."""

    toolkit_source = FOUNDATION_TOOL_SOURCE
    toolkit_version = FOUNDATION_TOOLKIT_VERSION

    def __init__(self, *, context: Optional[FileTaskToolContext] = None):
        from app.core.agent.task_tools import TaskToolsPlugin
        from app.core.agent.tool_registry import ToolRegistry

        self._context = context or FileTaskToolContext()
        self._registry = ToolRegistry()
        self._registry.register_plugin(
            TaskToolsPlugin(
                task_files=self._context.task_files or [],
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

    def normalize_args(
        self, tool_name: str, tool_args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply the legacy registry's documented scalar/JSON coercions.

        This adapter keeps old Office tools compatible while the Kernel still
        validates the normalized arguments against their published schema.
        New providers should publish exact schemas and avoid coercion.
        """

        from app.core.agent.tool_registry import normalize_tool_args_for_spec

        spec = self._registry.catalog.require(tool_name)
        return normalize_tool_args_for_spec(spec, dict(tool_args or {}))


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
        tool_executor: Optional[LegacyToolExecutor] = None,
    ):
        self._context = context or FileTaskToolContext()
        self._task_file_types = {
            str(item.get("type") or item.get("file_type") or "")
            .strip()
            .lower()
            .lstrip(".")
            for item in (self._context.task_files or [])
            if isinstance(item, dict)
        }
        self._task_file_types.discard("")
        self._task_file_types.update(self._request_context_file_types())
        provider_list = list(providers or [])
        if tool_executor is not None:
            provider_list.append(CallableFileTaskToolProvider(tool_executor))
        if not provider_list:
            provider_list.append(
                RegistryBackedFileTaskToolProvider(context=self._context)
            )

        self._providers = provider_list
        self._provider_by_tool: Dict[str, FileTaskToolProvider] = {}
        self._definitions = self._merge_definitions(provider_list)
        self._catalog = self._build_catalog()
        self._kernel_executor = KernelToolExecutor(
            self._catalog,
            ToolExecutionPolicy(default_timeout_seconds=600.0),
        )

    def definitions(self) -> List[Dict[str, Any]]:
        return [dict(definition) for definition in self._definitions]

    def allowed_names(self) -> set[str]:
        return set(self._provider_by_tool)

    @property
    def catalog(self) -> ToolCatalog:
        """Canonical Kernel catalog for this request's file capabilities."""

        return self._catalog

    def execute(self, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        name = str(tool_name or "").strip()
        if not is_file_task_tool(name):
            raise ValueError(f"Tool '{name}' is not allowlisted for Koto file tasks")
        provider = self._provider_by_tool.get(name)
        if provider is None:
            raise ValueError(f"Tool '{name}' has no registered Koto file-task provider")
        normalized_args = dict(tool_args or {})
        normalizer = getattr(provider, "normalize_args", None)
        if callable(normalizer):
            normalized_args = normalizer(name, normalized_args)
        spec = self._catalog.get(name)
        transaction: FileMutationTransaction | None = None
        before_structure = None
        if spec is not None and spec.read_only is False:
            target_path = write_target_for_tool(name, normalized_args)
            if not target_path and name == "run_python_code":
                candidate = str(self._context.request_context.get("target_path") or "")
                if Path(candidate).suffix.lower() == ".docx":
                    target_path = candidate
            if target_path:
                run_id = str(self._context.request_context.get("run_id") or "")
                transaction = FileMutationTransaction(
                    target_path,
                    run_id=run_id,
                ).begin()
                before_structure = structure_before(transaction)
        try:
            result = self._kernel_executor.invoke(
                ToolCall(name=name, arguments=normalized_args)
            )
        except BaseException:
            if transaction is not None:
                transaction.rollback()
            raise
        if result.ok:
            if (
                isinstance(result.value, FileTaskToolStreamResult)
                and transaction is not None
            ):
                return self._transactional_stream(
                    result.value, transaction, before_structure
                )
            value = result.value
            if transaction is not None:
                if self._result_reports_error(value):
                    transaction.rollback()
                else:
                    try:
                        assert_transaction_structure_preserved(transaction)
                        value = with_verified_structure(
                            value, transaction, before_structure
                        )
                        transaction.commit()
                    except DocxStructureLossError as exc:
                        transaction.rollback()
                        raise RuntimeError(
                            "DOCX 写入会丢失原有结构（"
                            + ", ".join(exc.lost_features)
                            + "），原文件已回滚，本次写入未提交。"
                        ) from exc
                    except BaseException:
                        transaction.rollback()
                        raise
            return value
        if transaction is not None:
            transaction.rollback()
        raise RuntimeError(result.error_message)

    def _transactional_stream(self, value, transaction, before_structure=None):
        """A generator has not written anything until it has been consumed."""

        def chunks():
            final_result = None
            completed = False
            try:
                for chunk in value.chunks:
                    if getattr(chunk, "kind", "") == "result":
                        final_result = with_verified_structure(
                            chunk.payload, transaction, before_structure
                        )
                        chunk = FileTaskToolStreamChunk(
                            kind=chunk.kind,
                            payload=final_result,
                            event_type=chunk.event_type,
                        )
                        completed = True
                    yield chunk
                if not completed:
                    transaction.rollback()
                    raise RuntimeError(
                        "Tool stream ended without a final execution result"
                    )
                if self._result_reports_error(final_result):
                    transaction.rollback()
                else:
                    assert_transaction_structure_preserved(transaction)
                    transaction.commit()
            except DocxStructureLossError as exc:
                transaction.rollback()
                raise RuntimeError(
                    "DOCX 写入会丢失原有结构（"
                    + ", ".join(exc.lost_features)
                    + "），原文件已回滚，本次写入未提交。"
                ) from exc
            except BaseException:
                transaction.rollback()
                raise

        return FileTaskToolStreamResult(chunks=chunks())

    @staticmethod
    def _result_reports_error(value: Any) -> bool:
        payload = value
        if isinstance(value, str):
            try:
                payload = json.loads(value)
            except (TypeError, ValueError):
                return False
        return bool(isinstance(payload, dict) and payload.get("error"))

    def _build_catalog(self) -> ToolCatalog:
        catalog = ToolCatalog()
        specs: List[ToolSpec] = []
        for definition in self._definitions:
            name = str(definition.get("name") or "").strip()
            provider = self._provider_by_tool.get(name)
            if not name or provider is None:
                continue
            provider_source = str(
                definition.get("source")
                or getattr(provider, "toolkit_source", "")
                or f"provider:{provider.__class__.__module__}.{provider.__class__.__name__}"
            ).strip()
            provider_version = str(
                definition.get("version")
                or getattr(provider, "toolkit_version", "")
                or "1.0.0"
            ).strip()

            def _handler(
                _provider: FileTaskToolProvider = provider,
                _name: str = name,
                **kwargs: Any,
            ) -> Any:
                return _provider.execute(_name, dict(kwargs))

            specs.append(
                ToolSpec(
                    name=name,
                    description=str(
                        definition.get("description") or f"Koto file-task tool: {name}"
                    ),
                    input_schema=dict(
                        definition.get("parameters")
                        or {"type": "object", "properties": {}}
                    ),
                    handler=_handler,
                    source=provider_source,
                    version=provider_version,
                    capabilities=tuple(
                        str(item)
                        for item in (definition.get("file_types") or [])
                        if str(item)
                    ),
                    read_only=definition.get("read_only"),
                    timeout_seconds=float(definition.get("timeout_seconds") or 600.0),
                )
            )
        catalog.register_many(specs)
        return catalog

    def _merge_definitions(
        self, providers: List[FileTaskToolProvider]
    ) -> List[Dict[str, Any]]:
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
                if (
                    is_file_task_tool(name)
                    and self._tool_matches_context(name)
                    and name not in definitions_by_name
                ):
                    normalized = dict(definition)
                    file_spec = next(
                        (item for item in file_task_tool_specs() if item.name == name),
                        None,
                    )
                    if file_spec is not None:
                        # The format capability catalog owns mutation semantics;
                        # legacy plugin schemas often omit these fields.
                        normalized["read_only"] = bool(file_spec.read_only)
                        normalized["file_types"] = list(file_spec.file_types)
                        normalized["produces_file_change"] = bool(
                            file_spec.produces_file_change
                        )
                    definitions_by_name[name] = normalized

        for name in self._provider_by_tool:
            definitions_by_name.setdefault(name, _minimal_definition(name))

        spec_order = [spec.name for spec in file_task_tool_specs()]
        return [
            definitions_by_name[name]
            for name in spec_order
            if name in definitions_by_name
        ]

    def _tool_matches_context(self, tool_name: str) -> bool:
        if not self._task_file_types:
            return True

        spec = next(
            (item for item in file_task_tool_specs() if item.name == tool_name), None
        )
        if spec is None or not spec.file_types:
            return True
        return bool(self._task_file_types.intersection(spec.file_types))

    def _request_context_file_types(self) -> set[str]:
        request_context = (
            self._context.request_context
            if isinstance(self._context.request_context, dict)
            else {}
        )
        inferred: set[str] = set()
        target_path = str(request_context.get("target_path") or "").strip()
        target_suffix = Path(target_path).suffix.lstrip(".").lower()
        if target_suffix:
            inferred.add(target_suffix)
        options = (
            request_context.get("options")
            if isinstance(request_context.get("options"), dict)
            else {}
        )
        option_type = (
            str(
                options.get("inferred_target_file_type")
                or options.get("target_file_type")
                or ""
            )
            .strip()
            .lower()
            .lstrip(".")
        )
        if option_type:
            inferred.add(option_type)
        task_text = str(request_context.get("task") or "").strip().lower()
        if re.search(
            r"(?:创建|新建|生成|输出|写入|加入|插入|整理成|create|generate|output|record|write).{0,24}(?:docx|word|文档)",
            task_text,
            re.IGNORECASE,
        ):
            inferred.add("docx")
        if re.search(
            r"(?:创建|新建|生成|输出|写入|加入|插入|整理成).{0,24}(?:pptx|ppt|幻灯片|演示文稿|slides?)",
            task_text,
            re.IGNORECASE,
        ):
            inferred.add("pptx")
        if re.search(
            r"(?:创建|新建|生成|输出|写入|加入|插入|整理成).{0,24}(?:xlsx|excel|工作簿|表格)",
            task_text,
            re.IGNORECASE,
        ):
            inferred.add("xlsx")
        return {item for item in inferred if item}
