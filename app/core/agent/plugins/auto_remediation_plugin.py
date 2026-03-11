"""
Phase 5c: Auto-Remediation Plugin

Provides tools for managing remediation actions with approval workflow.
"""

import logging
from typing import Any, Dict, List, Optional

from app.core.agent.base import AgentPlugin
from app.core.remediation.remediation_manager import (
    RemediationStatus,
    get_remediation_manager,
)

logger = logging.getLogger(__name__)


class AutoRemediationPlugin(AgentPlugin):
    """
    Auto-remediation plugin for system monitoring.

    Tools:
    - create_remediation_action: Create new remediation action
    - approve_remediation_action: Approve pending action
    - reject_remediation_action: Reject pending action
    - get_pending_remediations: List pending actions
    - execute_remediation_action: Execute approved action
    - get_remediation_status: Check action status
    - get_remediation_stats: View remediation statistics
    """

    @property
    def name(self) -> str:
        """Plugin name."""
        return "AutoRemediationPlugin"

    @property
    def description(self) -> str:
        """Plugin description."""
        return "Auto-remediation with approval workflow for system issues"

    def __init__(self):
        """Initialize plugin."""
        self.remediation_manager = get_remediation_manager()

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions."""
        return [
            {
                "name": "create_remediation_action",
                "func": self.create_remediation_action,
                "description": "Create a new remediation action for an issue",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "event_id": {
                            "type": "INTEGER",
                            "description": "Associated event ID from monitoring",
                        },
                        "action_type": {
                            "type": "STRING",
                            "description": "Type of remediation (e.g., restart_service, clear_cache)",
                        },
                        "description": {
                            "type": "STRING",
                            "description": "Human-readable description of the action",
                        },
                        "fix_script": {
                            "type": "STRING",
                            "description": "Script or command to execute",
                        },
                        "risk_level": {
                            "type": "STRING",
                            "description": "Risk assessment: low, medium, high",
                        },
                    },
                    "required": ["event_id", "action_type", "description"],
                },
            },
            {
                "name": "approve_remediation_action",
                "func": self.approve_remediation_action,
                "description": "Approve a pending remediation action",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "action_id": {
                            "type": "STRING",
                            "description": "ID of action to approve",
                        },
                        "reason": {
                            "type": "STRING",
                            "description": "Reason for approval (optional)",
                        },
                    },
                    "required": ["action_id"],
                },
            },
            {
                "name": "reject_remediation_action",
                "func": self.reject_remediation_action,
                "description": "Reject a pending remediation action",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "action_id": {
                            "type": "STRING",
                            "description": "ID of action to reject",
                        },
                        "reason": {
                            "type": "STRING",
                            "description": "Reason for rejection",
                        },
                    },
                    "required": ["action_id"],
                },
            },
            {
                "name": "get_pending_remediations",
                "func": self.get_pending_remediations,
                "description": "List all pending remediation actions",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "execute_remediation_action",
                "func": self.execute_remediation_action,
                "description": "Execute an approved remediation action",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "action_id": {
                            "type": "STRING",
                            "description": "ID of action to execute",
                        }
                    },
                    "required": ["action_id"],
                },
            },
            {
                "name": "get_remediation_status",
                "func": self.get_remediation_status,
                "description": "Get status of a remediation action",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "action_id": {
                            "type": "STRING",
                            "description": "ID of action to check",
                        }
                    },
                    "required": ["action_id"],
                },
            },
            {
                "name": "get_remediation_stats",
                "func": self.get_remediation_stats,
                "description": "Get overall remediation statistics",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
        ]

    def create_remediation_action(
        self,
        event_id: int,
        action_type: str,
        description: str,
        fix_script: Optional[str] = None,
        risk_level: str = "low",
    ) -> str:
        """Create remediation action."""
        try:
            action_id = self.remediation_manager.create_action(
                event_id=event_id,
                action_type=action_type,
                description=description,
                fix_script=fix_script,
                risk_level=risk_level,
            )
            return (
                f"Remediation action created (ID: {action_id})\n"
                f"Type: {action_type}\n"
                f"Risk Level: {risk_level}\n"
                f"Status: Pending approval"
            )
        except Exception as e:
            return f"Error creating remediation action: {str(e)}"

    def approve_remediation_action(
        self, action_id: str, reason: Optional[str] = None
    ) -> str:
        """Approve remediation action."""
        try:
            result = self.remediation_manager.approve_action(action_id, reason)

            if result:
                return (
                    f"Remediation action '{action_id}' approved\n"
                    f"Ready for execution"
                )
            else:
                return (
                    f"Failed to approve action '{action_id}' - may already be processed"
                )
        except Exception as e:
            return f"Error approving remediation action: {str(e)}"

    def reject_remediation_action(
        self, action_id: str, reason: Optional[str] = None
    ) -> str:
        """Reject remediation action."""
        try:
            result = self.remediation_manager.reject_action(action_id, reason)

            if result:
                msg = f"Remediation action '{action_id}' rejected"
                if reason:
                    msg += f"\nReason: {reason}"
                return msg
            else:
                return (
                    f"Failed to reject action '{action_id}' - may already be processed"
                )
        except Exception as e:
            return f"Error rejecting remediation action: {str(e)}"

    def get_pending_remediations(self) -> str:
        """Get pending remediations."""
        try:
            pending = self.remediation_manager.get_pending_actions()

            if not pending:
                return "No pending remediation actions"

            result = f"Pending Remediation Actions ({len(pending)}):\n\n"
            for action in pending:
                result += f"ID: {action['id']}\n"
                result += f"  Type: {action['action_type']}\n"
                result += f"  Description: {action['description']}\n"
                result += f"  Risk Level: {action['risk_level']}\n"
                result += f"  Created: {action['created_at']}\n\n"

            return result
        except Exception as e:
            return f"Error getting pending remediations: {str(e)}"

    def execute_remediation_action(self, action_id: str) -> str:
        """Execute remediation action."""
        try:
            result = self.remediation_manager.execute_action(action_id)

            if result:
                return (
                    f"Remediation action '{action_id}' started execution\n"
                    f"Status: Executing"
                )
            else:
                return (
                    f"Failed to execute action '{action_id}' - must be approved first"
                )
        except Exception as e:
            return f"Error executing remediation action: {str(e)}"

    def get_remediation_status(self, action_id: str) -> str:
        """Get remediation status."""
        try:
            action = self.remediation_manager.get_action(action_id)

            if not action:
                return f"Remediation action '{action_id}' not found"

            result = f"Remediation Action: {action_id}\n\n"
            result += f"Type: {action['action_type']}\n"
            result += f"Description: {action['description']}\n"
            result += f"Status: {action['status'].upper()}\n"
            result += f"Risk Level: {action['risk_level']}\n"
            result += f"Created: {action['created_at']}\n"

            if action["approved_at"]:
                result += f"Approved: {action['approved_at']}\n"
            if action["executed_at"]:
                result += f"Executed: {action['executed_at']}\n"
            if action["result"]:
                result += f"Result: {action['result']}\n"

            return result
        except Exception as e:
            return f"Error getting remediation status: {str(e)}"

    def get_remediation_stats(self) -> str:
        """Get remediation statistics."""
        try:
            stats = self.remediation_manager.get_stats()

            result = "Remediation Statistics:\n\n"
            result += f"Total Actions: {stats['total_actions']}\n\n"
            result += "By Status:\n"
            for status, count in stats["by_status"].items():
                result += f"  {status.upper()}: {count}\n"

            return result
        except Exception as e:
            return f"Error getting remediation stats: {str(e)}"
