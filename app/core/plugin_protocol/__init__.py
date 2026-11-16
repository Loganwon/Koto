# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Plugin Protocol — standardized plugin manifest, lifecycle, sandbox, and permissions.

Package structure:
  manifest.py   — PluginManifestV1 schema, validation, serialization
  lifecycle.py  — KotoPlugin protocol, PluginHostContext, PluginHealth
  sandbox.py    — PluginSandbox: filesystem/network isolation, resource limits
  permission.py — PermissionChecker: grant, check, enforce, audit

Canonical implementations of manifest and lifecycle contracts live at
app.core.agent.plugin_protocol; this package re-exports them and adds sandbox
and permission layers. Addon installation state is owned by
``app.core.agent.addons.store.AddonRegistrationStore``.
"""

from app.core.plugin_protocol.lifecycle import (
    AddonInvocationContext,
    KotoPlugin,
    PluginHealth,
    PluginHealthStatus,
    PluginHostContext,
)
from app.core.plugin_protocol.manifest import (
    PLUGIN_MANIFEST_JSON_SCHEMA,
    PLUGIN_MANIFEST_SCHEMA_ID,
    PLUGIN_PROTOCOL_VERSION,
    ContributionKind,
    DataClassification,
    PersistenceMode,
    PluginContribution,
    PluginDataPolicy,
    PluginDependency,
    PluginLimits,
    PluginManifestV1,
    PluginPermission,
    PluginProtocolError,
    PluginRuntimeSpec,
    PluginTransport,
    manifest_digest,
    manifest_from_dict,
    manifest_to_dict,
)
from app.core.plugin_protocol.permission import (
    PERMISSION_CATEGORIES,
    PERMISSION_DESCRIPTIONS,
    PermissionCategory,
    PermissionChecker,
    PermissionDeniedError,
    PermissionGrant,
    get_permission_checker,
    reset_permission_checker,
)
from app.core.plugin_protocol.sandbox import (
    PluginSandbox,
    SandboxLimits,
    SandboxViolation,
)

__all__ = [
    # Manifest
    "PLUGIN_MANIFEST_JSON_SCHEMA",
    "PLUGIN_MANIFEST_SCHEMA_ID",
    "PLUGIN_PROTOCOL_VERSION",
    "ContributionKind",
    "DataClassification",
    "PersistenceMode",
    "PluginContribution",
    "PluginDataPolicy",
    "PluginDependency",
    "PluginLimits",
    "PluginManifestV1",
    "PluginPermission",
    "PluginProtocolError",
    "PluginRuntimeSpec",
    "PluginTransport",
    "manifest_digest",
    "manifest_from_dict",
    "manifest_to_dict",
    # Lifecycle
    "AddonInvocationContext",
    "KotoPlugin",
    "PluginHealth",
    "PluginHealthStatus",
    "PluginHostContext",
    # Sandbox
    "PluginSandbox",
    "SandboxLimits",
    "SandboxViolation",
    # Permission
    "PermissionCategory",
    "PERMISSION_CATEGORIES",
    "PERMISSION_DESCRIPTIONS",
    "PermissionGrant",
    "PermissionChecker",
    "PermissionDeniedError",
    "get_permission_checker",
    "reset_permission_checker",
]
