"""Trusted host bootstrap for persisted Addon registrations."""

from __future__ import annotations

import importlib
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from app.core.agent.plugin_protocol import (
    KotoPlugin,
    PluginAdmissionPolicy,
    PluginHostContext,
    PluginPermission,
    PluginProtocolError,
    PluginTransport,
    manifest_digest,
    manifest_from_dict,
)

from .runtime import AddonRuntime, get_addon_runtime, set_addon_runtime
from .store import AddonRegistrationStore, binding_from_dict, get_addon_store

logger = logging.getLogger(__name__)

AddonFactory = Callable[[Any, Mapping[str, Any]], KotoPlugin]

_factories: dict[str, AddonFactory] = {}
_factory_lock = threading.RLock()
_bootstrap_lock = threading.RLock()


@dataclass(frozen=True)
class AddonBootstrapReport:
    admitted: tuple[str, ...] = ()
    disabled: tuple[str, ...] = ()
    blocked: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": list(self.admitted),
            "disabled": list(self.disabled),
            "blocked": dict(self.blocked),
        }


def register_addon_factory(addon_id: str, factory: AddonFactory) -> None:
    """Register trusted executable code from host bootstrap code.

    An HTTP request cannot call this function. Operators load factory modules
    explicitly through ``KOTO_ADDON_BOOTSTRAP_MODULES`` or application code.
    """

    normalized = str(addon_id or "").strip()
    if not normalized or not callable(factory):
        raise PluginProtocolError("Addon factory requires an id and callable")
    with _factory_lock:
        _factories[normalized] = factory


def unregister_addon_factory(addon_id: str) -> None:
    with _factory_lock:
        _factories.pop(str(addon_id), None)


def clear_addon_factories() -> None:
    with _factory_lock:
        _factories.clear()


def load_configured_factory_modules() -> tuple[str, ...]:
    """Import only operator-allowlisted modules that register Addon factories."""

    configured = os.environ.get("KOTO_ADDON_BOOTSTRAP_MODULES", "")
    modules = tuple(
        dict.fromkeys(item.strip() for item in configured.split(",") if item.strip())
    )
    for module_name in modules:
        importlib.import_module(module_name)
    return modules


def _audit(event: Mapping[str, Any]) -> None:
    payload = dict(event)
    logger.info("[AddonAudit] %s", json.dumps(payload, ensure_ascii=False))
    from .audit import get_addon_audit_store

    get_addon_audit_store().append(payload)


def _secret_resolver(bindings: Mapping[str, str]) -> Callable[[str], str]:
    def resolve(name: str) -> str:
        reference = str(bindings.get(name) or "")
        env_name = reference[4:] if reference.startswith("env:") else reference
        value = os.environ.get(env_name, "") if env_name else ""
        if not value:
            raise PluginProtocolError(f"Addon secret reference is unavailable: {name}")
        return value

    return resolve


def _available_secret_names(bindings: Mapping[str, str]) -> frozenset[str]:
    available = set()
    for name, reference in bindings.items():
        env_name = (
            reference[4:] if str(reference).startswith("env:") else str(reference)
        )
        if env_name and os.environ.get(env_name):
            available.add(str(name))
    return frozenset(available)


def _stop_runtime(runtime: AddonRuntime) -> None:
    for item in runtime.catalog_snapshot().get("addons", []):
        try:
            runtime.shutdown(str(item["addon_id"]))
        except Exception:
            logger.debug("Addon shutdown during refresh failed", exc_info=True)


