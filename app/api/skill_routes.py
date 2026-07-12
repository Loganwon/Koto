# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
skill_routes.py — Skill CRUD & MCP 导出 API Blueprint
======================================================
挂载前缀: /api/skills

端点列表:
  GET    /api/skills                  列出所有 Skill（支持 tag/search 过滤）
  POST   /api/skills                  创建自定义 Skill
  GET    /api/skills/<id>             获取单个 Skill 详情
  PUT    /api/skills/<id>             更新 Skill
  DELETE /api/skills/<id>             删除 Skill（仅自定义）
  POST   /api/skills/<id>/toggle      启用 / 禁用 Skill
  POST   /api/skills/<id>/record      从会话提取 Skill（触发 SkillRecorder）
  GET    /api/skills/mcp              以 MCP 工具格式导出所有启用的 Skill
  GET    /api/skills/stats            每个 Skill 的调用成本统计
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys as _sys
from pathlib import Path
from typing import Dict, Optional

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

skill_bp = Blueprint("skills", __name__, url_prefix="/api/skills")

# ── 路径 ──────────────────────────────────────────────────────────────────────


def _get_base_dir() -> Path:
    if getattr(_sys, "frozen", False):
        return Path(_sys.executable).parent
    return Path(__file__).resolve().parents[2]


_BASE_DIR = _get_base_dir()
_SKILLS_DIR = str(_BASE_DIR / "config" / "skills")


# ── 懒加载辅助 ────────────────────────────────────────────────────────────────


def _sm():
    from app.core.skills.skill_manager import SkillManager

    return SkillManager


def _schema():
    from app.core.skills.skill_schema import InputVariable, OutputSpec, SkillDefinition

    return SkillDefinition, InputVariable, OutputSpec


def _recorder():
    from app.core.skills.skill_recorder import SkillRecorder

    return SkillRecorder


def _binding_manager():
    from app.core.skills.skill_trigger_binding import get_skill_binding_manager

    return get_skill_binding_manager()


def _tracer():
    from app.core.learning.shadow_tracer import ShadowTracer

    return ShadowTracer


def _token_tracker():
    import app.core.analytics.token_tracker as token_tracker

    return token_tracker


# ══════════════════════════════════════════════════════════════════════════════
# GET  /api/skills/<id>/permissions       — 查询 Skill 的权限状态
# POST /api/skills/<id>/permissions       — 授予权限
# DELETE /api/skills/<id>/permissions     — 撤销权限
# ══════════════════════════════════════════════════════════════════════════════


