"""Strict JSON manifest schema and serialization helpers for plugin packages."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from jsonschema import Draft202012Validator

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

PLUGIN_MANIFEST_SCHEMA_ID = "https://koto.ai/schemas/plugin-manifest-v1.json"

_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
_SEMVER_PATTERN = (
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_JSON_SCHEMA = {"type": "object"}

PLUGIN_MANIFEST_JSON_SCHEMA: Mapping[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": PLUGIN_MANIFEST_SCHEMA_ID,
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "plugin_id",
        "version",
        "api_version",
        "name",
        "description",
        "publisher",
        "runtime",
        "permissions",
        "contributions",
        "limits",
        "data_policy",
    ],
    "properties": {
        "schema_version": {"const": PLUGIN_PROTOCOL_VERSION},
        "plugin_id": {"type": "string", "pattern": _ID_PATTERN},
        "version": {"type": "string", "pattern": _SEMVER_PATTERN},
        "api_version": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1, "maxLength": 120},
        "description": {"type": "string", "minLength": 1, "maxLength": 1000},
        "publisher": {"type": "string", "minLength": 1, "maxLength": 200},
        "runtime": {
            "type": "object",
            "additionalProperties": False,
            "required": ["transport", "entrypoint"],
            "properties": {
                "transport": {"enum": [item.value for item in PluginTransport]},
                "entrypoint": {"type": "string", "minLength": 1},
            },
        },
        "permissions": {
            "type": "array",
            "uniqueItems": True,
            "items": {"enum": [item.value for item in PluginPermission]},
        },
        "contributions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "kind",
                    "name",
                    "description",
                    "capabilities",
                    "permissions",
                    "read_only",
                    "input_schema",
                    "output_schema",
                ],
                "properties": {
                    "id": {"type": "string", "pattern": _ID_PATTERN},
                    "kind": {"enum": [item.value for item in ContributionKind]},
                    "name": {"type": "string", "pattern": _ID_PATTERN},
                    "description": {"type": "string", "minLength": 1},
                    "capabilities": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string", "pattern": _ID_PATTERN},
                    },
                    "permissions": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"enum": [item.value for item in PluginPermission]},
                    },
                    "read_only": {"type": "boolean"},
                    "input_schema": _JSON_SCHEMA,
                    "output_schema": _JSON_SCHEMA,
                    "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
                },
            },
        },
        "dependencies": {
            "type": "array",
            "default": [],
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["plugin_id"],
                "properties": {
                    "plugin_id": {"type": "string", "pattern": _ID_PATTERN},
                    "min_version": {"type": "string", "pattern": _SEMVER_PATTERN},
                    "max_version": {"type": "string", "pattern": _SEMVER_PATTERN},
                    "optional": {"type": "boolean"},
                },
            },
        },
        "limits": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "max_timeout_seconds",
                "max_result_bytes",
                "max_concurrency",
                "max_rag_chunks",
            ],
            "properties": {
                "max_timeout_seconds": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": 600,
                },
                "max_result_bytes": {
                    "type": "integer",
                    "minimum": 1024,
                    "maximum": 50_000_000,
                },
                "max_concurrency": {"type": "integer", "minimum": 1, "maximum": 32},
                "max_rag_chunks": {"type": "integer", "minimum": 1, "maximum": 100},
            },
        },
        "data_policy": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "accepts",
                "emits",
                "persistence",
                "retention_days",
                "tenant_isolation",
                "sends_data_external",
            ],
            "properties": {
                "accepts": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"enum": [item.value for item in DataClassification]},
                },
                "emits": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"enum": [item.value for item in DataClassification]},
                },
                "persistence": {"enum": [item.value for item in PersistenceMode]},
                "retention_days": {"type": "integer", "minimum": 0, "maximum": 3650},
                "tenant_isolation": {"type": "boolean"},
                "sends_data_external": {"type": "boolean"},
            },
        },
        "config_schema": _JSON_SCHEMA,
        "secret_names": {
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "string", "pattern": _ID_PATTERN},
        },
    },
}


def manifest_from_dict(data: Mapping[str, Any]) -> PluginManifestV1:
    if not isinstance(data, Mapping):
        raise PluginProtocolError("plugin manifest must be an object")
    payload = dict(data)
    errors = sorted(
        Draft202012Validator(PLUGIN_MANIFEST_JSON_SCHEMA).iter_errors(payload),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        error = errors[0]
        path = ".".join(str(item) for item in error.absolute_path)
        location = f" at '{path}'" if path else ""
        raise PluginProtocolError(f"invalid plugin manifest{location}: {error.message}")

    runtime_data = payload["runtime"]
    limits_data = payload["limits"]
    policy_data = payload["data_policy"]
    contributions = tuple(
        PluginContribution(
            contribution_id=item["id"],
            kind=ContributionKind(item["kind"]),
            name=item["name"],
            description=item["description"],
            capabilities=tuple(item["capabilities"]),
            permissions=tuple(PluginPermission(value) for value in item["permissions"]),
            read_only=bool(item["read_only"]),
            input_schema=item["input_schema"],
            output_schema=item["output_schema"],
            timeout_seconds=item.get("timeout_seconds"),
        )
        for item in payload["contributions"]
    )
    dependencies = tuple(
        PluginDependency(
            plugin_id=item["plugin_id"],
            min_version=item.get("min_version", ""),
            max_version=item.get("max_version", ""),
            optional=bool(item.get("optional", False)),
        )
        for item in payload.get("dependencies", [])
    )
    return PluginManifestV1(
        plugin_id=payload["plugin_id"],
        version=payload["version"],
        api_version=payload["api_version"],
        description=payload["description"],
        schema_version=payload["schema_version"],
        name=payload["name"],
        publisher=payload["publisher"],
        runtime=PluginRuntimeSpec(
            transport=PluginTransport(runtime_data["transport"]),
            entrypoint=runtime_data["entrypoint"],
        ),
        permissions=tuple(PluginPermission(value) for value in payload["permissions"]),
        contributions=contributions,
        dependencies=dependencies,
        limits=PluginLimits(**limits_data),
        data_policy=PluginDataPolicy(
            accepts=tuple(
                DataClassification(value) for value in policy_data["accepts"]
            ),
            emits=tuple(DataClassification(value) for value in policy_data["emits"]),
            persistence=PersistenceMode(policy_data["persistence"]),
            retention_days=policy_data["retention_days"],
            tenant_isolation=policy_data["tenant_isolation"],
            sends_data_external=policy_data["sends_data_external"],
        ),
        config_schema=payload.get(
            "config_schema",
            {"type": "object", "properties": {}, "additionalProperties": False},
        ),
        secret_names=tuple(payload.get("secret_names", [])),
    )


def manifest_to_dict(manifest: PluginManifestV1) -> dict[str, Any]:
    return {
        "schema_version": manifest.schema_version,
        "plugin_id": manifest.plugin_id,
        "version": manifest.version,
        "api_version": manifest.api_version,
        "name": manifest.name,
        "description": manifest.description,
        "publisher": manifest.publisher,
        "runtime": {
            "transport": manifest.runtime.transport.value,
            "entrypoint": manifest.runtime.entrypoint,
        },
        "permissions": [item.value for item in manifest.permissions],
        "contributions": [
            {
                "id": item.contribution_id,
                "kind": item.kind.value,
                "name": item.name,
                "description": item.description,
                "capabilities": list(item.capabilities),
                "permissions": [permission.value for permission in item.permissions],
                "read_only": item.read_only,
                "input_schema": dict(item.input_schema),
                "output_schema": dict(item.output_schema),
                **(
                    {"timeout_seconds": item.timeout_seconds}
                    if item.timeout_seconds is not None
                    else {}
                ),
            }
            for item in manifest.contributions
        ],
        "dependencies": [
            {
                "plugin_id": item.plugin_id,
                **({"min_version": item.min_version} if item.min_version else {}),
                **({"max_version": item.max_version} if item.max_version else {}),
                **({"optional": True} if item.optional else {}),
            }
            for item in manifest.dependencies
        ],
        "limits": {
            "max_timeout_seconds": manifest.limits.max_timeout_seconds,
            "max_result_bytes": manifest.limits.max_result_bytes,
            "max_concurrency": manifest.limits.max_concurrency,
            "max_rag_chunks": manifest.limits.max_rag_chunks,
        },
        "data_policy": {
            "accepts": [item.value for item in manifest.data_policy.accepts],
            "emits": [item.value for item in manifest.data_policy.emits],
            "persistence": manifest.data_policy.persistence.value,
            "retention_days": manifest.data_policy.retention_days,
            "tenant_isolation": manifest.data_policy.tenant_isolation,
            "sends_data_external": manifest.data_policy.sends_data_external,
        },
        "config_schema": dict(manifest.config_schema),
        "secret_names": list(manifest.secret_names),
    }


def manifest_digest(manifest: PluginManifestV1) -> str:
    canonical = json.dumps(
        manifest_to_dict(manifest),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


__all__ = [
    "PLUGIN_MANIFEST_JSON_SCHEMA",
    "PLUGIN_MANIFEST_SCHEMA_ID",
    "manifest_digest",
    "manifest_from_dict",
    "manifest_to_dict",
]
