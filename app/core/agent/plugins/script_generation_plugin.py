"""
Phase 4c: Script Generation Plugin

Agent plugin for auto-generating fix scripts.
"""

import logging
import os
import platform
from typing import Any, Dict, List, Optional

from app.core.agent.base import AgentPlugin
from app.core.scripts.script_generator import ScriptGenerator, ScriptType

logger = logging.getLogger(__name__)


class ScriptGenerationPlugin(AgentPlugin):
    """
    Plugin for auto-generating executable scripts to fix system issues.
    """

    @property
    def name(self) -> str:
        """Plugin name"""
        return "ScriptGenerationPlugin"

    @property
    def description(self) -> str:
        """Plugin description"""
        return "Auto-generate executable scripts to fix detected system issues"

    def __init__(self):
        super().__init__()
        # Detect OS and use appropriate script type
        if platform.system() == "Windows":
            self.script_type = ScriptType.POWERSHELL
        else:
            self.script_type = ScriptType.BASH
        self.generator = ScriptGenerator(script_type=self.script_type)

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return tools for script generation."""
        return [
            {
                "name": "generate_fix_script",
                "description": "Generate an executable script to fix a detected system issue (high CPU, high memory, low disk space, etc.)",
                "func": self.generate_fix_script,
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "issue_type": {
                            "type": "STRING",
                            "description": "Type of issue: 'cpu_high', 'memory_high', 'disk_full', 'process_memory_high', 'service_restart', 'disk_health'",
                        },
                        "process_name": {
                            "type": "STRING",
                            "description": "Process name to kill (for process_memory_high issue type) (optional)",
                        },
                        "service_name": {
                            "type": "STRING",
                            "description": "Service name to restart (for service_restart issue type) (optional)",
                        },
                        "min_gb": {
                            "type": "INTEGER",
                            "description": "Minimum GB to free up (for disk_full issue type, default 5) (optional)",
                        },
                    },
                    "required": ["issue_type"],
                },
            },
            {
                "name": "save_script_to_file",
                "description": "Save generated script to a file in workspace directory for manual execution",
                "func": self.save_script_to_file,
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "script_content": {
                            "type": "STRING",
                            "description": "The script content to save",
                        },
                        "filename": {
                            "type": "STRING",
                            "description": "Filename for the script (e.g., 'fix_cpu_high.ps1')",
                        },
                    },
                    "required": ["script_content", "filename"],
                },
            },
            {
                "name": "list_available_scripts",
                "description": "List available fix script templates that can be generated",
                "func": self.list_available_scripts,
                "parameters": {"type": "OBJECT", "properties": {}, "required": []},
            },
            {
                "name": "get_script_type",
                "description": "Get current script type (PowerShell or Bash) based on OS",
                "func": self.get_script_type,
                "parameters": {"type": "OBJECT", "properties": {}, "required": []},
            },
        ]

    def generate_fix_script(
        self,
        issue_type: str,
        process_name: Optional[str] = None,
        service_name: Optional[str] = None,
        min_gb: int = 5,
        **kwargs,
    ) -> Dict[str, Any]:
        """Generate a fix script for a specific issue."""
        try:
            result = self.generator.generate_fix_script(
                issue_type=issue_type,
                process_name=process_name,
                service_name=service_name,
                min_gb=min_gb,
            )
            return result
        except Exception as e:
            logger.error(f"Error generating script: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Failed to generate script: {str(e)}",
            }

    def save_script_to_file(self, script_content: str, filename: str) -> Dict[str, Any]:
        """Save script to file in workspace directory."""
        try:
            # Get project root and workspace directory
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            scripts_dir = os.path.join(project_root, "workspace", "scripts")
            os.makedirs(scripts_dir, exist_ok=True)

            # Ensure safe filename
            filename = os.path.basename(filename)  # Prevent path traversal
            filepath = os.path.join(scripts_dir, filename)

            # Write script
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(script_content)

            # Make executable on Unix-like systems
            if platform.system() != "Windows":
                import stat

                os.chmod(filepath, os.stat(filepath).st_mode | stat.S_IEXEC)

            return {
                "status": "success",
                "message": f"Script saved to {filepath}",
                "filepath": filepath,
                "next_step": f"Run: {self.generator._get_run_command(os.path.splitext(filename)[1])}",
            }
        except Exception as e:
            logger.error(f"Error saving script: {e}", exc_info=True)
            return {"status": "error", "message": f"Failed to save script: {str(e)}"}

    def list_available_scripts(self) -> Dict[str, Any]:
        """List available fix script templates."""
        scripts = {
            "cpu_high": {
                "description": "Identify and stop high CPU processes",
                "parameters": ["process_name (optional)"],
            },
            "memory_high": {
                "description": "Clear memory caches and optimize RAM",
                "parameters": [],
            },
            "disk_full": {
                "description": "Remove temp files and free up disk space",
                "parameters": ["min_gb (default 5)"],
            },
            "process_memory_high": {
                "description": "Kill a specific high-memory process",
                "parameters": ["process_name (required)"],
            },
            "service_restart": {
                "description": "Restart a system service",
                "parameters": ["service_name (required)"],
            },
            "disk_health": {
                "description": "Check disk space and health status",
                "parameters": [],
            },
        }

        return {
            "status": "success",
            "script_type": self.script_type.value,
            "available_scripts": scripts,
            "examples": {
                "cpu_high": "generate_fix_script(issue_type='cpu_high', process_name='python.exe')",
                "disk_full": "generate_fix_script(issue_type='disk_full', min_gb=10)",
                "process_memory_high": "generate_fix_script(issue_type='process_memory_high', process_name='chrome.exe')",
            },
        }

    def get_script_type(self) -> Dict[str, Any]:
        """Get current script type based on OS."""
        return {
            "status": "success",
            "os": platform.system(),
            "script_type": self.script_type.value,
            "extension": ".ps1" if self.script_type == ScriptType.POWERSHELL else ".sh",
        }