@skill_bp.route("/<skill_id>/permissions", methods=["GET"])
def get_skill_permissions(skill_id: str):
    """返回该 Skill 所需权限及当前授权状态。"""
    try:
        from app.core.skills.skill_permissions import (
            PERMISSION_META,
            SkillPermissionManager,
        )

        sm = _sm()
        skill = sm.get_definition(skill_id)
        if not skill:
            return jsonify({"success": False, "error": "Skill not found"}), 404

        required = list(getattr(skill, "permissions", None) or [])
        granted = SkillPermissionManager.get_granted(skill_id)
        missing = SkillPermissionManager.get_missing(skill_id, required)

        perms_info = []
        for perm in required:
            meta = PERMISSION_META.get(perm, {})
            perms_info.append(
                {
                    "id": perm,
                    "label": meta.get("label", perm),
                    "description": meta.get("description", ""),
                    "risk": meta.get("risk", "unknown"),
                    "granted": perm in granted,
                }
            )

        return jsonify(
            {
                "success": True,
                "skill_id": skill_id,
                "required": required,
                "granted": granted,
                "missing": missing,
                "permissions": perms_info,
            }
        )
    except Exception as e:
        logger.error(f"[skills] get permissions error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@skill_bp.route("/<skill_id>/permissions", methods=["POST"])
def grant_skill_permissions(skill_id: str):
    """为 Skill 授予指定权限列表。Body: {\"permissions\": [\"ui_interactive\", ...]}"""
    try:
        from app.core.skills.skill_permissions import (
            PERMISSION_META,
            SkillPermissionManager,
        )

        body = request.get_json(silent=True) or {}
        perms = body.get("permissions", [])
        if not isinstance(perms, list):
            return (
                jsonify({"success": False, "error": "permissions must be a list"}),
                400,
            )

        unknown = [p for p in perms if p not in PERMISSION_META]
        if unknown:
            return (
                jsonify({"success": False, "error": f"Unknown permissions: {unknown}"}),
                400,
            )

        sm = _sm()
        skill = sm.get_definition(skill_id)
        if not skill:
            return jsonify({"success": False, "error": "Skill not found"}), 404

        for perm in perms:
            SkillPermissionManager.grant(skill_id, perm)

        return jsonify(
            {
                "success": True,
                "skill_id": skill_id,
                "granted": SkillPermissionManager.get_granted(skill_id),
            }
        )
    except Exception as e:
        logger.error(f"[skills] grant permissions error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@skill_bp.route("/<skill_id>/permissions", methods=["DELETE"])
def revoke_skill_permissions(skill_id: str):
    """撤销 Skill 的指定权限列表。Body: {\"permissions\": [\"ui_interactive\", ...]}"""
    try:
        from app.core.skills.skill_permissions import SkillPermissionManager

        body = request.get_json(silent=True) or {}
        perms = body.get("permissions", [])
        if not isinstance(perms, list):
            return (
                jsonify({"success": False, "error": "permissions must be a list"}),
                400,
            )

        sm = _sm()
        skill = sm.get_definition(skill_id)
        if not skill:
            return jsonify({"success": False, "error": "Skill not found"}), 404

        for perm in perms:
            SkillPermissionManager.revoke(skill_id, perm)

        return jsonify(
            {
                "success": True,
                "skill_id": skill_id,
                "granted": SkillPermissionManager.get_granted(skill_id),
            }
        )
    except Exception as e:
        logger.error(f"[skills] revoke permissions error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skills  —  列出所有 Skill
# ══════════════════════════════════════════════════════════════════════════════


@skill_bp.route("", methods=["GET"])
def list_skills():
    """
    查询参数:
      tag     - 按 tag 过滤 (可多次传入)
      search  - 按 name/description 模糊搜索
      enabled - "true"/"false" 过滤启用状态
    """
    tag_filter = request.args.getlist("tag")
    search = request.args.get("search", "").strip().lower()
    enabled_filter = request.args.get("enabled")

    try:
        sm = _sm()
        all_skills = (
            sm.list_skills()
        )  # 返回 List[Dict]，含 name/category/icon/enabled 等 UI 字段

        # 过滤
        result = []
        for s in all_skills:
            if tag_filter and not any(t in s.get("tags", []) for t in tag_filter):
                continue
            if (
                search
                and search not in s.get("name", "").lower()
                and search not in s.get("description", "").lower()
            ):
                continue
            if enabled_filter == "true" and not s.get("enabled", False):
                continue
            if enabled_filter == "false" and s.get("enabled", False):
                continue
            result.append(s)

        return jsonify(
            {
                "success": True,
                "count": len(result),
                "skills": result,
            }
        )
    except Exception as e:
        logger.error(f"[skills] list error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skills/active-ui-config  —  返回当前激活 Skill 的合并 UI 配置
# ══════════════════════════════════════════════════════════════════════════════


@skill_bp.route("/active-ui-config", methods=["GET"])
def get_active_ui_config():
    """
    返回当前所有已启用 Skill 的合并 UI 配置。
    前端用来实现 Skill UI 主题切换、背景特效、占位符变更等。

    响应:
    {
      "success": true,
      "has_ui": bool,
      "config": {
        "theme": str,
        "css_vars": { "--var-name": "value", ... },
        "input_placeholder": str,
        "welcome_text": str,
        "overlay_effect": str,
        "title_text": str,
        "subtitle_text": str,
        "assistant_prefix": str,
        "font_style": str,
        "hide_skill_bar": bool
      },
      "sources": ["skill_id1", ...]
    }
    """
    try:
        sm = _sm()
        result = sm.get_active_ui_config()
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"[skills] active-ui-config error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skills  —  创建自定义 Skill
# ══════════════════════════════════════════════════════════════════════════════


@skill_bp.route("", methods=["POST"])
def create_skill():
    """
    请求体 (JSON):
    {
      "id": str (可选，自动从 name 生成),
      "name": str,
      "description": str,
      "system_prompt": str,
      "tags": [str, ...],
      "input_variables": [{"name": str, "description": str, "required": bool, "example": str}, ...],
      "output_spec": {"format": str, "max_length": int}  (可选)
    }
    """
    data = request.json or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"success": False, "error": "name 不能为空"}), 400

    try:
        SkillDefinition, InputVariable, OutputSpec = _schema()

        # 构建输入变量
        raw_inputs = data.get("input_variables", [])
        if not raw_inputs:
            raw_inputs = [
                {"name": "input", "description": "用户输入", "required": True}
            ]
        input_vars = [
            InputVariable(
                name=iv.get("name", "input"),
                description=iv.get("description", ""),
                required=iv.get("required", True),
                example=iv.get("example", ""),
                type=iv.get("type", "string"),
            )
            for iv in raw_inputs
        ]

        # 输出规格
        raw_out = data.get("output_spec", {})
        out_spec = OutputSpec(
            format=raw_out.get("format", "text"),
            max_chars=int(raw_out.get("max_length", raw_out.get("max_chars", 4000))),
        )

        # Skill ID
        from app.core.skills.skill_recorder import _make_skill_id

        skill_id = data.get("id") or _make_skill_id(name)

        sd = SkillDefinition(
            id=skill_id,
            name=name,
            icon=data.get("icon", "🤖"),
            category=data.get("category", "custom"),
            description=data.get("description", ""),
            version="1.0.0",
            author=data.get("author", "user"),
            tags=data.get("tags", ["general"]),
            input_variables=input_vars,
            system_prompt_template=data.get(
                "system_prompt", f"你是一个专注于「{name}」任务的 AI 助手。"
            ),
            output_spec=out_spec,
        )

        from app.core.skills.skill_recorder import SkillRecorder

        sid = SkillRecorder.save_and_register(sd, overwrite=False)
        return jsonify({"success": True, "skill_id": sid, "skill": sd.to_dict()}), 201

    except FileExistsError as e:
        return jsonify({"success": False, "error": str(e)}), 409
    except Exception as e:
        logger.error(f"[skills] create error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skills/mcp  —  MCP 工具导出（注意：路由顺序在 <id> 之前）
# ══════════════════════════════════════════════════════════════════════════════


@skill_bp.route("/mcp", methods=["GET"])
def export_mcp_tools():
    """导出所有启用 Skill 的 MCP 兼容工具描述列表。"""
    try:
        sm = _sm()
        tools = sm.list_mcp_tools()  # 只返回启用的
        return jsonify(
            {
                "success": True,
                "schema_version": "1.0",
                "tools": tools,
                "count": len(tools),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _compute_perf_score(
    rating_avg: Optional[float],
    approved: int,
    total_calls: int,
) -> float:
    """综合性能得分（0-10），用于排行榜排序。"""
    # 评分分量：0-5 → 0-4 分
    rating_score = ((rating_avg or 3.0) / 5.0) * 4.0
    # 采纳比率分量：approved/max(calls,1) → 0-3 分
    adopt_ratio = approved / max(total_calls, 1)
    adopt_score = min(adopt_ratio * 3.0, 3.0)
    # 调用量对数分量：log10(calls+1) → 0-3 分（1000次调用满分）
    call_score = min(math.log10(total_calls + 1) / 3.0 * 3.0, 3.0)
    return round(rating_score + adopt_score + call_score, 3)


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skills/stats  —  每 Skill 的综合性能分析


@skill_bp.route("/stats", methods=["GET"])
def skill_stats():
    """
    综合 Skill 性能分析：token 成本 + 用户评分 + 影子记录数量 per skill。

    Query params:
      sort    — 排序字段 (rating | calls | cost | approved)，默认 rating
      order   — asc / desc，默认 desc
      min_calls — 最少调用次数过滤（默认 0，不过滤）
    """
    sort_field = request.args.get("sort", "rating")
    order = request.args.get("order", "desc").lower()
    min_calls = int(request.args.get("min_calls", 0))

    # ── 1. Token 成本统计 ─────────────────────────────────────────────────────
    token_stats: dict = {}
    try:
        tt = _token_tracker()
        token_stats = tt.get_skill_stats()
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)

    # ── 2. 影子记录数量 ───────────────────────────────────────────────────────
    trace_counts: dict = {}
    try:
        tracer = _tracer()
        trace_counts = tracer.get_counts()
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)

    # ── 3. 用户评分（从 skill_ratings.json 读取）──────────────────────────────
    ratings: dict = {}
    try:
        ratings_path = _BASE_DIR / "config" / "skill_ratings.json"
        if ratings_path.exists():
            raw = json.loads(ratings_path.read_text(encoding="utf-8"))
            for sid, val in raw.items():
                if isinstance(val, dict):
                    ratings[sid] = {
                        "avg": round(float(val.get("avg", 0)), 2),
                        "count": int(val.get("count", 0)),
                    }
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)

    # ── 4. Skill 元数据（名称 / 类别）────────────────────────────────────────
    skill_meta: dict = {}
    try:
        sm = _sm()
        for s in sm.list_skills():
            skill_meta[s["id"]] = {
                "name": s.get("name", s["id"]),
                "icon": s.get("icon", ""),
                "category": s.get("category", ""),
                "enabled": s.get("enabled", False),
            }
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)

    # ── 5. 合并 ──────────────────────────────────────────────────────────────
    all_ids = set(
        list(token_stats.keys())
        + list(trace_counts.keys())
        + list(ratings.keys())
        + list(skill_meta.keys())
    )
    merged = {}
    for sid in all_ids:
        ts = token_stats.get(sid, {})
        r = ratings.get(sid, {})
        meta = skill_meta.get(sid, {})
        total_calls = int(ts.get("total_calls", 0))
        if total_calls < min_calls:
            continue
        merged[sid] = {
            # 身份信息
            "skill_id": sid,
            "name": meta.get("name", sid),
            "icon": meta.get("icon", ""),
            "category": meta.get("category", ""),
            "enabled": meta.get("enabled", False),
            # 使用量
            "total_calls": total_calls,
            "total_tokens": int(ts.get("total_tokens", 0)),
            "cost_cny": round(float(ts.get("cost_cny", 0.0)), 4),
            # 质量
            "approved_traces": int(trace_counts.get(sid, 0)),
            "rating_avg": r.get("avg", None),
            "rating_count": r.get("count", 0),
            # 综合得分（归一化 0-10：评分×2 + 采纳比率×3 + 调用量对数×2）
            "_score": _compute_perf_score(
                rating_avg=r.get("avg"),
                approved=int(trace_counts.get(sid, 0)),
                total_calls=total_calls,
            ),
        }

    # ── 6. 排序 ──────────────────────────────────────────────────────────────
    _sort_key_map = {
        "rating": lambda x: (x[1].get("rating_avg") or 0),
        "calls": lambda x: x[1].get("total_calls", 0),
        "cost": lambda x: x[1].get("cost_cny", 0),
        "approved": lambda x: x[1].get("approved_traces", 0),
        "score": lambda x: x[1].get("_score", 0),
    }
    _key_fn = _sort_key_map.get(sort_field, _sort_key_map["rating"])
    sorted_items = sorted(merged.items(), key=_key_fn, reverse=(order == "desc"))

    result = [v for _, v in sorted_items]
    # 移除内部评分字段
    for item in result:
        item.pop("_score", None)

    return jsonify({"success": True, "count": len(result), "analytics": result})


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skills/<id>  —  获取单个 Skill
# ══════════════════════════════════════════════════════════════════════════════


@skill_bp.route("/<skill_id>", methods=["GET"])
def get_skill(skill_id: str):
    try:
        sm = _sm()
        sd = sm.get_definition(skill_id)
        if sd is None:
            return (
                jsonify({"success": False, "error": f"Skill '{skill_id}' 不存在"}),
                404,
            )
        return jsonify({"success": True, "skill": sd.to_dict()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# PUT /api/skills/<id>  —  更新 Skill
# ══════════════════════════════════════════════════════════════════════════════


@skill_bp.route("/<skill_id>", methods=["PUT"])
def update_skill(skill_id: str):
    """
    支持部分更新：只需传入要修改的字段。
    可更新: name, description, system_prompt, tags, input_variables, output_spec, examples
    """
    data = request.json or {}
    skill_file = os.path.join(_SKILLS_DIR, f"{skill_id}.json")

    if not os.path.exists(skill_file):
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Skill '{skill_id}' 不存在或非自定义 Skill",
                }
            ),
            404,
        )

    try:
        with open(skill_file, "r", encoding="utf-8") as f:
            existing = json.load(f)

        # 允许更新的字段
        updatable = [
            "name",
            "description",
            "system_prompt",
            "tags",
            "input_variables",
            "output_spec",
            "examples",
            "enabled",
            "author",
            "ui_config",
            "ui_extensions",
            "permissions",
        ]
        for field in updatable:
            if field in data:
                existing[field] = data[field]

        with open(skill_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        # 重新注册到 SkillManager
        SkillDefinition, _, _ = _schema()
        sd = SkillDefinition.from_dict(existing)
        _sm().register_custom(sd)

        return jsonify({"success": True, "skill": existing})
    except Exception as e:
        logger.error(f"[skills] update error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# DELETE /api/skills/<id>  —  删除 Skill（仅自定义）
# ══════════════════════════════════════════════════════════════════════════════


@skill_bp.route("/<skill_id>", methods=["DELETE"])
def delete_skill(skill_id: str):
    skill_file = os.path.join(_SKILLS_DIR, f"{skill_id}.json")
    if not os.path.exists(skill_file):
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Skill '{skill_id}' 不存在或非自定义 Skill",
                }
            ),
            404,
        )

    try:
        os.remove(skill_file)
        # 从 SkillManager registry 移除（如果支持）
        try:
            sm = _sm()
            if hasattr(sm, "_def_registry"):
                sm._def_registry.pop(skill_id, None)
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Silenced exception caught", exc_info=True
            )
        return jsonify({"success": True, "deleted": skill_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skills/<id>/record  —  从会话自动提取 Skill
# ══════════════════════════════════════════════════════════════════════════════


@skill_bp.route("/<skill_id>/toggle", methods=["POST"])
def toggle_skill_v2(skill_id: str):
    """
    前端专用：启用 / 禁用 Skill（内置 + 自定义均支持）。
    请求体: { "enabled": true | false }
    """
    data = request.json or {}
    enabled = bool(data.get("enabled", True))
    try:
        from app.core.skills.skill_mutations import set_skill_enabled

        if not set_skill_enabled(skill_id, enabled):
            return jsonify({"success": False, "error": f"Skill '{skill_id}' 不存在"}), 404
        return jsonify({"success": True, "skill_id": skill_id, "enabled": enabled})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@skill_bp.route("/<skill_id>/prompt", methods=["POST"])
def save_skill_prompt(skill_id: str):
    """
    前端专用：保存用户自定义的 Skill Prompt。
    请求体: { "prompt": str }
    """
    data = request.json or {}
    prompt = data.get("prompt", "")
    try:
        sm = _sm()
        ok = sm.update_prompt(skill_id, prompt)
        if not ok:
            return (
                jsonify({"success": False, "error": f"Skill '{skill_id}' 不存在"}),
                404,
            )
        return jsonify({"success": True, "skill_id": skill_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@skill_bp.route("/<skill_id>/reset", methods=["POST"])
def reset_skill_prompt(skill_id: str):
    """
    前端专用：将 Skill Prompt 恢复为内置默认值。
    """
    try:
        sm = _sm()
        ok = sm.reset_prompt(skill_id)
        if not ok:
            return (
                jsonify({"success": False, "error": f"Skill '{skill_id}' 不存在"}),
                404,
            )
        return jsonify({"success": True, "skill_id": skill_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@skill_bp.route("/<skill_id>/record", methods=["POST"])
def record_from_session(skill_id: str):
    """
    从对话会话自动提取/更新 SkillDefinition。

    请求体:
    {
      "session_id": str,
      "skill_name": str (可选，默认用 skill_id),
      "description": str (可选),
      "overwrite": bool (默认 false)
    }
    """
    data = request.json or {}
    session_id = data.get("session_id", "")
    skill_name = data.get("skill_name") or skill_id
    description = data.get("description", "")
    overwrite = data.get("overwrite", False)

    if not session_id:
        return jsonify({"success": False, "error": "session_id 不能为空"}), 400

    try:
        SkillRecorder = _recorder()
        sd = SkillRecorder.from_conversation(
            session_id=session_id,
            skill_name=skill_name,
            description=description,
        )
        # 强制使用传入的 skill_id
        sd.id = skill_id

        saved_id = SkillRecorder.save_and_register(sd, overwrite=overwrite)
        return jsonify(
            {
                "success": True,
                "skill_id": saved_id,
                "skill": sd.to_dict(),
                "source_session": session_id,
            }
        )
    except FileExistsError as e:
        return (
            jsonify(
                {
                    "success": False,
                    "error": str(e),
                    "hint": "传 overwrite:true 强制覆盖",
                }
            ),
            409,
        )
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except Exception as e:
        logger.error(f"[skills/record] 错误: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skills/bindings  —  列出技能绑定
# ══════════════════════════════════════════════════════════════════════════════


@skill_bp.route("/bindings", methods=["GET"])
def list_bindings():
    """列出所有技能绑定，支持按 skill_id / binding_type 过滤。"""
    skill_id = request.args.get("skill_id")
    binding_type = request.args.get("binding_type")

    try:
        bindings = _binding_manager().list_bindings(
            skill_id=skill_id,
            binding_type=binding_type,
        )
        return jsonify(
            {
                "success": True,
                "count": len(bindings),
                "bindings": [binding.to_dict() for binding in bindings],
            }
        )
    except Exception as e:
        logger.error(f"[skills/bindings] list error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@skill_bp.route("/bindings/bootstrap", methods=["POST"])
def bootstrap_bindings():
    """Seed curated built-in bindings for first-run automation."""
    data = request.json or {}
    force = bool(data.get("force", False))

    try:
        result = _binding_manager().ensure_recommended_bindings(force=force)
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"[skills/bindings/bootstrap] error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skills/<id>/bindings/intent  —  创建意图绑定
# ══════════════════════════════════════════════════════════════════════════════


@skill_bp.route("/<skill_id>/bindings/intent", methods=["POST"])
def bind_skill_intent(skill_id: str):
    """创建一个基于关键词匹配的技能意图绑定。"""
    data = request.json or {}
    patterns = data.get("patterns") or data.get("intent_patterns") or []
    patterns = [str(pattern).strip() for pattern in patterns if str(pattern).strip()]
    if not patterns:
        return jsonify({"success": False, "error": "patterns 不能为空"}), 400

    try:
        sm = _sm()
        if not sm.get_definition(skill_id):
            return (
                jsonify({"success": False, "error": f"Skill '{skill_id}' 不存在"}),
                404,
            )

        binding = _binding_manager().bind_intent(
            skill_id=skill_id,
            intent_patterns=patterns,
            auto_disable_after_turns=int(data.get("auto_disable_after_turns", 3)),
        )
        return jsonify({"success": True, "binding": binding.to_dict()}), 201
    except Exception as e:
        logger.error(f"[skills/bindings/intent] error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skills/<id>/bindings/trigger  —  创建触发器绑定
# ══════════════════════════════════════════════════════════════════════════════


@skill_bp.route("/<skill_id>/bindings/trigger", methods=["POST"])
def bind_skill_trigger(skill_id: str):
    """创建一个调度触发器绑定，并同步注册到 TriggerRegistry。"""
    data = request.json or {}
    trigger_type = str(data.get("trigger_type") or data.get("type") or "").strip()
    if not trigger_type:
        return jsonify({"success": False, "error": "trigger_type 不能为空"}), 400

    try:
        sm = _sm()
        if not sm.get_definition(skill_id):
            return (
                jsonify({"success": False, "error": f"Skill '{skill_id}' 不存在"}),
                404,
            )

        binding = _binding_manager().bind_trigger(
            skill_id=skill_id,
            trigger_type=trigger_type,
            trigger_config=data.get("config") or {},
            mode=data.get("mode", "execute"),
            job_payload=data.get("job_payload") or {},
            name=data.get("name"),
        )
        return jsonify({"success": True, "binding": binding.to_dict()}), 201
    except Exception as e:
        logger.error(f"[skills/bindings/trigger] error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skills/bindings/<id>/toggle  —  启用 / 禁用绑定
# ══════════════════════════════════════════════════════════════════════════════


@skill_bp.route("/bindings/<binding_id>/toggle", methods=["POST"])
def toggle_binding(binding_id: str):
    data = request.json or {}
    enabled = bool(data.get("enabled", True))

    try:
        manager = _binding_manager()
        binding = manager.get(binding_id)
        if not binding:
            return (
                jsonify({"success": False, "error": f"Binding '{binding_id}' 不存在"}),
                404,
            )

        manager.enable(binding_id, enabled)
        updated = manager.get(binding_id)
        return jsonify(
            {"success": True, "binding": updated.to_dict() if updated else None}
        )
    except Exception as e:
        logger.error(f"[skills/bindings/toggle] error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# DELETE /api/skills/bindings/<id>  —  删除绑定
# ══════════════════════════════════════════════════════════════════════════════


@skill_bp.route("/bindings/<binding_id>", methods=["DELETE"])
def delete_binding(binding_id: str):
    try:
        removed = _binding_manager().remove(binding_id)
        if not removed:
            return (
                jsonify({"success": False, "error": f"Binding '{binding_id}' 不存在"}),
                404,
            )
        return jsonify({"success": True, "deleted": binding_id})
    except Exception as e:
        logger.error(f"[skills/bindings/delete] error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skills/usage  —  记录 Skill 使用（前端发起）
# GET  /api/skills/recommendations  —  按使用量返回推荐 Skill 列表
# POST /api/skills/ask-koto  —  让 Koto 为指定任务推荐合适的 Skill
# ══════════════════════════════════════════════════════════════════════════════

import threading as _threading
import time as _time

_USAGE_FILE = _BASE_DIR / "config" / "skill_usage_log.json"
_usage_lock = _threading.Lock()


def _load_usage() -> Dict:
    try:
        if _USAGE_FILE.exists():
            return json.loads(_USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)
    return {}


def _save_usage(data: Dict) -> None:
    try:
        _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _USAGE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_USAGE_FILE)
    except Exception as e:
        logger.warning(f"[skills/usage] save error: {e}")


@skill_bp.route("/usage", methods=["POST"])
def record_skill_usage():
    """
    前端在每次发消息时调用，记录当前激活的 Skill 使用事件。
    请求体: { "skill_ids": ["id1", "id2"], "session_id": "..." }
    """
    data = request.get_json(silent=True) or {}
    skill_ids = data.get("skill_ids", [])
    session_id = data.get("session_id", "")
    if not isinstance(skill_ids, list) or not skill_ids:
        return jsonify({"success": True, "recorded": 0})

    now = int(_time.time())
    with _usage_lock:
        usage = _load_usage()
        for sid in skill_ids:
            if not isinstance(sid, str) or not sid:
                continue
            entry = usage.setdefault(sid, {"total": 0, "last_used": 0, "events": []})
            entry["total"] = entry.get("total", 0) + 1
            entry["last_used"] = now
            # 只保留最近 200 条事件，避免文件无限增大
            events = entry.get("events", [])
            events.append({"ts": now, "session": session_id})
            entry["events"] = events[-200:]
        _save_usage(usage)

    return jsonify({"success": True, "recorded": len(skill_ids)})


@skill_bp.route("/recommendations", methods=["GET"])
def get_skill_recommendations():
    """
    返回推荐 Skill 列表。
    策略：最近使用 + 使用频率综合排序，融合当前所有可用 Skill 信息。
    查询参数: limit (默认 8)
    """
    limit = min(int(request.args.get("limit", 8)), 30)
    try:
        sm = _sm()
        all_skills = sm.list_skills()
        skill_map = {
            s["id"]: s for s in all_skills if not s.get("skill_nature") == "system"
        }

        with _usage_lock:
            usage = _load_usage()

        now = _time.time()
        # 计算每个 skill 的推荐得分: 频率 * 衰减
        scored = []
        for skill_id, info in usage.items():
            if skill_id not in skill_map:
                continue
            total = info.get("total", 0)
            last_used = info.get("last_used", 0)
            age_days = (now - last_used) / 86400.0 if last_used else 9999
            # 半衰期 30 天
            decay = 0.5 ** (age_days / 30.0)
            score = total * decay
            scored.append((skill_id, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        top_ids = [s[0] for s in scored[:limit]]

        # 补全未使用过的高评分 skill（精选列表），凑满 limit 个
        _POPULAR_FALLBACK = [
            "step_by_step",
            "concise_mode",
            "code_best_practices",
            "professional_tone",
            "teaching_mode",
            "deep_think",
        ]
        for fid in _POPULAR_FALLBACK:
            if len(top_ids) >= limit:
                break
            if fid in skill_map and fid not in top_ids:
                top_ids.append(fid)

        result = [skill_map[sid] for sid in top_ids if sid in skill_map]
        return jsonify({"success": True, "skills": result, "total": len(result)})
    except Exception as e:
        logger.error(f"[skills/recommendations] error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@skill_bp.route("/ask-koto", methods=["POST"])
def ask_koto_recommend():
    """
    让 Koto（LLM）根据用户描述的任务，从所有可用 Skill 中挑选最合适的几个。
    请求体: { "task": "帮我分析一份财务报表" }
    返回: { "success": true, "skills": [...], "reasoning": "..." }
    """
    data = request.get_json(silent=True) or {}
    task = (data.get("task") or "").strip()
    if not task:
        return jsonify({"success": False, "error": "task 不能为空"}), 400

    try:
        sm = _sm()
        all_skills = [
            s for s in sm.list_skills() if not s.get("skill_nature") == "system"
        ]

        # 构建 Skill 目录摘要给 LLM
        skill_catalog = "\n".join(
            f"- [{s['id']}] {s.get('icon','🔧')} {s['name']}: {s.get('description','')}"
            for s in all_skills
        )

        prompt = f"""你是 Koto 的 Skill 顾问。用户描述了一个任务，请从下面的 Skill 列表中挑选最合适的 1-4 个 Skill。

## 用户任务
{task}

## 可用 Skill 列表（格式：[id] 图标 名称: 描述）
{skill_catalog}

## 要求
1. 只选真正有帮助的 Skill，不要凑数
2. 以 JSON 格式输出，结构如下（只输出 JSON，不要其他文字）：
{{
  "skill_ids": ["id1", "id2"],
  "reasoning": "简短说明为什么选这几个（≤60字）"
}}"""

        from app.core.llm.provider_factory import get_llm_provider

        client = get_llm_provider(provider="deepseek", allow_local_fallback=False)
        raw = client.generate_content(
            prompt=prompt,
            temperature=0.2,
            max_tokens=400,
        )
        text = raw.get("text", "") if isinstance(raw, dict) else str(raw)
        text = text.strip()
        # 去掉可能的 ```json 包裹
        import re

        if text.startswith("```"):
            text = re.sub(r"^```[\w]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text.strip())

        parsed = json.loads(text)
        recommended_ids = [str(i) for i in (parsed.get("skill_ids") or []) if i]
        reasoning = str(parsed.get("reasoning") or "")

        skill_map = {s["id"]: s for s in all_skills}
        skills_out = [skill_map[sid] for sid in recommended_ids if sid in skill_map]

        return jsonify(
            {
                "success": True,
                "skills": skills_out,
                "reasoning": reasoning,
            }
        )

    except json.JSONDecodeError as e:
        logger.warning(f"[skills/ask-koto] LLM 输出解析失败: {e}")
        return jsonify({"success": False, "error": "AI 返回格式异常，请重试"}), 500
    except Exception as e:
        logger.error(f"[skills/ask-koto] error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
