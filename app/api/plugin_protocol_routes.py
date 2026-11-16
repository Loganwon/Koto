"""HTTP surface for Koto's versioned Add-on integration contract.

This blueprint validates manifests and reports the host-managed Add-on
runtime.  It deliberately does not discover, install or import package code.
"""

from __future__ import annotations

import copy
import logging
import os
import secrets
from typing import Any, Mapping

from flask import Blueprint, jsonify, request

from app.core.agent.plugin_protocol import (
    PLUGIN_MANIFEST_JSON_SCHEMA,
    PLUGIN_MANIFEST_SCHEMA_ID,
    PLUGIN_PROTOCOL_VERSION,
    ContributionKind,
    DataClassification,
    PersistenceMode,
    PluginPermission,
    PluginProtocolError,
    PluginTransport,
    manifest_digest,
    manifest_from_dict,
    manifest_to_dict,
)

logger = logging.getLogger(__name__)

plugin_protocol_bp = Blueprint(
    "plugin_protocol", __name__, url_prefix="/api/plugin-protocol"
)

_MAX_MANIFEST_BYTES = 1_000_000

_PERMISSION_META: Mapping[PluginPermission, Mapping[str, str]] = {
    PluginPermission.WORKSPACE_READ: {
        "label": "读取工作区",
        "description": "读取任务明确提供的工作区文件。",
        "risk": "low",
    },
    PluginPermission.WORKSPACE_WRITE: {
        "label": "修改工作区",
        "description": "创建或修改工作区文件。",
        "risk": "high",
    },
    PluginPermission.NETWORK_EGRESS: {
        "label": "外部网络",
        "description": "向插件声明的外部服务发送请求。",
        "risk": "high",
    },
    PluginPermission.DATABASE_READ: {
        "label": "读取数据库",
        "description": "在租户与访问控制边界内查询数据库。",
        "risk": "medium",
    },
    PluginPermission.DATABASE_WRITE: {
        "label": "写入数据库",
        "description": "新增或修改数据库记录。",
        "risk": "high",
    },
    PluginPermission.MODEL_INVOKE: {
        "label": "调用模型",
        "description": "调用宿主允许的 AI 模型。",
        "risk": "medium",
    },
    PluginPermission.PROCESS_EXECUTE: {
        "label": "执行进程",
        "description": "启动受控的本地进程或命令。",
        "risk": "critical",
    },
    PluginPermission.SECRETS_USE: {
        "label": "使用密钥",
        "description": "按名称使用宿主绑定的密钥，插件不能读取未声明密钥。",
        "risk": "high",
    },
    PluginPermission.USER_NOTIFY: {
        "label": "通知用户",
        "description": "向用户发送任务状态或结果通知。",
        "risk": "medium",
    },
}

_RISK_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _management_denied():
    """Require the operator token for Addon mutations outside desktop mode."""
    auth_enabled = os.environ.get("KOTO_AUTH_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    if not auth_enabled:
        return None
    expected = os.environ.get("KOTO_ADMIN_TOKEN", "")
    supplied = request.headers.get("X-Admin-Token", "")
    if expected and secrets.compare_digest(supplied, expected):
        return None
    return (
        jsonify(
            {"success": False, "error": "Addon management requires admin authorization"}
        ),
        403,
    )


def _example_manifest() -> dict[str, Any]:
    return {
        "schema_version": PLUGIN_PROTOCOL_VERSION,
        "plugin_id": "com.example.knowledge",
        "version": "1.0.0",
        "api_version": "1",
        "name": "Example Knowledge Connector",
        "description": "Read-only example for protocol validation.",
        "publisher": "Example Publisher",
        "runtime": {
            "transport": "in_process",
            "entrypoint": "example.knowledge:Plugin",
        },
        "permissions": ["database.read"],
        "contributions": [
            {
                "id": "knowledge_lookup",
                "kind": "retriever",
                "name": "example_knowledge_lookup",
                "description": "Retrieve access-controlled evidence.",
                "capabilities": ["knowledge.lookup"],
                "permissions": ["database.read"],
                "read_only": True,
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"chunks": {"type": "array"}},
                    "required": ["chunks"],
                    "additionalProperties": False,
                },
                "timeout_seconds": 20,
            }
        ],
        "dependencies": [],
        "limits": {
            "max_timeout_seconds": 30,
            "max_result_bytes": 2_000_000,
            "max_concurrency": 4,
            "max_rag_chunks": 20,
        },
        "data_policy": {
            "accepts": ["internal"],
            "emits": ["internal"],
            "persistence": "none",
            "retention_days": 0,
            "tenant_isolation": True,
            "sends_data_external": False,
        },
        "config_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "secret_names": [],
    }


