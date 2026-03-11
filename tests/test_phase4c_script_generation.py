"""
Phase 4c: Script Generation Tests

Tests for auto-generating fix scripts.
"""

import os
import tempfile
import unittest

from app.core.agent.plugins.script_generation_plugin import ScriptGenerationPlugin
from app.core.scripts.script_generator import ScriptGenerator, ScriptType


class TestScriptGenerator(unittest.TestCase):
    """Test ScriptGenerator functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.ps_gen = ScriptGenerator(script_type=ScriptType.POWERSHELL)
        self.bash_gen = ScriptGenerator(script_type=ScriptType.BASH)

    def test_generate_kill_process_script_powershell(self):
        """Test PowerShell kill process script."""
        script = self.ps_gen.generate_kill_process_script("chrome.exe", pid=1234)
        self.assertIn("Stop-Process", script)
        self.assertIn("1234", script)
        self.assertIn("chrome.exe", script)

    def test_generate_kill_process_script_bash(self):
        """Test Bash kill process script."""
        script = self.bash_gen.generate_kill_process_script("chrome", pid=1234)
        self.assertIn("kill", script)
        self.assertIn("1234", script)
        self.assertIn("#!/bin/bash", script)

    def test_generate_clear_disk_space_powershell(self):
        """Test PowerShell clear disk script."""
        script = self.ps_gen.generate_clear_disk_space_script(min_gb=10)
        self.assertIn("Recycle Bin", script)
        self.assertIn("10", script)
        self.assertIn("Remove-Item", script)

    def test_generate_clear_disk_space_bash(self):
        """Test Bash clear disk script."""
        script = self.bash_gen.generate_clear_disk_space_script(min_gb=10)
        self.assertIn("apt-get", script)
        self.assertIn("#!/bin/bash", script)
        self.assertIn("10", script)

    def test_generate_memory_cleanup_powershell(self):
        """Test PowerShell memory cleanup script."""
        script = self.ps_gen.generate_memory_cleanup_script()
        self.assertIn("GC", script)
        self.assertIn("Clipboard", script)

    def test_generate_memory_cleanup_bash(self):
        """Test Bash memory cleanup script."""
        script = self.bash_gen.generate_memory_cleanup_script()
        self.assertIn("#!/bin/bash", script)
        self.assertIn("drop_caches", script)

    def test_generate_fix_script_cpu_high(self):
        """Test generating CPU high fix script."""
        result = self.ps_gen.generate_fix_script("cpu_high", process_name="python.exe")
        self.assertEqual(result["status"], "success")
        self.assertIn("script", result)
        self.assertEqual(result["issue_type"], "cpu_high")
        self.assertIn("python.exe", result["script"])

    def test_generate_fix_script_memory_high(self):
        """Test generating memory high fix script."""
        result = self.ps_gen.generate_fix_script("memory_high")
        self.assertEqual(result["status"], "success")
        self.assertIn("script", result)
        self.assertEqual(result["issue_type"], "memory_high")

    def test_generate_fix_script_disk_full(self):
        """Test generating disk full fix script."""
        result = self.ps_gen.generate_fix_script("disk_full", min_gb=15)
        self.assertEqual(result["status"], "success")
        self.assertIn("15", result["script"])

    def test_generate_fix_script_invalid_type(self):
        """Test generating with invalid issue type."""
        result = self.ps_gen.generate_fix_script("invalid_issue")
        self.assertEqual(result["status"], "error")
        self.assertIn("Unknown issue type", result["message"])

    def test_script_metadata(self):
        """Test script metadata in result."""
        result = self.ps_gen.generate_fix_script("cpu_high")
        self.assertIn("filename", result)
        self.assertIn("description", result)
        self.assertIn("run_command", result)
        self.assertIn("requires_admin", result)
        self.assertTrue(result["filename"].endswith(".ps1"))

    def test_requires_admin(self):
        """Test requires_admin flag."""
        disk_result = self.ps_gen.generate_fix_script("disk_full")
        self.assertTrue(disk_result["requires_admin"])

        cpu_result = self.ps_gen.generate_fix_script("cpu_high")
        self.assertFalse(cpu_result["requires_admin"])


class TestScriptGenerationPlugin(unittest.TestCase):
    """Test ScriptGenerationPlugin."""

    def setUp(self):
        """Set up test fixtures."""
        self.plugin = ScriptGenerationPlugin()

    def test_plugin_name_and_description(self):
        """Test plugin metadata."""
        self.assertIsNotNone(self.plugin.name)
        self.assertIsNotNone(self.plugin.description)
        self.assertEqual(self.plugin.name, "ScriptGenerationPlugin")

    def test_plugin_tools(self):
        """Test plugin exposes all tools."""
        tools = self.plugin.get_tools()
        tool_names = [t["name"] for t in tools]

        self.assertIn("generate_fix_script", tool_names)
        self.assertIn("save_script_to_file", tool_names)
        self.assertIn("list_available_scripts", tool_names)
        self.assertIn("get_script_type", tool_names)

    def test_generate_fix_script(self):
        """Test plugin generate_fix_script tool."""
        result = self.plugin.generate_fix_script("memory_high")
        self.assertEqual(result["status"], "success")
        self.assertIn("script", result)

    def test_list_available_scripts(self):
        """Test list_available_scripts tool."""
        result = self.plugin.list_available_scripts()
        self.assertEqual(result["status"], "success")
        self.assertIn("available_scripts", result)
        self.assertGreater(len(result["available_scripts"]), 0)
        self.assertIn("cpu_high", result["available_scripts"])

    def test_get_script_type(self):
        """Test get_script_type tool."""
        result = self.plugin.get_script_type()
        self.assertEqual(result["status"], "success")
        self.assertIn("script_type", result)
        self.assertIn("extension", result)

    def test_save_script_to_file(self):
        """Test saving script to file."""
        script_content = "Write-Host 'Test script'"
        filename = "test_script.ps1"

        result = self.plugin.save_script_to_file(
            script_content=script_content, filename=filename
        )

        self.assertEqual(result["status"], "success")
        self.assertIn("filepath", result)
        self.assertTrue(os.path.exists(result["filepath"]))

        # Verify content
        with open(result["filepath"], "r", encoding="utf-8") as f:
            saved_content = f.read()
        self.assertEqual(saved_content, script_content)

        # Clean up
        os.remove(result["filepath"])

    def test_save_script_prevents_path_traversal(self):
        """Test that saving prevents path traversal attacks."""
        script_content = "Test"
        dangerous_name = "../../../etc/test.sh"

        result = self.plugin.save_script_to_file(
            script_content=script_content, filename=dangerous_name
        )

        # Should save with safe filename
        self.assertEqual(result["status"], "success")
        filepath = result["filepath"]
        # Path should not contain '..'
        self.assertNotIn("..", filepath)

        # Clean up
        if os.path.exists(filepath):
            os.remove(filepath)

    def test_cpu_high_script_with_process(self):
        """Test CPU high script includes process name."""
        result = self.plugin.generate_fix_script(
            issue_type="cpu_high", process_name="test_process"
        )
        self.assertEqual(result["status"], "success")
        self.assertIn("test_process", result["script"])


if __name__ == "__main__":
    unittest.main()
