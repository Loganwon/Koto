"""Regression guards for the high-risk module extraction seams."""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TASK_TOOLS = ROOT / "app" / "core" / "agent" / "task_tools.py"
TASK_TOOL_REGISTRY = ROOT / "app" / "core" / "agent" / "task_tools_registry.py"
TASK_TOOL_OPERATION_BINDINGS = ROOT / "app" / "core" / "agent" / "task_tool_operation_bindings.py"
TASK_RUNTIME = ROOT / "app" / "core" / "agent" / "file_task_runtime.py"
EXECUTION_LOOP = ROOT / "app" / "core" / "agent" / "file_task_execution_loop.py"
FINALIZATION = ROOT / "app" / "core" / "agent" / "file_task_finalization.py"
CONTEXT_READ = ROOT / "app" / "core" / "agent" / "file_task_context_read.py"
PLANNING = ROOT / "app" / "core" / "agent" / "file_task_planning.py"
DOCX_PARSER = ROOT / "app" / "core" / "file" / "parsers" / "docx_parser.py"
DOCX_RICH_RENDERER = ROOT / "app" / "core" / "file" / "parsers" / "docx_rich_renderer.py"
OFFICE_CREATE = ROOT / "app" / "core" / "agent" / "task_tools_office_create.py"
XLSX_TOOLS = ROOT / "app" / "core" / "agent" / "task_tools_xlsx.py"
CONVERSION_TOOLS = ROOT / "app" / "core" / "agent" / "task_tools_conversion.py"
DOCX_TEMPLATE_TOOLS = ROOT / "app" / "core" / "agent" / "task_tools_docx_template.py"
PLAN_PRESENTATION = ROOT / "app" / "core" / "agent" / "file_task_plan_presentation.py"
DOCX_REVIEW = ROOT / "app" / "core" / "file" / "parsers" / "docx_parser_review.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_god_file_line_budgets_only_ratchet_down() -> None:
    """Keep future work in focused modules rather than restoring monoliths."""
    assert len(_source(TASK_TOOLS).splitlines()) <= 5395
    assert len(_source(TASK_RUNTIME).splitlines()) <= 3421
    assert len(_source(DOCX_PARSER).splitlines()) <= 762


def test_extracted_boundaries_remain_explicit_and_acyclic() -> None:
    task_tools = _source(TASK_TOOLS)
    task_tool_registry = _source(TASK_TOOL_REGISTRY)
    operation_bindings = _source(TASK_TOOL_OPERATION_BINDINGS)
    task_runtime = _source(TASK_RUNTIME)
    execution_loop = _source(EXECUTION_LOOP)
    finalization = _source(FINALIZATION)
    context_read = _source(CONTEXT_READ)
    planning = _source(PLANNING)
    docx_parser = _source(DOCX_PARSER)
    docx_rich_renderer = _source(DOCX_RICH_RENDERER)
    office_create = _source(OFFICE_CREATE)
    xlsx_tools = _source(XLSX_TOOLS)
    conversion_tools = _source(CONVERSION_TOOLS)
    docx_template_tools = _source(DOCX_TEMPLATE_TOOLS)
    plan_presentation = _source(PLAN_PRESENTATION)
    docx_review = _source(DOCX_REVIEW)

    assert "from app.core.agent.task_tools_office_create import" in task_tools
    assert "from app.core.agent.task_tools_conversion import (" in task_tools
    assert "from app.core.agent.task_tools_docx_template import (" in task_tools
    assert "from app.core.agent.task_tools_registry import build_task_tool_definitions" in task_tools
    assert "from app.core.agent.task_tool_operation_bindings import build_task_tool_operations" in task_tools
    assert "from app.core.agent.file_task_plan_presentation import" in task_runtime
    assert "from app.core.agent.file_task_execution_loop import FileTaskExecutionLoop" in task_runtime
    assert "from app.core.agent.file_task_finalization import FileTaskFinalizationPhase" in task_runtime
    assert "from app.core.agent.file_task_context_read import FileTaskContextReadPhase" in task_runtime
    assert "from app.core.agent.file_task_planning import FileTaskPlanningPhase" in task_runtime
    assert "from app.core.file.parsers.docx_parser_review import" in docx_parser
    assert "from app.core.file.parsers.docx_rich_renderer import _docx_to_rich_html" in docx_parser
    assert "from app.core.agent import task_tools" not in office_create
    assert "from .task_tools import" not in xlsx_tools
    assert "from app.core.agent.task_tools import" not in conversion_tools
    assert "from app.core.agent.task_tools import" not in docx_template_tools
    assert "def _task_tools_helper(" in xlsx_tools
    assert "file_task_runtime import" not in task_tool_registry
    assert "from app.core.agent.task_tools import" not in task_tool_registry
    assert "from app.core.agent.task_tools import (" in operation_bindings
    assert "file_task_runtime import" not in plan_presentation
    assert "file_task_runtime import" not in execution_loop
    assert "file_task_runtime import" not in finalization
    assert "file_task_runtime import" not in context_read
    assert "file_task_runtime import" not in planning
    assert "docx_parser import" not in docx_review
    assert "from app.core.file.parsers.docx_parser import" not in docx_rich_renderer


def test_task_tools_drops_unused_runtime_imports() -> None:
    task_tools = _source(TASK_TOOLS)

    assert "import subprocess" not in task_tools
    assert "FileTaskToolStreamChunk" not in task_tools
    assert "FileTaskToolStreamResult" in task_tools


def test_task_tools_registry_receives_only_explicit_operation_bindings() -> None:
    task_tools = _source(TASK_TOOLS)
    operation_bindings = _source(TASK_TOOL_OPERATION_BINDINGS)

    assert "sys.modules[__name__]" not in task_tools
    assert "build_task_tool_definitions(self, build_task_tool_operations())" in task_tools
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
                "from app.core.agent import task_tools_xlsx; "
                "payload = json.loads(task_tools_xlsx.read_sheet_data('__missing__.xlsx')); "
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
                "from app.core.agent import task_tools_conversion; "
                "assert task_tools_conversion.normalize_conversion_extension('pdf') == '.pdf'; "
                "print('conversion import and helper resolution ok')"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr or result.stdout
