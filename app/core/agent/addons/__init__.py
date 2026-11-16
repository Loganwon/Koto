"""Independent Addon protocol, admission, routing, and execution runtime."""

from .audit import AddonAuditStore, get_addon_audit_store
from .bootstrap import (
    addon_system_snapshot,
    initialize_addon_system,
    refresh_addon_runtime,
    register_addon_factory,
)
from .contracts import AddonBinding, AddonExecutionPlan, AddonTaskRequest
from .information_adapter import InformationRetrieverAdapter
from .runtime import AddonRuntime, get_addon_runtime, set_addon_runtime
from .store import AddonRegistrationStore, get_addon_store, set_addon_store

__all__ = [
    "AddonBinding",
    "AddonAuditStore",
    "AddonExecutionPlan",
    "AddonRuntime",
    "AddonTaskRequest",
    "AddonRegistrationStore",
    "InformationRetrieverAdapter",
    "addon_system_snapshot",
    "get_addon_audit_store",
    "get_addon_runtime",
    "get_addon_store",
    "initialize_addon_system",
    "refresh_addon_runtime",
    "register_addon_factory",
    "set_addon_store",
    "set_addon_runtime",
]
