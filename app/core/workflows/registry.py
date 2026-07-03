# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Core workflow executor registry.

The web workflow API owns Flask/SSE transport and public workflow metadata. This
module owns the Python executor lookup so workflow execution does not depend on a
blueprint-level import table.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkflowExecutorSpec:
    workflow_id: str
    module: str
    class_name: str


WORKFLOW_EXECUTOR_SPECS: tuple[WorkflowExecutorSpec, ...] = (
    WorkflowExecutorSpec(
        "action_item_extractor",
        "app.core.workflows.action_item_extractor",
        "ActionItemExtractor",
    ),
    WorkflowExecutorSpec("comm_digest", "app.core.workflows.comm_digest", "CommDigest"),
    WorkflowExecutorSpec(
        "contract_clause_matrix",
        "app.core.workflows.contract_clause_matrix",
        "ContractClauseMatrix",
    ),
    WorkflowExecutorSpec(
        "contract_diff_markup",
        "app.core.workflows.contract_diff_markup",
        "ContractDiffMarkup",
    ),
    WorkflowExecutorSpec(
        "cross_format_extractor",
        "app.core.workflows.cross_format_extractor",
        "CrossFormatExtractor",
    ),
    WorkflowExecutorSpec(
        "data_anomaly_report",
        "app.core.workflows.data_anomaly_report",
        "DataAnomalyReport",
    ),
    WorkflowExecutorSpec(
        "data_fill_report",
        "app.core.workflows.data_fill_report",
        "DataFillReport",
    ),
    WorkflowExecutorSpec(
        "data_format_cleaner",
        "app.core.workflows.data_format_cleaner",
        "DataFormatCleaner",
    ),
    WorkflowExecutorSpec("doc_ai_review", "app.core.workflows.doc_ai_review", "DocAIReview"),
    WorkflowExecutorSpec(
        "doc_deep_compare",
        "app.core.workflows.doc_deep_compare",
        "DocDeepCompare",
    ),
    WorkflowExecutorSpec(
        "doc_smart_compare",
        "app.core.workflows.doc_smart_compare",
        "DocSmartCompare",
    ),
    WorkflowExecutorSpec(
        "email_thread_digest",
        "app.core.workflows.email_thread_digest",
        "EmailThreadDigest",
    ),
    WorkflowExecutorSpec(
        "multi_file_synthesis_report",
        "app.core.workflows.multi_file_synthesis_report",
        "MultiFileSynthesisReport",
    ),
    WorkflowExecutorSpec(
        "pptx_data_refresh",
        "app.core.workflows.pptx_data_refresh",
        "PptxDataRefresh",
    ),
    WorkflowExecutorSpec(
        "questionnaire_filler",
        "app.core.workflows.questionnaire_filler",
        "QuestionnaireFiller",
    ),
)

_EXECUTOR_SPEC_BY_ID = {
    spec.workflow_id: spec for spec in WORKFLOW_EXECUTOR_SPECS
}


def registered_workflow_ids() -> tuple[str, ...]:
    return tuple(_EXECUTOR_SPEC_BY_ID)


def get_workflow_executor(workflow_id: str) -> Any | None:
    """Return a new executor instance for workflow_id, or None when unknown."""
    spec = _EXECUTOR_SPEC_BY_ID.get(str(workflow_id or "").strip())
    if spec is None:
        return None

    try:
        module = importlib.import_module(spec.module)
        executor_cls = getattr(module, spec.class_name)
        return executor_cls()
    except Exception as exc:
        logger.error("[WorkflowRegistry] Failed to load executor %s: %s", workflow_id, exc)
        return None
