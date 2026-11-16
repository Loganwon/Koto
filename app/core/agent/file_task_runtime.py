"""Composition root for the single Koto file-task runtime."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from app.core.agent.file_task_cancel import is_cancel_requested as _is_cancel_requested
from app.core.agent.file_task_cancel import request_cancel as _request_cancel
from app.core.agent.file_task_generated_image_validation import (
    pending_generated_docx_images,
)
from app.core.agent.file_task_intent_planner import FileTaskIntentPlanner
from app.core.agent.file_task_model import FileTaskModelClient
from app.core.agent.file_task_read_evidence import (
    explicit_file_reference_was_read as _explicit_file_reference_was_read,
)
from app.core.agent.file_task_read_evidence import (
    file_references_in_task_text as _file_references_in_task_text,
)
from app.core.agent.file_task_read_evidence import (
    readonly_task_requires_file_context as _readonly_task_requires_file_context,
)
from app.core.agent.file_task_read_evidence import (
    unsatisfied_explicit_read_file_references as _unsatisfied_explicit_read_file_references,
)
from app.core.agent.file_task_runtime_patterns import _MAX_MODEL_ROUNDS
from app.core.agent.file_task_tool_gateway import (
    FileTaskToolGateway,
    FileTaskToolProvider,
    ToolExecutor,
)
from app.core.agent.task_supervisor import TaskSupervisor

from .runtime.execute_phase import _FileTaskRuntimePart3
from .runtime.plan_phase import _FileTaskRuntimePart2
from .runtime.read_phase import _FileTaskRuntimePart1
from .runtime.verify_phase import _FileTaskRuntimePart4

ModelCaller = Callable[..., Dict[str, Any]]


def request_cancel(run_id: str) -> bool:
    return _request_cancel(run_id)


def is_cancel_requested(run_id: str) -> bool:
    return _is_cancel_requested(run_id)


class FileTaskRuntime(
    _FileTaskRuntimePart1,
    _FileTaskRuntimePart2,
    _FileTaskRuntimePart3,
    _FileTaskRuntimePart4,
):
    """Kernel-backed runtime for the one supported file-task execution path."""

    def __init__(
        self,
        *,
        tool_executor: Optional[ToolExecutor] = None,
        tool_provider: Optional[FileTaskToolProvider] = None,
        tool_gateway: Optional[FileTaskToolGateway] = None,
        model_client: Optional[FileTaskModelClient | ModelCaller] = None,
        intent_planner: Optional[FileTaskIntentPlanner] = None,
        workspace_root: str = "",
        task_supervisor: Optional[TaskSupervisor] = None,
        yield_thinking: Any = None,
        max_rounds: int = _MAX_MODEL_ROUNDS,
    ):
        self._tool_executor = tool_executor
        self._tool_provider = tool_provider
        self._tool_gateway = tool_gateway
        self._model_client = model_client or FileTaskModelClient()
        self._intent_planner = intent_planner or FileTaskIntentPlanner()
        self._workspace_root = workspace_root
        self._max_rounds = max(1, int(max_rounds or _MAX_MODEL_ROUNDS))
        self._task_supervisor = task_supervisor
        self._yield_thinking = yield_thinking

    _pending_generated_docx_images = pending_generated_docx_images
    _readonly_task_requires_file_context = staticmethod(
        _readonly_task_requires_file_context
    )
    _unsatisfied_explicit_read_file_references = staticmethod(
        _unsatisfied_explicit_read_file_references
    )
    _file_references_in_task_text = staticmethod(_file_references_in_task_text)
    _explicit_file_reference_was_read = staticmethod(_explicit_file_reference_was_read)


__all__ = ["FileTaskRuntime", "is_cancel_requested", "request_cancel"]
