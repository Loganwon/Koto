from __future__ import annotations

from pathlib import Path

from app.core.agent.base import AgentPlugin
from app.core.agent.file_task_tool_gateway import FileTaskToolGateway
from app.core.agent.kernel import KERNEL_API_VERSION
from app.core.agent.task_tools import TaskToolsPlugin
from app.core.agent.tool_registry import ToolRegistry, normalize_tool_args_for_spec
from app.core.agent.toolkits.foundation import (
    FOUNDATION_TOOL_SOURCE,
    FOUNDATION_TOOLKIT,
    FOUNDATION_TOOLKIT_ID,
    FOUNDATION_TOOLKIT_VERSION,
    CapabilityMaturity,
    foundation_capabilities,
    foundation_capability_report,
    validate_foundation_capabilities,
)


def test_foundation_toolkit_has_stable_identity() -> None:
    assert FOUNDATION_TOOLKIT_ID == "koto.foundation"
    assert FOUNDATION_TOOLKIT_VERSION == "1.0.0"
    assert FOUNDATION_TOOL_SOURCE == "toolkit:koto.foundation"
    assert FOUNDATION_TOOLKIT.api_version == KERNEL_API_VERSION
    assert "office.read" in FOUNDATION_TOOLKIT.capabilities
    assert "sandbox.execute" in FOUNDATION_TOOLKIT.capabilities


def test_foundation_capability_inventory_covers_every_public_tool() -> None:
    validate_foundation_capabilities()
    report = foundation_capability_report()

    assert report["tool_count"] == 30
    assert {item.maturity for item in foundation_capabilities()} == {
        CapabilityMaturity.READY,
        CapabilityMaturity.CONDITIONAL,
    }
    assert {item.capability_id for item in foundation_capabilities()} == set(
        FOUNDATION_TOOLKIT.capabilities
    )


def test_extracted_implementations_live_under_one_foundation_package() -> None:
    agent_dir = Path(__file__).resolve().parents[2] / "app" / "core" / "agent"
    foundation_dir = agent_dir / "toolkits" / "foundation"

    assert {
        "conversion.py",
        "docx_compare.py",
        "docx_minimal.py",
        "docx_review_cleanup.py",
        "docx_style.py",
        "docx_table_helpers.py",
        "docx_template.py",
        "multi_file.py",
        "office_create.py",
        "pdf_window.py",
        "pptx.py",
        "pptx_layout.py",
        "pptx_theme.py",
        "registry.py",
        "xlsx.py",
        "xlsx_sheet_selection.py",
        "xlsx_structure.py",
    } <= {path.name for path in foundation_dir.glob("*.py")}
    assert {path.name for path in agent_dir.glob("task_tools_*.py")} == {
        "task_tools_common.py"
    }
    assert not (agent_dir / "file_task_tool_catalog.py").exists()


def test_task_tools_compatibility_plugin_identifies_as_foundation_toolkit() -> None:
    assert TaskToolsPlugin.toolkit_id == FOUNDATION_TOOLKIT_ID
    assert TaskToolsPlugin.toolkit_version == FOUNDATION_TOOLKIT_VERSION
    assert TaskToolsPlugin.toolkit_source == FOUNDATION_TOOL_SOURCE


def test_registry_preserves_toolkit_source_and_version() -> None:
    class FoundationContributor(AgentPlugin):
        name = "foundation-test"
        description = "foundation metadata test"
        toolkit_source = FOUNDATION_TOOL_SOURCE
        toolkit_version = FOUNDATION_TOOLKIT_VERSION

        def get_tools(self):
            return [
                {
                    "name": "foundation_probe",
                    "description": "Probe foundation metadata.",
                    "func": lambda: "ok",
                    "parameters": {"type": "object", "properties": {}},
                }
            ]

    registry = ToolRegistry()
    registry.register_plugin(FoundationContributor())

    spec = registry.catalog.require("foundation_probe")
    assert spec.source == FOUNDATION_TOOL_SOURCE
    assert spec.version == FOUNDATION_TOOLKIT_VERSION


def test_foundation_structured_schemas_keep_legacy_plan_inputs_compatible() -> None:
    registry = ToolRegistry()
    registry.register_plugin(TaskToolsPlugin())

    cases = {
        "write_sheet_data": ("updates", '[{"row":1,"col":2,"value":"ok"}]', list),
        "write_docx_content": ("paragraphs", "一段旧格式正文", list),
        "fill_docx_template": ("data", '{"customer":"Koto"}', dict),
        "write_pptx_slides": (
            "updates",
            '[{"slide_index":0,"shape_index":1,"text":"Koto"}]',
            list,
        ),
    }

    for tool_name, (field, legacy_value, expected_type) in cases.items():
        spec = registry.catalog.require(tool_name)
        assert str(spec.input_schema["properties"][field]["type"]).lower() in {
            "array",
            "object",
        }
        normalized = normalize_tool_args_for_spec(spec, {field: legacy_value})
        assert isinstance(normalized[field], expected_type)


def test_file_task_gateway_publishes_foundation_owned_tools() -> None:
    gateway = FileTaskToolGateway(tool_executor=lambda _name, _args: "ok")

    spec = gateway.catalog.require("parse_file_to_text")
    assert spec.source == FOUNDATION_TOOL_SOURCE
    assert spec.version == FOUNDATION_TOOLKIT_VERSION


def test_file_task_gateway_preserves_addon_provider_identity() -> None:
    class LegalAddonProvider:
        toolkit_source = "plugin:koto.legal"
        toolkit_version = "2.3.0"

        def definitions(self):
            return [
                {
                    "name": "parse_file_to_text",
                    "description": "Read text with legal context.",
                    "parameters": {"type": "object", "properties": {}},
                    "read_only": True,
                }
            ]

        def allowed_names(self):
            return {"parse_file_to_text"}

        def execute(self, _tool_name, _tool_args):
            return "ok"

    gateway = FileTaskToolGateway(providers=[LegalAddonProvider()])

    spec = gateway.catalog.require("parse_file_to_text")
    assert spec.source == "plugin:koto.legal"
    assert spec.version == "2.3.0"
