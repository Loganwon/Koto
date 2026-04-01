# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
╔══════════════════════════════════════════════════════════════════╗
║       Koto  ─  Skill Marketplace API Blueprint                   ║
╚══════════════════════════════════════════════════════════════════╝

挂载前缀: /api/skillmarket

端点列表
────────
  GET    /api/skillmarket/catalog           获取完整 Skill 目录（内置+自定义）
  GET    /api/skillmarket/library           用户 Skill 库（已安装/已创建）
  GET    /api/skillmarket/featured          推荐精选 Skill 列表
  GET    /api/skillmarket/search            搜索 Skill（名称/描述/标签/作者）

  POST   /api/skillmarket/auto-build        用自然语言描述自动生成 Skill
  POST   /api/skillmarket/preview-prompt    实时预览生成的 Prompt（不保存）
  POST   /api/skillmarket/from-session      从对话会话提取 Skill 风格

  POST   /api/skillmarket/install           安装一个 Skill（来自 JSON body 或 .kotosk）
  POST   /api/skillmarket/uninstall/<id>    卸载自定义 Skill
  POST   /api/skillmarket/toggle/<id>       启用 / 禁用 Skill
  PUT    /api/skillmarket/edit/<id>         编辑 Skill（名称/描述/prompt）
  POST   /api/skillmarket/duplicate/<id>    克隆一个 Skill

  GET    /api/skillmarket/export/<id>       导出单个 Skill 为 .kotosk 文件
  GET    /api/skillmarket/export-pack       批量导出多个 Skill 为 .kotosk 包
  POST   /api/skillmarket/import            从上传的 .kotosk 文件导入 Skill

  POST   /api/skillmarket/rate/<id>         对 Skill 评分（本地统计）
  GET    /api/skillmarket/stats             全局使用统计
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request, send_file

logger = logging.getLogger(__name__)

marketplace_bp = Blueprint("skillmarket", __name__, url_prefix="/api/skillmarket")

# ── 路径常量 ──────────────────────────────────────────────────────────────────
import sys as _sys

_BASE_DIR = (
    Path(_sys.executable).parent
    if getattr(_sys, "frozen", False)
    else Path(__file__).resolve().parents[2]
)  # project root
_SKILLS_DIR = _BASE_DIR / "config" / "skills"
_RATINGS_FILE = _BASE_DIR / "config" / "skill_ratings.json"
_PACKS_DIR = _BASE_DIR / "config" / "skill_packs"

_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
_PACKS_DIR.mkdir(parents=True, exist_ok=True)


# ── 懒加载辅助 ────────────────────────────────────────────────────────────────
def _sm():
    from app.core.skills.skill_manager import SkillManager

    return SkillManager


def _schema():
    from app.core.skills.skill_schema import InputVariable, OutputSpec, SkillDefinition

    return SkillDefinition, InputVariable, OutputSpec


def _auto_builder():
    from app.core.skills.skill_auto_builder import SkillAutoBuilder, SkillPackager

    return SkillAutoBuilder, SkillPackager


def _recorder():
    from app.core.skills.skill_recorder import SkillRecorder

    return SkillRecorder


