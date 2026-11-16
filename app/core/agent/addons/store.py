"""Crash-safe persisted registrations for Koto Addons.

The store contains declarative manifests, routing bindings and host grants. It
never stores executable code or secret values. Registration is therefore a
separate state from runtime admission.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from app.core.agent.plugin_protocol import (
    PluginPermission,
    PluginProtocolError,
    manifest_digest,
    manifest_from_dict,
    manifest_to_dict,
)
from app.core.config.runtime_storage import (
    legacy_config_path,
    migrate_legacy_file,
    runtime_data_path,
)
from app.core.config.settings_store import settings_file_lock

from .contracts import AddonBinding


def _default_store_path() -> Path:
    configured = os.environ.get("KOTO_ADDON_REGISTRY_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return migrate_legacy_file(
        runtime_data_path("addons.json"),
        legacy_paths=(legacy_config_path("addons.json"),),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _binding_to_dict(binding: AddonBinding) -> dict[str, Any]:
    return {
        "contribution_name": binding.contribution_name,
        "task_types": list(binding.task_types),
        "intent_patterns": list(binding.intent_patterns),
        "file_types": list(binding.file_types),
        "priority": binding.priority,
    }


def binding_from_dict(payload: Mapping[str, Any]) -> AddonBinding:
    if not isinstance(payload, Mapping):
        raise PluginProtocolError("addon binding must be an object")
    return AddonBinding(
        contribution_name=str(payload.get("contribution_name") or ""),
        task_types=tuple(payload.get("task_types") or ()),
        intent_patterns=tuple(payload.get("intent_patterns") or ()),
        file_types=tuple(payload.get("file_types") or ()),
        priority=int(payload.get("priority", 50)),
    )


class AddonRegistrationStore:
    """Host-owned registry of declarative Addon connection requests."""

    def __init__(self, path: str | os.PathLike[str] | None = None):
        self.path = Path(path).resolve() if path else _default_store_path()
        self._lock = threading.RLock()

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"schema_version": "1.1", "revision": 0, "addons": {}}

    def _load_locked(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError) as exc:
            raise PluginProtocolError(f"cannot read Addon registry: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("addons"), dict):
            raise PluginProtocolError("Addon registry must contain an addons object")
        payload.setdefault("schema_version", "1.1")
        payload.setdefault("revision", 0)
        return payload

    @staticmethod
    def _bump_revision(payload: dict[str, Any]) -> int:
        revision = max(0, int(payload.get("revision") or 0)) + 1
        payload["revision"] = revision
        payload["schema_version"] = "1.1"
        return revision

    def _write_locked(self, payload: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def register(
        self,
        manifest_payload: Mapping[str, Any],
        *,
        bindings: Sequence[Mapping[str, Any] | AddonBinding],
        granted_permissions: Sequence[str | PluginPermission] = (),
        config: Mapping[str, Any] | None = None,
        secret_bindings: Mapping[str, str] | None = None,
        enabled: bool = False,
    ) -> dict[str, Any]:
        manifest = manifest_from_dict(manifest_payload)
        normalized_bindings = tuple(
            item if isinstance(item, AddonBinding) else binding_from_dict(item)
            for item in bindings
        )
        if not normalized_bindings:
            raise PluginProtocolError(
                "Addon registration requires at least one explicit routing binding"
            )
        declared_names = {item.name for item in manifest.contributions}
        unknown = sorted(
            item.contribution_name
            for item in normalized_bindings
            if item.contribution_name not in declared_names
        )
        if unknown:
            raise PluginProtocolError(
                "bindings reference undeclared contributions: " + ", ".join(unknown)
            )

        grants = tuple(
            dict.fromkeys(PluginPermission(item) for item in granted_permissions)
        )
        undeclared_grants = sorted(
            item.value for item in grants if item not in manifest.permissions
        )
        if undeclared_grants:
            raise PluginProtocolError(
                "host grants are absent from the manifest: "
                + ", ".join(undeclared_grants)
            )
        normalized_config = copy.deepcopy(dict(config or {}))
        try:
            Draft202012Validator(manifest.config_schema).validate(normalized_config)
        except ValidationError as exc:
            raise PluginProtocolError(
                f"Addon config does not match config_schema: {exc.message}"
            ) from exc

        normalized_secrets = {
            str(name).strip(): str(reference).strip()
            for name, reference in dict(secret_bindings or {}).items()
            if str(name).strip() and str(reference).strip()
        }
        unknown_secrets = sorted(set(normalized_secrets) - set(manifest.secret_names))
        if unknown_secrets:
            raise PluginProtocolError(
                "secret bindings are absent from the manifest: "
                + ", ".join(unknown_secrets)
            )
        now = _utc_now()
        with self._lock, settings_file_lock(self.path):
            payload = self._load_locked()
            previous = payload["addons"].get(manifest.plugin_id, {})
            record = {
                "manifest": manifest_to_dict(manifest),
                "manifest_sha256": manifest_digest(manifest),
                "bindings": [_binding_to_dict(item) for item in normalized_bindings],
                "granted_permissions": [item.value for item in grants],
                "config": normalized_config,
                # Values are environment/secret-store references, never secrets.
                "secret_bindings": normalized_secrets,
                "enabled": bool(enabled),
                "state": "registered",
                "last_error": "",
                "created_at": previous.get("created_at") or now,
                "updated_at": now,
            }
            payload["addons"][manifest.plugin_id] = record
            self._bump_revision(payload)
            self._write_locked(payload)
        return self.public_record(manifest.plugin_id)

    def list_records(self) -> list[dict[str, Any]]:
        with self._lock, settings_file_lock(self.path):
            payload = self._load_locked()
            return [
                {"addon_id": addon_id, **copy.deepcopy(record)}
                for addon_id, record in sorted(payload["addons"].items())
            ]

    def get_record(self, addon_id: str) -> dict[str, Any] | None:
        with self._lock, settings_file_lock(self.path):
            record = self._load_locked()["addons"].get(str(addon_id))
            return copy.deepcopy(record) if isinstance(record, dict) else None

    def revision(self) -> int:
        """Return the cross-process runtime configuration revision."""
        with self._lock, settings_file_lock(self.path):
            return max(0, int(self._load_locked().get("revision") or 0))

    def set_enabled(self, addon_id: str, enabled: bool) -> dict[str, Any]:
        with self._lock, settings_file_lock(self.path):
            payload = self._load_locked()
            record = payload["addons"].get(str(addon_id))
            if not isinstance(record, dict):
                raise KeyError(str(addon_id))
            changed = bool(record.get("enabled")) is not bool(enabled)
            record["enabled"] = bool(enabled)
            record["state"] = "registered" if enabled else "disabled"
            record["last_error"] = ""
            record["updated_at"] = _utc_now()
            if changed:
                self._bump_revision(payload)
            self._write_locked(payload)
        return self.public_record(addon_id)

    def update_runtime_state(
        self,
        addon_id: str,
        *,
        state: str,
        last_error: str = "",
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock, settings_file_lock(self.path):
            payload = self._load_locked()
            record = payload["addons"].get(str(addon_id))
            if not isinstance(record, dict):
                raise KeyError(str(addon_id))
            record["state"] = str(state)
            record["last_error"] = str(last_error or "")[:2000]
            if enabled is not None:
                enabled_changed = bool(record.get("enabled")) != bool(enabled)
                record["enabled"] = bool(enabled)
                if enabled_changed:
                    self._bump_revision(payload)
            record["updated_at"] = _utc_now()
            self._write_locked(payload)
        return self.public_record(addon_id)

    def remove(self, addon_id: str) -> bool:
        with self._lock, settings_file_lock(self.path):
            payload = self._load_locked()
            removed = payload["addons"].pop(str(addon_id), None)
            if removed is None:
                return False
            self._bump_revision(payload)
            self._write_locked(payload)
            return True

    def public_record(self, addon_id: str) -> dict[str, Any]:
        record = self.get_record(addon_id)
        if record is None:
            raise KeyError(str(addon_id))
        manifest = record.get("manifest") or {}
        return {
            "addon_id": str(addon_id),
            "plugin_id": str(addon_id),
            "name": manifest.get("name") or addon_id,
            "description": manifest.get("description") or "",
            "version": manifest.get("version") or "",
            "publisher": manifest.get("publisher") or "",
            "transport": (manifest.get("runtime") or {}).get("transport") or "",
            "enabled": bool(record.get("enabled")),
            "state": record.get("state") or "registered",
            "last_error": record.get("last_error") or "",
            "manifest_sha256": record.get("manifest_sha256") or "",
            "granted_permissions": list(record.get("granted_permissions") or []),
            "secret_bindings": [
                {"name": name, "configured": bool(reference)}
                for name, reference in sorted(
                    (record.get("secret_bindings") or {}).items()
                )
            ],
            "bindings": copy.deepcopy(record.get("bindings") or []),
            "tools": [
                item.get("name")
                for item in manifest.get("contributions") or []
                if item.get("kind") == "tool"
            ],
            "retrievers": [
                item.get("name")
                for item in manifest.get("contributions") or []
                if item.get("kind") == "retriever"
            ],
            "created_at": record.get("created_at") or "",
            "updated_at": record.get("updated_at") or "",
        }


_store: AddonRegistrationStore | None = None
_store_lock = threading.RLock()


def get_addon_store() -> AddonRegistrationStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = AddonRegistrationStore()
        return _store


def set_addon_store(store: AddonRegistrationStore | None) -> None:
    global _store
    with _store_lock:
        _store = store


__all__ = [
    "AddonRegistrationStore",
    "binding_from_dict",
    "get_addon_store",
    "set_addon_store",
]
