# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Plugin Permission — permission declaration and runtime enforcement.

Defines the permission model for Koto plugins:
  - Permission declarations in plugin.json
  - Runtime permission checks before tool execution
  - Scope narrowing (plugin requests X, user grants subset Y)
  - Audit trail for permission-sensitive operations
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set

from app.core.plugin_protocol.manifest import PluginPermission

logger = logging.getLogger(__name__)


# ── Permission Categories ───────────────────────────────────────────────────


class PermissionCategory:
    """Human-readable categories for grouping permissions."""

    FILESYSTEM = "filesystem"
    NETWORK = "network"
    DATABASE = "database"
    MODEL = "model"
    SYSTEM = "system"
    SECRETS = "secrets"
    USER = "user"


PERMISSION_CATEGORIES: Dict[PluginPermission, str] = {
    PluginPermission.WORKSPACE_READ: PermissionCategory.FILESYSTEM,
    PluginPermission.WORKSPACE_WRITE: PermissionCategory.FILESYSTEM,
    PluginPermission.NETWORK_EGRESS: PermissionCategory.NETWORK,
    PluginPermission.DATABASE_READ: PermissionCategory.DATABASE,
    PluginPermission.DATABASE_WRITE: PermissionCategory.DATABASE,
    PluginPermission.MODEL_INVOKE: PermissionCategory.MODEL,
    PluginPermission.PROCESS_EXECUTE: PermissionCategory.SYSTEM,
    PluginPermission.SECRETS_USE: PermissionCategory.SECRETS,
    PluginPermission.USER_NOTIFY: PermissionCategory.USER,
}


PERMISSION_DESCRIPTIONS: Dict[PluginPermission, str] = {
    PluginPermission.WORKSPACE_READ: "Read files from the workspace",
    PluginPermission.WORKSPACE_WRITE: "Write or modify files in the workspace",
    PluginPermission.NETWORK_EGRESS: "Make outbound network requests",
    PluginPermission.DATABASE_READ: "Read from databases",
    PluginPermission.DATABASE_WRITE: "Write to databases",
    PluginPermission.MODEL_INVOKE: "Invoke AI models",
    PluginPermission.PROCESS_EXECUTE: "Execute system processes/commands",
    PluginPermission.SECRETS_USE: "Access configured secrets and API keys",
    PluginPermission.USER_NOTIFY: "Send notifications to the user",
}


# ── Permission Grant ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PermissionGrant:
    """Represents a granted permission set for a specific plugin."""

    plugin_id: str
    granted_permissions: FrozenSet[PluginPermission]
    reason: str = ""
    granted_at: str = ""
    granted_by: str = ""

    def has_permission(self, permission: PluginPermission) -> bool:
        return permission in self.granted_permissions

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "granted_permissions": [
                p.value for p in sorted(self.granted_permissions, key=lambda x: x.value)
            ],
            "reason": self.reason,
            "granted_at": self.granted_at,
            "granted_by": self.granted_by,
        }


# ── Permission Checker ──────────────────────────────────────────────────────