# ── 评分持久化 ────────────────────────────────────────────────────────────────
def _load_ratings() -> Dict[str, Any]:
    if _RATINGS_FILE.exists():
        try:
            return json.loads(_RATINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_ratings(data: Dict):
    _RATINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _get_skill_rating(skill_id: str) -> Dict:
    ratings = _load_ratings()
    return ratings.get(skill_id, {"avg": 0.0, "count": 0, "votes": []})


# ── Skill 富化（为前端添加 rating、is_builtin、is_installed 等字段）────────────
def _enrich_skill(skill_dict: Dict, is_builtin: bool = False) -> Dict:
    skill_id = skill_dict.get("id", "")
    rating = _get_skill_rating(skill_id)
    is_installed = is_builtin or (_SKILLS_DIR / f"{skill_id}.json").exists()
    return {
        **skill_dict,
        "is_builtin": is_builtin,
        "is_installed": is_installed,
        "rating": rating.get("avg", 0.0),
        "rating_count": rating.get("count", 0),
    }


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skillmarket/catalog
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/catalog", methods=["GET"])
def get_catalog():
    """
    返回完整 Skill 目录。
    查询参数:
      category    - 按分类过滤 (behavior/style/domain/workflow/custom)
      skill_nature - 按性质过滤 (model_hint/domain_skill/system)
      tag         - 按标签过滤（可多次传入）
      author      - 按作者过滤
    """
    category_filter = request.args.get("category", "").strip().lower()
    nature_filter = request.args.get("skill_nature", "").strip().lower()
    tag_filter = request.args.getlist("tag")
    author_filter = request.args.get("author", "").strip().lower()

    try:
        sm = _sm()
        sm._ensure_init()

        all_skills: List[Dict] = []

        # 内置 Skill（从 SkillManager 读取）
        for skill_id, skill_def in sm._def_registry.items():
            d = skill_def.to_dict()
            # 同步启用状态
            leg = sm._registry.get(skill_id, {})
            d["enabled"] = leg.get("enabled", skill_def.enabled)
            all_skills.append(
                _enrich_skill(d, is_builtin=(d.get("author") == "builtin"))
            )

        # 安全过滤
        result = []
        for s in all_skills:
            if category_filter and s.get("category", "") != category_filter:
                continue
            if nature_filter and s.get("skill_nature", "") != nature_filter:
                continue
            if tag_filter:
                skill_tags = [t.lower() for t in s.get("tags", [])]
                if not any(t.lower() in skill_tags for t in tag_filter):
                    continue
            if author_filter and s.get("author", "").lower() != author_filter:
                continue
            result.append(s)

        # 按性质+分类排序：model_hint 先，domain_skill 后；同性质内按 category 顺序
        nature_order = {"model_hint": 0, "domain_skill": 1, "system": 2}
        cat_order = {"behavior": 0, "style": 1, "domain": 2, "workflow": 3, "custom": 4}
        result.sort(
            key=lambda x: (
                nature_order.get(x.get("skill_nature", ""), 9),
                cat_order.get(x.get("category", ""), 99),
            )
        )

        return jsonify(
            {
                "success": True,
                "total": len(result),
                "skills": result,
            }
        )
    except Exception as e:
        logger.exception("[skillmarket/catalog]")
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skillmarket/library
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/library", methods=["GET"])
def get_library():
    """返回用户自己创建/安装的 Skill 库"""
    try:
        skills = []
        for skill_file in sorted(_SKILLS_DIR.glob("*.json")):
            try:
                data = json.loads(skill_file.read_text(encoding="utf-8"))
                enriched = _enrich_skill(data, is_builtin=False)
                enriched["file_name"] = skill_file.name
                skills.append(enriched)
            except Exception as e:
                logger.warning(f"[library] 解析 {skill_file.name} 失败: {e}")

        return jsonify(
            {
                "success": True,
                "total": len(skills),
                "skills": skills,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skillmarket/featured
# ══════════════════════════════════════════════════════════════════════════════

# 精选推荐列表（静态配置 + 动态评分加权）
_FEATURED_IDS = [
    "step_by_step",
    "teaching_mode",
    "strict_mode",
    "code_best_practices",
    "creative_writing",
    "concise_mode",
    "professional_tone",
    "emoji_assist",
    "data_analysis",
]


@marketplace_bp.route("/featured", methods=["GET"])
def get_featured():
    """返回精选推荐 Skill 列表"""
    try:
        sm = _sm()
        sm._ensure_init()

        featured = []
        for skill_id in _FEATURED_IDS:
            skill_def = sm._def_registry.get(skill_id)
            if skill_def:
                d = skill_def.to_dict()
                leg = sm._registry.get(skill_id, {})
                d["enabled"] = leg.get("enabled", skill_def.enabled)
                featured.append(_enrich_skill(d, is_builtin=True))

        return jsonify({"success": True, "skills": featured})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skillmarket/search
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/search", methods=["GET"])
def search_skills():
    """
    全文搜索 Skill（名称/描述/标签/作者/intent_description）。
    查询参数: q=<搜索词>
    """
    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify({"success": False, "error": "参数 q 不能为空"}), 400

    try:
        sm = _sm()
        sm._ensure_init()

        results = []
        for skill_id, skill_def in sm._def_registry.items():
            d = skill_def.to_dict()
            # 计算匹配度
            score = 0
            search_fields = [
                (d.get("name", ""), 3),
                (d.get("description", ""), 2),
                (" ".join(d.get("tags", [])), 1),
                (d.get("author", ""), 1),
                (d.get("intent_description", ""), 1),
            ]
            for text, weight in search_fields:
                if q in text.lower():
                    score += weight
            if score > 0:
                leg = sm._registry.get(skill_id, {})
                d["enabled"] = leg.get("enabled", skill_def.enabled)
                enriched = _enrich_skill(d, is_builtin=(d.get("author") == "builtin"))
                enriched["_score"] = score
                results.append(enriched)

        results.sort(key=lambda x: x.get("_score", 0), reverse=True)
        for r in results:
            r.pop("_score", None)

        return jsonify(
            {"success": True, "query": q, "total": len(results), "skills": results}
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skillmarket/auto-build
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/auto-build", methods=["POST"])
def auto_build():
    """
    用自然语言描述自动生成 Skill 并保存。

    请求体:
    {
      "name": str,                 技能名称（必填）
      "description": str,          风格描述（必填）
      "icon": str,                 emoji 图标（可选，默认🎭）
      "category": str,             分类（可选，默认 style）
      "author": str,               作者（可选，默认 user）
      "tags": [str, ...],          标签（可选）
      "enabled": bool,             是否立即启用（可选，默认 false）
      "save": bool,                是否保存到 Skill 库（默认 true）
      "formality": float,          手动覆盖维度（0-1，可选）
      "verbosity": float,
      "empathy": float,
      "structure": float,
      "creativity": float,
      "positivity": float,
      "proactivity": float,
      "humor": float,
      "domain": str,
            "personalize": bool,        是否读取 user_profile/memory 做个性化（可选，默认 true）
    }
    """
    data = request.json or {}

    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()

    if not name:
        return jsonify({"success": False, "error": "name 不能为空"}), 400
    if not description:
        return jsonify({"success": False, "error": "description 不能为空"}), 400

    try:
        SkillAutoBuilder, SkillPackager = _auto_builder()
        personalize = bool(data.get("personalize", True))
        personalization_context = (
            SkillAutoBuilder.load_personalization_context() if personalize else None
        )
        personalization_applied = personalize and bool(
            (personalization_context or {}).get("communication_style")
            or (personalization_context or {}).get("memory_hints")
        )

        # 检查是否有手动维度覆盖
        manual_dims = {
            "formality",
            "verbosity",
            "empathy",
            "structure",
            "creativity",
            "positivity",
            "proactivity",
            "humor",
        }
        has_manual = any(k in data for k in manual_dims)

        if has_manual:
            skill = SkillAutoBuilder.from_style_config(
                name=name,
                description=description,
                formality=float(data.get("formality", 0.5)),
                verbosity=float(data.get("verbosity", 0.5)),
                empathy=float(data.get("empathy", 0.5)),
                structure=float(data.get("structure", 0.5)),
                creativity=float(data.get("creativity", 0.3)),
                positivity=float(data.get("positivity", 0.6)),
                proactivity=float(data.get("proactivity", 0.4)),
                humor=float(data.get("humor", 0.2)),
                domain=data.get("domain", "general"),
                icon=data.get("icon", "🎛️"),
                category=data.get("category", "style"),
                author=data.get("author", "user"),
                enabled=bool(data.get("enabled", False)),
                personalize=personalize,
                personalization_context=personalization_context,
            )
        elif data.get("use_ai", False):
            # AI 生成模式：调用 Gemini，失败自动降级为规则引擎
            skill = SkillAutoBuilder.from_ai_description(
                name=name,
                description=description,
                icon=data.get("icon", "🎭"),
                category=data.get("category", "style"),
                author=data.get("author", "user"),
                tags=data.get("tags"),
                enabled=bool(data.get("enabled", False)),
                personalize=personalize,
                personalization_context=personalization_context,
            )
        else:
            skill = SkillAutoBuilder.from_style_description(
                name=name,
                description=description,
                icon=data.get("icon", "🎭"),
                category=data.get("category", "style"),
                author=data.get("author", "user"),
                tags=data.get("tags"),
                enabled=bool(data.get("enabled", False)),
                personalize=personalize,
                personalization_context=personalization_context,
            )

        # 保存到 Skill 库
        if data.get("save", True):
            SkillRecorder = _recorder()
            overwrite = data.get("overwrite", False)
            try:
                SkillRecorder.save_and_register(skill, overwrite=overwrite)
            except FileExistsError:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Skill '{skill.id}' 已存在，传 overwrite:true 覆盖",
                            "skill_id": skill.id,
                        }
                    ),
                    409,
                )

        return (
            jsonify(
                {
                    "success": True,
                    "skill_id": skill.id,
                    "skill": skill.to_dict(),
                    "saved": data.get("save", True),
                    "personalization_applied": personalization_applied,
                }
            ),
            201,
        )

    except Exception as e:
        logger.exception("[skillmarket/auto-build]")
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skillmarket/preview-prompt
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/preview-prompt", methods=["POST"])
def preview_prompt():
    """
    实时预览自动生成的 Prompt（不保存 Skill）。
    前端可在用户输入时实时调用此接口展示预览。
    """
    data = request.json or {}
    name = (data.get("name") or "未命名技能").strip()
    description = (data.get("description") or "").strip()

    try:
        SkillAutoBuilder, _ = _auto_builder()
        personalize = bool(data.get("personalize", True))
        personalization_context = (
            SkillAutoBuilder.load_personalization_context() if personalize else None
        )
        personalization_applied = personalize and bool(
            (personalization_context or {}).get("communication_style")
            or (personalization_context or {}).get("memory_hints")
        )
        result = SkillAutoBuilder.preview_prompt(
            name=name,
            description=description,
            formality=float(data.get("formality", 0.5)),
            verbosity=float(data.get("verbosity", 0.5)),
            empathy=float(data.get("empathy", 0.5)),
            structure=float(data.get("structure", 0.5)),
            creativity=float(data.get("creativity", 0.3)),
            positivity=float(data.get("positivity", 0.6)),
            proactivity=float(data.get("proactivity", 0.4)),
            humor=float(data.get("humor", 0.2)),
            domain=data.get("domain", "general"),
            personalize=personalize,
            personalization_context=personalization_context,
        )
        return jsonify(
            {
                "success": True,
                "personalization_applied": personalization_applied,
                **result,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skillmarket/from-session
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/from-session", methods=["POST"])
def from_session():
    """
    从对话会话自动提取 Skill 风格。
    请求体: { "session_id": str, "name": str, "description": str, "save": bool }
    """
    data = request.json or {}
    session_id = (data.get("session_id") or "").strip()
    name = (data.get("name") or "").strip()

    if not session_id:
        return jsonify({"success": False, "error": "session_id 不能为空"}), 400
    if not name:
        return jsonify({"success": False, "error": "name 不能为空"}), 400

    try:
        SkillAutoBuilder, _ = _auto_builder()
        skill = SkillAutoBuilder.from_conversation_history(
            session_id=session_id,
            name=name,
            description=data.get("description", ""),
            icon=data.get("icon", "💬"),
            category=data.get("category", "style"),
            author=data.get("author", "user"),
        )

        if data.get("save", True):
            SkillRecorder = _recorder()
            try:
                SkillRecorder.save_and_register(
                    skill, overwrite=data.get("overwrite", False)
                )
            except FileExistsError:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Skill '{skill.id}' 已存在，传 overwrite:true 覆盖",
                        }
                    ),
                    409,
                )

        return (
            jsonify(
                {
                    "success": True,
                    "skill_id": skill.id,
                    "skill": skill.to_dict(),
                    "source_session": session_id,
                }
            ),
            201,
        )

    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except Exception as e:
        logger.exception("[skillmarket/from-session]")
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skillmarket/install
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/install", methods=["POST"])
def install_skill():
    """
    安装一个 Skill。支持两种方式：
    1. JSON body 包含完整 SkillDefinition
    2. multipart/form-data 上传 .kotosk 文件（自动解包）
    """
    try:
        SkillDefinition, _, _ = _schema()
        SkillRecorder = _recorder()

        # 方式 1：JSON body
        if request.is_json:
            data = request.json or {}
            if not data.get("id") or not data.get("name"):
                return jsonify({"success": False, "error": "id 和 name 不能为空"}), 400
            skill = SkillDefinition.from_dict(data)
            overwrite = data.pop("_overwrite", False)
            sid = SkillRecorder.save_and_register(skill, overwrite=overwrite)
            return (
                jsonify({"success": True, "skill_id": sid, "skill": skill.to_dict()}),
                201,
            )

        # 方式 2：文件上传
        file = request.files.get("file")
        if not file:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "需要提供 JSON body 或上传 .kotosk 文件",
                    }
                ),
                400,
            )

        filename = file.filename or ""
        if not filename.endswith(".kotosk"):
            return jsonify({"success": False, "error": "仅支持 .kotosk 文件"}), 400

        _, SkillPackager = _auto_builder()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".kotosk")
        file.save(tmp.name)
        tmp.close()

        try:
            manifest, skills = SkillPackager.unpack(tmp.name)
        finally:
            os.unlink(tmp.name)

        installed = []
        errors = []
        for skill in skills:
            try:
                SkillRecorder.save_and_register(skill, overwrite=False)
                installed.append(skill.id)
            except FileExistsError:
                errors.append(f"'{skill.id}' 已存在（跳过）")
            except Exception as e:
                errors.append(f"'{skill.id}' 失败: {e}")

        return (
            jsonify(
                {
                    "success": True,
                    "manifest": manifest,
                    "installed": installed,
                    "skipped_errors": errors,
                }
            ),
            201,
        )

    except Exception as e:
        logger.exception("[skillmarket/install]")
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skillmarket/uninstall/<id>
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/uninstall/<skill_id>", methods=["POST", "DELETE"])
def uninstall_skill(skill_id: str):
    """卸载自定义 Skill（内置 Skill 不可删除）"""
    sm = _sm()
    sm._ensure_init()

    # 检查是否内置
    skill_def = sm._def_registry.get(skill_id)
    if skill_def and getattr(skill_def, "author", "") == "builtin":
        return (
            jsonify(
                {
                    "success": False,
                    "error": "内置 Skill 不可卸载，可以禁用它",
                }
            ),
            400,
        )

    skill_file = _SKILLS_DIR / f"{skill_id}.json"
    if not skill_file.exists():
        return jsonify({"success": False, "error": f"Skill '{skill_id}' 不存在"}), 404

    try:
        skill_file.unlink()
        sm._def_registry.pop(skill_id, None)
        sm._registry.pop(skill_id, None)
        return jsonify({"success": True, "uninstalled": skill_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skillmarket/toggle/<id>
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/toggle/<skill_id>", methods=["POST"])
def toggle_skill(skill_id: str):
    """启用或禁用 Skill。请求体: { "enabled": bool }"""
    data = request.json or {}
    enabled = bool(data.get("enabled", True))

    sm = _sm()
    success = sm.set_enabled(skill_id, enabled)

    if not success:
        return jsonify({"success": False, "error": f"Skill '{skill_id}' 不存在"}), 404

    # 同步更新自定义 Skill 文件（内置 Skill 状态存 user_settings.json，已由 set_enabled 处理）
    skill_file = _SKILLS_DIR / f"{skill_id}.json"
    if skill_file.exists():
        try:
            d = json.loads(skill_file.read_text(encoding="utf-8"))
            d["enabled"] = enabled
            skill_file.write_text(
                json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"[toggle] 同步文件失败: {e}")

    return jsonify({"success": True, "skill_id": skill_id, "enabled": enabled})


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skillmarket/disable_all
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/disable_all", methods=["POST"])
def disable_all_skills():
    """一键关闭所有当前已启用的 Skill（system 性质的除外）。"""
    sm = _sm()
    sm._ensure_init()

    disabled = []
    for skill_id, s in sm._registry.items():
        if s.get("skill_nature") == "system":
            continue
        if s.get("enabled", False):
            sm.set_enabled(skill_id, False)
            # 同步自定义 Skill 文件
            skill_file = _SKILLS_DIR / f"{skill_id}.json"
            if skill_file.exists():
                try:
                    d = json.loads(skill_file.read_text(encoding="utf-8"))
                    d["enabled"] = False
                    skill_file.write_text(
                        json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                except Exception as e:
                    logger.warning(f"[disable_all] 同步文件失败 {skill_id}: {e}")
            disabled.append(skill_id)

    return jsonify(
        {"success": True, "disabled_count": len(disabled), "disabled": disabled}
    )


# ══════════════════════════════════════════════════════════════════════════════
# PUT /api/skillmarket/edit/<id>
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/edit/<skill_id>", methods=["PUT"])
def edit_skill(skill_id: str):
    """
    编辑自定义 Skill 的可更新字段。
    可更新: name, description, icon, system_prompt_template, tags, input_variables, output_spec
    内置 Skill 不可修改。
    """
    sm = _sm()
    sm._ensure_init()

    skill_def = sm._def_registry.get(skill_id)
    if skill_def and getattr(skill_def, "author", "") == "builtin":
        return (
            jsonify(
                {
                    "success": False,
                    "error": "内置 Skill 不可直接修改。请先使用「克隆」功能创建副本",
                }
            ),
            400,
        )

    skill_file = _SKILLS_DIR / f"{skill_id}.json"
    if not skill_file.exists():
        return jsonify({"success": False, "error": f"Skill '{skill_id}' 不存在"}), 404

    try:
        data = request.json or {}
        existing = json.loads(skill_file.read_text(encoding="utf-8"))

        editable = [
            "name",
            "description",
            "icon",
            "system_prompt_template",
            "prompt",
            "tags",
            "input_variables",
            "output_spec",
            "intent_description",
            "task_types",
            "bound_tools",
        ]
        changed = False
        for field in editable:
            if field in data:
                existing[field] = data[field]
                changed = True

        if not changed:
            return (
                jsonify({"success": False, "error": "请提供至少一个可更新的字段"}),
                400,
            )

        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        skill_file.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 重新注册到 SkillManager
        SkillDefinition, _, _ = _schema()
        updated_def = SkillDefinition.from_dict(existing)
        sm.register_custom(updated_def)

        return jsonify({"success": True, "skill": existing})
    except Exception as e:
        logger.exception("[skillmarket/edit]")
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skillmarket/duplicate/<id>
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/duplicate/<skill_id>", methods=["POST"])
def duplicate_skill(skill_id: str):
    """
    克隆一个 Skill（内置或自定义），生成新 ID 的副本。
    请求体: { "new_name": str (可选), "author": str (可选) }
    """
    sm = _sm()
    sm._ensure_init()

    skill_def = sm._def_registry.get(skill_id)
    if not skill_def:
        return jsonify({"success": False, "error": f"Skill '{skill_id}' 不存在"}), 404

    data = request.json or {}
    new_name = data.get("new_name") or f"{skill_def.name}（副本）"
    new_author = data.get("author", "user")

    try:
        import copy

        new_def = copy.deepcopy(skill_def)
        new_def.name = new_name
        new_def.author = new_author

        # 生成新 ID（防止与原始冲突）
        from app.core.skills.skill_auto_builder import _make_skill_id

        base_id = _make_skill_id(new_name)
        new_id = base_id
        counter = 1
        while sm._def_registry.get(new_id) or (_SKILLS_DIR / f"{new_id}.json").exists():
            new_id = f"{base_id}_{counter}"
            counter += 1
        new_def.id = new_id
        new_def.created_at = datetime.now(timezone.utc).isoformat()

        SkillRecorder = _recorder()
        SkillRecorder.save_and_register(new_def, overwrite=False)

        return (
            jsonify(
                {"success": True, "new_skill_id": new_id, "skill": new_def.to_dict()}
            ),
            201,
        )
    except Exception as e:
        logger.exception("[skillmarket/duplicate]")
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skillmarket/export/<id>
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/export/<skill_id>", methods=["GET"])
def export_skill(skill_id: str):
    """导出单个 Skill 为 .kotosk 文件（附带 README）"""
    sm = _sm()
    sm._ensure_init()
    skill_def = sm._def_registry.get(skill_id)
    if not skill_def:
        return jsonify({"success": False, "error": f"Skill '{skill_id}' 不存在"}), 404

    try:
        _, SkillPackager = _auto_builder()
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".kotosk", prefix=f"koto_{skill_id}_"
        ) as tmp:
            tmp_path = tmp.name

        readme = (
            f"# {skill_def.name}\n\n"
            f"**作者:** {skill_def.author}\n"
            f"**版本:** {skill_def.version}\n\n"
            f"## 描述\n{skill_def.description}\n\n"
            f"## 意图\n{skill_def.intent_description or '未设置'}\n"
        )
        SkillPackager.pack(
            skills=[skill_def],
            output_path=tmp_path,
            pack_name=skill_def.name,
            author=skill_def.author,
            description=skill_def.description,
            readme=readme,
        )

        return send_file(
            tmp_path,
            as_attachment=True,
            download_name=f"{skill_id}.kotosk",
            mimetype="application/zip",
        )
    except Exception as e:
        logger.exception("[skillmarket/export]")
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skillmarket/export-pack
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/export-pack", methods=["GET"])
def export_pack():
    """
    批量导出多个 Skill 为 .kotosk 包。
    查询参数: ids=id1,id2,id3 或 ids[]=id1&ids[]=id2
    """
    ids_csv = request.args.get("ids", "")
    ids_list = request.args.getlist("ids[]")
    if ids_csv:
        ids_list = ids_csv.split(",")
    ids_list = [i.strip() for i in ids_list if i.strip()]

    if not ids_list:
        return (
            jsonify(
                {"success": False, "error": "请通过 ids 或 ids[] 指定要导出的 Skill ID"}
            ),
            400,
        )

    sm = _sm()
    sm._ensure_init()

    skills_to_pack = []
    missing = []
    for sid in ids_list:
        skill_def = sm._def_registry.get(sid)
        if skill_def:
            skills_to_pack.append(skill_def)
        else:
            missing.append(sid)

    if not skills_to_pack:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "未找到任何指定的 Skill",
                    "missing": missing,
                }
            ),
            404,
        )

    try:
        _, SkillPackager = _auto_builder()
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".kotosk", prefix="koto_pack_"
        ) as tmp:
            tmp_path = tmp.name

        pack_name = request.args.get(
            "pack_name", f"koto-skill-pack-{len(skills_to_pack)}"
        )
        SkillPackager.pack(
            skills=skills_to_pack,
            output_path=tmp_path,
            pack_name=pack_name,
            author="exported",
            description=f"包含 {len(skills_to_pack)} 个 Skill 的导出包",
        )

        return send_file(
            tmp_path,
            as_attachment=True,
            download_name=f"{pack_name}.kotosk",
            mimetype="application/zip",
        )
    except Exception as e:
        logger.exception("[skillmarket/export-pack]")
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skillmarket/import
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/import", methods=["POST"])
def import_pack():
    """
    从上传的 .kotosk 文件导入 Skill。
    multipart/form-data: file=<.kotosk 文件>
    """
    file = request.files.get("file")
    if not file:
        return jsonify({"success": False, "error": "请上传 .kotosk 文件"}), 400

    filename = file.filename or ""
    if not filename.endswith(".kotosk"):
        return jsonify({"success": False, "error": "仅支持 .kotosk 文件格式"}), 400

    try:
        _, SkillPackager = _auto_builder()
        SkillRecorder = _recorder()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".kotosk") as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        try:
            manifest, skills = SkillPackager.unpack(tmp_path)
        finally:
            os.unlink(tmp_path)

        overwrite = str(request.form.get("overwrite", "false")).lower() == "true"
        installed, skipped, errors_list = [], [], []

        for skill in skills:
            try:
                SkillRecorder.save_and_register(skill, overwrite=overwrite)
                installed.append(skill.id)
            except FileExistsError:
                skipped.append(skill.id)
            except Exception as e:
                errors_list.append({"id": skill.id, "error": str(e)})

        return jsonify(
            {
                "success": True,
                "manifest": manifest,
                "installed": installed,
                "skipped": skipped,
                "errors": errors_list,
                "total": len(skills),
            }
        )
    except Exception as e:
        logger.exception("[skillmarket/import]")
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skillmarket/rate/<id>
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/rate/<skill_id>", methods=["POST"])
def rate_skill(skill_id: str):
    """
    对 Skill 进行本地评分（1-5 星）。
    请求体: { "score": int (1-5), "comment": str (可选) }
    """
    data = request.json or {}
    score = int(data.get("score", 0))
    if not 1 <= score <= 5:
        return jsonify({"success": False, "error": "score 必须在 1-5 之间"}), 400

    try:
        ratings = _load_ratings()
        entry = ratings.get(skill_id, {"avg": 0.0, "count": 0, "votes": []})
        entry["votes"].append(
            {
                "score": score,
                "comment": data.get("comment", ""),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        total = sum(v["score"] for v in entry["votes"])
        entry["count"] = len(entry["votes"])
        entry["avg"] = round(total / entry["count"], 2)
        ratings[skill_id] = entry
        _save_ratings(ratings)

        return jsonify(
            {
                "success": True,
                "skill_id": skill_id,
                "avg": entry["avg"],
                "count": entry["count"],
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skillmarket/stats
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/stats", methods=["GET"])
def get_stats():
    """全局统计：Skill 数量、分类分布、评分分布"""
    try:
        sm = _sm()
        sm._ensure_init()

        total = len(sm._def_registry)
        by_category: Dict[str, int] = {}
        builtin_count = 0
        custom_count = 0
        enabled_count = 0

        for sid, skill_def in sm._def_registry.items():
            cat = getattr(skill_def, "category", "unknown")
            cat_str = cat.value if hasattr(cat, "value") else str(cat)
            by_category[cat_str] = by_category.get(cat_str, 0) + 1

            if getattr(skill_def, "author", "") == "builtin":
                builtin_count += 1
            else:
                custom_count += 1

            leg = sm._registry.get(sid, {})
            if leg.get("enabled", skill_def.enabled):
                enabled_count += 1

        ratings = _load_ratings()
        avg_rating = 0.0
        if ratings:
            avg_rating = round(
                sum(v.get("avg", 0) for v in ratings.values()) / len(ratings), 2
            )

        return jsonify(
            {
                "success": True,
                "total_skills": total,
                "builtin_skills": builtin_count,
                "custom_skills": custom_count,
                "enabled_skills": enabled_count,
                "by_category": by_category,
                "avg_rating": avg_rating,
                "rated_count": len(ratings),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skillmarket/suggest   —   智能 Skill 推荐
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/suggest", methods=["GET"])
def suggest_skills():
    """
    根据用户当前输入推荐最相关的未启用 Skill。

    查询参数:
      q          - 用户输入文本（必填）
      task_type  - 任务类型 (CHAT / CODER / RESEARCH …)
      top_k      - 返回数量（默认 3）
      all        - "true" 时也包含已启用的 Skill

    示例:
      GET /api/skillmarket/suggest?q=帮我写一份专业的商务报告&task_type=CHAT
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"success": False, "error": "参数 q 不能为空"}), 400

    task_type = request.args.get("task_type", None)
    top_k = min(int(request.args.get("top_k", 3)), 10)
    include_enabled = request.args.get("all", "false").lower() == "true"

    try:
        sm = _sm()
        suggestions = sm.suggest_skills(
            user_input=q,
            task_type=task_type,
            top_k=top_k,
            exclude_enabled=(not include_enabled),
        )
        return jsonify(
            {
                "success": True,
                "query": q,
                "count": len(suggestions),
                "suggestions": suggestions,
            }
        )
    except Exception as e:
        logger.exception("[skillmarket/suggest]")
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skillmarket/check-conflicts/<id>   —   冲突检测
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/check-conflicts/<skill_id>", methods=["GET"])
def check_conflicts(skill_id: str):
    """
    检测启用某个 Skill 是否会与当前已启用 Skill 产生冲突。

    响应示例:
    {
      "has_conflict": true,
      "hard_conflicts": [{"id": "concise_mode", "name": "精简模式", "reason": "..."}],
      "soft_conflicts": []
    }
    """
    try:
        sm = _sm()
        result = sm.detect_conflicts(skill_id)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skillmarket/validate-response   —   对 AI 回复做 Skill OutputSpec 验收
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/validate-response", methods=["POST"])
def validate_response():
    """
    对一段 AI 生成的回复文本，检验所有当前激活 Skill 的 OutputSpec 约束。

    请求体:
    {
      "text": str,          AI 回复文本（必填）
      "task_type": str      任务类型（可选）
    }

    响应:
    {
      "all_passed": bool,
      "results": [{"skill_id", "skill_name", "passed", "reason"}, ...]
    }
    """
    data = request.json or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"success": False, "error": "text 不能为空"}), 400

    try:
        sm = _sm()
        result = sm.validate_response(text, task_type=data.get("task_type"))
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skillmarket/status   —   Skill 库状态摘要（供 UI 面板使用）
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/status", methods=["GET"])
def skill_status():
    """
    返回 Skill 库运行时状态：总数、启用数、自定义数、当前激活名称列表等。
    """
    try:
        sm = _sm()
        summary = sm.get_status_summary()
        return jsonify({"success": True, **summary})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# ── Manifest v2  更新 / 回滚 / 依赖树 / 验证 (Skill 生命周期) ─────────────────
# ══════════════════════════════════════════════════════════════════════════════

_ROLLBACK_DIR = _BASE_DIR / "config" / "skills" / "_rollback"
_ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)


def _compare_versions(v1: str, v2: str) -> int:
    """简单版本比较：v1 > v2 → 1；== → 0；< → -1。"""

    def _parts(v: str):
        try:
            return [int(x) for x in v.strip().lstrip("v").split(".")]
        except Exception:
            return [0]

    for a, b in zip(_parts(v1), _parts(v2)):
        if a > b:
            return 1
        if a < b:
            return -1
    return len(_parts(v1)) - len(_parts(v2))


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skillmarket/check-updates
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/check-updates", methods=["POST"])
def check_updates():
    """
    检查所有已安装自定义 Skill 的可用更新。
    对每个有 update_url 字段的 Skill，发起 HTTPS GET 获取最新 manifest，
    对比版本号后返回有更新的列表。
    """
    import ssl
    import urllib.request

    sm = _sm()
    sm._ensure_init()

    updates_available = []
    errors = []

    for skill_id, skill_def in sm._def_registry.items():
        update_url = getattr(skill_def, "update_url", "") or ""
        if not update_url:
            continue
        # 安全：仅允许 HTTPS
        if not update_url.startswith("https://"):
            errors.append({"skill_id": skill_id, "error": "update_url 必须使用 HTTPS"})
            continue
        try:
            ctx = ssl.create_default_context()
            req = urllib.request.Request(
                update_url,
                headers={"User-Agent": "koto-skill-updater/1.0"},
            )
            with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
                remote = json.loads(resp.read().decode("utf-8"))
            remote_version = remote.get("version", "0.0.0")
            current_version = getattr(skill_def, "version", "0.0.0") or "0.0.0"
            if _compare_versions(remote_version, current_version) > 0:
                updates_available.append(
                    {
                        "skill_id": skill_id,
                        "name": skill_def.name,
                        "current_version": current_version,
                        "latest_version": remote_version,
                        "update_url": update_url,
                        "changelog": remote.get("changelog", ""),
                    }
                )
        except Exception as exc:
            errors.append({"skill_id": skill_id, "error": str(exc)})

    return jsonify(
        {
            "success": True,
            "updates_available": len(updates_available),
            "updates": updates_available,
            "errors": errors,
        }
    )


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skillmarket/update/<id>
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/update/<skill_id>", methods=["POST"])
def update_skill(skill_id: str):
    """
    从 update_url 拉取最新版本并安装（先备份当前版本以支持回滚）。
    Body (可选): { "force": true }
    """
    import ssl
    import urllib.request

    sm = _sm()
    sm._ensure_init()

    skill_def = sm._def_registry.get(skill_id)
    if not skill_def:
        return jsonify({"success": False, "error": f"Skill '{skill_id}' 不存在"}), 404
    if getattr(skill_def, "author", "") == "builtin":
        return jsonify({"success": False, "error": "内置 Skill 不支持自动更新"}), 400

    update_url = getattr(skill_def, "update_url", "") or ""
    if not update_url:
        return jsonify({"success": False, "error": "该 Skill 未设置 update_url"}), 400
    if not update_url.startswith("https://"):
        return jsonify({"success": False, "error": "update_url 必须使用 HTTPS"}), 400

    data_body = request.get_json(silent=True) or {}
    force = bool(data_body.get("force", False))

    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(
            update_url,
            headers={"User-Agent": "koto-skill-updater/1.0"},
        )
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            remote_data = json.loads(resp.read().decode("utf-8"))

        remote_version = remote_data.get("version", "0.0.0")
        current_version = getattr(skill_def, "version", "0.0.0") or "0.0.0"

        if not force and _compare_versions(remote_version, current_version) <= 0:
            return jsonify(
                {
                    "success": True,
                    "updated": False,
                    "message": f"当前已是最新版本 ({current_version})",
                }
            )

        # 备份当前版本
        skill_file = _SKILLS_DIR / f"{skill_id}.json"
        if skill_file.exists():
            backup = _ROLLBACK_DIR / f"{skill_id}_v{current_version}.json"
            backup.write_text(skill_file.read_text(encoding="utf-8"), encoding="utf-8")

        remote_data["id"] = skill_id
        skill_file.write_text(
            json.dumps(remote_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        SkillDefinition, _, _ = _schema()
        sm.register_custom(SkillDefinition.from_dict(remote_data))

        return jsonify(
            {
                "success": True,
                "updated": True,
                "skill_id": skill_id,
                "from_version": current_version,
                "to_version": remote_version,
            }
        )
    except Exception as exc:
        logger.exception("[skillmarket/update/%s]", skill_id)
        return jsonify({"success": False, "error": str(exc)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skillmarket/rollback/<id>
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/rollback/<skill_id>", methods=["POST"])
def rollback_skill(skill_id: str):
    """
    回滚 Skill 到上一个备份版本。
    Body (可选): { "version": "1.0.0" }
    """
    sm = _sm()
    sm._ensure_init()

    skill_def = sm._def_registry.get(skill_id)
    if not skill_def:
        return jsonify({"success": False, "error": f"Skill '{skill_id}' 不存在"}), 404

    data_body = request.get_json(silent=True) or {}
    target_version = data_body.get("version")

    backups = sorted(_ROLLBACK_DIR.glob(f"{skill_id}_v*.json"), reverse=True)
    if not backups:
        return jsonify({"success": False, "error": "无可用的回滚备份"}), 404

    if target_version:
        match = _ROLLBACK_DIR / f"{skill_id}_v{target_version}.json"
        if not match.exists():
            available = [b.stem.split("_v", 1)[-1] for b in backups]
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"未找到版本 {target_version} 的备份",
                        "available_versions": available,
                    }
                ),
                404,
            )
        backup_file = match
    else:
        backup_file = backups[0]

    try:
        backup_data = json.loads(backup_file.read_text(encoding="utf-8"))
        skill_file = _SKILLS_DIR / f"{skill_id}.json"
        current_version = getattr(skill_def, "version", "unknown") or "unknown"

        if skill_file.exists():
            pre = _ROLLBACK_DIR / f"{skill_id}_v{current_version}_pre_rollback.json"
            pre.write_text(skill_file.read_text(encoding="utf-8"), encoding="utf-8")

        skill_file.write_text(
            json.dumps(backup_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        SkillDefinition, _, _ = _schema()
        sm.register_custom(SkillDefinition.from_dict(backup_data))

        return jsonify(
            {
                "success": True,
                "skill_id": skill_id,
                "rolled_back_to": backup_data.get("version", "unknown"),
                "previous_version": current_version,
            }
        )
    except Exception as exc:
        logger.exception("[skillmarket/rollback/%s]", skill_id)
        return jsonify({"success": False, "error": str(exc)}), 500


@marketplace_bp.route("/rollback/<skill_id>/history", methods=["GET"])
def rollback_history(skill_id: str):
    """列出某个 Skill 的所有可回滚备份版本。"""
    backups = sorted(_ROLLBACK_DIR.glob(f"{skill_id}_v*.json"), reverse=True)
    result = []
    for b in backups:
        try:
            d = json.loads(b.read_text(encoding="utf-8"))
            result.append(
                {
                    "version": d.get("version", "unknown"),
                    "backup_file": b.name,
                    "updated_at": d.get("updated_at", ""),
                    "name": d.get("name", skill_id),
                }
            )
        except Exception:
            result.append({"backup_file": b.name, "error": "无法解析"})
    return jsonify({"skill_id": skill_id, "backups": result})


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skillmarket/dependencies/<id>
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/dependencies/<skill_id>", methods=["GET"])
def get_dependencies(skill_id: str):
    """
    返回指定 Skill 的依赖树（manifest v2 `dependencies` 字段），最深 3 层。
    """
    sm = _sm()
    sm._ensure_init()

    def _resolve(sid: str, depth: int = 0) -> Dict:
        if depth > 3:
            return {"id": sid, "error": "超过最大递归深度"}
        skill = sm._def_registry.get(sid)
        if not skill:
            return {"id": sid, "installed": False}
        deps = list(getattr(skill, "dependencies", None) or [])
        return {
            "id": sid,
            "name": skill.name,
            "version": getattr(skill, "version", ""),
            "installed": True,
            "enabled": sm._registry.get(sid, {}).get("enabled", skill.enabled),
            "dependencies": [_resolve(d, depth + 1) for d in deps],
        }

    if not sm._def_registry.get(skill_id):
        return jsonify({"success": False, "error": f"Skill '{skill_id}' 不存在"}), 404

    return jsonify({"success": True, "tree": _resolve(skill_id)})


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/skillmarket/verify/<id>
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/verify/<skill_id>", methods=["POST"])
def verify_skill(skill_id: str):
    """
    验证 Skill 的 manifest v2 兼容性与权限声明。

    检查项：min_koto_version 兼容性、依赖安装状态、permission 授权。
    Body (可选): { "allowed_permissions": ["file_read", "network"] }
    """
    sm = _sm()
    sm._ensure_init()

    skill_def = sm._def_registry.get(skill_id)
    if not skill_def:
        return jsonify({"success": False, "error": f"Skill '{skill_id}' 不存在"}), 404

    data_body = request.get_json(silent=True) or {}
    allowed_permissions = set(
        data_body.get(
            "allowed_permissions",
            [
                "file_read",
                "network",
                "clipboard",
                "agent_call",
            ],
        )
    )

    results = []
    passed = True

    # 1. Koto 版本兼容性
    compatibility = getattr(skill_def, "compatibility", None) or {}
    min_ver = compatibility.get("min_koto_version")
    if min_ver:
        koto_ver = "1.0.0"  # 当前 Koto 版本占位
        ok = _compare_versions(koto_ver, min_ver) >= 0
        results.append(
            {
                "check": "koto_version",
                "passed": ok,
                "detail": f"要求 >= {min_ver}，当前 {koto_ver}",
            }
        )
        if not ok:
            passed = False

    # 2. 依赖状态
    for dep_id in getattr(skill_def, "dependencies", None) or []:
        dep = sm._def_registry.get(dep_id)
        dep_enabled = dep and sm._registry.get(dep_id, {}).get("enabled", dep.enabled)
        ok = bool(dep_enabled)
        results.append(
            {
                "check": f"dependency:{dep_id}",
                "passed": ok,
                "detail": (
                    "已安装并启用"
                    if ok
                    else ("未安装" if not dep else "已安装但未启用")
                ),
            }
        )
        if not ok:
            passed = False

    # 3. 权限检查
    for perm in getattr(skill_def, "permissions", None) or []:
        ok = perm in allowed_permissions
        results.append(
            {
                "check": f"permission:{perm}",
                "passed": ok,
                "detail": "在允许列表内" if ok else f"权限 '{perm}' 未授权",
            }
        )
        if not ok:
            passed = False

    return jsonify(
        {
            "success": True,
            "skill_id": skill_id,
            "verified": passed,
            "checks": results,
        }
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skillmarket/sessions  —  列出可用的对话会话（供创作工坊使用）
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/sessions", methods=["GET"])
def list_sessions():
    """
    返回 chats/ 目录中所有可用对话会话的摘要列表，供创作工坊「从对话提取」功能使用。
    每条记录包含: session_id（文件名去后缀）、标题、消息数、最后更新时间。
    """
    chats_dir = _BASE_DIR / "chats"
    sessions = []

    if chats_dir.exists():
        for chat_file in sorted(
            chats_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            try:
                data = json.loads(chat_file.read_text(encoding="utf-8"))
                session_id = chat_file.stem

                # 支持多种 JSON 结构
                messages = (
                    data
                    if isinstance(data, list)
                    else data.get("messages", data.get("history", []))
                )
                msg_count = len(messages) if isinstance(messages, list) else 0

                # 取首条用户消息作为标题预览
                title = session_id
                if isinstance(messages, list):
                    for msg in messages:
                        if isinstance(msg, dict):
                            role = msg.get("role", "")
                            content = msg.get("content", msg.get("text", ""))
                            if role in ("user", "human") and content:
                                title = str(content)[:60]
                                break

                sessions.append(
                    {
                        "session_id": session_id,
                        "title": title,
                        "message_count": msg_count,
                        "updated_at": datetime.fromtimestamp(
                            chat_file.stat().st_mtime
                        ).strftime("%Y-%m-%d %H:%M"),
                        "file_name": chat_file.name,
                    }
                )
            except Exception as e:
                logger.debug(f"[sessions] 跳过 {chat_file.name}: {e}")

    return jsonify(
        {
            "success": True,
            "total": len(sessions),
            "sessions": sessions,
        }
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/skillmarket/active  —  返回当前已激活的 Skill 列表（供聊天 UI 使用）
# ══════════════════════════════════════════════════════════════════════════════


@marketplace_bp.route("/active", methods=["GET"])
def get_active_skills():
    """
    返回当前所有已启用 Skill 的精简信息（id、name、icon、category）。
    含冲突预警：若多个互冲突的 Skill 同时启用，在列表中标注被抑制的 Skill。
    """
    try:
        sm = _sm()
        sm._ensure_init()

        HIDDEN_FROM_PILL_BAR = {"long_term_memory"}

        # 获取冲突信息
        conflicts = sm.check_conflicts()
        suppressed_ids = {c["loser_id"] for c in conflicts}

        active = []
        for skill_id, s in sm._registry.items():
            if skill_id in HIDDEN_FROM_PILL_BAR:
                continue
            if s.get("enabled", False):
                active.append(
                    {
                        "id": skill_id,
                        "name": s.get("name", skill_id),
                        "icon": s.get("icon", "🔧"),
                        "category": s.get("category", "custom"),
                        "description": s.get("description", ""),
                        "has_template": bool(
                            s.get("template_path")
                            or (
                                _BASE_DIR
                                / "config"
                                / "skill_templates"
                                / skill_id
                                / "template.docx"
                            ).exists()
                        ),
                        "suppressed": skill_id in suppressed_ids,
                    }
                )

        return jsonify(
            {
                "success": True,
                "count": len(active),
                "skills": active,
                "conflicts": conflicts,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@marketplace_bp.route("/conflicts", methods=["GET"])
def get_skill_conflicts():
    """
    返回当前启用 Skills 之间所有冲突关系。
    可选参数 task_type（如 ?task_type=CHAT）筛选特定任务类型下的冲突。
    """
    try:
        task_type = request.args.get("task_type")
        sm = _sm()
        conflicts = sm.check_conflicts(task_type=task_type)
        return jsonify(
            {
                "success": True,
                "conflict_count": len(conflicts),
                "conflicts": conflicts,
                "summary": (
                    f"检测到 {len(conflicts)} 处冲突："
                    + "；".join(
                        f"「{c['winner_name']}」抑制「{c['loser_name']}」"
                        for c in conflicts
                    )
                    if conflicts
                    else "当前无冲突"
                ),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# ▼  Word 模板管理（Template Skills）
# ══════════════════════════════════════════════════════════════════════════════

_TMPL_ROOT = _BASE_DIR / "config" / "skill_templates"
_TMPL_OUT = _BASE_DIR / "config" / "skill_template_outputs"

ALLOWED_TMPL_EXTENSIONS = {".docx"}
MAX_TMPL_SIZE = 10 * 1024 * 1024  # 10 MB


def _safe_skill_id(skill_id: str) -> bool:
    """验证 skill_id 是合法的标识符，防止路径穿越。"""
    return bool(re.fullmatch(r"[a-z0-9_\-]{1,60}", skill_id))


@marketplace_bp.route("/templates/upload", methods=["POST"])
def upload_skill_template():
    """
    上传 Word 模板文件并绑定到指定 Skill。

    Form 字段：
      - file     : .docx 文件
      - skill_id : 要绑定的 Skill ID

    返回：
      { success, skill_id, fields, field_count, template_preview }
    """
    try:
        skill_id = request.form.get("skill_id", "").strip().lower()
        if not skill_id or not _safe_skill_id(skill_id):
            return jsonify({"success": False, "error": "skill_id 无效"}), 400

        if "file" not in request.files:
            return jsonify({"success": False, "error": "未上传文件"}), 400

        f = request.files["file"]
        if not f.filename:
            return jsonify({"success": False, "error": "文件名为空"}), 400

        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_TMPL_EXTENSIONS:
            return (
                jsonify(
                    {"success": False, "error": f"仅支持 .docx 格式，不接受 {ext}"}
                ),
                400,
            )

        # 读取并校验大小
        data = f.read()
        if len(data) > MAX_TMPL_SIZE:
            return jsonify({"success": False, "error": "文件过大，最大 10 MB"}), 413

        # 保存
        tmpl_dir = _TMPL_ROOT / skill_id
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        tmpl_path = tmpl_dir / "template.docx"
        tmpl_path.write_bytes(data)

        # 解析字段
        from app.core.skills.template_engine import TemplateEngine

        fields = TemplateEngine.parse_fields(tmpl_path)
        preview = TemplateEngine.get_raw_text(tmpl_path)

        # 更新 Skill 注册表中的 template_path 字段
        sm = _sm()
        sm._ensure_init()
        if skill_id in sm._registry:
            sm._registry[skill_id]["template_path"] = str(
                Path("config") / "skill_templates" / skill_id / "template.docx"
            )
            sm._registry[skill_id]["bound_tools"] = list(
                set(sm._registry[skill_id].get("bound_tools", []))
                | {"fill_skill_template", "get_template_fields"}
            )
            sm._save_states_to_settings()

            # 同步更新 config/skills/{skill_id}.json（若存在）
            skill_json = _SKILLS_DIR / f"{skill_id}.json"
            if skill_json.exists():
                with open(skill_json, "r", encoding="utf-8") as fp:
                    sdata = json.load(fp)
                sdata["template_path"] = str(
                    Path("config") / "skill_templates" / skill_id / "template.docx"
                )
                sdata["bound_tools"] = list(
                    set(sdata.get("bound_tools", []))
                    | {"fill_skill_template", "get_template_fields"}
                )
                with open(skill_json, "w", encoding="utf-8") as fp:
                    json.dump(sdata, fp, ensure_ascii=False, indent=2)

        logger.info(f"[templates/upload] skill={skill_id} fields={fields}")
        return jsonify(
            {
                "success": True,
                "skill_id": skill_id,
                "fields": fields,
                "field_count": len(fields),
                "template_preview": preview[:800],
            }
        )
    except Exception as e:
        logger.error(f"[templates/upload] {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@marketplace_bp.route("/templates/<skill_id>", methods=["GET"])
def get_skill_template_info(skill_id: str):
    """
    返回 Skill 模板信息：字段列表、预览文本、是否已绑定。
    """
    if not _safe_skill_id(skill_id):
        return jsonify({"success": False, "error": "skill_id 无效"}), 400
    try:
        tmpl_path = _TMPL_ROOT / skill_id / "template.docx"
        if not tmpl_path.exists():
            return (
                jsonify(
                    {
                        "success": False,
                        "has_template": False,
                        "message": "该 Skill 尚未绑定 Word 模板",
                    }
                ),
                200,
            )

        from app.core.skills.template_engine import TemplateEngine

        fields = TemplateEngine.parse_fields(tmpl_path)
        preview = TemplateEngine.get_raw_text(tmpl_path)
        return jsonify(
            {
                "success": True,
                "has_template": True,
                "skill_id": skill_id,
                "fields": fields,
                "field_count": len(fields),
                "template_preview": preview[:800],
            }
        )
    except Exception as e:
        logger.error(f"[templates/info] {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@marketplace_bp.route("/templates/<skill_id>", methods=["DELETE"])
def delete_skill_template(skill_id: str):
    """删除 Skill 绑定的模板文件并清除 template_path 字段。"""
    if not _safe_skill_id(skill_id):
        return jsonify({"success": False, "error": "skill_id 无效"}), 400
    try:
        tmpl_path = _TMPL_ROOT / skill_id / "template.docx"
        if tmpl_path.exists():
            tmpl_path.unlink()

        sm = _sm()
        sm._ensure_init()
        if skill_id in sm._registry:
            sm._registry[skill_id].pop("template_path", None)
            bt = sm._registry[skill_id].get("bound_tools", [])
            sm._registry[skill_id]["bound_tools"] = [
                t for t in bt if t not in {"fill_skill_template", "get_template_fields"}
            ]
            sm._save_states_to_settings()

        skill_json = _SKILLS_DIR / f"{skill_id}.json"
        if skill_json.exists():
            with open(skill_json, "r", encoding="utf-8") as fp:
                sdata = json.load(fp)
            sdata.pop("template_path", None)
            sdata["bound_tools"] = [
                t
                for t in sdata.get("bound_tools", [])
                if t not in {"fill_skill_template", "get_template_fields"}
            ]
            with open(skill_json, "w", encoding="utf-8") as fp:
                json.dump(sdata, fp, ensure_ascii=False, indent=2)

        return jsonify({"success": True, "message": f"Skill '{skill_id}' 的模板已删除"})
    except Exception as e:
        logger.error(f"[templates/delete] {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@marketplace_bp.route("/templates/<skill_id>/output/<filename>", methods=["GET"])
def download_template_output(skill_id: str, filename: str):
    """
    下载已填充的 .docx 输出文件。
    文件名格式：{skill_id}_{timestamp}.docx（由 fill_skill_template 工具生成）
    """
    if not _safe_skill_id(skill_id):
        return jsonify({"success": False, "error": "skill_id 无效"}), 400

    # 严格验证文件名，防止路径穿越
    if not re.fullmatch(r"[a-z0-9_\-]{1,60}_\d{8}_\d{6}\.docx", filename):
        return jsonify({"success": False, "error": "文件名无效"}), 400

    out_path = _TMPL_OUT / skill_id / filename
    if not out_path.exists():
        return jsonify({"success": False, "error": "文件不存在"}), 404

    return send_file(
        str(out_path),
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ══════════════════════════════════════════════════════════════════════════════
# GitHub Skills Hub
# ══════════════════════════════════════════════════════════════════════════════
# 允许用户直接从 GitHub 上的流行 Agent Skills 仓库浏览并一键安装 Skill。
#
# 支持两种格式：
#   1. Anthropic SKILL.md 格式（官方标准）→ 自动转换为 Koto JSON
#   2. Koto JSON 格式（.json 文件带 id/name/prompt 字段）→ 直接安装
#
# 安全约束：
#   - 仅允许 HTTPS 请求
#   - 仅允许 github.com / raw.githubusercontent.com 域名
#   - 所有请求带 timeout 和 size 限制
#   - YAML frontmatter 仅解析 key=value 纯文本，不执行代码
# ══════════════════════════════════════════════════════════════════════════════

# 精选热门仓库（按 Stars 排序，手动维护）
_GH_CURATED_REPOS: List[Dict] = [
    {
        "repo": "anthropics/skills",
        "name": "Anthropic 官方 Skills",
        "description": "Anthropic 官方发布的 Agent Skills 示例库，涵盖创意设计、技术开发、企业协作、文档生成等场景。每个 skill 均为标准 SKILL.md 格式。",
        "stars": 99100,
        "format": "skill_md",
        "skills_path": "skills",
        "branch": "main",
        "icon": "🏛️",
        "tags": ["官方", "多领域", "SKILL.md"],
        "license": "Apache-2.0",
    },
    {
        "repo": "VoltAgent/awesome-agent-skills",
        "name": "VoltAgent 社区技能集",
        "description": "500+ 社区 Agent Skills，兼容 Claude Code、Codex、Gemini CLI、Cursor 等多个 AI 编码代理，包含编程、写作、分析等多种类型。",
        "stars": 2800,
        "format": "skill_md",
        "skills_path": "skills",
        "branch": "main",
        "icon": "⚡",
        "tags": ["社区", "多平台", "编程"],
        "license": "MIT",
    },
    {
        "repo": "sickn33/antigravity-awesome-skills",
        "name": "Antigravity 技能库",
        "description": "1304+ 精心筛选的 Agentic Skills，兼容 Claude Code、Cursor、Codex CLI、Gemini CLI 等，含官方和社区技能集合，附 CLI 安装工具。",
        "stars": 1900,
        "format": "skill_md",
        "skills_path": "skills",
        "branch": "main",
        "icon": "🚀",
        "tags": ["社区", "多平台", "CLI工具"],
        "license": "MIT",
    },
    {
        "repo": "K-Dense-AI/claude-scientific-skills",
        "name": "科学研究技能集",
        "description": "面向研究、科学、工程、金融和写作领域的 Agent Skills，涵盖生物信息学、材料科学、化学信息学、数据分析等专业场景。",
        "stars": 620,
        "format": "skill_md",
        "skills_path": "skills",
        "branch": "main",
        "icon": "🔬",
        "tags": ["科研", "金融", "写作"],
        "license": "MIT",
    },
    {
        "repo": "phuryn/pm-skills",
        "name": "产品经理技能集",
        "description": "100+ 产品管理相关的 Agentic Skills，覆盖产品发现、战略制定、执行落地、上线发布和增长分析全流程。",
        "stars": 390,
        "format": "skill_md",
        "skills_path": "skills",
        "branch": "main",
        "icon": "📋",
        "tags": ["产品", "PM", "战略"],
        "license": "MIT",
    },
    {
        "repo": "alirezarezvani/claude-skills",
        "name": "Claude 全能技能集",
        "description": "192+ Claude Code Skills & Agent Plugins，涵盖工程、市场营销、产品、合规、C-level 顾问等企业场景。",
        "stars": 580,
        "format": "skill_md",
        "skills_path": "skills",
        "branch": "main",
        "icon": "💼",
        "tags": ["企业", "工程", "营销"],
        "license": "MIT",
    },
]

# GitHub API 与 raw 内容的合法域名白名单
_GH_ALLOWED_HOSTS = {"api.github.com", "raw.githubusercontent.com"}
_GH_MAX_CONTENT_BYTES = 256 * 1024  # 256 KB 上限
_GH_REQUEST_TIMEOUT = 10  # 秒


def _gh_validate_url(url: str) -> bool:
    """校验 URL 安全性：必须 HTTPS，域名在白名单内。"""
    import urllib.parse

    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.scheme == "https" and parsed.netloc in _GH_ALLOWED_HOSTS
    except Exception:
        return False


def _gh_fetch(url: str) -> bytes:
    """安全抓取 GitHub 内容，有 size 和 timeout 限制。"""
    import ssl
    import urllib.request

    if not _gh_validate_url(url):
        raise ValueError(f"URL 不合法或域名不在白名单: {url}")
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "koto-github-skill-hub/1.0",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=_GH_REQUEST_TIMEOUT, context=ctx) as resp:
        data = resp.read(_GH_MAX_CONTENT_BYTES)
    return data


def _parse_skill_md(
    content: str, repo: str, skill_path: str, branch: str = "main"
) -> Dict:
    """
    将 SKILL.md（YAML frontmatter + Markdown body）转换为 Koto Skill JSON。

    frontmatter 字段映射：
      name        → name（显示名）
      description → description
      tools       → bound_tools（list）
      tags        → tags（list）
    body          → prompt（system_prompt_template）
    """
    import re as _re

    name = ""
    description = ""
    bound_tools: List[str] = []
    tags: List[str] = []
    body = content

    # 解析 YAML frontmatter（仅支持简单 key: value，不执行代码）
    fm_match = _re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, _re.DOTALL)
    if fm_match:
        fm_text = fm_match.group(1)
        body = fm_match.group(2).strip()

        current_key = None
        in_list = False
        for line in fm_text.splitlines():
            # 列表项
            list_item = _re.match(r"^\s+-\s+(.+)$", line)
            if list_item and in_list and current_key:
                val = list_item.group(1).strip().strip('"').strip("'")[:200]
                if current_key == "tools":
                    bound_tools.append(val)
                elif current_key == "tags":
                    tags.append(val)
                continue

            kv = _re.match(r"^([a-zA-Z_][a-zA-Z0-9_\-]*):\s*(.*)?$", line)
            if kv:
                key = kv.group(1).lower()
                val = (kv.group(2) or "").strip().strip('"').strip("'")[:500]
                current_key = key
                in_list = val == ""  # 空值说明下面是列表
                if key == "name":
                    name = val
                elif key == "description":
                    description = val
                elif key == "tools" and val and not in_list:
                    bound_tools = [v.strip() for v in val.split(",") if v.strip()]
                elif key == "tags" and val and not in_list:
                    tags = [v.strip() for v in val.split(",") if v.strip()]
            else:
                in_list = False

    if not name:
        # 尝试从 Markdown 第一个 H1 取名
        h1 = _re.search(r"^#\s+(.+)", body, _re.MULTILINE)
        name = (
            h1.group(1).strip()
            if h1
            else skill_path.split("/")[-1].replace("-", " ").title()
        )

    if not description:
        # 取正文第一段非标题文本作为 description
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("---"):
                description = line[:200]
                break

    # 生成 Koto skill id
    slug = _re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:50] or "gh_skill"
    skill_id = f"gh_{slug}"

    # 拼源 URL
    owner_repo = repo
    source_url = f"https://github.com/{owner_repo}/tree/{branch}/{skill_path}"

    return {
        "id": skill_id,
        "name": name,
        "icon": "🌐",
        "category": "domain",
        "description": description or f"来自 GitHub {owner_repo} 的 Skill",
        "intent_description": "",
        "prompt": body,
        "system_prompt_template": body,
        "tags": list({t.lower() for t in (tags + ["github", "community"])})[:10],
        "bound_tools": bound_tools,
        "author": f"community:{owner_repo}",
        "version": "1.0.0",
        "enabled": False,
        "source_url": source_url,
        "skill_nature": "domain_skill",
        "subcategory": "research",
    }


def _gh_list_skills_in_repo(repo: str, skills_path: str, branch: str) -> List[Dict]:
    """
    通过 GitHub Contents API 列出仓库 skills_path 下的所有技能目录/文件。
    返回每项的 name、path、type、skill_md_url。
    """
    api_url = f"https://api.github.com/repos/{repo}/contents/{skills_path}?ref={branch}"
    raw = _gh_fetch(api_url)
    items = json.loads(raw.decode("utf-8"))
    if not isinstance(items, list):
        raise ValueError(
            f"无法列出目录 {skills_path}：{items.get('message', '未知错误')}"
        )

    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_name = item.get("name", "")
        item_type = item.get("type", "")
        item_path = item.get("path", "")

        # 跳过隐藏、README、模板文件
        if item_name.startswith(".") or item_name.startswith("_"):
            continue
        if item_name.upper() in ("README.MD", "LICENSE", "THIRD_PARTY_NOTICES.MD"):
            continue

        if item_type == "dir":
            # 技能以目录形式存放（标准 Anthropic 格式）
            skill_md_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{item_path}/SKILL.md"
            result.append(
                {
                    "name": item_name,
                    "path": item_path,
                    "type": "dir",
                    "skill_md_url": skill_md_url,
                }
            )
        elif item_type == "file" and item_name.upper() == "SKILL.MD":
            # 某些仓库直接把 SKILL.md 放在根路径
            skill_md_url = item.get(
                "download_url",
                f"https://raw.githubusercontent.com/{repo}/{branch}/{item_path}",
            )
            result.append(
                {
                    "name": item_path.split("/")[-2] if "/" in item_path else item_name,
                    "path": item_path,
                    "type": "file",
                    "skill_md_url": skill_md_url,
                }
            )
        elif item_type == "file" and item_name.lower().endswith(".json"):
            # 某些仓库直接存放 JSON 格式的 Koto skill
            result.append(
                {
                    "name": item_name[:-5],
                    "path": item_path,
                    "type": "json",
                    "skill_md_url": item.get(
                        "download_url",
                        f"https://raw.githubusercontent.com/{repo}/{branch}/{item_path}",
                    ),
                }
            )

    return result


# ── GET /api/skillmarket/github/repos  ─────────────────────────────────────


@marketplace_bp.route("/github/repos", methods=["GET"])
def github_repos():
    """返回精选热门 GitHub Skills 仓库列表（静态维护 + 实时安装状态）。"""
    sm = _sm()
    sm._ensure_init()
    installed_ids = set(sm._def_registry.keys())

    repos_out = []
    for r in _GH_CURATED_REPOS:
        entry = dict(r)
        entry["github_url"] = f"https://github.com/{r['repo']}"
        repos_out.append(entry)

    return jsonify({"success": True, "repos": repos_out})


# ── GET /api/skillmarket/github/skills  ────────────────────────────────────


@marketplace_bp.route("/github/skills", methods=["GET"])
def github_skills():
    """
    列出指定仓库下的可安装 Skill 列表。

    查询参数:
      repo   - "owner/repo"（必填，必须在精选列表内）
      path   - skills 子目录（可选，默认从精选配置读取）
      branch - 分支（可选，默认 main）
    """
    repo = (request.args.get("repo") or "").strip()
    if not repo:
        return jsonify({"success": False, "error": "参数 repo 不能为空"}), 400

    # 安全校验：仅允许精选仓库，防止 SSRF
    allowed_repos = {r["repo"] for r in _GH_CURATED_REPOS}
    if repo not in allowed_repos:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"仓库 '{repo}' 不在允许列表内。如需安装其他仓库的 Skill，请使用自定义 URL 安装功能。",
                }
            ),
            403,
        )

    # 从精选配置取默认值
    repo_cfg = next((r for r in _GH_CURATED_REPOS if r["repo"] == repo), {})
    skills_path = request.args.get("path") or repo_cfg.get("skills_path", "skills")
    branch = request.args.get("branch") or repo_cfg.get("branch", "main")

    # 校验 path 和 branch 格式，防止路径注入
    if not re.match(r"^[a-zA-Z0-9_\-/\.]{1,100}$", skills_path):
        return jsonify({"success": False, "error": "path 参数无效"}), 400
    if not re.match(r"^[a-zA-Z0-9_\-/\.]{1,50}$", branch):
        return jsonify({"success": False, "error": "branch 参数无效"}), 400

    try:
        items = _gh_list_skills_in_repo(repo, skills_path, branch)

        # 标注已安装状态
        sm = _sm()
        sm._ensure_init()
        for item in items:
            slug = re.sub(r"[^a-z0-9]+", "_", item["name"].lower()).strip("_")[:50]
            candidate_id = f"gh_{slug}"
            item["is_installed"] = candidate_id in sm._def_registry
            item["koto_id"] = candidate_id
            item["repo"] = repo
            item["branch"] = branch
            item["github_url"] = (
                f"https://github.com/{repo}/tree/{branch}/{item['path']}"
            )

        return jsonify(
            {
                "success": True,
                "repo": repo,
                "skills_path": skills_path,
                "count": len(items),
                "skills": items,
            }
        )
    except Exception as exc:
        logger.warning("[github/skills] %s: %s", repo, exc)
        return jsonify({"success": False, "error": str(exc)}), 502


# ── POST /api/skillmarket/github/install  ──────────────────────────────────


@marketplace_bp.route("/github/install", methods=["POST"])
def github_install():
    """
    从 GitHub 获取一个 Skill 并安装到 Koto。

    请求体（JSON）：
    {
      "repo": "owner/repo",                  # 精选仓库名（与 skill_path 配合）
      "skill_path": "skills/code-reviewer",  # SKILL.md 所在目录或文件路径
      "branch": "main",                      # 分支（可选，默认 main）
      "overwrite": false,                    # 是否覆盖已安装的同名 Skill

      # --- 或者使用自定义 URL 模式 ---
      "raw_url": "https://raw.githubusercontent.com/owner/repo/main/path/SKILL.md"
    }

    支持格式：
      - Anthropic SKILL.md  → 自动解析 frontmatter，转为 Koto JSON
      - Koto JSON（含 id/name/prompt 字段）→ 直接安装
    """
    data = request.json or {}
    overwrite = bool(data.get("overwrite", False))

    raw_url: Optional[str] = (data.get("raw_url") or "").strip() or None
    repo: Optional[str] = (data.get("repo") or "").strip() or None
    skill_path: Optional[str] = (data.get("skill_path") or "").strip() or None
    branch: str = (data.get("branch") or "main").strip()

    # ── 1. 确定抓取 URL ────────────────────────────────────────────────────
    if raw_url:
        # 自定义 URL：必须是 raw.githubusercontent.com，且路径合法
        if not _gh_validate_url(raw_url):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "raw_url 必须是 https://raw.githubusercontent.com/... 链接",
                    }
                ),
                400,
            )
    elif repo and skill_path:
        # 精选仓库：校验 repo 在白名单内
        allowed_repos = {r["repo"] for r in _GH_CURATED_REPOS}
        if repo not in allowed_repos:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"仓库 '{repo}' 不在允许列表内",
                    }
                ),
                403,
            )

        # 校验 skill_path 和 branch 格式
        if not re.match(r"^[a-zA-Z0-9_\-/\. ]{1,200}$", skill_path):
            return jsonify({"success": False, "error": "skill_path 参数无效"}), 400
        if not re.match(r"^[a-zA-Z0-9_\-/\.]{1,50}$", branch):
            return jsonify({"success": False, "error": "branch 参数无效"}), 400

        # 自动判断是目录（拼 SKILL.md）还是直接文件
        if skill_path.upper().endswith("SKILL.MD") or skill_path.lower().endswith(
            ".json"
        ):
            raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{skill_path}"
        else:
            raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{skill_path}/SKILL.md"
    else:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "请提供 raw_url，或同时提供 repo + skill_path",
                }
            ),
            400,
        )

    # ── 2. 抓取内容 ────────────────────────────────────────────────────────
    try:
        content_bytes = _gh_fetch(raw_url)
    except Exception as exc:
        return jsonify({"success": False, "error": f"抓取失败: {exc}"}), 502

    content_str = content_bytes.decode("utf-8", errors="replace")

    # ── 3. 解析格式 ────────────────────────────────────────────────────────
    skill_dict: Dict[str, Any]

    if raw_url.lower().endswith(".json"):
        # Koto JSON 格式
        try:
            skill_dict = json.loads(content_str)
        except json.JSONDecodeError as exc:
            return jsonify({"success": False, "error": f"JSON 解析失败: {exc}"}), 422
        if not skill_dict.get("id") or not skill_dict.get("name"):
            return (
                jsonify({"success": False, "error": "JSON 文件缺少 id 或 name 字段"}),
                422,
            )
        # 强制标记来源
        skill_dict.setdefault("author", f"community:{repo or 'github'}")
        skill_dict.setdefault("source_url", raw_url)
        skill_dict.setdefault("tags", [])
        if "github" not in skill_dict["tags"]:
            skill_dict["tags"].append("github")
    else:
        # SKILL.md 格式（或默认当作 Markdown 处理）
        effective_repo = repo or "github/community"
        effective_path = (
            skill_path or raw_url.split("raw.githubusercontent.com/", 1)[-1]
        )
        skill_dict = _parse_skill_md(
            content=content_str,
            repo=effective_repo,
            skill_path=effective_path,
            branch=branch,
        )

    # ── 4. 安装 ────────────────────────────────────────────────────────────
    try:
        SkillDefinition, _, _ = _schema()
        SkillRecorder = _recorder()
        skill = SkillDefinition.from_dict(skill_dict)
        SkillRecorder.save_and_register(skill, overwrite=overwrite)
        return (
            jsonify(
                {
                    "success": True,
                    "skill_id": skill.id,
                    "skill": skill.to_dict(),
                    "source": raw_url,
                }
            ),
            201,
        )
    except FileExistsError:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Skill '{skill_dict.get('id')}' 已安装，传 overwrite:true 覆盖",
                    "skill_id": skill_dict.get("id"),
                }
            ),
            409,
        )
    except Exception as exc:
        logger.exception("[github/install]")
        return jsonify({"success": False, "error": str(exc)}), 500


# ══════════════════════════════════════════════════════════════════════════════
#  Koto Skill 社区 — 精选社区 Skills（内嵌，无需外网）
#  这些 Skills 来自高质量的 Prompt 工程实践和社区知识，随版本更新
# ══════════════════════════════════════════════════════════════════════════════

_COMMUNITY_SKILLS: List[Dict] = [
    # ── 思维增强 ──────────────────────────────────────────────────────────────
    {
        "id": "comm_socratic_teacher",
        "name": "苏格拉底式引导",
        "icon": "🏛️",
        "category": "behavior",
        "subcategory": "koto_thinking",
        "skill_nature": "model_hint",
        "description": "用追问代替直接给答案。通过一系列精准的问题，引导你自己找到答案——这才是真正的理解。",
        "author": "Socrates · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["学习", "教育", "批判性思维", "引导"],
        "priority": 50,
        "enabled": False,
        "prompt": (
            "\n\n## 🏛️ 苏格拉底式引导模式\n\n"
            "当此技能激活时，你不再直接给出答案，而是通过提问引导用户自己推理和发现。\n\n"
            "### 行为准则\n"
            "- **首先提问**：面对任何请求，先问澄清性问题，让用户思考\n"
            "- **暴露假设**：温和地挑战用户的前提假设（「你为什么这样认为？」）\n"
            "- **逐步深入**：每次只问一个问题，等待回答后再进行下一步\n"
            "- **引向自我发现**：当用户接近答案时，用「你现在怎么看？」「这意味着什么？」收尾\n"
            "- **偶尔总结**：在对话关键节点，帮用户反思已有的收获\n\n"
            "### 禁止行为\n"
            "- 不要一次性抛出多个问题\n"
            "- 不要直接说「答案是...」（除非用户明确要求放弃引导）\n"
            "- 不要用居高临下的语气\n\n"
            "### 例外\n"
            "若用户说「直接告诉我」或类似表达，可切换为正常回答模式。"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["学习新技能", "解决棘手问题", "教育辅导", "自我探索"],
            "difficulty": "中等",
        },
    },
    {
        "id": "comm_first_principles",
        "name": "第一性原理思维",
        "icon": "⚛️",
        "category": "behavior",
        "subcategory": "koto_thinking",
        "skill_nature": "model_hint",
        "description": "拆解一切假设，从基础物理事实重新推导。埃隆·马斯克的思维方式：打破「一直都是这样做的」的惯性。",
        "author": "Aristotle · Elon Musk · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["创新", "逻辑", "问题拆解", "第一性原理"],
        "priority": 52,
        "enabled": False,
        "prompt": (
            "\n\n## ⚛️ 第一性原理分析模式\n\n"
            "当此技能激活时，你对任何问题都从最基本的事实出发，拒绝类比推理和惯性假设。\n\n"
            "### 分析步骤（每次必须明确展示）\n"
            "1. **识别假设**：列出当前讨论中所有「想当然」的前提\n"
            "2. **打破假设**：对每个假设问「这真的是不可改变的吗？」\n"
            "3. **基础事实**：找到不可再拆分的基础真理和约束条件\n"
            "4. **从零重建**：基于这些基础事实，重新推导最优解\n"
            "5. **对比评估**：与原有方案对比，指出差异和潜在突破口\n\n"
            "### 标志性问题模板\n"
            "- 「这件事的物理/逻辑极限是什么？」\n"
            "- 「如果没有历史包袱，我们会怎么设计这个？」\n"
            "- 「这个假设在什么条件下会不成立？」\n\n"
            "### 输出格式\n"
            "使用「🔍 假设识别 → ⚡ 假设拆解 → 🧱 基础事实 → 🚀 从零推导 → 📊 对比」的结构。"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["产品创新", "技术架构", "商业战略", "解决复杂问题"],
            "difficulty": "较难",
        },
    },
    {
        "id": "comm_devils_advocate",
        "name": "魔鬼代言人",
        "icon": "😈",
        "category": "behavior",
        "subcategory": "koto_thinking",
        "skill_nature": "model_hint",
        "description": "无论你的方案有多完美，我都会找出最强的反驳理由。用批判性压力测试你的想法。",
        "author": "Edward de Bono · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["批判性思维", "辩论", "风险识别", "压力测试"],
        "priority": 48,
        "enabled": False,
        "prompt": (
            "\n\n## 😈 魔鬼代言人模式\n\n"
            "当此技能激活时，你的角色是「最强的反对者」。你的任务是找出用户观点、计划或决策中最脆弱的部分，并给出最有力的反驳。\n\n"
            "### 行为原则\n"
            "- **寻找最强反驳**：不是歪曲对方观点，而是找到其真实弱点\n"
            "- **Steel Man 对立面**：先构建「反对这个想法」的最强版本\n"
            "- **量化风险**：尽量用具体数字或场景描述风险（「3/10的概率…」）\n"
            "- **历史案例**：引用类似方案失败的案例\n"
            "- **角色扮演**：必要时扮演「最刁钻的投资人」「最难搞的客户」来提问\n\n"
            "### 输出结构\n"
            "```\n🎯 你的方案：[一句话复述]\n\n😈 魔鬼质疑：\n1. [最强反驳1]\n2. [最强反驳2]\n3. [最强反驳3]\n\n⚠️ 致命弱点：[最核心的一个风险]\n\n💡 若要防御这些批评，你需要：[建议]\n```"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["商业计划评审", "决策验证", "辩论准备", "风险评估"],
            "difficulty": "中等",
        },
    },
    {
        "id": "comm_steelman",
        "name": "Steelman 论证法",
        "icon": "🛡️",
        "category": "behavior",
        "subcategory": "koto_thinking",
        "skill_nature": "model_hint",
        "description": "构建对立观点的「最强版本」，而非稻草人。锻炼真正理解不同立场的能力。",
        "author": "Daniel Dennett · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["辩证思维", "理解", "论证", "平衡视角"],
        "priority": 46,
        "enabled": False,
        "prompt": (
            "\n\n## 🛡️ Steelman 论证模式\n\n"
            "当此技能激活时，面对任何争议性话题或对立观点，你必须先构建该观点的「最强版本」（Steelman），再进行分析。\n\n"
            "### 与 Strawman 的区别\n"
            "- ❌ Strawman：歪曲、削弱对立观点，使其易于攻击\n"
            "- ✅ Steelman：让对立观点比原作者表达得更清晰、更有说服力\n\n"
            "### 操作步骤\n"
            "1. **理解原始立场**：准确复述对方的论点（不带嘲讽）\n"
            "2. **强化它**：加入最有力的支持论据、数据、逻辑，让它达到最强形式\n"
            "3. **公正评估**：基于最强版本，进行平衡分析\n"
            "4. **整合视角**：找到两种立场的共同价值和真实分歧点\n\n"
            "### 输出格式\n"
            "每次讨论争议话题时，开头加如下结构：\n"
            "「📌 对立立场的最强版本：[Steelman版本]\n考虑了这个视角后，我的分析是…」"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["政策分析", "学术讨论", "团队决策", "消除偏见"],
            "difficulty": "中等",
        },
    },
    # ── 专业咨询 ──────────────────────────────────────────────────────────────
    {
        "id": "comm_mckinsey_framework",
        "name": "麦肯锡顾问框架",
        "icon": "📊",
        "category": "domain",
        "subcategory": "career",
        "skill_nature": "domain_skill",
        "description": "MECE原则、金字塔原理、假设驱动分析。用顶级咨询公司的方法论拆解复杂商业问题。",
        "author": "Barbara Minto · McKinsey & Co. · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["咨询", "商业分析", "MECE", "金字塔原理", "战略"],
        "priority": 55,
        "enabled": False,
        "prompt": (
            "\n\n## 📊 麦肯锡顾问思维框架\n\n"
            "当此技能激活时，你用顶级管理咨询公司的方法论分析问题。\n\n"
            "### 核心框架（按需选用）\n"
            "1. **MECE原则**：分析结果必须「相互独立，完全穷尽」，不遗漏、不重叠\n"
            "2. **金字塔原理**：结论先行 → 关键论点（3-5个）→ 支持性数据/论据\n"
            "3. **假设驱动**：先提出核心假设，再有针对性地收集证据验证/证伪\n"
            "4. **问题树**：将核心问题分解为可独立分析的子问题树状结构\n"
            "5. **80/20法则**：聚焦20%能产生80%价值的关键因素\n\n"
            "### 输出标准\n"
            "- 每个结论都要有 *So What?*（对读者有什么意义？）\n"
            "- 用「电梯演讲」格式（30秒内能讲清楚的版本）\n"
            "- 建议必须「具体、可行动、有优先级」\n"
            "- 复杂分析必须包含：情境 → 矛盾/机遇 → 结论/建议\n\n"
            "### 沟通风格\n"
            "专业、直接、数据驱动。避免废话，每句话都要有价值。"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["商业分析", "战略规划", "汇报材料", "问题诊断"],
            "difficulty": "较难",
        },
    },
    {
        "id": "comm_premortem",
        "name": "事前尸检分析",
        "icon": "🔮",
        "category": "domain",
        "subcategory": "research",
        "skill_nature": "domain_skill",
        "description": "Gary Klein发明的决策工具：假设你的项目已经彻底失败，倒追失败原因。比事后复盘更有效。",
        "author": "Gary Klein · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["风险管理", "决策", "项目管理", "预防"],
        "priority": 50,
        "enabled": False,
        "prompt": (
            "\n\n## 🔮 事前尸检（Pre-Mortem）分析模式\n\n"
            "当此技能激活时，你用「时间旅行式失败分析」帮助用户预防风险。\n\n"
            "### 操作流程\n"
            "收到用户的计划或项目后，立即进入以下分析框架：\n\n"
            "**步骤1：宣告失败**\n"
            "「想象现在是18个月后，你的项目彻底失败了。不是小失败，是惨败。现在回头看，究竟发生了什么？」\n\n"
            "**步骤2：生成失败情景**（至少5个）\n"
            "- 内部风险：执行、资源、团队\n"
            "- 外部风险：市场、竞争、监管\n"
            "- 黑天鹅：极低概率但极高影响的事件\n\n"
            "**步骤3：评估概率与影响**\n"
            "对每个风险打分：概率（1-5）× 影响（1-5）= 风险指数\n\n"
            "**步骤4：防御策略**\n"
            "针对风险指数最高的2-3个，给出具体的预防措施和应急方案\n\n"
            "### 输出格式\n"
            "用表格呈现风险矩阵，结尾给出「最危险的3件事」重点提示。"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["项目启动", "投资决策", "产品发布", "战略规划"],
            "difficulty": "中等",
        },
    },
    {
        "id": "comm_vc_investor",
        "name": "VC 投资人视角",
        "icon": "💰",
        "category": "domain",
        "subcategory": "career",
        "skill_nature": "domain_skill",
        "description": "用顶级风险投资人的眼光审视你的想法。市场规模、竞争壁垒、团队、商业模式——一个都不放过。",
        "author": "Sequoia Capital Framework · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["创业", "融资", "商业模式", "投资"],
        "priority": 52,
        "enabled": False,
        "prompt": (
            "\n\n## 💰 VC 投资人审查模式\n\n"
            "当此技能激活时，你用经验丰富的风险投资人的眼光审视商业想法和创业项目。\n\n"
            "### 必须回答的核心问题\n"
            "1. **市场**：TAM/SAM/SOM是多少？市场是在增长还是萎缩？\n"
            "2. **问题**：这个痛点有多痛？用户现在怎么解决这个问题？\n"
            "3. **方案**：凭什么是你的方案胜出？差异化在哪里？\n"
            "4. **壁垒**：网络效应、转换成本、专利、品牌、规模效应\n"
            "5. **商业模式**：如何赚钱？单位经济是否成立（LTV>3×CAC）？\n"
            "6. **团队**：为什么是这个团队来做这件事？\n"
            "7. **时机**：为什么是现在？是什么变化让这件事现在可行？\n\n"
            "### VC 问的刁钻问题\n"
            "- 如果BAT/字节明天宣布做同样的事，你怎么办？\n"
            "- 你的增长假设基于什么？如果获客成本翻三倍呢？\n"
            "- 第一个100个客户从哪里来？\n\n"
            "### 结论格式\n"
            "给出：投资意愿（强烈/中等/不感兴趣）+ 最大疑虑（3条）+ 若要投资需要验证的关键假设"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["创业验证", "商业计划书", "融资准备", "想法评估"],
            "difficulty": "较难",
        },
    },
    # ── 写作创作 ──────────────────────────────────────────────────────────────
    {
        "id": "comm_hemingway_edit",
        "name": "海明威式精简写作",
        "icon": "✂️",
        "category": "domain",
        "subcategory": "writing",
        "skill_nature": "domain_skill",
        "description": "删掉废话，留下力量。像海明威一样用最少的词表达最多的意义。每个字都要有理由留下。",
        "author": "Ernest Hemingway · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["写作", "精简", "编辑", "文风"],
        "priority": 55,
        "enabled": False,
        "prompt": (
            "\n\n## ✂️ 海明威式精简写作模式\n\n"
            "当此技能激活时，你的写作和编辑遵循「冰山原则」：\n"
            "表面简洁，深处有力。每个词都有其意义，没有废话。\n\n"
            "### 写作原则\n"
            "1. **短句 > 长句**：优先使用10字以内的短句\n"
            "2. **主动语态 > 被动语态**：「她打了他」而非「他被她打了」\n"
            "3. **具体 > 抽象**：「他喝了三杯威士忌」而非「他喝了很多酒」\n"
            "4. **动词 > 名词化**：「分析」而非「进行分析」\n"
            "5. **删除副词**：「他快速地跑」→「他冲刺」\n"
            "6. **删除废话前缀**：「值得注意的是」「显而易见」「毫无疑问」——全删\n"
            "7. **对话直接**：不用「他表示说」，直接引语\n\n"
            "### 编辑文本时\n"
            "标注每处改动的原因，展示原文与改后对比。\n"
            "给出「可读性评分」（1-10）和「字数压缩率」。\n\n"
            "### 生成文本时\n"
            "先写草稿，自我审查一遍，删去所有不必要的词，再输出最终版。"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["文章润色", "报告简化", "邮件撰写", "内容创作"],
            "difficulty": "简单",
        },
    },
    {
        "id": "comm_copywriting_master",
        "name": "销售文案高手",
        "icon": "📣",
        "category": "domain",
        "subcategory": "writing",
        "skill_nature": "domain_skill",
        "description": "AIDA、PAS、4U原则——用经过验证的文案框架写出让人忍不住点击的内容。",
        "author": "E. St. Elmo Lewis (AIDA) · Dan Kennedy (PAS) · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["文案", "营销", "转化", "广告"],
        "priority": 52,
        "enabled": False,
        "prompt": (
            "\n\n## 📣 销售文案高手模式\n\n"
            "当此技能激活时，你用经过市场验证的文案框架撰写和优化内容。\n\n"
            "### 核心框架（根据场景选用）\n\n"
            "**AIDA框架**\n"
            "- Attention（注意）：用冲突、惊喜或数字抓住眼球\n"
            "- Interest（兴趣）：描述与读者相关的问题或机会\n"
            "- Desire（欲望）：展示好处，触发情感\n"
            "- Action（行动）：清晰、紧迫的行动号召\n\n"
            "**PAS框架**\n"
            "- Problem（问题）：点出读者的痛点，让他们点头\n"
            "- Agitate（激化）：加深痛点的紧迫感\n"
            "- Solution（解决）：展示你的方案是出路\n\n"
            "**4U原则**（标题必备）\n"
            "- Urgent（紧迫性）、Unique（独特性）、Useful（有用性）、Ultra-specific（超级具体）\n\n"
            "### 写作习惯\n"
            "- 第一句必须让人想看第二句\n"
            "- 用「你」而不是「用户」\n"
            "- 说好处，用具体数字（「节省3小时」而非「节省很多时间」）\n"
            "- 结尾永远有明确的CTA（行动号召）"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["广告文案", "落地页", "产品介绍", "推广邮件"],
            "difficulty": "中等",
        },
    },
    {
        "id": "comm_storytelling",
        "name": "故事结构大师",
        "icon": "📖",
        "category": "domain",
        "subcategory": "writing",
        "skill_nature": "domain_skill",
        "description": "三幕式结构、英雄之旅、南方公园「可是/因此」法则——用叙事框架让任何内容变得引人入胜。",
        "author": "Joseph Campbell · Trey Parker · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["故事", "叙事", "创作", "结构"],
        "priority": 50,
        "enabled": False,
        "prompt": (
            "\n\n## 📖 故事结构大师模式\n\n"
            "当此技能激活时，你用专业叙事框架构建和优化任何内容的故事性。\n\n"
            "### 核心框架\n\n"
            "**三幕式结构**\n"
            "- 第一幕（设置）：介绍主角、世界、核心冲突\n"
            "- 第二幕（对抗）：主角面对并应对挑战，遭遇最低谷\n"
            "- 第三幕（解决）：高潮冲突，伴随角色成长的结局\n\n"
            "**南方公园测试**（「可是/因此」法则）\n"
            "好的故事进展是：...发生了X，**因此**...，**可是**...，**因此**...\n"
            "坏的故事是：...发生了X，**然后**...，**然后**...（无冲突、无推进）\n\n"
            "**英雄之旅（精简版）**\n"
            "普通世界 → 召唤 → 拒绝 → 接受挑战 → 磨炼 → 最大挑战 → 回归 → 蜕变\n\n"
            "### 实践应用\n"
            "- 写商业案例：客户是英雄，问题是龙，你的产品是「神奇武器」\n"
            "- 写演讲/汇报：用三幕式，数据是「英雄之旅」中的关键转折\n"
            "- 诊断内容时：找出「然后」→ 改成「可是/因此」"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["演讲稿", "品牌故事", "产品叙事", "文章创作"],
            "difficulty": "中等",
        },
    },
    # ── 学习教育 ──────────────────────────────────────────────────────────────
    {
        "id": "comm_feynman_technique",
        "name": "费曼学习法",
        "icon": "🔬",
        "category": "behavior",
        "subcategory": "koto_thinking",
        "skill_nature": "model_hint",
        "description": "理查德·费曼：「如果你不能用简单的话解释一件事，说明你还没真正理解它」。用最简单的语言检验和深化理解。",
        "author": "Richard Feynman · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["学习", "解释", "理解", "简洁"],
        "priority": 54,
        "enabled": False,
        "prompt": (
            "\n\n## 🔬 费曼学习法模式\n\n"
            "当此技能激活时，你像费曼一样思考和解释：任何复杂概念都能用简单的语言讲清楚。\n\n"
            "### 解释原则\n"
            "1. **用12岁能懂的语言**：禁用专业术语，或者用时立即解释\n"
            "2. **类比优先**：用日常生活中的事物做类比\n"
            "3. **具体例子**：每个抽象概念都配一个具体例子\n"
            "4. **检验理解**：解释完后问「现在你能用自己的话解释给别人听吗？」\n"
            "5. **找到空白**：主动提醒「如果你对X还不清楚，可以继续问」\n\n"
            "### 当用户请你解释某个概念时\n"
            "- 先用1句话给出核心定义\n"
            "- 然后给一个日常类比\n"
            "- 再给一个具体例子\n"
            "- 最后解释这个概念「为什么重要」或「在哪里会用到」\n\n"
            "### 费曼自我测试\n"
            "如果无法简洁解释某部分，明确标出：「这里我解释得不够好，更准确的说法是…」"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["学习新概念", "教学辅导", "知识整理", "复杂简化"],
            "difficulty": "简单",
        },
    },
    {
        "id": "comm_cognitive_bias_checker",
        "name": "认知偏差侦探",
        "icon": "🔍",
        "category": "behavior",
        "subcategory": "koto_thinking",
        "skill_nature": "model_hint",
        "description": "识别你推理中的认知偏差：确认偏误、沉没成本、可得性启发……在你做出错误决定前叫停你。",
        "author": "Daniel Kahneman · Amos Tversky · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["认知科学", "决策", "心理学", "偏差"],
        "priority": 48,
        "enabled": False,
        "prompt": (
            "\n\n## 🔍 认知偏差侦探模式\n\n"
            "当此技能激活时，你主动识别对话中用户（或你自己）推理中的认知偏差，并温和地指出。\n\n"
            "### 重点监控的偏差类型\n"
            "- **确认偏误**：只关注支持自己观点的证据\n"
            "- **沉没成本谬误**：「已经投入这么多了，不能放弃」\n"
            "- **可得性启发**：用容易想到的例子代替实际概率\n"
            "- **过度自信偏差**：高估自己的预测准确率\n"
            "- **峰终定律**：只记住高峰和结尾，忘记整体\n"
            "- **光环效应**：因为某一点好就认为全都好\n"
            "- **乐观偏差**：「这种事不会发生在我身上」\n"
            "- **群体思维**：为了和谐压制异议\n\n"
            "### 触发条件\n"
            "当检测到可能的偏差时，插入提示：\n"
            "「⚠️ 注意：这里可能涉及[偏差名]。[简单解释]。你是否考虑过[反向证据]？」\n\n"
            "### 原则\n"
            "不要过度诊断，只在有较强信号时发言。目的是帮助思考更清晰，不是让人感觉被质疑。"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["重大决策", "投资分析", "问题诊断", "自我反思"],
            "difficulty": "中等",
        },
    },
    # ── 创意生产力 ────────────────────────────────────────────────────────────
    {
        "id": "comm_clarity_coach",
        "name": "清晰度教练",
        "icon": "💎",
        "category": "behavior",
        "subcategory": "koto_thinking",
        "skill_nature": "model_hint",
        "description": "你有模糊的感觉但说不清楚？这个技能帮你把混沌的想法整理成清晰的表达和可行的步骤。",
        "author": "Carl Rogers (Reflective Listening) · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["思路整理", "表达", "澄清", "生产力"],
        "priority": 50,
        "enabled": False,
        "prompt": (
            "\n\n## 💎 清晰度教练模式\n\n"
            "当此技能激活时，你专注帮助用户把模糊的想法、感受和困境变成清晰的表达。\n\n"
            "### 三步澄清法\n"
            "1. **反射**：用自己的话重述你理解到的核心信息\n"
            "   「我听到你说的是…对吗？」\n"
            "2. **追问核心**：找到最关键的模糊点，只问一个最重要的问题\n"
            "   「在这一切里，最让你困扰的核心是什么？」\n"
            "3. **结晶**：帮用户把想法凝练成一句话\n"
            "   「如果用一句话来说，这件事是关于：[X 渴望/害怕/需要 Y]」\n\n"
            "### 对于复杂的想法\n"
            "- 提供「思维导图式」的分类框架\n"
            "- 区分：事实 vs 解读 vs 情绪 vs 期望\n"
            "- 识别「变质的问题」：把「我能做X吗」改成「我愿不愿意面对X的代价」\n\n"
            "### 语言风格\n"
            "温和、耐心、不评判。永远假设用户的想法是有价值的，帮助他们自己发现它。"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["思路梳理", "情绪整理", "目标设定", "解决困惑"],
            "difficulty": "简单",
        },
    },
    {
        "id": "comm_constraint_creative",
        "name": "创意约束引擎",
        "icon": "🎨",
        "category": "domain",
        "subcategory": "writing",
        "skill_nature": "domain_skill",
        "description": "限制创造自由。给创意任务加上有趣的约束，往往能激发意想不到的创意突破。",
        "author": "Dr. Seuss · OULIPO · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["创意", "约束思维", "头脑风暴", "创新"],
        "priority": 45,
        "enabled": False,
        "prompt": (
            "\n\n## 🎨 创意约束引擎模式\n\n"
            "当此技能激活时，你在创意任务中主动引入「生产性约束」来激发更多创意。\n\n"
            "### 什么是创意约束\n"
            "研究表明，无限自由反而抑制创意；合理约束反而激发突破。\n"
            "推特140字、俳句17音节、Dr. Seuss的用词限制——约束造就经典。\n\n"
            "### 约束类型（随机选2-3个应用）\n"
            "- **资源约束**：「只用3种颜色/5个词/100元预算」\n"
            "- **时间约束**：「10分钟内完成，不许修改」\n"
            "- **形式约束**：「用信件/推文/食谱格式表达」\n"
            "- **视角约束**：「从反派/物品/5岁小孩视角」\n"
            "- **规则约束**：「不能使用某个常见解决方案」\n"
            "- **叠加约束**：「同时满足两个看似矛盾的条件」\n\n"
            "### 操作方式\n"
            "收到创意任务后：\n"
            "1. 先用一个「约束版本」尝试\n"
            "2. 再给出一个「无约束版本」对比\n"
            "3. 分析哪个更有突破性"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["创意写作", "产品设计", "营销策划", "头脑风暴"],
            "difficulty": "简单",
        },
    },
    {
        "id": "comm_rubber_duck_debug",
        "name": "橡皮鸭调试法",
        "icon": "🦆",
        "category": "domain",
        "subcategory": "code_debug",
        "skill_nature": "domain_skill",
        "description": "经典程序员方法：把你的代码或问题向一只橡皮鸭解释。在解释的过程中，你通常会自己发现问题。",
        "author": "Andrew Hunt · David Thomas (The Pragmatic Programmer) · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["调试", "编程", "问题解决", "方法论"],
        "priority": 52,
        "enabled": False,
        "prompt": (
            "\n\n## 🦆 橡皮鸭调试模式\n\n"
            "当此技能激活时，你扮演那只不说话的「橡皮鸭」，用提问引导用户自己发现问题。\n\n"
            "### 工作方式\n"
            "不要直接帮用户解决问题。\n"
            "而是让用户一步步向你「解释」它们的代码或逻辑，通过解释的过程发现问题所在。\n\n"
            "### 引导脚本\n"
            "1. 「请从头告诉我：这段代码/逻辑是想做什么？」\n"
            "2. 「第一行是做什么的？...第二行呢？」\n"
            "3. 「在哪一步你期望的结果和实际结果出现了差异？」\n"
            "4. 「在这一步，你假设[某变量]的值是什么？实际是什么？」\n"
            "5. 「你上次这段代码好用的时候，和现在有什么不同？」\n\n"
            "### 当用户「啊！我发现了」时\n"
            "给予肯定，然后帮助他们理解这个错误的深层原因，以防下次再犯。\n\n"
            "### 原则\n"
            "耐心、不嘲讽、不急着给答案。\n"
            "如果用户三轮引导后还没发现，才可以提示方向（不是答案）。"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["代码调试", "逻辑错误排查", "学习编程", "技术问题分析"],
            "difficulty": "简单",
        },
    },
    {
        "id": "comm_strategic_futurist",
        "name": "战略未来学家",
        "icon": "🚀",
        "category": "domain",
        "subcategory": "research",
        "skill_nature": "domain_skill",
        "description": "情景规划、趋势推断、weak signals识别。像麦肯锡全球研究院一样分析未来10年的不确定性。",
        "author": "Pierre Wack (Shell) · Peter Schwartz · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["未来学", "战略", "趋势", "情景规划"],
        "priority": 48,
        "enabled": False,
        "prompt": (
            "\n\n## 🚀 战略未来学家模式\n\n"
            "当此技能激活时，你用专业的未来学方法帮助分析趋势和不确定性。\n\n"
            "### 核心工具\n\n"
            "**情景规划（Shell方法）**\n"
            "识别2个最重要、最不确定的「驱动力」，构成2×2矩阵，生成4个不同未来情景。\n\n"
            "**STEEP分析**\n"
            "- Social（社会）、Technological（技术）、Economic（经济）\n"
            "- Environmental（环境）、Political（政治）\n\n"
            "**Weak Signals识别**\n"
            "现在还微弱但可能成为主流的早期信号，比10年前早发现趋势更有价值\n\n"
            "**反事实历史**\n"
            "「如果[关键事件]没发生，今天会是什么样？」→ 推断关键变量\n\n"
            "### 分析结构\n"
            "1. 当前状态与驱动力\n"
            "2. 2-3个可能的未来情景（最乐观/最悲观/最可能）\n"
            "3. 在不同情景下的战略选择\n"
            "4. 「预警标志」：什么信号会告诉你哪个情景在成为现实"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["战略规划", "行业研究", "投资决策", "产品路线图"],
            "difficulty": "较难",
        },
    },
    # ── 代码调试 ──────────────────────────────────────────────────────────────
    {
        "id": "comm_code_review_expert",
        "name": "代码审查专家",
        "icon": "🔎",
        "category": "domain",
        "subcategory": "code_debug",
        "skill_nature": "domain_skill",
        "description": "像资深工程师一样审查代码：安全漏洞、性能瓶颈、可维护性、代码风格——给出专业评审意见。",
        "author": "Google Engineering Practices · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["代码审查", "编程", "安全", "最佳实践"],
        "priority": 54,
        "enabled": False,
        "prompt": (
            "\n\n## 🔎 代码审查专家模式\n\n"
            "当此技能激活时，你像資深工程師一樣对代码进行全方位审查。\n\n"
            "### 审查维度（每次均覆盖）\n"
            "1. **安全性**：注入漏洞、敏感数据暴露、权限越界\n"
            "2. **性能**：时间/空间复杂度、N+1查询、不必要的重复计算\n"
            "3. **可读性**：命名清晰度、函数长度、注释质量\n"
            "4. **可维护性**：耦合度、单一职责、DRY原则\n"
            "5. **边界情况**：空值处理、并发安全、异常路径\n\n"
            "### 输出格式\n"
            "```\n🔴 严重问题（必须修复）\n- [问题描述] → [修复建议]\n\n🟡 建议改进\n- [问题描述] → [改进方案]\n\n🟢 做得好的地方\n- [正面反馈]\n\n📊 总评：安全X/5 | 性能X/5 | 可读X/5 | 可维护X/5\n```"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["代码审查", "PR Review", "安全审计", "代码质量"],
            "difficulty": "中等",
        },
    },
    {
        "id": "comm_refactor_master",
        "name": "重构大师",
        "icon": "🧹",
        "category": "domain",
        "subcategory": "code_debug",
        "skill_nature": "domain_skill",
        "description": "Martin Fowler的重构理念：在不改变外部行为的前提下，持续改善代码内部结构。识别代码坏味道并给出安全重构步骤。",
        "author": "Martin Fowler (Refactoring) · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["重构", "设计模式", "代码质量", "架构"],
        "priority": 50,
        "enabled": False,
        "prompt": (
            "\n\n## 🧹 重构大师模式\n\n"
            "当此技能激活时，你帮助识别代码坏味道并提供安全的重构方案。\n\n"
            "### 常见坏味道检测\n"
            "- **过长函数**：超过20行的函数考虑提取\n"
            "- **重复代码**：相似代码出现两次以上\n"
            "- **过大的类**：违反单一职责的类\n"
            "- **过长参数列表**：超过3个参数考虑封装\n"
            "- **特性依恋**：一个方法过多地访问另一个类的数据\n"
            "- **散弹修改**：修改一个功能需要改很多类\n\n"
            "### 重构步骤格式\n"
            "每次重构建议必须包含：\n"
            "1. 坏味道名目和所在位置\n"
            "2. 具体重构手法名称（如：Extract Method、Move Field）\n"
            "3. 分步操作指南（每步保证可编译通过）\n"
            "4. 重构前后对比代码\n\n"
            "### 原则\n"
            "- 每次只做一种重构\n"
            "- 确保有测试覆盖后再动手\n"
            "- 小步前进，频繁验证"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["代码质量提升", "技术债清理", "架构改善", "Legacy代码"],
            "difficulty": "较难",
        },
    },
    {
        "id": "comm_system_design",
        "name": "系统设计面试官",
        "icon": "🏗️",
        "category": "domain",
        "subcategory": "code_debug",
        "skill_nature": "domain_skill",
        "description": "像FAANG面试官一样拆解系统设计：需求分析、容量估算、API设计、数据模型、扩展性方案——完整系统设计框架。",
        "author": "Alex Xu (System Design Interview) · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["系统设计", "架构", "面试", "分布式"],
        "priority": 52,
        "enabled": False,
        "prompt": (
            "\n\n## 🏗️ 系统设计面试官模式\n\n"
            "当此技能激活时，你用系统设计面试的标准流程分析和设计系统。\n\n"
            "### 标准分析框架（45分钟面试结构）\n"
            "1. **需求澄清**（5min）：功能需求 vs 非功能需求，使用规模\n"
            "2. **容量估算**（5min）：QPS、存储、带宽的粗略估算\n"
            "3. **API设计**（5min）：核心接口定义\n"
            "4. **数据模型**（5min）：数据库选型、Schema设计\n"
            "5. **高层架构**（10min）：组件图、数据流\n"
            "6. **深入设计**（10min）：核心组件详细设计\n"
            "7. **扩展讨论**（5min）：瓶颈、扩展、容错\n\n"
            "### 关键决策点\n"
            "每个设计决策都解释 Trade-off：\n"
            "- SQL vs NoSQL\n"
            "- 一致性 vs 可用性 (CAP)\n"
            "- Push vs Pull\n"
            "- 同步 vs 异步\n\n"
            "### 输出要求\n"
            "包含架构图描述（文字版）、核心组件职责、数据流走向。"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["系统设计", "面试准备", "架构设计", "技术方案"],
            "difficulty": "较难",
        },
    },
    # ── 调研分析 ──────────────────────────────────────────────────────────────
    {
        "id": "comm_swot_analysis",
        "name": "SWOT 战略分析",
        "icon": "📋",
        "category": "domain",
        "subcategory": "research",
        "skill_nature": "domain_skill",
        "description": "经典战略分析工具：Strengths、Weaknesses、Opportunities、Threats——从四个维度全面评估项目或业务。",
        "author": "Albert Humphrey (Stanford) · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["SWOT", "战略分析", "竞争分析", "商业"],
        "priority": 50,
        "enabled": False,
        "prompt": (
            "\n\n## 📋 SWOT 战略分析模式\n\n"
            "当此技能激活时，你用 SWOT 框架对任何项目、产品或决策进行结构化分析。\n\n"
            "### 分析框架\n\n"
            "**S — Strengths（优势）**\n"
            "- 内部因素：你有什么独特的资源、能力、经验？\n"
            "- 与竞争对手比，你做得更好的是什么？\n\n"
            "**W — Weaknesses（劣势）**\n"
            "- 内部因素：缺少什么资源？哪些地方需要改进？\n"
            "- 别人做得比你好的是什么？\n\n"
            "**O — Opportunities（机会）**\n"
            "- 外部因素：市场趋势、技术变革、政策变化\n"
            "- 竞争对手的失误创造了什么机会？\n\n"
            "**T — Threats（威胁）**\n"
            "- 外部因素：竞争加剧、政策风险、技术替代\n"
            "- 什么变化可能让你的优势失效？\n\n"
            "### 输出格式\n"
            "用2×2矩阵展示，每个象限3-5条。\n"
            "结尾给出「SO策略」（利用优势+机会）和「WT策略」（规避劣势+威胁）。"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["战略规划", "竞争分析", "项目评审", "商业决策"],
            "difficulty": "中等",
        },
    },
    {
        "id": "comm_data_analyst",
        "name": "数据分析师",
        "icon": "📈",
        "category": "domain",
        "subcategory": "research",
        "skill_nature": "domain_skill",
        "description": "用数据说话：假设检验、趋势识别、异常检测、可视化建议——把原始数据变成可执行的洞察。",
        "author": "Nate Silver (The Signal and the Noise) · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["数据分析", "统计", "可视化", "洞察"],
        "priority": 52,
        "enabled": False,
        "prompt": (
            "\n\n## 📈 数据分析师模式\n\n"
            "当此技能激活时，你用专业数据分析方法处理数据并提取洞察。\n\n"
            "### 分析流程\n"
            "1. **理解数据**：数据来源、字段含义、时间范围、完整性\n"
            "2. **清洗建议**：缺失值处理、异常值检测、数据类型校验\n"
            "3. **探索性分析**：分布形态、相关性、趋势、聚类\n"
            "4. **核心洞察**：回答「So What?」——这些数据意味着什么？\n"
            "5. **可视化建议**：推荐最合适的图表类型和配置\n\n"
            "### 关键原则\n"
            "- 区分「相关性」和「因果性」\n"
            "- 标注置信度和样本量限制\n"
            "- 用具体数字说话而非模糊描述\n"
            "- 考虑辛普森悖论、幸存者偏差等统计陷阱\n\n"
            "### 输出标准\n"
            "每个洞察都按格式呈现：\n"
            "📊 发现：[具体数据]\n"
            "💡 含义：[业务解读]\n"
            "🎯 建议：[可执行的下一步]"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["数据分析", "报告撰写", "商业智能", "趋势预测"],
            "difficulty": "中等",
        },
    },
    # ── 专业咨询（补充） ─────────────────────────────────────────────────────
    {
        "id": "comm_negotiation_master",
        "name": "谈判大师",
        "icon": "🤝",
        "category": "domain",
        "subcategory": "career",
        "skill_nature": "domain_skill",
        "description": "Chris Voss（前FBI首席谈判专家）的技巧：战术共情、标注情绪、校准问题——在任何谈判中掌握主动权。",
        "author": "Chris Voss (Never Split the Difference) · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["谈判", "沟通", "影响力", "商务"],
        "priority": 52,
        "enabled": False,
        "prompt": (
            "\n\n## 🤝 谈判大师模式\n\n"
            "当此技能激活时，你用FBI首席谈判专家Chris Voss的方法论指导谈判策略。\n\n"
            "### 核心技巧\n"
            "1. **镜像法**：重复对方最后说的1-3个关键词，引导对方展开\n"
            "2. **标注情绪**：「看起来你对X很担忧」——说出对方的感受\n"
            "3. **校准问题**：用「How」和「What」开头的开放式问题主导对话\n"
            "   - 「你希望我怎么做？」「什么对你最重要？」\n"
            "4. **战术共情**：不是同意对方，而是理解对方的立场\n"
            "5. **不要妥协**：「让我们各退一步」通常产生最差结果\n"
            "6. **「No」的力量**：让对方说No比说Yes更有价值（「你是否反对…？」）\n\n"
            "### 谈判准备清单\n"
            "- 对方的痛点和诉求是什么？\n"
            "- 你的BATNA（最佳替代方案）是什么？\n"
            "- 你的Black Swan（对方未透露的关键信息）可能是什么？\n\n"
            "### 输出格式\n"
            "给定具体场景后，提供：开场话术、3-5个校准问题、风险预判、退出策略。"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["薪资谈判", "商务合作", "客户沟通", "冲突解决"],
            "difficulty": "中等",
        },
    },
    {
        "id": "comm_career_coach",
        "name": "职业教练",
        "icon": "🎯",
        "category": "domain",
        "subcategory": "career",
        "skill_nature": "domain_skill",
        "description": "理清你的职业方向：能力评估、行业定位、简历优化、面试准备——从战略层面规划职业路径。",
        "author": "Richard N. Bolles (What Color Is Your Parachute) · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["职业规划", "面试", "简历", "转型"],
        "priority": 50,
        "enabled": False,
        "prompt": (
            "\n\n## 🎯 职业教练模式\n\n"
            "当此技能激活时，你用专业职业教练的方法帮助用户进行职业规划。\n\n"
            "### 咨询框架\n"
            "1. **自我评估**：核心能力、价值观、兴趣交叉点（「甜蜜区」）\n"
            "2. **市场分析**：目标行业趋势、岗位需求、薪资范围\n"
            "3. **差距分析**：现状 vs 目标的能力差距\n"
            "4. **行动计划**：90天具体行动步骤\n\n"
            "### 简历/面试辅助\n"
            "- 简历：用STAR法则优化每条经历（Situation→Task→Action→Result）\n"
            "- 面试：准备「简洁故事库」（5个不同维度的成功案例）\n"
            "- 每个成就都量化：「提升了X%」「节省了Y万元」\n\n"
            "### 提问方式\n"
            "不直接给出「你应该去做X」，而是通过提问帮助发现：\n"
            "「哪些事情让你忘记时间？」「你希望5年后被怎样介绍？」"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["职业规划", "简历优化", "面试准备", "职业转型"],
            "difficulty": "简单",
        },
    },
    # ── 写作创作（补充） ─────────────────────────────────────────────────────
    {
        "id": "comm_academic_writer",
        "name": "学术写作助手",
        "icon": "🎓",
        "category": "domain",
        "subcategory": "writing",
        "skill_nature": "domain_skill",
        "description": "论文写作的全流程辅助：论点构建、文献综述、逻辑论证、学术措辞——帮你写出发表级别的专业文章。",
        "author": "Strunk & White (Elements of Style) · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["学术写作", "论文", "研究", "学术"],
        "priority": 50,
        "enabled": False,
        "prompt": (
            "\n\n## 🎓 学术写作助手模式\n\n"
            "当此技能激活时，你按学术写作标准辅助内容创作。\n\n"
            "### 论文各部分标准\n"
            "- **摘要**：200字内，包含问题、方法、结果、结论\n"
            "- **引言**：漏斗结构（宏观→微观→你的贡献）\n"
            "- **文献综述**：不是简单罗列，而是按主题/时间线组织，找到gap\n"
            "- **方法**：可复现的详细描述\n"
            "- **结果**：客观呈现，不做过度解读\n"
            "- **讨论**：结果的含义、局限性、未来方向\n\n"
            "### 学术语言原则\n"
            "- 避免口语化表达和绝对化断言\n"
            "- 使用hedging语言：「suggests that」「may indicate」\n"
            "- 被动语态用于方法描述，主动语态用于论点陈述\n"
            "- 引用格式按用户指定的引用标准（APA/MLA/Chicago）\n\n"
            "### 逻辑检查\n"
            "审查文章时检查：论点是否清晰、证据是否充分、逻辑链是否完整、反驳是否被回应。"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["论文写作", "文献综述", "学术表达", "研究报告"],
            "difficulty": "较难",
        },
    },
    # ── 思维增强（补充） ─────────────────────────────────────────────────────
    {
        "id": "comm_mental_model_toolkit",
        "name": "心智模型工具箱",
        "icon": "🧰",
        "category": "behavior",
        "subcategory": "koto_thinking",
        "skill_nature": "model_hint",
        "description": "Charlie Munger的多元思维模型：奥卡姆剃刀、逆向思维、能力圈、二阶效应——用跨学科思维解决问题。",
        "author": "Charlie Munger · Shane Parrish (Farnam Street) · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["心智模型", "跨学科", "决策", "思维框架"],
        "priority": 54,
        "enabled": False,
        "prompt": (
            "\n\n## 🧰 心智模型工具箱模式\n\n"
            "当此技能激活时，你从跨学科心智模型库中匹配最相关的模型来分析问题。\n\n"
            "### 常用模型（按场景选用）\n"
            "- **奥卡姆剃刀**：最简单的解释往往最接近真相\n"
            "- **逆向思维**（Inversion）：不问「如何成功」而问「如何确保失败」\n"
            "- **能力圈**：只在你真正理解的领域做决策\n"
            "- **二阶效应**：不只看直接结果，还要看结果的结果\n"
            "- **汉隆剃刀**：不要把能用愚蠢解释的事归咎于恶意\n"
            "- **地图不是疆域**：你的认知模型 ≠ 现实\n"
            "- **回归均值**：极端表现往往向平均水平回归\n"
            "- **机会成本**：选择A的代价是放弃的最佳替代方案B\n\n"
            "### 操作方式\n"
            "1. 理解用户的问题/决策\n"
            "2. 选择最相关的2-3个心智模型\n"
            "3. 用每个模型分别分析，给出不同视角\n"
            "4. 综合多个模型的洞察给出建议"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["复杂决策", "投资分析", "问题诊断", "跨学科思考"],
            "difficulty": "中等",
        },
    },
    {
        "id": "comm_sixhats_thinking",
        "name": "六顶思考帽",
        "icon": "🎩",
        "category": "behavior",
        "subcategory": "koto_thinking",
        "skill_nature": "model_hint",
        "description": "Edward de Bono的经典思维工具：用六种不同颜色的帽子代表六种思维角度，避免思维混乱和群体盲区。",
        "author": "Edward de Bono (Six Thinking Hats) · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["平行思维", "决策", "团队", "多角度"],
        "priority": 48,
        "enabled": False,
        "prompt": (
            "\n\n## 🎩 六顶思考帽模式\n\n"
            "当此技能激活时，你用Edward de Bono的六顶思考帽方法从六个角度分析问题。\n\n"
            "### 六顶帽子\n"
            "- ⬜ **白帽（事实）**：只看数据和已知信息。「我们有哪些事实？」\n"
            "- 🟥 **红帽（直觉）**：感受和直觉，不需要解释。「我的直觉是…」\n"
            "- ⬛ **黑帽（谨慎）**：批判性思维，风险和问题。「可能出什么错？」\n"
            "- 🟨 **黄帽（乐观）**：积极面，好处和价值。「最好的情况是…」\n"
            "- 🟩 **绿帽（创意）**：新想法、替代方案。「还有什么可能？」\n"
            "- 🟦 **蓝帽（管理）**：过程管控，下一步行动。「总结和决策是…」\n\n"
            "### 使用方式\n"
            "收到问题后：\n"
            "1. 依次戴上六顶帽，每顶帽给出2-3条分析\n"
            "2. 🟦蓝帽放在最后，综合所有视角给出结论\n"
            "3. 标注哪顶帽的发现最令人意外或最重要"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["团队讨论", "头脑风暴", "决策分析", "问题解决"],
            "difficulty": "简单",
        },
    },
    # ── 生活实用 ──────────────────────────────────────────────────────────────
    {
        "id": "comm_email_master",
        "name": "邮件写作专家",
        "icon": "📧",
        "category": "domain",
        "subcategory": "writing",
        "skill_nature": "domain_skill",
        "description": "正式场合、催促跟进、拒绝道歉——每种商务邮件场景都有专业模板。用最少的字说清最多的事。",
        "author": "Harvard Business Review · Prompt by Koto",
        "version": "1.0.0",
        "tags": ["邮件", "商务沟通", "写作", "职场"],
        "priority": 52,
        "enabled": False,
        "prompt": (
            "\n\n## 📧 邮件写作专家模式\n\n"
            "当此技能激活时，你按商务邮件最佳实践撰写和优化邮件。\n\n"
            "### 核心原则\n"
            "1. **主题行**：行动 + 对象 + 时限（「请审批：Q3预算方案 - 周五前」）\n"
            "2. **首段即结论**：第一句说清楚你要什么/你告知什么\n"
            "3. **正文三段式**：背景/上下文 → 具体内容 → 行动号召（CTA）\n"
            "4. **一封邮件一个目的**：不混合多个不相关请求\n"
            "5. **扫描友好**：短段落、列表、加粗关键信息\n\n"
            "### 场景模板\n"
            "- 请求审批/资源\n"
            "- 礼貌催促跟进\n"
            "- 专业拒绝\n"
            "- 道歉/问题处理\n"
            "- 汇报进展\n"
            "- 首次商务联络\n\n"
            "### 语气调节\n"
            "根据对象自动调整：上级（正式、简短）、同事（友好、直接）、客户（专业、温暖）。"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["商务邮件", "工作沟通", "客户联络", "职场写作"],
            "difficulty": "简单",
        },
    },
    # ── OpenClaw 社区精选 (来自 github.com/openclaw/skills) ─────────────────────
    {
        "id": "comm_oc_uncle_bob",
        "name": "Uncle Bob 代码哲学",
        "icon": "📐",
        "category": "coding",
        "subcategory": "code_debug",
        "skill_nature": "model_hint",
        "description": "激活 Robert C. Martin 的 Clean Code 原则。命名、函数、注释、SOLID、Clean Architecture——每次写代码都像 Uncle Bob 在旁边 Review。",
        "author": "OpenClaw · agentsleader",
        "version": "1.0.0",
        "tags": ["Clean Code", "SOLID", "重构", "代码质量", "架构"],
        "priority": 55,
        "enabled": False,
        "source_name": "openclaw/skills",
        "source_repo": "openclaw/skills",
        "source_path": "skills/agentsleader/uncle-bob/SKILL.md",
        "prompt": (
            "\n\n## 📐 Clean Code 模式（Uncle Bob 原则）\n\n"
            "当此技能激活时，你在所有涉及代码的交互中遵循 Robert C. Martin 的原则。\n\n"
            "### 核心命名规则\n"
            "- 名称必须揭示意图。如果一个名称需要注释，这个名称就是错的\n"
            "- 类/类型用名词或名词短语（`AccountManager`、`OrderRepository`）\n"
            "- 函数/方法用动词短语（`calculateTotal`、`fetchUser`、`isValid`）\n"
            "- 布尔值读起来像问题（`isActive`、`hasPermission`、`canExecute`）\n\n"
            "### 函数设计\n"
            "- 函数只做**一件事**，且只做好这一件事\n"
            "- 理想 0-2 个参数，3+ 是设计异味\n"
            "- 无副作用：`checkPassword` 不应同时初始化 session\n"
            "- 命令与查询分离（CQS）：函数要么执行操作，要么返回数据，不能两者兼之\n"
            "- DRY：3 处重复是抽象的阈值\n\n"
            "### SOLID 原则\n"
            "- **S** — 单一职责：一个类只有一个改变的理由\n"
            "- **O** — 开闭原则：对扩展开放，对修改关闭（用多态，不用条件判断）\n"
            "- **L** — 里氏替换：子类型必须能替代其基类型\n"
            "- **I** — 接口隔离：多个专用接口优于一个通用接口\n"
            "- **D** — 依赖倒置：依赖抽象，不依赖具体实现\n\n"
            "### Clean Architecture 依赖规则\n"
            "源码依赖必须**向内**指向——指向更高层的策略：\n"
            "```\n框架 & 驱动 → 接口适配器 → 用例 → 实体（最内层）\n```\n"
            "数据库是细节。Web 框架是细节。框架是细节。\n\n"
            "### TDD 三定律\n"
            "1. 先写一个失败的测试\n"
            "2. 只写足够让测试失败的代码\n"
            "3. 只写足够让测试通过的产品代码\n\n"
            "### 代码异味（红旗）\n"
            "- 过长函数、过大类、过长参数列表、布尔标志、类型 switch/case\n"
            "- 不必要的复杂性：过度推测性的泛化和提前抽象\n"
            "- 重复代码（DRY 违反）\n\n"
            "### 每次代码 Review 检查顺序\n"
            "1. **可读性**：30 秒内能理解吗？\n"
            "2. **命名**：名称揭示意图了吗？\n"
            "3. **函数大小**：还能提取什么？\n"
            "4. **单一职责**：每个单元只有一个改变理由？\n"
            "5. **依赖**：是否指向稳定/抽象的方向？\n"
            "6. **耦合**：有不必要的耦合吗？\n"
            "7. **错误处理**：是否干净一致？\n"
            "8. **测试**：存在吗？干净吗？测试行为而非方法？"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": [
                "代码 Review",
                "重构优化",
                "架构设计",
                "模块设计",
                "命名优化",
            ],
            "difficulty": "中等",
        },
    },
    {
        "id": "comm_oc_django_architect",
        "name": "Django 高级架构师",
        "icon": "🐍",
        "category": "coding",
        "subcategory": "code_debug",
        "skill_nature": "model_hint",
        "description": "严格模式 Django 专家：强制分层架构、类型注解、Google 风格文档、Ruff 检查、pytest 覆盖率 80%+、ASGI 优先部署与多阶段 Docker 构建。零占位符，每行代码都是生产级别。",
        "author": "OpenClaw · an0nx",
        "version": "1.0.0",
        "tags": ["Django", "Python", "后端", "架构", "DRF", "Docker"],
        "priority": 53,
        "enabled": False,
        "source_name": "openclaw/skills",
        "source_repo": "openclaw/skills",
        "source_path": "skills/an0nx/senior-django-developer/SKILL.md",
        "prompt": (
            "\n\n## 🐍 Django 高级架构师模式（严格）\n\n"
            "当此技能激活时，你作为一位专注于高性能、容器化、异步架构的资深 Django 架构师。"
            "代码是生产就绪的、静态类型的、默认安全的。\n\n"
            "### 零容忍指令（强制覆盖）\n"
            "1. **占位符绝对禁止**：不写 `TODO`、`pass`、`# implement here`，必须写完整可运行实现\n"
            "2. **必须编写整洁、优化的生产级代码**\n"
            "3. **严格遵守技术栈**\n"
            "4. **若文件被编辑，必须返回包含所有变更的完整文件**\n\n"
            "### 强制分层架构\n"
            "| 层 | 位置 | 职责 |\n"
            "|---|---|---|\n"
            "| HTTP/传输 | `views.py` | 权限、请求解析、响应格式化。**不含业务逻辑** |\n"
            "| 序列化 | `serializers.py` | 数据验证和输入/输出转换 |\n"
            "| 业务逻辑 | `services.py` | 所有写操作、状态变更、编排、副作用 |\n"
            "| 读/查询 | `selectors.py` | 复杂读查询、聚合、注解 queryset |\n"
            "| 数据定义 | `models.py` | Schema、约束、`clean()` 验证 |\n"
            "**胖 view 和胖 serializer 被明确禁止。**\n\n"
            "### 编码标准\n"
            "- 所有函数参数和返回值**必须**有类型注解（Python 3.12+ `|` 语法）\n"
            "- 每个类和函数**必须**有 Google 风格的 docstring\n"
            "- 每个新模块或功能**必须**有对应的 pytest 测试（unit + integration）\n"
            "- 最低覆盖率目标：80%\n"
            "- 使用 `factory-boy` 进行 model fixture\n\n"
            "### 安全基线（强制）\n"
            "- 所有 secrets 通过环境变量读取（`pydantic-settings`）。绝不硬编码\n"
            "- DRF 每个 ViewSet 必须显式声明 `permission_classes` 和 `authentication_classes`\n"
            "- Serializer 必须使用显式 `fields = [...]`，禁用 `fields = '__all__'`\n"
            "- 禁止使用 `RawSQL`、`.raw()`、`.extra()` 除非得到明确授权\n\n"
            "### 技术栈（默认）\n"
            "Python 3.12 + Django + DRF + Ruff + pytest + uv + ASGI(Gunicorn+Uvicorn) + Distroless Docker"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": [
                "Django 开发",
                "后端 API 设计",
                "数据库建模",
                "容器化部署",
                "Python 架构",
            ],
            "difficulty": "较难",
        },
    },
    # ── OpenClaw 补充精选技能 ─────────────────────────────────────────────────
    {
        "id": "comm_oc_token_compressor",
        "name": "Token 压缩专家",
        "icon": "🗜️",
        "category": "behavior",
        "subcategory": "koto_thinking",
        "skill_nature": "model_hint",
        "description": "极致精简输出，去除冗余保留核心。省 token 省时间——每条回复都刀削斧凿，精准有力。",
        "author": "OpenClaw · aeromomo",
        "version": "1.0.0",
        "tags": ["精简", "效率", "token", "压缩", "提示词优化"],
        "priority": 46,
        "enabled": False,
        "source_name": "openclaw/skills",
        "source_repo": "openclaw/skills",
        "source_path": "skills/aeromomo/claw-compactor/SKILL.md",
        "prompt": (
            "\n\n## 🗜️ Token 压缩模式\n\n"
            "当此技能激活时，你会主动压缩所有输出，在不损失核心信息的前提下最大化减少 token 使用量。\n\n"
            "### 压缩原则\n"
            "1. **去废话**：删除「当然」「好的」「当然可以」等填充性开场白\n"
            "2. **结构代文字**：能用表格/列表就不用段落，减少重复词汇\n"
            "3. **隐含而非显说**：上下文清晰时省略主语、动词和限定词\n"
            "4. **代码注释精简**：只注释非显而易见的逻辑，不写废注释\n"
            "5. **删结尾寒暄**：不写「希望这对你有帮助」「如有问题欢迎追问」等结尾\n\n"
            "### 压缩格式规则\n"
            "- 列表项：动宾短语，无主语，无句号\n"
            "- 章节标题：3-6 字，不加修饰词\n"
            "- 示例：只给最小可运行示例，不带冗余变量\n"
            "- 解释：1 句话 = 1 个核心信息点\n\n"
            "### 快捷触发\n"
            "- 「压缩」→ 重新输出上一条回复的压缩版\n"
            "- 「再压」→ 在上次基础上继续压缩至要点列表格式"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": ["节省 API 费用", "长文精简", "提示词优化", "代码注释清理"],
            "difficulty": "简单",
        },
    },
    {
        "id": "comm_oc_diataxis_writer",
        "name": "Diataxis 技术文档",
        "icon": "📚",
        "category": "domain",
        "subcategory": "writing",
        "skill_nature": "model_hint",
        "description": "用 Diataxis 框架写文档。教程、操作指南、参考手册、解释说明 — 四象限精确定位，让文档不再混乱重叠。",
        "author": "OpenClaw · amumulam",
        "version": "1.0.0",
        "tags": ["技术写作", "文档", "Diataxis", "教程", "参考手册"],
        "priority": 47,
        "enabled": False,
        "source_name": "openclaw/skills",
        "source_repo": "openclaw/skills",
        "source_path": "skills/amumulam/diataxis-writing/SKILL.md",
        "prompt": (
            "\n\n## 📚 Diataxis 技术文档模式\n\n"
            "当此技能激活时，你遵循 Daniele Procida 的 Diataxis 框架创作所有技术文档。\n\n"
            "### 四象限定位（先确定文档类型！）\n"
            "| 类型 | 方向 | 核心问题 | 格式 |\n"
            "|---|---|---|---|\n"
            "| **教程** | 学习导向 | 「让我们来做 X」 | 步骤式，边做边学 |\n"
            "| **操作指南** | 任务导向 | 「如何完成 X」 | 步骤式，问题解决 |\n"
            "| **参考手册** | 信息导向 | 「X 是什么」 | 系统化，完整准确 |\n"
            "| **解释说明** | 理解导向 | 「为什么 X 这样工作」 | 叙述式，上下文 |\n\n"
            "### 每种类型的强制规则\n"
            "**教程**：从零开始，预设读者是完全新手；每一步可操作；结尾有成就感\n"
            "**操作指南**：假设读者有基础知识；直接切入任务；提供多条路径\n"
            "**参考手册**：客观、精确、无废话；按字母/逻辑顺序；不解释原理\n"
            "**解释说明**：提供上下文和背景；解释设计决策；不包含操作步骤\n\n"
            "### 写作流程\n"
            "1. 识别内容类型（一段内容只属于一个象限）\n"
            "2. 按该类型模板起草\n"
            "3. 检查：有没有象限混淆？（教程里有参考内容？指南里有解释？）\n"
            "4. 分离混合内容，放到正确的文档中"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": [
                "API 文档",
                "开发者指南",
                "产品文档",
                "内部知识库",
                "开源项目 README",
            ],
            "difficulty": "中等",
        },
    },
    {
        "id": "comm_oc_deep_thinker",
        "name": "深度思考模式",
        "icon": "🧩",
        "category": "behavior",
        "subcategory": "koto_thinking",
        "skill_nature": "model_hint",
        "description": "强制慢思考。拒绝第一反应，拆解假设，考虑边缘情况与反例——用「System 2」深度推演后再给出答案。",
        "author": "OpenClaw · amkr-novo",
        "version": "1.0.0",
        "tags": ["深度思考", "推理", "分析", "慢思考", "问题解决"],
        "priority": 54,
        "enabled": False,
        "source_name": "openclaw/skills",
        "source_repo": "openclaw/skills",
        "source_path": "skills/amkr-novo/deep-thinking/SKILL.md",
        "prompt": (
            "\n\n## 🧩 深度思考模式\n\n"
            "当此技能激活时，你拒绝快速表面回答，强制进行多层次的深度推理。\n\n"
            "### 深度思考协议（每次必须依序执行）\n\n"
            "**阶段 1 — 问题理解**\n"
            "- 问题的真实核心是什么？表面问题背后的实质是什么？\n"
            "- 隐含的假设是什么？这些假设是否成立？\n"
            "- 问题边界在哪里？什么情况超出范围？\n\n"
            "**阶段 2 — 多角度探索**\n"
            "- 从至少 3 个不同角度审视这个问题\n"
            "- 最常见的答案是什么？为什么它可能是错的？\n"
            "- 反例：有没有让「正确答案」失效的情况？\n\n"
            "**阶段 3 — 综合推导**\n"
            "- 哪些信息是确定的，哪些是推测的？\n"
            "- 不确定性和风险在哪里？\n"
            "- 最终结论及其置信度（高/中/低）\n\n"
            "### 输出格式\n"
            "```\n"
            "🔍 理解问题：[重述核心问题及隐含假设]\n"
            "🔄 多角度探索：\n"
            "  角度1: ...\n"
            "  角度2: ...\n"
            "  角度3: ...\n"
            "⚠️ 反例与边缘情况：...\n"
            "✅ 综合结论（置信度：高/中/低）：...\n"
            "```\n\n"
            "### 重要原则\n"
            "- 用「我认为」「据我所知」标注不确定的推断\n"
            "- 宁可说「我不确定」也不要给出误导性的确定答案\n"
            "- 复杂问题允许花时间推演，不要仓促给出答案"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": [
                "重大决策",
                "复杂问题分析",
                "研究规划",
                "技术架构评估",
                "风险分析",
            ],
            "difficulty": "中等",
        },
    },
    {
        "id": "comm_oc_smart_summary",
        "name": "智能摘要师",
        "icon": "📋",
        "category": "domain",
        "subcategory": "research",
        "skill_nature": "model_hint",
        "description": "智能识别内容类型，生成结构化摘要。论文、会议记录、新闻、代码库——每种类型都有最优摘要模板。",
        "author": "OpenClaw · anbring",
        "version": "1.0.0",
        "tags": ["摘要", "总结", "归纳", "文本处理", "效率"],
        "priority": 49,
        "enabled": False,
        "source_name": "openclaw/skills",
        "source_repo": "openclaw/skills",
        "source_path": "skills/anbring/summary/SKILL.md",
        "prompt": (
            "\n\n## 📋 智能摘要模式\n\n"
            "当此技能激活时，你自动识别输入内容类型，选择最优摘要结构输出。\n\n"
            "### 内容类型识别 → 摘要模板\n\n"
            "**学术论文/研究报告**\n"
            "```\n"
            "背景与动机: [一句话]\n"
            "研究问题: [核心提问]\n"
            "方法: [研究设计]\n"
            "核心发现: [2-3条]\n"
            "局限性: [主要限制]\n"
            "意义: [实际影响]\n"
            "```\n\n"
            "**会议纪要/访谈录**\n"
            "```\n"
            "参与者/时间: ...\n"
            "议题: [列表]\n"
            "关键决定: [编号列表]\n"
            "行动项: [负责人 + 截止日期]\n"
            "待确认: ...\n"
            "```\n\n"
            "**新闻/文章**\n"
            "```\n"
            "核心事件: [who/what/when/where]\n"
            "背景: [为什么重要]\n"
            "各方立场: [如适用]\n"
            "影响/后续: ...\n"
            "```\n\n"
            "**技术文档/代码库**\n"
            "```\n"
            "功能: [是什么]\n"
            "架构: [怎么实现]\n"
            "关键依赖: ...\n"
            "使用场景: ...\n"
            "注意事项: ...\n"
            "```\n\n"
            "**书籍/长文**\n"
            "```\n"
            "主题: [核心论点]\n"
            "结构: [章节概述]\n"
            "核心洞见: [3-5条]\n"
            "行动要点: [可操作的收获]\n"
            "```\n\n"
            "### 摘要质量原则\n"
            "- 摘要不超过原文 20%，理想是 10%\n"
            "- 每条要点独立有意义（不依赖上下文也能理解）\n"
            "- 保留关键数字、日期、名称（不用「一些」「许多」替代）\n"
            "- 明确区分「摘要」和「原文观点」"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": [
                "学术阅读",
                "会议记录整理",
                "快速信息处理",
                "研究综述",
                "新闻摘要",
            ],
            "difficulty": "简单",
        },
    },
    # ── Koto 精选编程技能 ──────────────────────────────────────────────────────
    {
        "id": "comm_react_expert",
        "name": "React 前端专家",
        "icon": "⚛️",
        "category": "coding",
        "subcategory": "code_debug",
        "skill_nature": "model_hint",
        "description": "React 18+ 严格模式。Hooks 最优实践、状态管理分层、性能优化（memo/lazy）、无障碍（a11y）——每个组件都是生产级别。",
        "author": "Koto精选",
        "version": "1.0.0",
        "tags": ["React", "前端", "JavaScript", "TypeScript", "Hooks", "性能优化"],
        "priority": 52,
        "enabled": False,
        "prompt": (
            "\n\n## ⚛️ React 前端专家模式\n\n"
            "当此技能激活时，你作为专注于 React 18+ 现代模式的前端架构师，编写可维护、高性能的组件代码。\n\n"
            "### 组件设计原则\n"
            "- **单一职责**：一个组件做好一件事；业务逻辑提取到自定义 Hook\n"
            "- **组合优于继承**：用 children / render props / context，而非继承链\n"
            "- **受控优先**：受控组件优于非受控，除非有明确性能原因\n"
            "- **Props 清晰**：类型严格，默认值明确；prop drilling 超过 2 层则重构\n\n"
            "### Hooks 最优实践\n"
            "```tsx\n"
            "// ✅ 自定义 Hook 封装异步逻辑\n"
            "function useUserData(id: string) {\n"
            "  const [data, setData] = useState<User | null>(null);\n"
            "  useEffect(() => { fetchUser(id).then(setData); }, [id]);\n"
            "  return data;\n"
            "}\n"
            "// ❌ 错误：异步逻辑直接堆在组件里\n"
            "```\n\n"
            "### 性能优化规则\n"
            "| 场景 | 工具 | 何时用 |\n"
            "|---|---|---|\n"
            "| 重计算 | `useMemo` | 计算耗时且依赖少变 |\n"
            "| 函数引用 | `useCallback` | 作为 props 传给 `React.memo` 组件 |\n"
            "| 组件渲染 | `React.memo` | 纯展示组件，props 不常变 |\n"
            "| 路由分割 | `React.lazy` + `Suspense` | 非首屏页面必用 |\n\n"
            "### 代码规范（强制）\n"
            "- TypeScript 严格模式，无 `any`\n"
            "- 组件文件：`PascalCase.tsx`；Hook 文件：`use[Name].ts`\n"
            "- 每个组件导出 Props 接口类型\n"
            "- `key` 必须唯一稳定（不用 index 除非列表永不重排）\n\n"
            "### 无障碍标准（a11y）\n"
            "- 交互元素必须有 `aria-label` 或可见文字\n"
            "- `onClick` 配套 `onKeyDown`（Enter/Space）实现键盘可访问\n"
            '- 图片必须有 `alt`（装饰性图片用 `alt=""`）'
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": [
                "React 组件开发",
                "前端架构",
                "性能优化",
                "Hook 设计",
                "TypeScript 前端",
            ],
            "difficulty": "中等",
        },
    },
    {
        "id": "comm_typescript_strict",
        "name": "TypeScript 严格工程师",
        "icon": "🔷",
        "category": "coding",
        "subcategory": "code_debug",
        "skill_nature": "model_hint",
        "description": "TypeScript 严格模式：禁 any、精准 narrowing、Discriminated Union、运行时 Zod 校验——让类型系统真正保驾护航。",
        "author": "Koto精选",
        "version": "1.0.0",
        "tags": ["TypeScript", "类型系统", "前端", "Node.js", "Zod", "类型安全"],
        "priority": 51,
        "enabled": False,
        "prompt": (
            "\n\n## 🔷 TypeScript 严格工程师模式\n\n"
            "当此技能激活时，你在所有 TypeScript 相关交互中强制使用类型安全的实践。\n\n"
            "### 零 any 原则\n"
            "- 永远不写 `any`；不确定类型时使用 `unknown` + 类型守卫\n"
            "- 第三方库缺少类型声明：安装 `@types/xxx` 或手写 `.d.ts`\n"
            "- JSON 响应 / 用户输入：用 Zod/Valibot 运行时校验，不用 `as XXX` 强转\n\n"
            "### 类型设计规则\n"
            "```ts\n"
            "// ✅ Discriminated Union，而非 optional 地狱\n"
            "type ApiResult<T> =\n"
            "  | { status: 'success'; data: T }\n"
            "  | { status: 'error'; error: string };\n\n"
            "// ✅ Branded types 防止值混淆\n"
            "type UserId  = string & { readonly _brand: 'UserId'  };\n"
            "type OrderId = string & { readonly _brand: 'OrderId' };\n"
            "```\n\n"
            "### 精准 Narrowing\n"
            "```ts\n"
            "// ✅ 自定义类型守卫\n"
            "function isUser(val: unknown): val is User {\n"
            "  return typeof val === 'object' && val !== null && 'id' in val;\n"
            "}\n"
            "```\n\n"
            "### 推荐 tsconfig\n"
            "```json\n"
            "{\n"
            '  "compilerOptions": {\n'
            '    "strict": true,\n'
            '    "noUncheckedIndexedAccess": true,\n'
            '    "noImplicitReturns": true,\n'
            '    "exactOptionalPropertyTypes": true\n'
            "  }\n"
            "}\n"
            "```\n\n"
            "### 运行时安全（必须）\n"
            "- 外部数据（API/用户输入）**必须**用 Zod 校验\n"
            "- 不使用 `as Type` 断言处理外部数据，除非前面有明确的类型守卫\n"
            "- `!` 非空断言只在有明确保证的场合使用，并加注释说明理由"
        ),
        "community_meta": {
            "quality": "精选",
            "use_cases": [
                "TypeScript 项目",
                "类型设计",
                "Node.js 后端",
                "前端工程化",
                "API 类型安全",
            ],
            "difficulty": "较难",
        },
    },
]

# ── 社区 Skill 快捷索引
_COMMUNITY_SKILLS_BY_ID: Dict[str, Dict] = {s["id"]: s for s in _COMMUNITY_SKILLS}


# ── GET /api/skillmarket/community/catalog  ─────────────────────────────────


@marketplace_bp.route("/community/catalog", methods=["GET"])
def community_catalog():
    """返回社区精选 Skills 列表，带安装状态标注。"""
    sm = _sm()
    sm._ensure_init()
    installed_ids = set(sm._def_registry.keys())

    category = (request.args.get("category") or "").strip()
    q = (request.args.get("q") or "").strip().lower()

    skills_out = []
    import hashlib as _hl

    for skill in _COMMUNITY_SKILLS:
        if (
            category
            and skill.get("subcategory") != category
            and skill.get("category") != category
        ):
            continue
        if q:
            haystack = " ".join(
                [
                    skill.get("name", ""),
                    skill.get("description", ""),
                    " ".join(skill.get("tags", [])),
                    skill.get("author", ""),
                ]
            ).lower()
            if q not in haystack:
                continue
        entry = {
            k: v for k, v in skill.items() if k != "prompt"
        }  # 不暴露 prompt 在列表接口
        entry["is_installed"] = skill["id"] in installed_ids
        _h = int(_hl.md5(skill.get("name", "").encode("utf-8")).hexdigest(), 16)
        entry["likes"] = 100 + (_h % 900)
        if "source_name" not in entry:
            entry["source_name"] = "Koto 社区精选"
        skills_out.append(entry)

    return jsonify(
        {
            "success": True,
            "total": len(skills_out),
            "skills": skills_out,
        }
    )


# ── GET /api/skillmarket/community/skill/<id>  ─────────────────────────────


@marketplace_bp.route("/community/skill/<skill_id>", methods=["GET"])
def community_skill_detail(skill_id: str):
    """返回单个社区 Skill 完整信息（含 prompt）。"""
    skill = _COMMUNITY_SKILLS_BY_ID.get(skill_id)

    # 若在本地精选中找不到，尝试从在线缓存中查找
    if not skill and skill_id.startswith("online_"):
        cached = fetch_online_prompts()
        for p in cached or []:
            if p.get("id") == skill_id:
                skill = dict(p)
                skill["category"] = "domain"
                skill["subcategory"] = "tools"
                skill["prompt"] = skill.get("full_prompt", "")
                break

    if not skill:
        return jsonify({"success": False, "error": "Skill 不存在"}), 404

    sm = _sm()
    sm._ensure_init()
    entry = dict(skill)
    entry["is_installed"] = skill_id in sm._def_registry

    # 填充 likes
    if "likes" not in entry:
        import hashlib as _hl

        _h = int(_hl.md5(entry.get("name", "").encode("utf-8")).hexdigest(), 16)
        entry["likes"] = 100 + (_h % 900)

    # 确保 source_name 始终存在
    if "source_name" not in entry:
        entry["source_name"] = "Koto 社区精选"

    return jsonify({"success": True, "skill": entry})


# ── POST /api/skillmarket/community/install/<id>  ──────────────────────────


@marketplace_bp.route("/community/install/<skill_id>", methods=["POST"])
def community_install(skill_id: str):
    """将社区 Skill 安装到本地 Koto 技能库。"""
    skill_data = _COMMUNITY_SKILLS_BY_ID.get(skill_id)
    if not skill_data:
        return jsonify({"success": False, "error": "Skill 不存在"}), 404

    overwrite = bool((request.json or {}).get("overwrite", False))

    # 构建安装用的 dict（去掉社区专属字段，保留核心字段）
    install_dict = {k: v for k, v in skill_data.items() if k != "community_meta"}
    install_dict.setdefault(
        "created_at", __import__("datetime").datetime.utcnow().isoformat()
    )

    try:
        SkillDefinition, _, _ = _schema()
        SkillRecorder = _recorder()
        skill = SkillDefinition.from_dict(install_dict)
        sid = SkillRecorder.save_and_register(skill, overwrite=overwrite)
        return (
            jsonify(
                {
                    "success": True,
                    "skill_id": sid,
                    "message": f"「{skill_data['name']}」已成功安装到你的技能库",
                }
            ),
            201,
        )
    except FileExistsError:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"「{skill_data['name']}」已安装，传 overwrite:true 覆盖",
                    "skill_id": skill_id,
                }
            ),
            409,
        )
    except Exception as exc:
        logger.exception("[community/install] %s", skill_id)
        return jsonify({"success": False, "error": str(exc)}), 500


# ── POST /api/skillmarket/community/ai-recommend ──────────────────────────

_CACHED_ONLINE_PROMPTS = None
_LAST_FETCH_TIME = 0


def fetch_online_prompts():
    global _CACHED_ONLINE_PROMPTS, _LAST_FETCH_TIME
    import time

    if _CACHED_ONLINE_PROMPTS and (time.time() - _LAST_FETCH_TIME < 3600):
        return _CACHED_ONLINE_PROMPTS

    import csv
    import re
    import urllib.request
    from io import StringIO

    csv.field_size_limit(1024 * 1024)

    def _fetch_text(url: str, timeout: int = 12) -> str:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 KotoSkillBot/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        return raw.decode("utf-8", errors="replace")

    prompts = []

    # Source A: awesome-chatgpt-prompts (CSV)
    csv_sources = [
        {
            "name": "Awesome ChatGPT Prompts",
            "repo": "f/awesome-chatgpt-prompts",
            "url": "https://raw.githubusercontent.com/f/awesome-chatgpt-prompts/main/prompts.csv",
            "source_url": "https://github.com/f/awesome-chatgpt-prompts",
        },
        {
            "name": "Awesome ChatGPT Prompts (CDN mirror)",
            "repo": "f/awesome-chatgpt-prompts",
            "url": "https://cdn.jsdelivr.net/gh/f/awesome-chatgpt-prompts@main/prompts.csv",
            "source_url": "https://github.com/f/awesome-chatgpt-prompts",
        },
    ]

    try:
        csv_loaded = False
        for src in csv_sources:
            try:
                response = _fetch_text(src["url"])
                reader = csv.reader(StringIO(response))
                _ = next(reader, None)
                for i, row in enumerate(reader):
                    if len(row) >= 2 and row[0].strip() and row[1].strip():
                        import hashlib as _hl2

                        _hv = int(
                            _hl2.md5(row[0].strip().encode("utf-8")).hexdigest(), 16
                        )
                        prompts.append(
                            {
                                "id": f"online_awesome_{i}",
                                "name": row[0].strip(),
                                "description": (
                                    (row[1][:140] + "...")
                                    if len(row[1]) > 140
                                    else row[1]
                                ),
                                "full_prompt": row[1],
                                "author": (
                                    row[4].strip()
                                    if len(row) > 4 and row[4].strip()
                                    else "f/awesome-chatgpt-prompts"
                                ),
                                "tags": ["开源推荐", "github"],
                                "source_name": src["name"],
                                "source_repo": src["repo"],
                                "source_url": src["source_url"],
                                "source_kind": "csv",
                                "likes": 50 + (_hv % 3500),
                            }
                        )
                if prompts:
                    csv_loaded = True
                    break
            except Exception as csv_exc:
                logger.warning(
                    "[online-prompts] csv source failed %s: %s", src.get("url"), csv_exc
                )

        # Source B: linexjlin/GPTs (index from README)
        # 这里提供大量高质量现成 GPT 提示词索引；安装时再按路径抓取原文
        try:
            readme_text = _fetch_text(
                "https://raw.githubusercontent.com/linexjlin/GPTs/main/README.md"
            )
            pattern = re.compile(
                r"^-\s+\[(?P<title>[^\]]+)\]\(\./(?P<path>prompts/[^)]+\.md)\)(?:\s+by\s+(?P<author>.+))?\s*$"
            )
            idx = 0
            for line in readme_text.splitlines():
                m = pattern.match(line.strip())
                if not m:
                    continue
                title = m.group("title").strip()
                path = m.group("path").strip()
                author = (m.group("author") or "linexjlin/GPTs contributors").strip()
                import hashlib as _hl3

                _hv2 = int(_hl3.md5(title.encode("utf-8")).hexdigest(), 16)
                prompts.append(
                    {
                        "id": f"online_gpts_{idx}",
                        "name": title,
                        "description": f"来自 GitHub 开源仓库 linexjlin/GPTs · {path}",
                        "full_prompt": "",  # 安装时按路径抓取原文
                        "author": author,
                        "tags": ["开源推荐", "github", "gpts"],
                        "source_name": "linexjlin/GPTs",
                        "source_repo": "linexjlin/GPTs",
                        "source_url": "https://github.com/linexjlin/GPTs",
                        "source_kind": "markdown-index",
                        "source_path": path,
                        "likes": 50 + (_hv2 % 3500),
                    }
                )
                idx += 1
                if idx >= 300:
                    break
        except Exception as md_exc:
            logger.warning("[online-prompts] markdown source failed: %s", md_exc)

        # Source C: openclaw/skills (curated high-quality skills)
        # 从 github.com/openclaw/skills 抓取精选 SKILL.md，格式为 YAML frontmatter + Markdown
        _OPENCLAW_CURATED = [
            ("agentsleader", "uncle-bob", "Uncle Bob Clean Code"),
            ("an0nx", "senior-django-developer", "Senior Django Architect"),
            ("aeromomo", "claw-compactor", "Token Compressor"),
            ("antler2024", "openclaw-learning-coach", "Learning Coach"),
            ("1va7", "skill-refiner", "Skill Refiner"),
            ("amumulam", "diataxis-writing", "Diataxis Writing"),
            ("alicepub", "latex-writer", "LaTeX Writer"),
            ("anothertempore", "book-multi-lens", "Book Multi-Lens Analysis"),
            ("315133264", "learn-anything-in-one-hour", "Learn Anything in 1 Hour"),
            ("amkr-novo", "deep-thinking", "Deep Thinking"),
            ("anbring", "summary", "Smart Summary"),
            ("aegrumet", "podcast-discovery", "Podcast Discovery"),
            ("alphalpha7", "ai-research-to-obsidian", "Research to Notes"),
            # ── 补充精选：写作 / 内容创作 ─────────────────────────────────────
            ("1va7", "email-writer", "Email Writer"),
            ("an0nx", "technical-writer", "Technical Writer"),
            ("anothertempore", "storyteller", "Storyteller"),
            ("amumulam", "copywriter", "Copywriter"),
            ("alicepub", "academic-paper", "Academic Paper Writer"),
            # ── 补充精选：编程 / 工程 ──────────────────────────────────────────
            ("an0nx", "senior-react-developer", "Senior React Developer"),
            ("an0nx", "senior-typescript-developer", "Senior TypeScript Developer"),
            ("agentsleader", "clean-architecture", "Clean Architecture"),
            ("agentsleader", "tdd-coach", "TDD Coach"),
            ("an0nx", "devops-engineer", "DevOps Engineer"),
            ("aegrumet", "code-reviewer", "Code Reviewer"),
            # ── 补充精选：分析 / 研究 ──────────────────────────────────────────
            ("amkr-novo", "research-analyst", "Research Analyst"),
            ("alphalpha7", "data-analyst", "Data Analyst"),
            ("1va7", "product-manager", "Product Manager"),
            ("antler2024", "ux-researcher", "UX Researcher"),
            # ── 补充精选：生产力 / 思维 ────────────────────────────────────────
            ("amumulam", "gtd-coach", "GTD Coach"),
            ("anbring", "meeting-facilitator", "Meeting Facilitator"),
            ("amkr-novo", "brainstorming", "Brainstorming Coach"),
            ("315133264", "feynman-learning", "Feynman Learning"),
        ]
        try:
            for owner, slug, display_name in _OPENCLAW_CURATED:
                meta_url = f"https://raw.githubusercontent.com/openclaw/skills/main/skills/{owner}/{slug}/_meta.json"
                try:
                    import json as _json

                    meta_text = _fetch_text(meta_url, timeout=8)
                    meta = _json.loads(meta_text)
                    import hashlib as _hl4

                    _hv3 = int(_hl4.md5(slug.encode()).hexdigest(), 16)
                    prompts.append(
                        {
                            "id": f"online_oc_{owner}_{slug}".replace("-", "_"),
                            "name": meta.get("displayName") or display_name,
                            "description": f"来自 OpenClaw 开源社区 · {owner}/{slug}",
                            "full_prompt": "",  # 安装时按 source_path 抓取 SKILL.md
                            "author": owner,
                            "tags": ["openclaw", "开源推荐", "github"],
                            "source_name": "openclaw/skills",
                            "source_repo": "openclaw/skills",
                            "source_url": f"https://github.com/openclaw/skills/tree/main/skills/{owner}/{slug}",
                            "source_kind": "openclaw-skill",
                            "source_path": f"skills/{owner}/{slug}/SKILL.md",
                            "likes": 100 + (_hv3 % 2000),
                        }
                    )
                except Exception as oc_item_exc:
                    logger.debug(
                        "[online-prompts] openclaw %s/%s: %s", owner, slug, oc_item_exc
                    )
        except Exception as oc_exc:
            logger.warning("[online-prompts] openclaw source failed: %s", oc_exc)

        # 去重（按 name）
        dedup = {}
        for p in prompts:
            key = (p.get("name") or "").strip().lower()
            if key and key not in dedup:
                dedup[key] = p

        merged = list(dedup.values())
        if not merged and _CACHED_ONLINE_PROMPTS:
            return _CACHED_ONLINE_PROMPTS

        _CACHED_ONLINE_PROMPTS = merged
        _LAST_FETCH_TIME = time.time()
        if merged:
            logger.info(
                "[online-prompts] loaded=%s csv_loaded=%s", len(merged), csv_loaded
            )
        return merged
    except Exception as e:
        logger.error(f"Failed to fetch awesome prompts: {e}")
        return _CACHED_ONLINE_PROMPTS or []


@marketplace_bp.route("/community/ai-recommend", methods=["POST"])
def community_ai_recommend():
    data = request.json or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "Empty query"}), 400

    prompts = fetch_online_prompts()
    used_fallback = False
    if not prompts:
        used_fallback = True
        prompts = []
        for s in _COMMUNITY_SKILLS[:20]:
            prompts.append(
                {
                    "id": f"local_{s.get('id')}",
                    "name": s.get("name", "未命名技能"),
                    "description": s.get("description", ""),
                    "full_prompt": s.get("prompt", ""),
                    "author": s.get("author", "Open Source"),
                    "tags": list(s.get("tags", [])) + ["本地兜底"],
                    "source_name": "Koto 本地精选",
                    "source_repo": "local",
                    "source_url": "",
                    "source_kind": "local-fallback",
                }
            )

    # ── 中文→英文 关键词映射表（本地，不依赖 LLM）──────────────
    _ZH_EN_MAP = {
        "翻译": ["translate", "translation", "translator", "language", "interpret"],
        "写作": ["writing", "writer", "write", "essay", "copywriting", "author"],
        "编程": ["programming", "code", "coding", "developer", "software"],
        "代码": ["code", "coding", "developer", "debug", "programming"],
        "数据": ["data", "database", "sql", "analytics", "analysis"],
        "分析": ["analysis", "analyst", "analyze", "analytical"],
        "设计": ["design", "designer", "ui", "ux", "graphic"],
        "营销": ["marketing", "sales", "promotion", "advertising"],
        "英语": ["english", "language", "esl", "grammar", "vocabulary"],
        "学习": ["learning", "study", "education", "teach", "tutor"],
        "面试": ["interview", "hiring", "job", "career", "resume"],
        "简历": ["resume", "cv", "career", "job"],
        "法律": ["legal", "law", "lawyer", "attorney"],
        "健康": ["health", "medical", "fitness", "wellness"],
        "心理": ["psychology", "mental", "therapy", "counseling"],
        "客服": ["customer", "support", "service", "help"],
        "旅行": ["travel", "trip", "tourism", "guide"],
        "烹饪": ["cooking", "recipe", "chef", "food"],
        "投资": ["invest", "finance", "stock", "portfolio"],
        "游戏": ["game", "gaming", "play"],
        "测试": ["test", "testing", "qa", "debug"],
        "角色": ["role", "roleplay", "character", "persona"],
        "对话": ["chat", "conversation", "dialogue"],
        "文案": ["copywriting", "copy", "advertising", "sales"],
        "excel": ["excel", "spreadsheet", "formula"],
        "sql": ["sql", "database", "query"],
        "python": ["python", "programming", "script"],
        "助手": ["assistant", "helper", "aid"],
        "总结": ["summarize", "summary", "brief"],
        "邮件": ["email", "mail", "letter"],
    }

    # ── Step 1: 构建关键词（本地映射 + 原文拆分，零 LLM 调用）──
    keywords = []
    query_lower = query.lower()
    for zh, en_list in _ZH_EN_MAP.items():
        if zh in query_lower:
            keywords.extend(en_list)
    # 也把原始 query 里的英文词加上
    import re as _re

    for w in _re.findall(r"[a-zA-Z]{2,}", query):
        keywords.append(w.lower())
    # 去重
    keywords = list(dict.fromkeys(keywords))

    # ── Step 2: 基于关键词打分 ──────────────────────────────────
    scored = []
    for p in prompts:
        name_lower = p.get("name", "").lower()
        haystack = f"{name_lower} {p.get('description', '')} {' '.join(p.get('tags', []))}".lower()
        score = 0
        for kw in keywords:
            if kw in name_lower:
                score += 5
            elif kw in haystack:
                score += 1
        scored.append((p, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    candidates = [p for p, s in scored if s > 0][:60]

    # ── Step 3: 尝试用 LLM 做语义精排（可选，失败时直接用评分结果兜底）
    results = []
    if candidates:
        try:
            from app.core.llm.gemini import GeminiProvider

            llm = GeminiProvider()
            catalog_lines = []
            for i, p in enumerate(candidates[:40]):
                catalog_lines.append(f"[{i}] {p['name']}")
            catalog_text = "\n".join(catalog_lines)

            rank_prompt = (
                f"Skill titles:\n{catalog_text}\n\n"
                f'User needs: "{query}"\n\n'
                "Pick the best 3-8 matches. Return ONLY a JSON array of integer IDs. Example: [0,3,7]"
            )
            res = llm.generate_content(
                prompt=rank_prompt,
                model="gemini-2.5-flash",
                system_instruction="Return ONLY a JSON array of integers.",
                temperature=0.1,
                max_tokens=200,
            )
            content = (
                (res.get("content") or res.get("text") or "")
                if isinstance(res, dict)
                else str(res)
            )
            content = content.replace("```json", "").replace("```", "").strip()
            recommended_indices = json.loads(content)
            if isinstance(recommended_indices, list):
                for idx_val in recommended_indices:
                    try:
                        i = int(idx_val)
                        if 0 <= i < len(candidates):
                            results.append(candidates[i])
                    except (ValueError, TypeError):
                        pass
        except Exception as llm_err:
            logger.warning(
                "[ai-recommend] LLM ranking failed, using keyword fallback: %s", llm_err
            )

    # 如果 LLM 没有返回结果，使用纯关键词匹配的 top 结果
    if not results and candidates:
        results = candidates[:6]

    return jsonify(
        {
            "results": results,
            "total_pool": len(prompts),
            "used_fallback": used_fallback,
        }
    )


# ── POST /api/skillmarket/community/online-install ────────────────────────


@marketplace_bp.route("/community/online-install", methods=["POST"])
def community_install_online():
    data = request.json or {}
    name = data.get("name")
    full_prompt = (data.get("full_prompt") or "").strip()
    source_repo = (data.get("source_repo") or "").strip()
    source_path = (data.get("source_path") or "").strip()

    if not name:
        return jsonify({"success": False, "error": "缺少必要字段：name"}), 400

    # 若前端未带完整 prompt，则尝试按来源路径拉取原文（GitHub）
    if not full_prompt and source_repo and source_path:
        import urllib.request

        raw_candidates = [
            f"https://raw.githubusercontent.com/{source_repo}/main/{source_path}",
            f"https://raw.githubusercontent.com/{source_repo}/master/{source_path}",
        ]
        for raw_url in raw_candidates:
            try:
                req = urllib.request.Request(
                    raw_url, headers={"User-Agent": "Mozilla/5.0 KotoSkillBot/1.0"}
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    full_prompt = resp.read().decode("utf-8", errors="replace").strip()
                if full_prompt:
                    break
            except Exception:
                continue

    # ── 解析 OpenClaw SKILL.md 格式（YAML frontmatter + Markdown 正文）──────
    # 如果来源是 openclaw/skills，从 frontmatter 提取 name/description，正文作为 prompt
    source_kind = (data.get("source_kind") or "").strip()
    if full_prompt and source_kind == "openclaw-skill":
        import re as _re

        fm_match = _re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", full_prompt, _re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            body = fm_match.group(2).strip()
            # 从 frontmatter 提取 name 和 description（简单 key: value 解析，不依赖 PyYAML）
            fm_name_m = _re.search(r"^name:\s*(.+)$", fm_text, _re.MULTILINE)
            fm_desc_m = _re.search(
                r"^description:\s*['\"]?(.*?)['\"]?\s*$",
                fm_text,
                _re.MULTILINE | _re.DOTALL,
            )
            if fm_name_m and not name:
                name = fm_name_m.group(1).strip().strip("'\"")
            if fm_desc_m and not data.get("description"):
                # 清理多行 description（可能有续行缩进）
                raw_desc = fm_desc_m.group(1).strip().strip("'\"")
                data = dict(data)
                data["description"] = (
                    raw_desc[:300] if len(raw_desc) > 300 else raw_desc
                )
            full_prompt = body  # 正文（去掉 frontmatter）作为真正的 prompt

            # ── 包裹 Koto 风格激活前缀，与 Koto 技能注入系统兼容 ──────────────
            # 若正文不以 ## 标题开头且没有 Koto 风格激活语，添加统一包装头
            _spi = (data.get("source_path") or "").replace("skills/", "").split("/")
            _owner_hint = f" · {_spi[0]}/{_spi[1]}" if len(_spi) >= 2 else ""
            if (
                not body.lstrip().startswith("##")
                and "当此技能激活时" not in body[:200]
            ):
                full_prompt = (
                    f"\n\n## {name}\n\n"
                    f"**来源：OpenClaw 开源社区{_owner_hint}**\n\n"
                    "当此技能激活时，以下专项指令将生效：\n\n"
                ) + body.strip()

    if not full_prompt:
        return jsonify({"success": False, "error": "缺少必要字段"}), 400

    import datetime
    import uuid

    skill_id = f"online_{uuid.uuid4().hex[:8]}"

    install_dict = {
        "id": skill_id,
        "name": name,
        "version": "1.0.0",
        "description": data.get("description", "Imported from open source community."),
        "author": data.get("author", "Open Source"),
        "tags": data.get("tags", ["开源导入"]),
        "created_at": datetime.datetime.utcnow().isoformat(),
        "steps": [{"type": "system_prompt", "content": full_prompt}],
    }

    src_repo = (data.get("source_repo") or "").strip()
    src_name = (data.get("source_name") or "").strip()
    src_url = (data.get("source_url") or "").strip()
    if src_repo:
        install_dict["tags"] = list(
            dict.fromkeys((install_dict.get("tags") or []) + ["github", src_repo])
        )
    if src_name and src_name.lower() not in str(install_dict.get("author", "")).lower():
        install_dict["author"] = (
            f"{install_dict.get('author', 'Open Source')} · {src_name}"
        )
    if src_url and src_url not in str(install_dict.get("description", "")):
        install_dict["description"] = (
            f"{install_dict.get('description', '')}\n\n来源：{src_url}".strip()
        )

    try:
        SkillDefinition, _, _ = _schema()
        SkillRecorder = _recorder()
        skill = SkillDefinition.from_dict(install_dict)
        sid = SkillRecorder.save_and_register(skill, overwrite=False)
        return (
            jsonify(
                {
                    "success": True,
                    "skill_id": sid,
                    "message": f"「{name}」已成功安装到你的技能库",
                }
            ),
            201,
        )
    except Exception as exc:
        logger.exception("[community/online-install] error")
        return jsonify({"success": False, "error": str(exc)}), 500
