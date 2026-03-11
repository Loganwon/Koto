"""
Phase 5c: Auto-Remediation System

Manages remediation actions with approval workflow.
Tracks pending, executing, and completed fixes.
"""

import json
import logging
import threading
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RemediationStatus(Enum):
    """Status of remediation action."""

    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    REJECTED = "rejected"


class RemediationAction:
    """Represents a remediation action."""

    def __init__(
        self,
        event_id: int,
        action_type: str,
        description: str,
        fix_script: Optional[str] = None,
        risk_level: str = "low",
    ):
        """
        Initialize remediation action.

        Args:
            event_id: Associated event ID
            action_type: Type of action (restart_service, clear_cache, etc.)
            description: Human-readable description
            fix_script: Script to execute
            risk_level: low, medium, high
        """
        self.id = f"{event_id}_{int(datetime.now().timestamp())}"
        self.event_id = event_id
        self.action_type = action_type
        self.description = description
        self.fix_script = fix_script
        self.risk_level = risk_level
        self.status = RemediationStatus.PENDING
        self.created_at = datetime.now().isoformat()
        self.approved_at: Optional[str] = None
        self.executed_at: Optional[str] = None
        self.result: Optional[str] = None
        self.approval_reason: Optional[str] = None
        self.rejection_reason: Optional[str] = None

    def approve(self, reason: Optional[str] = None) -> bool:
        """Approve this action."""
        if self.status != RemediationStatus.PENDING:
            logger.warning(f"Cannot approve action {self.id} in state {self.status}")
            return False

        self.status = RemediationStatus.APPROVED
        self.approved_at = datetime.now().isoformat()
        self.approval_reason = reason
        return True

    def reject(self, reason: Optional[str] = None) -> bool:
        """Reject this action."""
        if self.status != RemediationStatus.PENDING:
            logger.warning(f"Cannot reject action {self.id} in state {self.status}")
            return False

        self.status = RemediationStatus.REJECTED
        self.rejection_reason = reason
        return True

    def start_execution(self) -> bool:
        """Mark as executing."""
        if self.status != RemediationStatus.APPROVED:
            logger.warning(f"Cannot execute non-approved action {self.id}")
            return False

        self.status = RemediationStatus.EXECUTING
        return True

    def complete(self, success: bool, result: str = "") -> bool:
        """Mark as completed."""
        if self.status != RemediationStatus.EXECUTING:
            logger.warning(f"Cannot complete non-executing action {self.id}")
            return False

        self.status = RemediationStatus.SUCCESS if success else RemediationStatus.FAILED
        self.executed_at = datetime.now().isoformat()
        self.result = result
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return {
            "id": self.id,
            "event_id": self.event_id,
            "action_type": self.action_type,
            "description": self.description,
            "risk_level": self.risk_level,
            "status": self.status.value,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "executed_at": self.executed_at,
            "result": self.result,
            "approval_reason": self.approval_reason,
            "rejection_reason": self.rejection_reason,
        }


class RemediationManager:
    """
    Manages remediation actions with approval workflow.
    """

    def __init__(self):
        """Initialize manager."""
        self.actions: Dict[str, RemediationAction] = {}
        self.action_history: List[Dict[str, Any]] = []
        self.lock = threading.Lock()

    def create_action(
        self,
        event_id: int,
        action_type: str,
        description: str,
        fix_script: Optional[str] = None,
        risk_level: str = "low",
    ) -> str:
        """
        Create a new remediation action.

        Args:
            event_id: Associated event
            action_type: Type of remediation
            description: Description for user
            fix_script: Script to execute
            risk_level: Risk assessment

        Returns:
            Action ID
        """
        with self.lock:
            action = RemediationAction(
                event_id=event_id,
                action_type=action_type,
                description=description,
                fix_script=fix_script,
                risk_level=risk_level,
            )
            self.actions[action.id] = action
            logger.info(f"Created remediation action: {action.id}")
            return action.id

    def approve_action(self, action_id: str, reason: Optional[str] = None) -> bool:
        """Approve a pending action."""
        with self.lock:
            action = self.actions.get(action_id)
            if not action:
                logger.warning(f"Action not found: {action_id}")
                return False

            result = action.approve(reason)
            if result:
                logger.info(f"Action approved: {action_id}")
            return result

    def reject_action(self, action_id: str, reason: Optional[str] = None) -> bool:
        """Reject a pending action."""
        with self.lock:
            action = self.actions.get(action_id)
            if not action:
                logger.warning(f"Action not found: {action_id}")
                return False

            result = action.reject(reason)
            if result:
                logger.info(f"Action rejected: {action_id}")
            return result

    def get_pending_actions(self) -> List[Dict[str, Any]]:
        """Get all pending actions."""
        with self.lock:
            pending = [
                action.to_dict()
                for action in self.actions.values()
                if action.status == RemediationStatus.PENDING
            ]
            return pending

    def get_action(self, action_id: str) -> Optional[Dict[str, Any]]:
        """Get action details."""
        with self.lock:
            action = self.actions.get(action_id)
            if action:
                return action.to_dict()
            return None

    def get_all_actions(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all actions, optionally filtered by status."""
        with self.lock:
            actions = list(self.actions.values())

            if status:
                try:
                    status_enum = RemediationStatus(status)
                    actions = [a for a in actions if a.status == status_enum]
                except ValueError:
                    logger.warning(f"Invalid status: {status}")
                    return []

            return [a.to_dict() for a in actions]

    def execute_action(self, action_id: str) -> bool:
        """
        Execute an approved action.

        Args:
            action_id: Action to execute

        Returns:
            True if execution started successfully
        """
        with self.lock:
            action = self.actions.get(action_id)
            if not action:
                logger.warning(f"Action not found: {action_id}")
                return False

            result = action.start_execution()
            if result:
                logger.info(f"Started execution: {action_id}")
                # In real implementation, would spawn execution thread
                # For now, simulate success
                threading.Thread(
                    target=self._execute_async, args=(action_id,), daemon=True
                ).start()
            return result

    def _execute_async(self, action_id: str) -> None:
        """Execute action asynchronously."""
        try:
            # Simulate execution (in reality would run fix_script)
            import time

            time.sleep(0.5)

            with self.lock:
                action = self.actions.get(action_id)
                if action:
                    action.complete(True, "Remediation completed successfully")
                    logger.info(f"Action completed: {action_id}")
        except Exception as e:
            logger.error(f"Error executing action: {e}")
            with self.lock:
                action = self.actions.get(action_id)
                if action:
                    action.complete(False, f"Error: {str(e)}")

    def get_stats(self) -> Dict[str, Any]:
        """Get remediation statistics."""
        with self.lock:
            total = len(self.actions)
            by_status = {}
            for status in RemediationStatus:
                count = sum(1 for a in self.actions.values() if a.status == status)
                by_status[status.value] = count

            return {
                "total_actions": total,
                "by_status": by_status,
                "timestamp": datetime.now().isoformat(),
            }


# Global instance
_remediation_manager: Optional[RemediationManager] = None
_remediation_lock = threading.Lock()


def get_remediation_manager() -> RemediationManager:
    """Get or create the singleton RemediationManager instance."""
    global _remediation_manager

    if _remediation_manager is None:
        with _remediation_lock:
            if _remediation_manager is None:
                _remediation_manager = RemediationManager()

    return _remediation_manager
