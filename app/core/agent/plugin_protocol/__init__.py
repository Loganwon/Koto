"""Public integration protocol for future Koto plugins.

The package contains contracts and admission gates only. It intentionally has
no plugin discovery, installer, marketplace, or business-specific plugin.
"""

from .admission import (
    AdmittedPluginContributions,
    PluginAdmissionController,
    PluginAdmissionPolicy,
    PluginAdmissionReport,
)
from .contracts import (
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
from .lifecycle import (
    AddonInvocationContext,
    KotoPlugin,
    PluginHealth,
    PluginHealthStatus,
    PluginHostContext,
)
from .retrieval import (
    RETRIEVAL_BATCH_JSON_SCHEMA,
    RETRIEVAL_REQUEST_JSON_SCHEMA,
    EvidenceChunk,
    RetrievalBatch,
    RetrievalRequest,
    RetrieverSpec,
)
from .schema import (
    PLUGIN_MANIFEST_JSON_SCHEMA,
    PLUGIN_MANIFEST_SCHEMA_ID,
    manifest_digest,
    manifest_from_dict,
    manifest_to_dict,
)

__all__ = [
    "AdmittedPluginContributions",
    "AddonInvocationContext",
    "ContributionKind",
    "DataClassification",
    "EvidenceChunk",
    "KotoPlugin",
    "PersistenceMode",
    "PLUGIN_MANIFEST_JSON_SCHEMA",
    "PLUGIN_MANIFEST_SCHEMA_ID",
    "PLUGIN_PROTOCOL_VERSION",
    "RETRIEVAL_BATCH_JSON_SCHEMA",
    "RETRIEVAL_REQUEST_JSON_SCHEMA",
    "PluginAdmissionController",
    "PluginAdmissionPolicy",
    "PluginAdmissionReport",
    "PluginContribution",
    "PluginDataPolicy",
    "PluginDependency",
    "PluginHealth",
    "PluginHealthStatus",
    "PluginHostContext",
    "PluginLimits",
    "PluginManifestV1",
    "PluginPermission",
    "PluginProtocolError",
    "PluginRuntimeSpec",
    "PluginTransport",
    "RetrievalBatch",
    "RetrievalRequest",
    "RetrieverSpec",
    "manifest_digest",
    "manifest_from_dict",
    "manifest_to_dict",
]
