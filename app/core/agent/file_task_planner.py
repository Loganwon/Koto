from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from app.core.agent.file_task_contract import FileTaskRequest

PlannerResponse = Dict[str, Any]


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


class FileTaskPlannerRegistry:
    def __init__(self, adapters: Optional[List[FileTaskPlannerAdapter]] = None):
        self._adapters: Dict[str, FileTaskPlannerAdapter] = {}
        for adapter in [] if adapters is None else adapters:
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
    return []
