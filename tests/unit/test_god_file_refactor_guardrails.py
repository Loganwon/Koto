"""Regression guards for the high-risk module extraction seams."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK_TOOLS = ROOT / "app" / "core" / "agent" / "task_tools.py"
TASK_TOOLS_COMMON = ROOT / "app" / "core" / "agent" / "task_tools_common.py"
FOUNDATION = ROOT / "app" / "core" / "agent" / "toolkits" / "foundation"
TASK_TOOL_REGISTRY = FOUNDATION / "registry.py"
TASK_TOOL_OPERATION_BINDINGS = (
    ROOT / "app" / "core" / "agent" / "task_tool_operation_bindings.py"
)
TASK_RUNTIME = ROOT / "app" / "core" / "agent" / "file_task_runtime.py"
EXECUTION_LOOP = ROOT / "app" / "core" / "agent" / "file_task_kernel_adapter.py"
FINALIZATION = ROOT / "app" / "core" / "agent" / "file_task_finalization.py"
CONTEXT_READ = ROOT / "app" / "core" / "agent" / "file_task_context_read.py"
PLANNING = ROOT / "app" / "core" / "agent" / "file_task_planning.py"
DOCX_PARSER = ROOT / "app" / "core" / "file" / "parsers" / "docx_parser.py"
DOCX_RICH_RENDERER = (
    ROOT / "app" / "core" / "file" / "parsers" / "docx_rich_renderer.py"
)
OFFICE_CREATE = FOUNDATION / "office_create.py"
XLSX_TOOLS = FOUNDATION / "xlsx.py"
XLSX_SHEET_SELECTION = FOUNDATION / "xlsx_sheet_selection.py"
XLSX_STRUCTURE = FOUNDATION / "xlsx_structure.py"
CONVERSION_TOOLS = FOUNDATION / "conversion.py"
DOCX_TEMPLATE_TOOLS = FOUNDATION / "docx_template.py"
DOCX_COMPARE_TOOLS = FOUNDATION / "docx_compare.py"
DOCX_REVIEW_CLEANUP_TOOLS = FOUNDATION / "docx_review_cleanup.py"
PDF_WINDOW_TOOLS = FOUNDATION / "pdf_window.py"
PLAN_PRESENTATION = ROOT / "app" / "core" / "agent" / "file_task_plan_presentation.py"
DOCX_REVIEW = ROOT / "app" / "core" / "file" / "parsers" / "docx_parser_review.py"
DOCX_FALLBACK = ROOT / "app" / "core" / "file" / "parsers" / "docx_parser_fallback.py"
DOCX_POSTPROCESS = (
    ROOT / "app" / "core" / "file" / "parsers" / "docx_parser_postprocess.py"
)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_god_file_line_budgets_only_ratchet_down() -> None:
    """Keep future work in focused modules rather than restoring monoliths."""
    # Black 26.5.1 wraps the public import index more aggressively; preserve
    # a tight ceiling while measuring the canonical formatted representation.
    assert len(_source(TASK_TOOLS).splitlines()) <= 320
    assert len(_source(TASK_RUNTIME).splitlines()) <= 500
    assert len(_source(DOCX_PARSER).splitlines()) <= 50


def test_file_runtime_and_tool_parts_have_single_shared_owners() -> None:
    agent_dir = ROOT / "app" / "core" / "agent"
    tool_parts = sorted(agent_dir.glob("task_tools_part_*.py"))
    assert (
        len(tool_parts) == 0
    ), f"task_tools_part_* files should be removed: {[p.name for p in tool_parts]}"

    assert len(_source(TASK_RUNTIME).splitlines()) <= 500
    assert len(_source(TASK_TOOLS).splitlines()) <= 320
    assert len(_source(TASK_TOOLS_COMMON).splitlines()) <= 450
    assert all(
        "_DOCX_REVIEW_CLEAR_SCOPE_ALIASES =" not in _source(path)
        for path in tool_parts[1:]
    )


def test_extracted_boundaries_remain_explicit_and_acyclic() -> None:
    task_tools = _source(TASK_TOOLS) + "\n" + _source(TASK_TOOLS_COMMON)
    task_tool_registry = _source(TASK_TOOL_REGISTRY)
    operation_bindings = _source(TASK_TOOL_OPERATION_BINDINGS)
    task_runtime = "\n".join(
        [_source(TASK_RUNTIME)]
        + [
            _source(path)
            for path in sorted((TASK_RUNTIME.parent / "runtime").glob("*_phase.py"))
        ]
    )
    execution_loop = _source(EXECUTION_LOOP)
    finalization = _source(FINALIZATION)
    context_read = _source(CONTEXT_READ)
    planning = _source(PLANNING)
    docx_parser = _source(DOCX_PARSER)
    docx_rich_renderer = _source(DOCX_RICH_RENDERER)
    office_create = _source(OFFICE_CREATE)
    xlsx_tools = _source(XLSX_TOOLS)
    xlsx_sheet_selection = _source(XLSX_SHEET_SELECTION)
    xlsx_structure = _source(XLSX_STRUCTURE)
    conversion_tools = _source(CONVERSION_TOOLS)
    docx_template_tools = _source(DOCX_TEMPLATE_TOOLS)
    docx_compare_tools = _source(DOCX_COMPARE_TOOLS)
    docx_review_cleanup_tools = _source(DOCX_REVIEW_CLEANUP_TOOLS)
    pdf_window_tools = _source(PDF_WINDOW_TOOLS)
    plan_presentation = _source(PLAN_PRESENTATION)
    docx_review = _source(DOCX_REVIEW)
    docx_fallback = _source(DOCX_FALLBACK)
    docx_postprocess = _source(DOCX_POSTPROCESS)
    assert "from app.core.agent.toolkits.foundation.office_create import" in task_tools
    assert "from app.core.agent.toolkits.foundation.conversion import (" in task_tools
    assert (
        "from app.core.agent.toolkits.foundation.docx_template import (" in task_tools
    )
    assert "from app.core.agent.toolkits.foundation.docx_compare import (" in task_tools
    assert (
        "from app.core.agent.toolkits.foundation.docx_review_cleanup import ("
        in task_tools
    )
    assert "from app.core.agent.toolkits.foundation.pdf_window import (" in task_tools
    assert (
        "from app.core.agent.toolkits.foundation.xlsx_sheet_selection import ("
        in task_tools
    )
    assert (
        "from app.core.agent.toolkits.foundation.xlsx_structure import (" in task_tools
    )
    assert (
        "from app.core.agent.toolkits.foundation.registry import build_task_tool_definitions"
        in task_tools
    )
    assert (
        "from app.core.agent.task_tool_operation_bindings import build_task_tool_operations"
        in task_tools
    )
    assert "from app.core.agent.file_task_plan_presentation import" in task_runtime
    assert (
        "from app.core.agent.file_task_kernel_adapter import FileTaskKernelAdapter"
        in task_runtime
    )
    assert (
        "from app.core.agent.file_task_finalization import FileTaskFinalizationPhase"
        in task_runtime
    )
    assert (
        "from app.core.agent.file_task_context_read import FileTaskContextReadPhase"
        in task_runtime
    )
    assert (
        "from app.core.agent.file_task_planning import FileTaskPlanningPhase"
        in task_runtime
    )
    assert "from app.core.file.parsers.docx_parser_review import" in docx_parser
    assert (
        "from app.core.file.parsers.docx_rich_renderer import _docx_to_rich_html"
        in docx_parser
    )
    assert "from app.core.file.parsers.docx_parser_fallback import" in docx_parser
    assert "from app.core.file.parsers.docx_parser_postprocess import" in docx_parser
    assert "from app.core.agent import task_tools" not in office_create
    assert "from .task_tools import" not in xlsx_tools
    assert "from app.core.agent.task_tools import" not in conversion_tools
    assert "from app.core.agent.task_tools import" not in docx_template_tools
    assert "from app.core.agent.task_tools import" not in docx_compare_tools
    assert "def _task_tools_helper(" in xlsx_tools
    assert (
        "from app.core.agent.toolkits.foundation.xlsx_sheet_selection import ("
        in xlsx_tools
    )
    assert "def select_workbook_sheet(" in xlsx_sheet_selection
    assert "def sample_sheet_rows(" in xlsx_structure
    assert "def remove_docx_comment_markup(" in docx_review_cleanup_tools
    assert "def accept_docx_revision_markup(" in docx_review_cleanup_tools
    assert "def remove_comments_relationships_xml(" in docx_review_cleanup_tools
    assert "def read_pdf_excerpt(" in pdf_window_tools
    assert "def read_pdf_letter_window(" in pdf_window_tools
    assert "file_task_runtime import" not in task_tool_registry
    assert "from app.core.agent.task_tools import" not in task_tool_registry
    assert "from app.core.agent.task_tools import (" in operation_bindings
    assert "file_task_runtime import" not in plan_presentation
    assert "file_task_runtime import" not in execution_loop
    assert "file_task_runtime import" not in finalization
    assert "file_task_runtime import" not in context_read
    assert "file_task_runtime import" not in planning
    assert "docx_parser import" not in docx_review
    assert "docx_parser import" not in docx_fallback
    assert "docx_parser import" not in docx_postprocess
    assert "from app.core.file.parsers.docx_parser import" not in docx_rich_renderer


def test_task_tools_drops_unused_runtime_imports() -> None:
    task_tools = _source(TASK_TOOLS) + "\n" + _source(TASK_TOOLS_COMMON)

    assert "import subprocess" not in task_tools
    assert "FileTaskToolStreamChunk" not in task_tools
    assert "FileTaskToolStreamResult" in task_tools


def test_task_tools_registry_receives_only_explicit_operation_bindings() -> None:
    task_tools = _source(TASK_TOOLS)
    operation_bindings = _source(TASK_TOOL_OPERATION_BINDINGS)

    assert "sys.modules[__name__]" not in task_tools
    assert (
        "build_task_tool_definitions(self, build_task_tool_operations())" in task_tools
    )
    assert "def build_task_tool_operations()" in operation_bindings


def test_task_tool_operation_bindings_match_registry_references() -> None:
    from app.core.agent.task_tool_operation_bindings import build_task_tool_operations

    registry_tree = ast.parse(_source(TASK_TOOL_REGISTRY))
    registry_operation_names = {
        node.attr
        for node in ast.walk(registry_tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "operations"
    }

    assert registry_operation_names == set(vars(build_task_tool_operations()))


def test_xlsx_tool_module_imports_without_task_tools_circularity() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from app.core.agent.toolkits.foundation import xlsx; "
                "payload = json.loads(xlsx.read_sheet_data('__missing__.xlsx')); "
                "assert payload['error'].startswith('File not found'); "
                "print('xlsx import and helper resolution ok')"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_conversion_tool_module_imports_without_task_tools_circularity() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app.core.agent.toolkits.foundation import conversion; "
                "assert conversion.normalize_conversion_extension('pdf') == '.pdf'; "
                "print('conversion import and helper resolution ok')"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr or result.stdout