def _example_registration() -> dict[str, Any]:
    manifest = _example_manifest()
    return {
        "manifest": manifest,
        "bindings": [
            {
                "contribution_name": "example_knowledge_lookup",
                "task_types": ["CHAT", "RESEARCH"],
                "intent_patterns": ["知识库", "历史资料", "查询依据"],
                "file_types": [],
                "priority": 70,
            }
        ],
        "granted_permissions": ["database.read"],
        "config": {},
        "secret_bindings": {},
        "enabled": False,
    }


def _permission_rows(values: Any) -> list[dict[str, str]]:
    rows = []
    for value in values:
        permission = PluginPermission(value)
        meta = _PERMISSION_META[permission]
        rows.append({"id": permission.value, **meta})
    return rows


def _risk_summary(manifest: Any) -> dict[str, Any]:
    permissions = _permission_rows(manifest.permissions)
    factors = [
        {
            "id": item["id"],
            "label": item["label"],
            "risk": item["risk"],
            "description": item["description"],
        }
        for item in permissions
    ]
    if manifest.data_policy.sends_data_external:
        factors.append(
            {
                "id": "data.external",
                "label": "数据发送到外部",
                "risk": "high",
                "description": "数据策略声明会把输入数据发送到外部系统。",
            }
        )
    if not manifest.data_policy.tenant_isolation:
        factors.append(
            {
                "id": "data.no_tenant_isolation",
                "label": "未声明租户隔离",
                "risk": "critical",
                "description": "该声明不适合多租户或银行数据环境。",
            }
        )
    highest = max(
        (item["risk"] for item in factors),
        key=lambda value: _RISK_ORDER[value],
        default="none",
    )
    return {
        "level": highest,
        "factors": factors,
        "external_data": manifest.data_policy.sends_data_external,
        "tenant_isolation": manifest.data_policy.tenant_isolation,
        "persistence": manifest.data_policy.persistence.value,
        "retention_days": manifest.data_policy.retention_days,
    }


@plugin_protocol_bp.route("", methods=["GET"])
@plugin_protocol_bp.route("/", methods=["GET"])
def protocol_status():
    from app.core.agent.addons import addon_system_snapshot

    snapshot = addon_system_snapshot()
    total = int(snapshot["total"])
    return jsonify(
        {
            "success": True,
            "protocol": {
                "name": "Koto Plugin Integration Protocol",
                "version": PLUGIN_PROTOCOL_VERSION,
                "schema_id": PLUGIN_MANIFEST_SCHEMA_ID,
                "status": "contract_ready",
            },
            "runtime": {
                "status": "ready",
                # Koto currently has no package installer.  Objects supplied
                # by host bootstrap can be admitted without being installed
                # by this API.
                "registered_addons": total,
                "admitted_addons": int(snapshot["admitted"]),
                "discovery": "host_allowlist",
                "installation": False,
                "registration": True,
                "execution": True,
                "task_routing": True,
                "enabled_transports": [PluginTransport.IN_PROCESS.value],
            },
            "endpoints": {
                "schema": "/api/plugin-protocol/schema",
                "example": "/api/plugin-protocol/example",
                "validate": "/api/plugin-protocol/validate",
                "catalog": "/api/plugin-protocol/catalog",
                "registrations": "/api/plugin-protocol/registrations",
                "audit": "/api/plugin-protocol/audit",
            },
            "supported": {
                "schema_transports": [item.value for item in PluginTransport],
                "runtime_enabled_transports": [PluginTransport.IN_PROCESS.value],
                "contribution_kinds": [item.value for item in ContributionKind],
                "permissions": _permission_rows(PluginPermission),
                "data_classifications": [item.value for item in DataClassification],
                "persistence_modes": [item.value for item in PersistenceMode],
            },
        }
    )


