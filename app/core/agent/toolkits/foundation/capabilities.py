"""Machine-readable capability inventory for the Koto foundation toolkit."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.core.agent.toolkits.foundation.catalog import file_task_tool_specs


class CapabilityMaturity(str, Enum):
    READY = "ready"
    CONDITIONAL = "conditional"


@dataclass(frozen=True)
class FoundationCapability:
    capability_id: str
    maturity: CapabilityMaturity
    description: str
    tool_names: tuple[str, ...]
    requirements: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "maturity": self.maturity.value,
            "description": self.description,
            "tool_names": list(self.tool_names),
            "requirements": list(self.requirements),
        }


_CAPABILITIES: tuple[FoundationCapability, ...] = (
    FoundationCapability(
        "office.read",
        CapabilityMaturity.READY,
        "Read mainstream Office, PDF, and text formats into bounded structured data.",
        (
            "parse_file_to_text",
            "read_docx_content",
            "read_sheet_data",
            "inspect_workbook_structure",
            "audit_financial_workbook",
            "read_file_range",
        ),
    ),
    FoundationCapability(
        "office.write",
        CapabilityMaturity.READY,
        "Create and mutate DOCX, XLSX, PPTX, and text artifacts with change records.",
        (
            "write_docx_content",
            "insert_docx_paragraph",
            "fill_docx_template",
            "clear_docx_review_marks",
            "insert_image_into_docx",
            "insert_excel_as_docx_table",
            "write_sheet_data",
            "design_pptx_theme_layout",
            "write_pptx_slides",
            "add_pptx_slides",
            "replace_file_selection",
            "create_file",
        ),
    ),
    FoundationCapability(
        "office.review",
        CapabilityMaturity.READY,
        "Compare supported files and write real Word comments.",
        (
            "compare_files",
            "compare_docx_and_annotate",
            "plan_docx_compare_annotations",
            "write_docx_comments",
        ),
    ),
    FoundationCapability(
        "file.convert",
        CapabilityMaturity.CONDITIONAL,
        "Convert supported file formats when a compatible local converter is installed.",
        ("convert_docx_to_pdf", "convert_file", "list_conversions"),
        ("A compatible converter such as Microsoft Office or LibreOffice",),
    ),
    FoundationCapability(
        "workspace.files",
        CapabilityMaturity.READY,
        "List, copy, create, and open files within the request workspace boundary.",
        ("list_workspace_files", "copy_file", "create_file", "open_file_in_editor"),
    ),
    FoundationCapability(
        "sandbox.execute",
        CapabilityMaturity.CONDITIONAL,
        "Run bounded Python transformations and collect declared output artifacts.",
        ("run_python_code",),
        ("The configured Koto Python sandbox runtime",),
    ),
    FoundationCapability(
        "task.verify",
        CapabilityMaturity.READY,
        "Verify that requested file changes exist before the agent reports completion.",
        ("verify_task_completion",),
    ),
)

FOUNDATION_CAPABILITY_IDS = tuple(item.capability_id for item in _CAPABILITIES)


def foundation_capabilities() -> tuple[FoundationCapability, ...]:
    return _CAPABILITIES


def foundation_capability_report() -> dict[str, Any]:
    """Return a stable payload suitable for diagnostics, UI, and profile planning."""

    validate_foundation_capabilities()
    return {
        "capabilities": [item.to_payload() for item in _CAPABILITIES],
        "tool_count": len(file_task_tool_specs()),
    }


def validate_foundation_capabilities() -> None:
    """Fail when the capability inventory drifts from the canonical tool catalog."""

    catalog_names = {spec.name for spec in file_task_tool_specs()}
    declared_names = {
        tool_name for capability in _CAPABILITIES for tool_name in capability.tool_names
    }
    unknown = sorted(declared_names - catalog_names)
    missing = sorted(catalog_names - declared_names)
    if unknown or missing:
        details = []
        if unknown:
            details.append(f"unknown tools: {', '.join(unknown)}")
        if missing:
            details.append(f"unclassified tools: {', '.join(missing)}")
        raise RuntimeError(
            "foundation capability inventory mismatch: " + "; ".join(details)
        )


__all__ = [
    "CapabilityMaturity",
    "FOUNDATION_CAPABILITY_IDS",
    "FoundationCapability",
    "foundation_capabilities",
    "foundation_capability_report",
    "validate_foundation_capabilities",
]