def refresh_addon_runtime(
    *,
    store: AddonRegistrationStore | None = None,
) -> AddonBootstrapReport:
    """Rebuild the executable runtime from persisted, explicitly enabled records."""

    active_store = store or get_addon_store()
    admitted: list[str] = []
    disabled: list[str] = []
    blocked: dict[str, str] = {}
    new_runtime = AddonRuntime(audit_sink=_audit)
    records = active_store.list_records()
    store_revision = active_store.revision()
    available_plugins = {
        item["addon_id"]: str((item.get("manifest") or {}).get("version") or "")
        for item in records
    }

    with _bootstrap_lock:
        for record in records:
            addon_id = str(record["addon_id"])
            if not record.get("enabled"):
                disabled.append(addon_id)
                if record.get("state") != "disabled":
                    active_store.update_runtime_state(addon_id, state="disabled")
                continue
            try:
                manifest = manifest_from_dict(record.get("manifest") or {})
                with _factory_lock:
                    factory = _factories.get(addon_id)
                if factory is None:
                    raise PluginProtocolError(
                        "trusted host factory is not loaded; configure "
                        "KOTO_ADDON_BOOTSTRAP_MODULES"
                    )
                plugin = factory(manifest, dict(record.get("config") or {}))
                if plugin.manifest.plugin_id != addon_id:
                    raise PluginProtocolError("factory returned a different Addon id")
                if manifest_digest(plugin.manifest) != manifest_digest(manifest):
                    raise PluginProtocolError(
                        "factory manifest differs from registration"
                    )

                grants = frozenset(
                    PluginPermission(item)
                    for item in record.get("granted_permissions") or ()
                )
                secret_bindings = dict(record.get("secret_bindings") or {})
                host = PluginHostContext(
                    plugin_id=addon_id,
                    granted_permissions=grants,
                    config=dict(record.get("config") or {}),
                    declared_secret_names=frozenset(secret_bindings),
                    secret_resolver=_secret_resolver(secret_bindings),
                    emit_audit=_audit,
                )
                policy = PluginAdmissionPolicy(
                    granted_permissions=grants,
                    allowed_transports=frozenset({PluginTransport.IN_PROCESS}),
                    available_plugins=available_plugins,
                    available_secret_names=_available_secret_names(secret_bindings),
                    max_timeout_seconds=120,
                    max_result_bytes=5_000_000,
                    max_concurrency=8,
                    max_rag_chunks=30,
                    require_audit_sink=True,
                )
                new_runtime.admit(
                    plugin,
                    host_context=host,
                    policy=policy,
                    bindings=tuple(
                        binding_from_dict(item) for item in record.get("bindings") or ()
                    ),
                )
                active_store.update_runtime_state(
                    addon_id, state="admitted", last_error="", enabled=True
                )
                admitted.append(addon_id)
            except Exception as exc:
                message = str(exc) or type(exc).__name__
                blocked[addon_id] = message
                active_store.update_runtime_state(
                    addon_id, state="blocked", last_error=message, enabled=True
                )

        previous = get_addon_runtime(sync=False)
        set_addon_runtime(new_runtime, revision=store_revision)
        if previous is not new_runtime:
            _stop_runtime(previous)

    return AddonBootstrapReport(
        admitted=tuple(admitted),
        disabled=tuple(disabled),
        blocked=blocked,
    )


def initialize_addon_system() -> AddonBootstrapReport:
    load_configured_factory_modules()
    return refresh_addon_runtime()


def addon_system_snapshot() -> dict[str, Any]:
    """Merge persisted registrations with runtime-only host admissions."""

    store = get_addon_store()
    registrations = {item["addon_id"]: item for item in store.list_records()}
    runtime_items = {
        item["addon_id"]: item
        for item in get_addon_runtime().catalog_snapshot().get("addons", [])
    }
    merged: list[dict[str, Any]] = []
    for addon_id in sorted(set(registrations) | set(runtime_items)):
        if addon_id in registrations:
            public = store.public_record(addon_id)
            runtime_item = runtime_items.get(addon_id)
            if runtime_item:
                public.update(
                    {
                        "health": runtime_item.get("health", "unknown"),
                        "stopped": runtime_item.get("stopped", False),
                        "runtime_admitted": True,
                    }
                )
            else:
                public.update(
                    {
                        "health": "unavailable",
                        "stopped": False,
                        "runtime_admitted": False,
                    }
                )
            merged.append(public)
        else:
            item = dict(runtime_items[addon_id])
            item.update({"state": "admitted", "runtime_admitted": True})
            merged.append(item)
    return {
        "addons": merged,
        "total": len(merged),
        "admitted": sum(1 for item in merged if item.get("runtime_admitted")),
        "enabled": sum(1 for item in merged if item.get("enabled")),
        "revision": store.revision(),
    }


__all__ = [
    "AddonBootstrapReport",
    "addon_system_snapshot",
    "clear_addon_factories",
    "initialize_addon_system",
    "load_configured_factory_modules",
    "refresh_addon_runtime",
    "register_addon_factory",
    "unregister_addon_factory",
]
