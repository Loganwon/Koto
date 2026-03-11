"""
Phase 2 Regression Tests — UnifiedAgent + Plugins + Routes

运行方式:
    cd C:\\Users\\12524\\Desktop\\Koto
    python -m pytest tests/test_phase2_regression.py -v
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure project root is on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ===================================================================
# 1. ToolRegistry tests
# ===================================================================
class TestToolRegistry(unittest.TestCase):

    def _make_registry(self):
        from app.core.agent.tool_registry import ToolRegistry

        return ToolRegistry()

    def test_register_and_execute(self):
        reg = self._make_registry()
        reg.register_tool("echo", lambda text="": text, "Echo tool")
        result = reg.execute("echo", {"text": "hello"})
        self.assertEqual(result, "hello")

    def test_unknown_tool_raises(self):
        reg = self._make_registry()
        with self.assertRaises(Exception):
            reg.execute("nonexistent_tool", {})


# ===================================================================
# 2. Plugin loading tests
# ===================================================================
class TestPlugins(unittest.TestCase):

    def test_basic_tools_plugin(self):
        from app.core.agent.plugins.basic_tools_plugin import BasicToolsPlugin

        p = BasicToolsPlugin()
        tools = p.get_tools()
        names = [t["name"] for t in tools]
        self.assertIn("get_current_time", names)
        self.assertIn("calculate", names)

    def test_system_tools_plugin(self):
        from app.core.agent.plugins.system_tools_plugin import SystemToolsPlugin

        p = SystemToolsPlugin()
        tools = p.get_tools()
        names = [t["name"] for t in tools]
        self.assertIn("python_exec", names)
        self.assertIn("pip_install", names)
        self.assertIn("pip_check", names)

    def test_python_exec_runs(self):
        from app.core.agent.plugins.system_tools_plugin import SystemToolsPlugin

        result = SystemToolsPlugin.python_exec("print(1+1)")
        self.assertIn("2", result)

    def test_data_process_plugin(self):
        from app.core.agent.plugins.data_process_plugin import DataProcessPlugin

        p = DataProcessPlugin()
        names = [t["name"] for t in p.get_tools()]
        self.assertIn("load_data", names)
        self.assertIn("query_data", names)
        self.assertIn("save_data", names)

    def test_network_plugin(self):
        from app.core.agent.plugins.network_plugin import NetworkPlugin

        p = NetworkPlugin()
        names = [t["name"] for t in p.get_tools()]
        self.assertIn("http_get", names)
        self.assertIn("http_post", names)
        self.assertIn("parse_html", names)

    def test_file_editor_plugin(self):
        from app.core.agent.plugins.file_editor_plugin import FileEditorPlugin

        p = FileEditorPlugin()
        names = [t["name"] for t in p.get_tools()]
        self.assertIn("read_file", names)
        self.assertIn("write_file", names)

    def test_search_plugin(self):
        from app.core.agent.plugins.search_plugin import SearchPlugin

        p = SearchPlugin(api_key="fake")
        names = [t["name"] for t in p.get_tools()]
        self.assertTrue(len(names) > 0)

    def test_system_info_plugin(self):
        from app.core.agent.plugins.system_info_plugin import SystemInfoPlugin

        p = SystemInfoPlugin()
        names = [t["name"] for t in p.get_tools()]
        self.assertIn("query_cpu_status", names)
        self.assertIn("query_memory_status", names)
        self.assertIn("query_disk_usage", names)
        self.assertIn("query_network_status", names)
        self.assertIn("query_python_env", names)
        self.assertIn("list_running_apps", names)
        self.assertIn("get_system_warnings", names)

    def test_performance_analysis_plugin(self):
        from app.core.agent.plugins.performance_analysis_plugin import (
            PerformanceAnalysisPlugin,
        )

        p = PerformanceAnalysisPlugin()
        names = [t["name"] for t in p.get_tools()]
        self.assertIn("analyze_system_performance", names)
        self.assertIn("suggest_optimizations", names)


# ===================================================================
# 3. Factory creates agent with all plugins
# ===================================================================
class TestFactory(unittest.TestCase):

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_create_agent_has_all_tools(self):
        from app.core.agent.factory import create_agent

        agent = create_agent(api_key="test-key")
        defs = agent.registry.get_definitions()
        tool_names = [d["name"] for d in defs]
        # Core tools from all plugins
        for expected in [
            "get_current_time",
            "calculate",
            "python_exec",
            "pip_install",
            "pip_check",
            "load_data",
            "query_data",
            "save_data",
            "http_get",
            "http_post",
            "parse_html",
            "read_file",
            "write_file",
            "list_files",
            "query_cpu_status",
            "query_memory_status",
            "query_disk_usage",
            "query_network_status",
            "query_python_env",
            "list_running_apps",
            "get_system_warnings",
        ]:
            self.assertIn(expected, tool_names, f"Missing tool: {expected}")


# ===================================================================
# 4. UnifiedAgent step types
# ===================================================================
class TestUnifiedAgentTypes(unittest.TestCase):

    def test_agent_step_to_dict(self):
        from app.core.agent.types import AgentStep, AgentStepType

        step = AgentStep(step_type=AgentStepType.THOUGHT, content="thinking...")
        d = step.to_dict()
        self.assertEqual(d["step_type"], "thought")
        self.assertEqual(d["content"], "thinking...")

    def test_agent_response_to_dict(self):
        from app.core.agent.types import AgentResponse, AgentStep, AgentStepType

        resp = AgentResponse(
            content="hello",
            steps=[AgentStep(step_type=AgentStepType.ANSWER, content="hello")],
        )
        d = resp.to_dict()
        self.assertEqual(d["content"], "hello")
        self.assertEqual(len(d["steps"]), 1)


# ===================================================================
# 5. Route registration smoke test
# ===================================================================
class TestRoutes(unittest.TestCase):

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_blueprint_routes_registered(self):
        import app.api.agent_routes as mod

        # Verify each endpoint function is defined and callable
        for fn_name in [
            "chat",
            "list_tools",
            "process_compat",
            "process_stream_compat",
            "agent_confirm",
            "agent_choice",
        ]:
            self.assertTrue(
                callable(getattr(mod, fn_name, None)),
                f"Missing route function: {fn_name}",
            )


# ===================================================================
# 6. Calculate tool end-to-end
# ===================================================================
class TestCalculateTool(unittest.TestCase):

    def test_basic_arithmetic(self):
        from app.core.agent.plugins.basic_tools_plugin import BasicToolsPlugin

        p = BasicToolsPlugin()
        self.assertEqual(p.calculate("2 + 3"), "5")
        self.assertEqual(p.calculate("10 / 2"), "5.0")

    def test_invalid_expression(self):
        from app.core.agent.plugins.basic_tools_plugin import BasicToolsPlugin

        p = BasicToolsPlugin()
        result = p.calculate("import os")
        self.assertIn("Error", result)


# ===================================================================
# 7. Phase3: Session state snapshot extraction/injection
# ===================================================================
class TestPhase3StateSnapshot(unittest.TestCase):

    def test_parse_observation_json(self):
        from app.api.agent_routes import _parse_observation_json

        # Valid JSON
        result = _parse_observation_json('{"cpu": 42}')
        self.assertEqual(result, {"cpu": 42})
        # Invalid JSON
        result = _parse_observation_json("not json")
        self.assertIsNone(result)
        # Non-string
        result = _parse_observation_json(123)
        self.assertIsNone(result)

    def test_merge_system_snapshot_from_steps(self):
        from app.api.agent_routes import _merge_system_snapshot_from_steps

        session_state = {"system_snapshot": {}, "updated_at": None}
        steps = [
            {
                "step_type": "action",
                "action": {"tool_name": "query_cpu_status"},
                "content": "calling tool",
            },
            {
                "step_type": "observation",
                "content": '{"usage_percent": 25}',
                "observation": '{"usage_percent": 25}',
            },
        ]
        merged = _merge_system_snapshot_from_steps(session_state, steps)
        self.assertIn("cpu", merged["system_snapshot"])
        self.assertIn("data", merged["system_snapshot"]["cpu"])
        self.assertEqual(merged["system_snapshot"]["cpu"]["data"]["usage_percent"], 25)

    def test_build_snapshot_context_text(self):
        from app.api.agent_routes import _build_snapshot_context_text

        session_state = {
            "system_snapshot": {
                "cpu": {"tool": "query_cpu_status", "data": {"usage_percent": 30}},
                "memory": {"tool": "query_memory_status", "data": {"percent": 50}},
            }
        }
        text = _build_snapshot_context_text(session_state)
        self.assertIn("cpu", text)
        self.assertIn("30", text)
        self.assertIn("memory", text)


if __name__ == "__main__":
    unittest.main()