class PermissionChecker:
    """Runtime permission enforcement for plugin operations.

    Usage:
        checker = PermissionChecker()
        checker.grant("my-plugin", {PluginPermission.WORKSPACE_READ})

        @checker.require(PluginPermission.WORKSPACE_READ)
        def read_file(path: str) -> str: ...

        # Or directly:
        checker.check("my-plugin", PluginPermission.WORKSPACE_READ)
    """

    def __init__(self):
        self._grants: Dict[str, PermissionGrant] = {}
        self._violations: List[Dict[str, Any]] = []

    # ── Grant Management ────────────────────────────────────────────────────

    def grant(
        self,
        plugin_id: str,
        permissions: Set[PluginPermission],
        reason: str = "",
    ) -> PermissionGrant:
        """Grant permissions to a plugin."""
        from datetime import datetime, timezone

        grant = PermissionGrant(
            plugin_id=plugin_id,
            granted_permissions=frozenset(permissions),
            reason=reason,
            granted_at=datetime.now(timezone.utc).isoformat(),
            granted_by="koto-runtime",
        )
        self._grants[plugin_id] = grant
        logger.info(
            "[PermissionChecker] granted %s permissions to %s: %s",
            len(permissions),
            plugin_id,
            [p.value for p in permissions],
        )
        return grant

    def revoke(self, plugin_id: str) -> None:
        """Revoke all permissions for a plugin."""
        self._grants.pop(plugin_id, None)
        logger.info("[PermissionChecker] revoked permissions for %s", plugin_id)

    def revoke_permission(self, plugin_id: str, permission: PluginPermission) -> None:
        """Revoke a specific permission from a plugin."""
        grant = self._grants.get(plugin_id)
        if grant is None:
            return
        new_perms = set(grant.granted_permissions)
        new_perms.discard(permission)
        if new_perms:
            self._grants[plugin_id] = PermissionGrant(
                plugin_id=plugin_id,
                granted_permissions=frozenset(new_perms),
                reason=grant.reason,
                granted_at=grant.granted_at,
                granted_by=grant.granted_by,
            )
        else:
            del self._grants[plugin_id]

    # ── Permission Checks ───────────────────────────────────────────────────

    def check(self, plugin_id: str, permission: PluginPermission) -> bool:
        """Check if a plugin has a specific permission. Returns True if allowed."""
        grant = self._grants.get(plugin_id)
        if grant is None:
            self._record_violation(plugin_id, permission, "No permission grant found")
            return False
        if not grant.has_permission(permission):
            self._record_violation(plugin_id, permission, "Permission not granted")
            return False
        return True

    def check_all(self, plugin_id: str, permissions: Set[PluginPermission]) -> bool:
        """Check if a plugin has all specified permissions."""
        return all(self.check(plugin_id, p) for p in permissions)

    def check_any(self, plugin_id: str, permissions: Set[PluginPermission]) -> bool:
        """Check if a plugin has any of the specified permissions."""
        return any(self.check(plugin_id, p) for p in permissions)

    def require(self, permission: PluginPermission):
        """Decorator to require a permission for a function call."""

        def decorator(func):
            from functools import wraps

            @wraps(func)
            def wrapper(plugin_id: str, *args: Any, **kwargs: Any) -> Any:
                if not self.check(plugin_id, permission):
                    raise PermissionDeniedError(
                        plugin_id=plugin_id,
                        permission=permission,
                        operation=func.__name__,
                    )
                return func(plugin_id, *args, **kwargs)

            return wrapper

        return decorator

    # ── Query ───────────────────────────────────────────────────────────────

    def get_grant(self, plugin_id: str) -> Optional[PermissionGrant]:
        """Get the permission grant for a plugin."""
        return self._grants.get(plugin_id)

    def list_grants(self) -> Dict[str, PermissionGrant]:
        """List all active permission grants."""
        return dict(self._grants)

    def get_permissions(self, plugin_id: str) -> FrozenSet[PluginPermission]:
        """Get the set of permissions granted to a plugin."""
        grant = self._grants.get(plugin_id)
        return grant.granted_permissions if grant else frozenset()

    # ── Violation Tracking ──────────────────────────────────────────────────

    def _record_violation(
        self,
        plugin_id: str,
        permission: PluginPermission,
        reason: str,
    ) -> None:
        import time

        self._violations.append(
            {
                "plugin_id": plugin_id,
                "permission": permission.value,
                "reason": reason,
                "timestamp": time.time(),
            }
        )
        if len(self._violations) > 500:
            self._violations = self._violations[-500:]

    def get_violations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent permission violations."""
        return list(self._violations[-limit:])

    def clear_violations(self) -> None:
        """Clear the violation log."""
        self._violations.clear()

    # ── Manifest-based Auto-Grant ───────────────────────────────────────────

    def grant_from_manifest(
        self,
        plugin_id: str,
        requested_permissions: List[PluginPermission],
        reason: str = "Declared in plugin manifest",
    ) -> PermissionGrant:
        """Grant permissions based on a plugin manifest declaration.

        All plugin-declared permissions must be approved by the user.
        This method grants exactly what was requested.
        """
        return self.grant(
            plugin_id=plugin_id,
            permissions=set(requested_permissions),
            reason=reason,
        )

    # ── Diagnostics ─────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        return {
            "granted_plugins": len(self._grants),
            "grants": {pid: grant.to_dict() for pid, grant in self._grants.items()},
            "violation_count": len(self._violations),
        }


# ── Error Types ─────────────────────────────────────────────────────────────


class PermissionDeniedError(PermissionError):
    """Raised when a plugin attempts an operation without required permission."""

    def __init__(
        self,
        plugin_id: str,
        permission: PluginPermission,
        operation: str = "",
    ):
        msg = f"Plugin {plugin_id!r} denied permission " f"{permission.value!r}" + (
            f" for operation {operation!r}" if operation else ""
        )
        super().__init__(msg)
        self.plugin_id = plugin_id
        self.permission = permission
        self.operation = operation


# ── Module-level singleton ──────────────────────────────────────────────────

import threading

_checker: Optional[PermissionChecker] = None
_checker_lock = threading.Lock()


def get_permission_checker() -> PermissionChecker:
    """Get or create the global permission checker."""
    global _checker
    with _checker_lock:
        if _checker is None:
            _checker = PermissionChecker()
        return _checker


def reset_permission_checker() -> None:
    """Reset the global permission checker (for testing)."""
    global _checker
    with _checker_lock:
        _checker = None


__all__ = [
    "PermissionCategory",
    "PERMISSION_CATEGORIES",
    "PERMISSION_DESCRIPTIONS",
    "PermissionGrant",
    "PermissionChecker",
    "PermissionDeniedError",
    "get_permission_checker",
    "reset_permission_checker",
]