@plugin_protocol_bp.route("/schema", methods=["GET"])
def protocol_schema():
    return jsonify(
        {
            "success": True,
            "schema_id": PLUGIN_MANIFEST_SCHEMA_ID,
            "schema": copy.deepcopy(dict(PLUGIN_MANIFEST_JSON_SCHEMA)),
        }
    )


@plugin_protocol_bp.route("/example", methods=["GET"])
def protocol_example():
    registration = _example_registration()
    return jsonify(
        {
            "success": True,
            "manifest": registration["manifest"],
            "registration": registration,
        }
    )


@plugin_protocol_bp.route("/catalog", methods=["GET"])
def protocol_catalog():
    """Return persisted registrations and host-admitted runtime Addons."""
    from app.core.agent.addons import addon_system_snapshot

    snapshot = addon_system_snapshot()
    addons = snapshot["addons"]
    return jsonify(
        {
            "success": True,
            "schema_version": "1.0",
            "addons": addons,
            "total": snapshot["total"],
            "admitted": snapshot["admitted"],
            "enabled": snapshot["enabled"],
            "revision": snapshot["revision"],
            "runtime_status": "ready",
            "message": (
                "当前没有已登记的 Addon。"
                if not addons
                else "登记项只有在权限授权和宿主工厂准入后才会进入 Agent。"
            ),
        }
    )


@plugin_protocol_bp.route("/audit", methods=["GET"])
def protocol_audit():
    denied = _management_denied()
    if denied is not None:
        return denied
    from app.core.agent.addons import get_addon_audit_store

    try:
        limit = max(1, min(int(request.args.get("limit", 100)), 1000))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "limit must be an integer"}), 400
    events = get_addon_audit_store().list_events(limit=limit)
    return jsonify({"success": True, "events": events, "total": len(events)})


@plugin_protocol_bp.route("/registrations", methods=["POST"])
def register_addon():
    """Persist a declarative connection request without executing code."""
    from app.core.agent.addons import get_addon_store

    if denied := _management_denied():
        return denied

    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("manifest"), dict):
        return jsonify({"success": False, "error": "manifest is required"}), 400
    try:
        record = get_addon_store().register(
            body["manifest"],
            bindings=body.get("bindings") or (),
            granted_permissions=body.get("granted_permissions") or (),
            config=body.get("config") or {},
            secret_bindings=body.get("secret_bindings") or {},
            # Registration never executes code. Enabling is a separate action.
            enabled=False,
        )
    except (PluginProtocolError, TypeError, ValueError) as exc:
        return (
            jsonify(
                {
                    "success": False,
                    "error": str(exc),
                    "stage": "addon_registration",
                }
            ),
            422,
        )
    return (
        jsonify(
            {
                "success": True,
                "addon": record,
                "stage": "registered_disabled",
                "message": "Addon 已登记但尚未启用，也未执行任何代码。",
            }
        ),
        201,
    )


@plugin_protocol_bp.route("/registrations/<addon_id>", methods=["GET"])
def get_addon_registration(addon_id: str):
    from app.core.agent.addons import get_addon_store

    if denied := _management_denied():
        return denied
    try:
        return jsonify(
            {"success": True, "addon": get_addon_store().public_record(addon_id)}
        )
    except KeyError:
        return jsonify({"success": False, "error": "Addon registration not found"}), 404


