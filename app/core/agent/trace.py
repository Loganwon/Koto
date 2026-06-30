# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Unified request tracing — single trace_id flowing end-to-end.

Every ChatPipeline.run() call generates a RequestTrace that follows the
request through routing → agent → validation → persistence.  Modules that
need to log or store trace data receive the trace object and append data
to it.  This replaces ad-hoc per-component IDs and enables root-cause
analysis across the entire pipeline.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class NormalizedRequest:
    message: str
    task_type: str = "CHAT"
    task_source: str = "none"
    model_source: str = "auto"
    user_chose_local: bool = False
    context_files: List[Dict[str, Any]] = field(default_factory=list)
    history: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class TraceValidation:
    action: str = "PASS"
    is_blocked: bool = False
    needs_retry: bool = False
    reasons: List[str] = field(default_factory=list)
    text: str = ""
    latency_ms: int = 0


@dataclass
class RequestTrace:
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: float = field(default_factory=time.time)

    session_id: str = ""
    user_input: str = ""
    task_type: str = ""
    model_id: str = ""

    routing_source: str = ""
    routing_latency_ms: int = 0

    agent_steps: List[Dict[str, Any]] = field(default_factory=list)
    agent_latency_ms: int = 0

    validation: Optional[TraceValidation] = None
    used_local_fallback: bool = False
    local_fallback_model: Optional[str] = None
    local_use_reason: Optional[str] = None

    pipeline_latency_ms: int = 0
    error: Optional[str] = None

    def finish(self):
        self.pipeline_latency_ms = int((time.time() - self.started_at) * 1000)

    def to_log_summary(self) -> str:
        return (
            f"[trace:{self.trace_id}] session={self.session_id} "
            f"task={self.task_type} model={self.model_id} "
            f"route={self.routing_source}({self.routing_latency_ms}ms) "
            f"agent={self.agent_latency_ms}ms "
            f"steps={len(self.agent_steps)} "
            f"valid={self.validation.action if self.validation else 'N/A'} "
            f"local={self.used_local_fallback}({self.local_use_reason}) "
            f"total={self.pipeline_latency_ms}ms"
            + (f" err={self.error}" if self.error else "")
        )
