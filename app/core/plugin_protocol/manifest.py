# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Plugin manifest — schema validation, serialization, and digest.

Re-exports the canonical implementation from app.core.agent.plugin_protocol.
"""

from app.core.agent.plugin_protocol.contracts import (
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
)
from app.core.agent.plugin_protocol.schema import (
    PLUGIN_MANIFEST_JSON_SCHEMA,
    PLUGIN_MANIFEST_SCHEMA_ID,
    manifest_digest,
    manifest_from_dict,
    manifest_to_dict,
)

__all__ = [
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
]