@plugin_protocol_bp.route("/registrations/<addon_id>/enabled", methods=["PUT"])
def set_addon_enabled(addon_id: str):
    from app.core.agent.addons import get_addon_store, refresh_addon_runtime

    if denied := _management_denied():
        return denied

    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
        return jsonify({"success": False, "error": "enabled must be a boolean"}), 400
    try:
        get_addon_store().set_enabled(addon_id, body["enabled"])
        report = refresh_addon_runtime()
        record = get_addon_store().public_record(addon_id)
    except KeyError:
        return jsonify({"success": False, "error": "Addon registration not found"}), 404
    if body["enabled"] and addon_id in report.blocked:
        return (
            jsonify(
                {
                    "success": False,
                    "addon": record,
                    "runtime": report.to_dict(),
                    "error": report.blocked[addon_id],
                    "stage": "runtime_admission",
                }
            ),
            409,
        )
    return jsonify(
        {
            "success": True,
            "addon": record,
            "runtime": report.to_dict(),
            "message": (
                "Addon 已启用并进入 Agent。" if body["enabled"] else "Addon 已停用。"
            ),
        }
    )


@plugin_protocol_bp.route("/registrations/<addon_id>", methods=["DELETE"])
def delete_addon_registration(addon_id: str):
    from app.core.agent.addons import get_addon_store, refresh_addon_runtime

    if denied := _management_denied():
        return denied

    store = get_addon_store()
    if not store.remove(addon_id):
        return jsonify({"success": False, "error": "Addon registration not found"}), 404
    report = refresh_addon_runtime()
    return jsonify(
        {
            "success": True,
            "removed": addon_id,
            "runtime": report.to_dict(),
        }
    )


@plugin_protocol_bp.route("/validate", methods=["POST"])
def validate_manifest():
    if request.content_length and request.content_length > _MAX_MANIFEST_BYTES:
        return (
            jsonify(
                {
                    "success": False,
                    "valid": False,
                    "error": "manifest exceeds the 1 MB validation limit",
                }
            ),
            413,
        )
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return (
            jsonify(
                {
                    "success": False,
                    "valid": False,
                    "error": "request body must be a JSON object",
                }
            ),
            400,
        )
    payload = body.get("manifest", body)
    if not isinstance(payload, dict):
        return (
            jsonify(
                {
                    "success": False,
                    "valid": False,
                    "error": "manifest must be a JSON object",
                }
            ),
            400,
        )
    try:
        manifest = manifest_from_dict(payload)
    except (PluginProtocolError, TypeError, ValueError) as exc:
        return (
            jsonify(
                {
                    "success": False,
                    "valid": False,
                    "error": str(exc),
                    "stage": "manifest_validation",
                }
            ),
            422,
        )
    normalized = manifest_to_dict(manifest)
    return jsonify(
        {
            "success": True,
            "valid": True,
            "stage": "manifest_validation",
            "manifest": normalized,
            "digest": manifest_digest(manifest),
            "summary": {
                "plugin_id": manifest.plugin_id,
                "name": manifest.name,
                "version": manifest.version,
                "publisher": manifest.publisher,
                "transport": manifest.runtime.transport.value,
                "permissions": _permission_rows(manifest.permissions),
                "contributions": [
                    {
                        "id": item.contribution_id,
                        "name": item.name,
                        "kind": item.kind.value,
                        "read_only": item.read_only,
                        "capabilities": list(item.capabilities),
                    }
                    for item in manifest.contributions
                ],
                "risk": _risk_summary(manifest),
            },
            "next_step": "manifest_valid_only",
            "message": "Manifest 合法；尚未安装、加载或执行任何插件代码。",
        }
    )


__all__ = ["plugin_protocol_bp"]
