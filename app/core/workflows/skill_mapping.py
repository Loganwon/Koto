# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Mapping between built-in prompt skills and deterministic workflow executors.

Built-in skills describe capability and prompt behavior. Workflow executors own
file-producing deterministic behavior. This module records the relationship so
the two systems do not drift independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowSkillMapping:
    skill_id: str
    executor_ids: tuple[str, ...]
    relation: str
    note: str


WORKFLOW_SKILL_MAPPINGS: tuple[WorkflowSkillMapping, ...] = (
    WorkflowSkillMapping(
        skill_id="cross_format_extractor",
        executor_ids=("cross_format_extractor",),
        relation="direct",
        note="Skill describes cross-format extraction; executor owns parsing and filling.",
    ),
    WorkflowSkillMapping(
        skill_id="doc_smart_compare",
        executor_ids=("doc_smart_compare",),
        relation="direct",
        note="Skill describes document comparison intent; executor owns diff output.",
    ),
    WorkflowSkillMapping(
        skill_id="questionnaire_filler",
        executor_ids=("questionnaire_filler",),
        relation="direct",
        note="Skill describes RFP/questionnaire intent; executor owns workbook output.",
    ),
    WorkflowSkillMapping(
        skill_id="data_format_cleaner",
        executor_ids=("data_format_cleaner",),
        relation="direct",
        note="Skill describes spreadsheet cleaning; executor owns code execution and preview.",
    ),
    WorkflowSkillMapping(
        skill_id="multi_doc_synthesis",
        executor_ids=("multi_file_synthesis_report",),
        relation="affinity",
        note="Prompt affinity is broader than the deterministic multi-file report workflow.",
    ),
    WorkflowSkillMapping(
        skill_id="spreadsheet_analyst",
        executor_ids=("data_anomaly_report", "data_format_cleaner"),
        relation="candidate",
        note="Router must choose based on whether the user asks for anomaly detection or cleaning.",
    ),
    WorkflowSkillMapping(
        skill_id="excel_data_cleaner",
        executor_ids=("data_format_cleaner",),
        relation="affinity",
        note="Excel prompt skill can route to the deterministic data cleaning workflow when files and intent match.",
    ),
    WorkflowSkillMapping(
        skill_id="contract_reviewer",
        executor_ids=("contract_clause_matrix", "contract_diff_markup", "doc_ai_review"),
        relation="candidate",
        note="Legal review prompts guide language; workflow selection must remain explicit.",
    ),
    WorkflowSkillMapping(
        skill_id="legal_doc_review",
        executor_ids=("contract_clause_matrix", "contract_diff_markup", "doc_ai_review"),
        relation="candidate",
        note="Legal document review can map to clause extraction, diff markup, or AI review by task intent.",
    ),
)

_MAPPING_BY_SKILL_ID = {
    mapping.skill_id: mapping for mapping in WORKFLOW_SKILL_MAPPINGS
}
_SKILL_IDS_BY_EXECUTOR_ID: dict[str, tuple[str, ...]] = {}
for _mapping in WORKFLOW_SKILL_MAPPINGS:
    for _executor_id in _mapping.executor_ids:
        _SKILL_IDS_BY_EXECUTOR_ID = {
            **_SKILL_IDS_BY_EXECUTOR_ID,
            _executor_id: (
                *_SKILL_IDS_BY_EXECUTOR_ID.get(_executor_id, ()),
                _mapping.skill_id,
            ),
        }


def get_workflow_candidates_for_skill(skill_id: str) -> tuple[str, ...]:
    mapping = _MAPPING_BY_SKILL_ID.get(str(skill_id or "").strip())
    return mapping.executor_ids if mapping else ()


def get_workflow_skill_mapping(skill_id: str) -> WorkflowSkillMapping | None:
    return _MAPPING_BY_SKILL_ID.get(str(skill_id or "").strip())


def get_skill_ids_for_workflow(workflow_id: str) -> tuple[str, ...]:
    return _SKILL_IDS_BY_EXECUTOR_ID.get(str(workflow_id or "").strip(), ())


def workflow_has_skill_mapping(workflow_id: str) -> bool:
    return bool(get_skill_ids_for_workflow(workflow_id))


def list_workflow_skill_mappings() -> list[dict[str, Any]]:
    return [
        {
            "skill_id": mapping.skill_id,
            "executor_ids": list(mapping.executor_ids),
            "relation": mapping.relation,
            "note": mapping.note,
        }
        for mapping in WORKFLOW_SKILL_MAPPINGS
    ]
